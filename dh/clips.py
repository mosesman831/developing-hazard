"""Clip loaders and the 30 second chunk definition.

Stdlib only. The pod imports this module. Loaders read ``DH_DATA_DIR``
(default ``data``): ``clips.json``, ``hazards.json`` and ``testset_v*.json``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

SEGMENT_OFFSETS_S = (0, 5, 10, 15, 20, 25)
SEGMENT_LENGTH_S = 5
CHUNK_LENGTH_S = 30
ONSET_MIN_S = 5
_META_KEYS = ("clip_id", "duration_s", "fps_sample", "segments")
_TESTSET_NAME = re.compile(r"testset_v(\d+)")


def data_dir() -> Path:
    return Path(os.environ.get("DH_DATA_DIR", "data"))


def load_clips() -> list[dict]:
    """``data/clips.json``."""
    return _load_list("clips.json")


def load_hazards() -> list[dict]:
    """``data/hazards.json``."""
    return _load_list("hazards.json")


def load_testset(testset_id: str | None = None) -> dict:
    """One frozen test set. The latest ``testset_vN`` when ``testset_id`` is omitted."""
    directory = data_dir()
    if testset_id:
        payload = _read_json(directory / f"{testset_id}.json")
    else:
        matches = []
        for path in directory.glob("testset_v*.json"):
            found = _TESTSET_NAME.fullmatch(path.stem)
            if found:
                matches.append((int(found.group(1)), path))
        if not matches:
            raise FileNotFoundError(f"no frozen test set in {directory}")
        payload = _read_json(max(matches)[1])
    if not isinstance(payload, dict):
        raise ValueError("test set must be an object")
    return payload


def clip_meta(clip: dict) -> dict:
    """Fields an agent may see. Never hazard or window fields."""
    return {key: clip[key] for key in _META_KEYS}


def segments_from_sources(
    sources: list[str],
    *,
    time_offset_s: float = 0.0,
) -> list[dict]:
    """Six segments at offsets 0, 5, 10, 15, 20 and 25 seconds, plus ``time_offset_s``."""
    if len(sources) != len(SEGMENT_OFFSETS_S):
        raise ValueError("a chunk has six segments")
    segments = []
    for offset_s, source in zip(SEGMENT_OFFSETS_S, sources):
        start_s = offset_s + time_offset_s
        segments.append(
            {
                "source": source,
                "start_s": float(start_s),
                "end_s": float(start_s + SEGMENT_LENGTH_S),
            }
        )
    return segments


def define_chunk_clip(
    sources: list[str],
    onset_s: float,
    previous_sources: list[str] | None = None,
) -> dict:
    """Clip definition for one 30 second chunk (SPEC 7.2).

    Hazard onset must be at least 5 seconds into the clip. If it is earlier,
    prepend the previous chunk of the same set (a 60 second clip) and shift
    this chunk by 30 seconds. Clip time 0 is the start of the first segment.
    """
    if onset_s < ONSET_MIN_S:
        if not previous_sources:
            raise ValueError(
                "onset is under 5 seconds and no previous chunk was given"
            )
        segments = segments_from_sources(previous_sources)
        segments.extend(
            segments_from_sources(sources, time_offset_s=CHUNK_LENGTH_S)
        )
        return {
            "segments": segments,
            "duration_s": float(CHUNK_LENGTH_S * 2),
            "onset_s": onset_s + CHUNK_LENGTH_S,
            "prepended": True,
        }
    return {
        "segments": segments_from_sources(sources),
        "duration_s": float(CHUNK_LENGTH_S),
        "onset_s": onset_s,
        "prepended": False,
    }


def read_json(name: str):
    return _read_json(data_dir() / name)


def write_json(name: str, payload) -> None:
    path = data_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_list(name: str) -> list[dict]:
    payload = read_json(name)
    if not isinstance(payload, list):
        raise ValueError(f"{name} must be a list")
    return payload


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
