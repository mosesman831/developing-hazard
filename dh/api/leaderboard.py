"""Leaderboard JSON from the data directory, or the example file."""

from __future__ import annotations

import json

from fastapi import APIRouter

from dh.api._stubs import example_leaderboard
from dh.api.runs import recorded_clip_rows
from dh.clips import data_dir

router = APIRouter()


def _load_board() -> dict:
    path = data_dir() / "leaderboard.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    try:
        return example_leaderboard()
    except OSError:
        # The demo pod does not ship contracts/examples. Do not invent scores.
        return {
            "testset_id": None,
            "max": None,
            "dvsa_reference_pct": 0.587,
            "rows": [],
        }


def _usable_blind_row(row: object) -> dict | None:
    """Keep a sit only when the client sent blind=true and the row is scored."""
    if not isinstance(row, dict) or row.get("blind") is not True:
        return None
    score = row.get("clip_score")
    clip_id = row.get("clip_id")
    name = row.get("name")
    if name == "smoke":
        return None
    if (
        isinstance(clip_id, str)
        and isinstance(name, str)
        and isinstance(score, int)
        and not isinstance(score, bool)
    ):
        return row
    return None


def _blind_humans() -> list[dict]:
    path = data_dir() / "humans.jsonl"
    chosen: list[dict] = []
    seen: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                session_id = row.get("session_id")
                if isinstance(session_id, str):
                    seen.add(session_id)
            accepted = _usable_blind_row(row)
            if accepted is not None:
                chosen.append(accepted)

    # Demo sits stay in memory. Dev also appends the same session to the file.
    from dh.api.human import sessions as live_sessions

    for row in live_sessions:
        if not isinstance(row, dict):
            continue
        session_id = row.get("session_id")
        if isinstance(session_id, str) and session_id in seen:
            continue
        accepted = _usable_blind_row(row)
        if accepted is None:
            continue
        chosen.append(accepted)
        if isinstance(session_id, str):
            seen.add(session_id)
    return chosen


def _test_clip_ids() -> list[str]:
    path = data_dir() / "clips.json"
    if not path.is_file():
        return []
    try:
        clips = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(clips, list):
        return []
    test = [
        clip["clip_id"]
        for clip in clips
        if isinstance(clip, dict) and clip.get("split") == "test" and isinstance(clip.get("clip_id"), str)
    ]
    if test:
        return test
    return [
        clip["clip_id"]
        for clip in clips
        if isinstance(clip, dict) and isinstance(clip.get("clip_id"), str)
    ]


def _best_agents(clip_rows: list[dict]) -> dict[str, tuple[str, int]]:
    best: dict[str, tuple[str, int]] = {}
    for row in clip_rows:
        clip_id = row.get("clip_id")
        agent = row.get("agent")
        score = row.get("clip_score")
        if not isinstance(clip_id, str) or not isinstance(agent, str):
            continue
        if isinstance(score, bool) or not isinstance(score, int):
            continue
        current = best.get(clip_id)
        if current is None or score > current[1] or (score == current[1] and agent < current[0]):
            best[clip_id] = (agent, score)
    return best


def _per_clip(humans: list[dict], clip_rows: list[dict]) -> list[dict]:
    best = _best_agents(clip_rows)
    table: list[dict] = []
    for session in humans:
        clip_id = session["clip_id"]
        agent_score = best.get(clip_id)
        table.append(
            {
                "clip_id": clip_id,
                "name": session["name"],
                "human_score": session["clip_score"],
                "best_agent": agent_score[0] if agent_score else None,
                "best_agent_score": agent_score[1] if agent_score else None,
            }
        )
    return table


def _full_set_humans(humans: list[dict], clip_ids: list[str]) -> list[dict]:
    if not clip_ids:
        return []
    needed = set(clip_ids)
    by_name: dict[str, dict[str, int]] = {}
    for session in humans:
        clip_id = session["clip_id"]
        if clip_id not in needed:
            continue
        by_name.setdefault(session["name"], {})[clip_id] = session["clip_score"]
    rows: list[dict] = []
    for name, scores in by_name.items():
        if set(scores) != needed:
            continue
        rows.append(
            {
                "name": name,
                "kind": "human",
                "score": sum(scores[clip_id] for clip_id in clip_ids),
                "n_clips": len(clip_ids),
            }
        )
    return rows


@router.get("/api/leaderboard")
def get_leaderboard(latency: str | None = None) -> dict:
    payload = _load_board()
    humans = _blind_humans()
    body = dict(payload)
    rows = body.get("rows")
    if isinstance(rows, list):
        body["rows"] = [
            row
            for row in rows
            if not (isinstance(row, dict) and row.get("name") == "smoke")
        ]
    if latency is None and not humans:
        return body

    if humans:
        clip_rows = recorded_clip_rows()
        body["per_clip"] = _per_clip(humans, clip_rows)
        full_set = _full_set_humans(humans, _test_clip_ids())
        if full_set:
            body["full_set_humans"] = full_set
    if latency:
        rows = body.get("rows") if isinstance(body.get("rows"), list) else []
        tagged = [row for row in rows if isinstance(row, dict) and row.get("latency_mode")]
        if tagged:
            body["rows"] = [row for row in tagged if row.get("latency_mode") == latency]
            body["latency_applied"] = True
        else:
            body["latency_applied"] = False
        body["latency"] = latency
    return body
