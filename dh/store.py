"""Local JSON is the source of truth. VastDB rows are a copy (SPEC 7.13).

Row builders do not open the network. ``write_*`` functions call VastDB only
for schema ``developing_hazard``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dh.clients.vastdb import (
    insert_hazard_rows,
    insert_hazard_score_rows,
    insert_run_rows,
)
from dh.score import score_clip


def hazard_rows(
    hazards: list[dict[str, Any]],
    clips: list[dict[str, Any]] | None = None,
    testset_id: str = "",
) -> list[dict[str, Any]]:
    """One VastDB row per segment source. Labeller A is riyu when present."""
    originals = {
        clip.get("clip_id"): clip.get("original_video") or ""
        for clip in (clips or [])
        if isinstance(clip, dict)
    }
    rows: list[dict[str, Any]] = []
    for hazard in hazards:
        labellers = hazard.get("labellers") if isinstance(hazard.get("labellers"), dict) else {}
        names = [name for name in labellers if isinstance(name, str)]
        labeller_a = "riyu" if "riyu" in names else (names[0] if names else "")
        others = [name for name in names if name != labeller_a]
        labeller_b = others[0] if others else ""
        sources = [
            source
            for source in (hazard.get("segment_sources") or [])
            if isinstance(source, str) and source
        ]
        if not sources:
            sources = [""]
        for source in sources:
            rows.append(
                {
                    "hazard_id": hazard.get("hazard_id") or "",
                    "clip_id": hazard.get("clip_id") or "",
                    "type": hazard.get("type") or "",
                    "window_start": float(hazard.get("window_start") or 0.0),
                    "window_end": float(hazard.get("window_end") or 0.0),
                    "segment_source": source,
                    "original_video": originals.get(hazard.get("clip_id"), "") or "",
                    "labeller_a": labeller_a,
                    "labeller_b": labeller_b,
                    "agreed": hazard.get("agreed") is True,
                    "testset_id": testset_id,
                }
            )
    return rows


def _sources_for_window(
    clip: dict[str, Any] | None,
    ws: float,
    we: float,
) -> list[str]:
    """Segment sources whose clip-time span overlaps the window."""
    if not clip:
        return []
    sources: list[str] = []
    for segment in clip.get("segments") or []:
        start_s = segment.get("start_s")
        end_s = segment.get("end_s")
        source = segment.get("source")
        if not isinstance(source, str):
            continue
        if not isinstance(start_s, (int, float)) or not isinstance(end_s, (int, float)):
            continue
        if end_s > ws and start_s < we:
            sources.append(source)
    return sources


def _click_times(clicks: list) -> list[float]:
    times: list[float] = []
    for click in clicks:
        if isinstance(click, dict) and click.get("t") is not None:
            times.append(float(click["t"]))
        elif isinstance(click, (int, float)):
            times.append(float(click))
    return times


def _latency_for_click(clicks: list, t: float | None) -> float | None:
    if t is None:
        return None
    for click in clicks:
        if isinstance(click, dict) and float(click.get("t", -1)) == float(t):
            lat = click.get("latency_s")
            return float(lat) if lat is not None else None
    return None


def run_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One VastDB row per run file. Totals are read from the ``totals`` key."""
    rows: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        totals = run.get("totals") if isinstance(run.get("totals"), dict) else {}
        agent_config = run.get("agent_config")
        if agent_config is None:
            config_text = ""
        elif isinstance(agent_config, str):
            config_text = agent_config
        else:
            config_text = json.dumps(agent_config, sort_keys=True, separators=(",", ":"))
        rows.append(
            {
                "run_id": run.get("run_id") or "",
                "agent": run.get("agent") or "",
                "agent_config": config_text,
                "testset_id": run.get("testset_id") or "",
                "testset_sha256": run.get("testset_sha256") or "",
                "scorer_version": run.get("scorer_version") or "",
                "pattern_version": run.get("pattern_version") or "",
                "latency_mode": run.get("latency_mode") or "",
                "git_sha": run.get("git_sha") or "",
                "score": totals.get("score"),
                "max": totals.get("max"),
                "pct": totals.get("pct"),
                "hit_rate": totals.get("hit_rate"),
                "pattern_rate": totals.get("pattern_rate"),
                "lift_vs_chance": totals.get("lift_vs_chance"),
                "median_reaction_s": totals.get("median_reaction_s"),
                "mean_latency_s": totals.get("mean_latency_s"),
                "weave_url": run.get("weave_url") or "",
            }
        )
    return rows


