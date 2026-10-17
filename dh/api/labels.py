"""Label routes owned by AG2 (contracts/api_routes.md).

Skeleton for Phase 1. Reads and writes the JSON files in ``DH_DATA_DIR``
(default ``data``). Tests point that directory at a copy of
``contracts/examples/`` so the contract files stay untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

from dh.clips import data_dir, load_clips, load_hazards, write_json


def _has_lone_surrogate(value: object) -> bool:
    """True when a parsed JSON value contains a lone UTF-16 surrogate."""
    if isinstance(value, str):
        return any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    if isinstance(value, dict):
        return any(
            _has_lone_surrogate(key) or _has_lone_surrogate(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_lone_surrogate(item) for item in value)
    return False


def _json_has_lone_surrogate(raw: bytes) -> bool:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return _has_lone_surrogate(payload)


def _rejects_surrogate_input(method: str, path: str) -> bool:
    if method != "POST":
        return False
    if path.rstrip("/") == "/api/hazards":
        return True
    parts = [part for part in path.split("/") if part]
    return len(parts) == 4 and parts[:2] == ["api", "clips"] and parts[3] == "status"


class _SurrogateGuardRoute(APIRoute):
    """Reject lone surrogates before the response encoder sees them."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            if _rejects_surrogate_input(request.method, request.url.path):
                raw = await request.body()
                if raw and _json_has_lone_surrogate(raw):
                    return JSONResponse(
                        status_code=422,
                        content={"detail": "input contains a lone UTF-16 surrogate"},
                    )
            return await original(request)

        return handler


router = APIRouter(route_class=_SurrogateGuardRoute)

HazardType = Literal[
    "pedestrian_crossing",
    "vehicle_pulling_out",
    "vehicle_cut_in",
    "lead_vehicle_braking",
    "cyclist",
    "vehicle_turning_across",
    "other",
]
ClipStatus = Literal["no_hazard", "rejected"]

_AGREE_START_S = 0.6
_AGREE_END_S = 0.8
_HAZARD_SUFFIX = re.compile(r"_h(\d+)$")
_STATUS_NOTE = re.compile(r"\s*\[status:(?:no_hazard|rejected)\]$")
_TESTSET_NAME = re.compile(r"testset_v(\d+)")


class HazardBody(BaseModel):
    labeller: str
    ws: float
    we: float
    type: HazardType
    description: str


class HazardCreate(HazardBody):
    clip_id: str


class ClipStatusBody(BaseModel):
    status: ClipStatus


@router.put("/api/hazards/{hazard_id}")
def put_hazard(hazard_id: str, body: HazardBody) -> dict:
    """Save one labeller window onto an existing hazard."""
    _check_window(body.ws, body.we)
    hazards = _hazards()
    for index, hazard in enumerate(hazards):
        if hazard.get("hazard_id") == hazard_id:
            updated = _apply_labeller(hazard, body)
            hazards[index] = updated
            write_json("hazards.json", hazards)
            return visible_hazard(updated, body.labeller)
    raise HTTPException(status_code=404, detail="hazard not found")


@router.post("/api/hazards", status_code=201)
def post_hazard(body: HazardCreate) -> dict:
    """Add a hazard to a clip."""
    _check_window(body.ws, body.we)
    if not body.clip_id or not body.labeller:
        raise HTTPException(status_code=422, detail="clip_id and labeller are required")
    hazards = _hazards()
    hazard = {
        "hazard_id": _next_hazard_id(hazards, body.clip_id),
        "clip_id": body.clip_id,
        "type": body.type,
        "window_start": body.ws,
        "window_end": body.we,
        "labellers": {body.labeller: [body.ws, body.we]},
        "agreed": False,
        "arbitrated_by": None,
        "auto_window": None,
        "track_id": None,
        "segment_sources": [],
        "description": body.description,
    }
    hazard["segment_sources"] = _sources_for_window(body.clip_id, body.ws, body.we)
    hazards.append(hazard)
    write_json("hazards.json", hazards)
    return visible_hazard(hazard, body.labeller)


