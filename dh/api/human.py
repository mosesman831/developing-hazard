"""Human sit sessions, scored on the server."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from dh.api._stubs import current_mode, example_score
from dh.api.clips import clip_with_hazards
from dh.api.runs import recorded_clip_rows
from dh.clips import data_dir

router = APIRouter()

_ROLES = frozenset({"team", "judge", "guest"})
_MAX_NAME_LEN = 64
_MAX_CLICKS = 1000

sessions: list[dict] = []


def _recorded_agents(clip_id: str) -> dict[str, int]:
    """Scores from recorded runs for this clip. Missing runs stay absent."""
    scores: dict[str, int] = {}
    for row in recorded_clip_rows():
        if row.get("clip_id") != clip_id:
            continue
        agent = row.get("agent")
        score = row.get("clip_score")
        if isinstance(agent, str) and isinstance(score, int) and not isinstance(score, bool):
            scores[agent] = score
    return scores


def _score(clicks: list[float], hazards: list[dict], duration_s: float) -> dict:
    """Score with AG1's scorer. The example score is only the import fallback."""
    try:
        from dh.score import score_clip
    except ImportError:
        return example_score()
    scored = score_clip(clicks, hazards, duration_s)
    if "agents" not in scored:
        scored = {**scored, "agents": {}}
    return scored


def _click_time(item: object) -> float:
    """One click time in seconds, or 422.

    JSON ``1e309`` parses as infinity, and ``round(t * 1000)`` in the scorer
    then raises. NaN does the same. Those are bad requests, not server errors.
    """
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise HTTPException(status_code=422, detail="clicks must be a list of numbers")
    value = float(item)
    scaled = value * 1000.0
    if value < 0 or not math.isfinite(value) or not math.isfinite(scaled):
        raise HTTPException(
            status_code=422,
            detail="clicks must be finite non-negative numbers",
        )
    return value


def _clicks(body: dict) -> list[float]:
    raw = body.get("clicks", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="clicks must be a list of numbers")
    if len(raw) > _MAX_CLICKS:
        raise HTTPException(status_code=422, detail=f"at most {_MAX_CLICKS} clicks")
    return [_click_time(item) for item in raw]


@router.post("/api/human")
def post_human(body: dict) -> dict:
    role = body.get("role")
    if role not in _ROLES:
        raise HTTPException(
            status_code=422,
            detail="role must be team, judge, or guest",
        )
    raw_name = body.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        name = raw_name.strip()
        if len(name) > _MAX_NAME_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"name must be at most {_MAX_NAME_LEN} characters",
            )
    else:
        name = "Anonymous"
    blind = body.get("blind", False)
    if not isinstance(blind, bool):
        raise HTTPException(status_code=422, detail="blind must be a boolean")
    clip_id = body.get("clip_id")
    if not isinstance(clip_id, str) or not clip_id:
        raise HTTPException(status_code=422, detail="clip_id is required")
    clicks = _clicks(body)

    found = clip_with_hazards(clip_id)
    if found is None:
        raise HTTPException(status_code=404, detail="clip not found")
    clip, hazards = found
    if "duration_s" not in clip:
        raise HTTPException(status_code=422, detail="clip has no duration")

    # Blind sits still score against labels. The server holds the windows.
    scored = _score(clicks, [dict(hazard) for hazard in hazards], float(clip["duration_s"]))
    session = {
        "session_id": f"h_{uuid.uuid4().hex[:8]}",
        "name": name,
        "role": role,
        "blind": blind,
        "clip_id": clip_id,
        "clicks": clicks,
        "clip_score": scored["clip_score"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    sessions.append(session)
    print(f"HUMAN {json.dumps(session)}", flush=True)

    if current_mode() == "dev":
        path = data_dir() / "humans.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(session) + "\n")

    return {
        "clip_score": scored["clip_score"],
        "pattern": scored["pattern"],
        "hazards": scored["hazards"],
        "agents": _recorded_agents(clip_id) or scored.get("agents") or {},
    }
