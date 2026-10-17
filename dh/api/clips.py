"""Clip list, clip detail, and tracks.

Live files under DH_DATA_DIR win. Missing or empty clip catalogues fall
back to contracts/examples/.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from dh.api._stubs import example_clips, example_hazards, example_tracks
from dh.clips import data_dir, load_clips, load_hazards

router = APIRouter()


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def load_clip_records() -> tuple[list[dict], list[dict], bool]:
    """Clips and hazards from the data directory, or the examples.

    The third value is true when the catalogue is the example file.
    Example tracks are only served in that case, so a real clip with no
    ``data/tracks`` file does not pick up placeholder boxes.
    """
    clips: list[dict] | None = None
    hazards: list[dict] | None = None
    try:
        loaded = load_clips()
        if loaded:
            clips = loaded
    except (OSError, ValueError):
        clips = None
    try:
        hazards = load_hazards()
    except (OSError, ValueError):
        hazards = None
    if not clips:
        return example_clips(), example_hazards(), True
    if hazards is None:
        hazards = []
    return clips, hazards, False


def _hazards_for(hazards: list[dict], clip_id: str) -> list[dict]:
    return [hazard for hazard in hazards if hazard.get("clip_id") == clip_id]


def clip_with_hazards(clip_id: str) -> tuple[dict, list[dict]] | None:
    clips, hazards, _examples = load_clip_records()
    for clip in clips:
        if clip.get("clip_id") == clip_id:
            return clip, _hazards_for(hazards, clip_id)
    return None


def media_sources() -> set[str]:
    """Segment sources and original videos the proxy is allowed to serve."""
    clips, _hazards, _examples = load_clip_records()
    sources: set[str] = set()
    for clip in clips:
        original = clip.get("original_video")
        if isinstance(original, str) and original:
            sources.add(original)
        for segment in clip.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            source = segment.get("source")
            if isinstance(source, str) and source:
                sources.add(source)
    return sources


def _summary(clip: dict, hazards: list[dict]) -> dict:
    clip_id = clip.get("clip_id")
    count = len(_hazards_for(hazards, clip_id))
    return {
        "clip_id": clip_id,
        "split": clip.get("split"),
        "duration_s": clip.get("duration_s"),
        "n_hazards": count,
        "label_status": "labelled" if count > 0 else "unlabelled",
    }


def _tracks_path(clip_id: str) -> Path | None:
    filename = f"{clip_id}.jsonl"
    if Path(filename).name != filename:
        return None
    return data_dir() / "tracks" / filename


@router.get("/api/clips")
def list_clips() -> list[dict]:
    clips, hazards, _examples = load_clip_records()
    return [_summary(clip, hazards) for clip in clips]


@router.get("/api/clips/{clip_id}")
def get_clip(clip_id: str, blind: str | None = None) -> dict:
    found = clip_with_hazards(clip_id)
    if found is None:
        raise HTTPException(status_code=404, detail="clip not found")
    clip, hazards = found
    payload = dict(clip)
    if blind == "1":
        payload.pop("hazards", None)
        return payload
    payload["hazards"] = hazards
    return payload


@router.get("/api/clips/{clip_id}/tracks")
def get_tracks(clip_id: str) -> list[dict]:
    if clip_with_hazards(clip_id) is None:
        raise HTTPException(status_code=404, detail="clip not found")
    path = _tracks_path(clip_id)
    if path is not None and path.is_file():
        return _read_jsonl(path)
    _clips, _hazards, examples = load_clip_records()
    if examples:
        return example_tracks(clip_id)
    return []


# ---- read-only inputs of the spatial view. A missing file is [] ("present but empty" is a
# different chip from 404 "missing"); the file name must be a plain name, so no path traversal.
def _safe_file(folder: Path, filename: str) -> Path | None:
    if Path(filename).name != filename or filename.startswith("."):
        return None
    return folder / filename


def _clip_file_rows(clip_id: str, folder: Path, suffix: str = ".jsonl") -> list[dict]:
    if clip_with_hazards(clip_id) is None:
        raise HTTPException(status_code=404, detail="clip not found")
    path = _safe_file(folder, f"{clip_id}{suffix}")
    if path is None:
        raise HTTPException(status_code=404, detail="clip not found")
    if not path.is_file():
        return []
    if suffix == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, list) else [doc]
    return _read_jsonl(path)


@router.get("/api/clips/{clip_id}/det")
def get_det(clip_id: str) -> list[dict]:
    return _clip_file_rows(clip_id, data_dir() / "det")


@router.get("/api/clips/{clip_id}/grid")
def get_grid(clip_id: str) -> list[dict]:
    return _clip_file_rows(clip_id, data_dir() / "grid" / "cosmos_verify_v2")


@router.get("/api/clips/{clip_id}/explain")
def get_explain(clip_id: str) -> list[dict]:
    return _clip_file_rows(clip_id, data_dir() / "cache" / "explain", ".json")


@router.get("/api/cameras/{camera_id}")
def get_camera(camera_id: str) -> dict:
    path = _safe_file(data_dir() / "cameras", f"{camera_id}.json")
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="no calibration for this camera")
    return json.loads(path.read_text(encoding="utf-8"))