def hazard_score_rows(
    run: dict[str, Any],
    clip_rows: list[dict[str, Any]],
    hazards: list[dict[str, Any]],
    clips: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Per-hazard score rows keyed by overlapping segment ``source``."""
    run_id = run.get("run_id") or ""
    by_clip = {
        clip.get("clip_id"): clip
        for clip in (clips or [])
        if isinstance(clip, dict) and clip.get("clip_id")
    }
    hazards_by_clip: dict[str, list[dict[str, Any]]] = {}
    for hazard in hazards:
        if not isinstance(hazard, dict):
            continue
        clip_id = hazard.get("clip_id")
        if not clip_id:
            continue
        hazards_by_clip.setdefault(clip_id, []).append(hazard)

    rows: list[dict[str, Any]] = []
    for clip_row in clip_rows:
        if not isinstance(clip_row, dict):
            continue
        clip_id = clip_row.get("clip_id") or ""
        clip_meta = by_clip.get(clip_id)
        duration_s = float(clip_meta.get("duration_s") or 30.0) if clip_meta else 30.0
        clip_hazards = hazards_by_clip.get(clip_id, [])
        clicks = clip_row.get("clicks") or []
        click_times = _click_times(clicks)
        scored = score_clip(click_times, clip_hazards, duration_s)
        breakdown = {h["hazard_id"]: h for h in scored.get("hazards") or []}
        points_map = clip_row.get("hazard_points") or scored.get("hazard_points") or {}

        for hazard in clip_hazards:
            hazard_id = hazard.get("hazard_id") or ""
            ws = float(hazard.get("window_start") or 0.0)
            we = float(hazard.get("window_end") or 0.0)
            detail = breakdown.get(hazard_id) or {}
            first_click = detail.get("first_click")
            points = points_map.get(hazard_id)
            if points is None:
                points = detail.get("points", 0)
            latency_s = _latency_for_click(clicks, first_click)

            sources = [
                source
                for source in (hazard.get("segment_sources") or [])
                if isinstance(source, str) and source
            ]
            if not sources:
                sources = _sources_for_window(clip_meta, ws, we)
            if not sources:
                sources = [""]

            for source in sources:
                rows.append(
                    {
                        "run_id": run_id,
                        "clip_id": clip_id,
                        "hazard_id": hazard_id,
                        "points": int(points) if points is not None else 0,
                        "first_click_t": first_click,
                        "window_start": ws,
                        "window_end": we,
                        "latency_s": latency_s,
                        "segment_source": source,
                    }
                )
    return rows


def load_run_docs(
    data_dir: str | Path | None = None,
    testset_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read ``run.json`` from each run directory under ``data/runs``."""
    from dh.config import DATA_DIR

    root = Path(data_dir) if data_dir is not None else Path(DATA_DIR)
    runs_root = root / "runs"
    if not runs_root.is_dir():
        return []
    docs: list[dict[str, Any]] = []
    for run_dir in sorted(runs_root.iterdir()):
        path = run_dir / "run.json"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if testset_id is not None and doc.get("testset_id") != testset_id:
            continue
        docs.append(doc)
    return docs


def load_clip_rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "clips.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_hazards(testset_id: str = "") -> int:
    """Insert the local hazard file into VastDB. JSON stays the source of truth."""
    from dh.clips import load_clips, load_hazards

    return insert_hazard_rows(hazard_rows(load_hazards(), load_clips(), testset_id))


def write_runs_and_scores(testset_id: str = "dev") -> tuple[int, int]:
    """Insert run and hazard_score rows for every matching run under ``data/runs``."""
    from dh.clips import load_clips, load_hazards

    from dh.config import DATA_DIR

    root = Path(DATA_DIR)
    hazards = load_hazards()
    clips = load_clips()
    run_docs = load_run_docs(root, testset_id=testset_id)
    run_table = run_rows(run_docs)
    score_table: list[dict[str, Any]] = []
    for doc in run_docs:
        run_id = doc.get("run_id")
        if not run_id:
            continue
        clip_rows = load_clip_rows(root / "runs" / run_id)
        score_table.extend(hazard_score_rows(doc, clip_rows, hazards, clips))
    return (insert_run_rows(run_table), insert_hazard_score_rows(score_table))


def main() -> None:
    """Lab VM entry point: write dev runs and hazard scores to VastDB."""
    runs_n, scores_n = write_runs_and_scores(testset_id="dev")
    print(f"inserted {runs_n} runs and {scores_n} hazard_scores rows")


if __name__ == "__main__":
    main()