@router.post("/api/clips/{clip_id}/status")
def post_clip_status(clip_id: str, body: ClipStatusBody) -> dict:
    """Mark a clip ``no_hazard`` (moved to dev) or ``rejected``."""
    try:
        clips = load_clips()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="clips.json is missing")
    for clip in clips:
        if clip.get("clip_id") != clip_id:
            continue
        notes = _STATUS_NOTE.sub("", clip.get("notes") or "")
        clip["notes"] = f"{notes} [status:{body.status}]".strip()
        if body.status == "no_hazard":
            clip["split"] = "dev"
        write_json("clips.json", clips)
        return clip
    raise HTTPException(status_code=404, detail="clip not found")


@router.post("/api/testset/freeze")
def post_testset_freeze() -> dict:
    """Freeze agreed test-split hazards into the next ``testset_vN`` file."""
    try:
        return _freeze_testset()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="clips or hazards are missing") from exc


@router.get("/api/clips/{clip_id}/proposal")
def get_proposal(clip_id: str) -> dict:
    """Auto window only after both labellers have saved, and only from a proposal file.

    This skeleton does not invent a window. A missing file is a 404.
    """
    if not _both_labellers_saved(clip_id):
        raise HTTPException(status_code=404, detail="proposal is not available")
    path = data_dir() / "proposals" / f"{clip_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="proposal is not available")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=404, detail="proposal is not available")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=404, detail="proposal is not available")
    return payload


def agreement_summary(hazards: list[dict]) -> dict:
    """Count labeller windows and pairwise agreement without mutating hazards."""
    windows = 0
    paired = 0
    agreed = 0
    for hazard in hazards:
        labellers = hazard.get("labellers")
        if not isinstance(labellers, dict):
            continue
        hazard_windows = [window for window in labellers.values() if _is_window(window)]
        if hazard_windows:
            windows += 1
        if len(hazard_windows) >= 2:
            paired += 1
            starts = [window[0] for window in hazard_windows]
            ends = [window[1] for window in hazard_windows]
            if (
                max(starts) - min(starts) <= _AGREE_START_S
                and max(ends) - min(ends) <= _AGREE_END_S
            ):
                agreed += 1
    return {
        "windows": windows,
        "paired": paired,
        "agreed": agreed,
        "status_text": f"{agreed} of {paired} windows agreed within tolerance",
    }


def visible_hazard(hazard: dict, caller: str) -> dict:
    """Return hazard JSON safe for the caller (HTTP); disk keeps the full record."""
    out = dict(hazard)
    labellers = dict(hazard.get("labellers") or {})
    if caller and caller in labellers:
        out["labellers"] = labellers
        if "auto_window" not in out:
            out["auto_window"] = None
    else:
        kept = {caller: labellers[caller]} if caller and caller in labellers else {}
        out["labellers"] = kept
        out["auto_window"] = None
    return out


def _hazards() -> list[dict]:
    try:
        return load_hazards()
    except FileNotFoundError:
        return []


def _check_window(ws: float, we: float) -> None:
    if we <= ws:
        raise HTTPException(status_code=422, detail="we must be after ws")


def _apply_labeller(hazard: dict, body: HazardBody) -> dict:
    if not body.labeller:
        raise HTTPException(status_code=422, detail="labeller is required")
    updated = dict(hazard)
    labellers = dict(updated.get("labellers") or {})
    labellers[body.labeller] = [body.ws, body.we]
    updated["labellers"] = labellers
    updated["type"] = body.type
    updated["description"] = body.description
    windows = [window for window in labellers.values() if _is_window(window)]
    if len(windows) >= 2:
        starts = [window[0] for window in windows]
        ends = [window[1] for window in windows]
        if (
            max(starts) - min(starts) <= _AGREE_START_S
            and max(ends) - min(ends) <= _AGREE_END_S
        ):
            updated["window_start"] = round(sum(starts) / len(starts), 3)
            updated["window_end"] = round(sum(ends) / len(ends), 3)
            updated["agreed"] = True
        else:
            updated["agreed"] = False
    else:
        updated["window_start"] = body.ws
        updated["window_end"] = body.we
        updated["agreed"] = False
    if "auto_window" not in updated:
        updated["auto_window"] = None
    updated["segment_sources"] = _sources_for_window(
        str(updated.get("clip_id") or ""),
        float(updated["window_start"]),
        float(updated["window_end"]),
    ) or list(updated.get("segment_sources") or [])
    return updated


