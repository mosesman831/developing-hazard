"""Human sit sessions, scored on the server."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from dh.api._stubs import current_mode, try_score_clip
from dh.api.clips import clip_with_hazards
from dh.clips import data_dir

router = APIRouter()

_ROLES = frozenset({"team", "judge", "guest"})

sessions: list[dict] = []


def _clicks(body: dict) -> list[float]:
    raw = body.get("clicks", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="clicks must be a list of numbers")
    clicks: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise HTTPException(status_code=422, detail="clicks must be a list of numbers")
        clicks.append(float(item))
    return clicks


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
    scored = try_score_clip(clicks, [dict(hazard) for hazard in hazards], float(clip["duration_s"]))
    session = {
        "session_id": f"h_{uuid.uuid4().hex[:8]}",
        "name": name,
        "role": role,
        "blind": blind,
        "clip_id": clip_id,
        "clicks": clicks,
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
        "agents": scored.get("agents") or {},
    }
