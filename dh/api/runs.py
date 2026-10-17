"""Run list, run detail, dev start, explain stub, and score stream."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from dh.api._stubs import (
    current_mode,
    example_clip_results,
    example_run,
)
from dh.clips import data_dir

router = APIRouter()


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def _iter_runs() -> list[tuple[dict, Path | None]]:
    directory = data_dir() / "runs"
    if not directory.is_dir():
        return [(example_run(), None)]
    found: list[tuple[dict, Path | None]] = []
    for path in sorted(directory.rglob("run.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            found.append((payload, path))
    return found


def _find_run(run_id: str) -> tuple[dict, Path | None] | None:
    for run, path in _iter_runs():
        if run.get("run_id") == run_id:
            return run, path
    return None


def _clip_results(run_id: str, path: Path | None) -> list[dict]:
    if path is not None:
        sibling = path.parent / "clips.jsonl"
        if sibling.is_file():
            return _read_jsonl(sibling)
        return []
    return [row for row in example_clip_results() if row.get("run_id") == run_id]


def recorded_clip_rows() -> list[dict]:
    """Clip results from ``data/runs`` only. Example runs are not included."""
    directory = data_dir() / "runs"
    if not directory.is_dir():
        return []
    rows: list[dict] = []
    for run, path in _iter_runs():
        run_id = run.get("run_id")
        if not isinstance(run_id, str):
            continue
        for clip in _clip_results(run_id, path):
            rows.append(
                {
                    "run_id": run_id,
                    "agent": run.get("agent"),
                    "latency_mode": run.get("latency_mode"),
                    "weave_url": run.get("weave_url") or "",
                    "clip_id": clip.get("clip_id"),
                    "clip_score": clip.get("clip_score"),
                    "clicks": clip.get("clicks") or [],
                }
            )
    return rows


@router.get("/api/runs")
def list_runs() -> list[dict]:
    return [run for run, _path in _iter_runs()]


@router.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    found = _find_run(run_id)
    if found is None:
        raise HTTPException(status_code=404, detail="run not found")
    run, path = found
    detail = dict(run)
    detail["clips"] = _clip_results(run_id, path)
    return detail


@router.post("/api/runs")
def post_run(body: dict) -> dict:
    if current_mode() != "dev":
        raise HTTPException(status_code=404, detail="not found")
    agent = body.get("agent")
    if not isinstance(agent, str) or not agent:
        raise HTTPException(status_code=422, detail="agent is required")
    config = body.get("config")
    if not isinstance(config, dict):
        config = {}
    try:
        from dh.evals import start_run
    except ImportError:
        return {"run_id": example_run()["run_id"], "stub": True}
    run_id = start_run(
        agent,
        config,
        body.get("testset_id"),
        body.get("latency_mode"),
    )
    return {"run_id": run_id}


def _approved_explanation(run_id: str, hazard_id: str) -> dict | None:
    path = data_dir() / "cache" / "explain" / run_id / f"{hazard_id}.json"
    try:
        found = path.is_file()
    except OSError:
        return None
    if not found:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("approved") is not True:
        return None
    return payload


@router.post("/api/explain/{run_id}/{hazard_id}")
def explain(run_id: str, hazard_id: str) -> dict:
    payload = _approved_explanation(run_id, hazard_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="explanation not approved")
    return payload


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _stream_events(chosen: dict | None, score) -> list[str]:
    lines: list[str] = []
    if isinstance(chosen, dict):
        for point in chosen.get("risk_curve") or []:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                lines.append(_sse("risk", {"t": point[0], "risk": point[1]}))
        for click in chosen.get("clicks") or []:
            if isinstance(click, dict) and "t" in click:
                lines.append(_sse("click", {"t": click["t"]}))
        for call in chosen.get("calls") or []:
            if isinstance(call, dict):
                lines.append(_sse("cosmos_call", call))
        hazards = chosen.get("hazard_points")
        score_payload = {"clip_score": score}
        if isinstance(hazards, dict):
            score_payload["hazards"] = hazards
        lines.append(_sse("score", score_payload))
        return lines
    lines.append(_sse("score", {"clip_score": score}))
    return lines


@router.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str, clip: str | None = None) -> StreamingResponse:
    found = _find_run(run_id)
    if found is None:
        raise HTTPException(status_code=404, detail="run not found")
    _run, path = found
    rows = _clip_results(run_id, path)
    chosen = None
    for row in rows:
        if clip and row.get("clip_id") != clip:
            continue
        chosen = row
        break
    if clip and chosen is None:
        raise HTTPException(status_code=404, detail="clip not in run")
    if chosen is None and rows and not clip:
        chosen = rows[0]
    score = chosen.get("clip_score") if chosen else None

    def events():
        yield from _stream_events(chosen, score)

    return StreamingResponse(events(), media_type="text/event-stream")