def _is_window(window: object) -> bool:
    return (
        isinstance(window, list)
        and len(window) == 2
        and all(isinstance(value, (int, float)) for value in window)
    )


def _next_hazard_id(hazards: list[dict], clip_id: str) -> str:
    numbers = []
    prefix = f"{clip_id}_h"
    for hazard in hazards:
        hazard_id = hazard.get("hazard_id")
        if not isinstance(hazard_id, str) or not hazard_id.startswith(prefix):
            continue
        found = _HAZARD_SUFFIX.search(hazard_id)
        if found:
            numbers.append(int(found.group(1)))
    nxt = max(numbers) + 1 if numbers else 1
    return f"{prefix}{nxt}"


def _both_labellers_saved(clip_id: str) -> bool:
    try:
        hazards = load_hazards()
    except FileNotFoundError:
        return False
    matched = [hazard for hazard in hazards if hazard.get("clip_id") == clip_id]
    if not matched:
        return False
    for hazard in matched:
        labellers = hazard.get("labellers")
        if not isinstance(labellers, dict) or len(labellers) < 2:
            return False
    return True


def _next_testset_version() -> int:
    versions = []
    for path in data_dir().glob("testset_v*.json"):
        found = _TESTSET_NAME.fullmatch(path.stem)
        if found:
            versions.append(int(found.group(1)))
    return max(versions) + 1 if versions else 0


def _sources_for_window(clip_id: str, ws: float, we: float) -> list[str]:
    """Segment sources whose clip-time span overlaps the window."""
    try:
        clips = load_clips()
    except FileNotFoundError:
        return []
    for clip in clips:
        if clip.get("clip_id") != clip_id:
            continue
        sources = []
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
    return []


def _in_test_split(clip: dict | None) -> bool:
    """Dev clips and rejected or no-hazard clips stay out of a frozen test set."""
    if not clip or clip.get("split") != "test":
        return False
    notes = clip.get("notes") or ""
    if "[status:rejected]" in notes or "[status:no_hazard]" in notes:
        return False
    return True


def _freeze_testset() -> dict:
    """Run the same logic as POST /api/testset/freeze without the HTTP layer."""
    hazards = load_hazards()
    clips = load_clips()
    clip_by_id = {clip.get("clip_id"): clip for clip in clips}
    agreed = [hazard for hazard in hazards if hazard.get("agreed") is True]
    clip_ids: list[str] = []
    hazard_ids: list[str] = []
    for hazard in agreed:
        clip_id = hazard.get("clip_id")
        hazard_id = hazard.get("hazard_id")
        if not _in_test_split(clip_by_id.get(clip_id)):
            continue
        if clip_id not in clip_ids:
            clip_ids.append(clip_id)
        if isinstance(hazard_id, str):
            hazard_ids.append(hazard_id)
    testset_id = f"testset_v{_next_testset_version()}"
    payload = {
        "testset_id": testset_id,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "clips": clip_ids,
        "hazards": hazard_ids,
        "scorer_version": "score_v1",
        "pattern_version": "PATTERN_V1",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["sha256"] = hashlib.sha256(canonical).hexdigest()
    write_json(f"{testset_id}.json", payload)
    return payload


if __name__ == "__main__":
    result = _freeze_testset()
    print(result["testset_id"])
    print(result["sha256"])
