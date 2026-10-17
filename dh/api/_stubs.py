"""Example payloads for routes when live data or modules are missing.

Numbers come from ``contracts/examples/``. This module does not invent scores.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"


def current_mode() -> str:
    """DH_MODE at call time, defaulting to dev.

    Read the environment on each call so tests can monkeypatch DH_MODE
    before ``create_app()``. When the variable is unset, use
    ``dh.config.MODE`` if that import works.
    """
    if "DH_MODE" in os.environ:
        return os.environ.get("DH_MODE") or "dev"
    try:
        from dh.config import MODE
    except ImportError:
        return os.environ.get("DH_MODE", "dev")
    if isinstance(MODE, str) and MODE:
        return MODE
    return os.environ.get("DH_MODE", "dev")


def _load_json(name: str):
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _load_jsonl(name: str) -> list[dict]:
    path = _EXAMPLES / name
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def example_clips() -> list[dict]:
    payload = _load_json("clips.json")
    if not isinstance(payload, list):
        return []
    return payload


def example_hazards() -> list[dict]:
    payload = _load_json("hazards.json")
    if not isinstance(payload, list):
        return []
    return payload


def example_testset() -> dict:
    payload = _load_json("testset_v0.json")
    if not isinstance(payload, dict):
        return {}
    return payload


def example_run() -> dict:
    payload = _load_json("run.json")
    if not isinstance(payload, dict):
        return {}
    return payload


def example_clip_results() -> list[dict]:
    return _load_jsonl("run_clips.jsonl")


def example_tracks(clip_id: str) -> list[dict]:
    return _load_jsonl(f"tracks_{clip_id}.jsonl")


def example_leaderboard() -> dict:
    payload = _load_json("leaderboard.json")
    if not isinstance(payload, dict):
        return {}
    return payload


def example_human() -> dict:
    rows = _load_jsonl("humans.jsonl")
    if not rows:
        return {}
    return rows[0]


def example_score() -> dict:
    """Scorer stand-in from the example clip result and hazard window.

    Shape used when ``dh.score`` cannot be imported. Clicks passed to the
    caller are ignored on that path; the example click time is used here.
    """
    result = example_clip_results()[0]
    hazards = {hazard["hazard_id"]: hazard for hazard in example_hazards()}
    clicks = result.get("clicks") or []
    first_click = None
    if clicks:
        click = clicks[0]
        first_click = click.get("t") if isinstance(click, dict) else click
    pattern = result.get("pattern") or {}
    breakdown = []
    for hazard_id, points in (result.get("hazard_points") or {}).items():
        hazard = hazards.get(hazard_id)
        if hazard is None:
            continue
        breakdown.append(
            {
                "hazard_id": hazard_id,
                "window": [hazard["window_start"], hazard["window_end"]],
                "points": points,
                "first_click": first_click,
            }
        )
    return {
        "clip_score": result["clip_score"],
        "pattern": {
            "flag": bool(pattern.get("flag")),
            "reasons": list(pattern.get("reasons") or []),
        },
        "hazards": breakdown,
        "agents": {},
    }


def try_score_clip(clicks: list[float], hazards: list[dict], duration_s: float) -> dict:
    """Score with ``dh.score`` when it imports, else the example score."""
    try:
        from dh.score import score_clip
    except ImportError:
        return example_score()
    scored = score_clip(clicks, hazards, duration_s)
    if "agents" not in scored:
        scored = {**scored, "agents": {}}
    return scored
