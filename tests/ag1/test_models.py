"""Round-trip checks for Phase 1 models against the contract examples."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dh.models import (
    Candidate,
    Clip,
    ClipMeta,
    ClipResult,
    Det,
    Hazard,
    HumanSession,
    Run,
    Track,
    clip_meta_from_clip,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"
_FORBIDDEN_META = {"hazards", "window_start", "window_end"}


def _load(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _load_jsonl(name: str) -> list[dict]:
    text = (EXAMPLES / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _round_trip(model, raw: dict) -> dict:
    dumped = model.model_validate(raw).model_dump(exclude_unset=True)
    assert dumped == raw
    return dumped


def test_clips_round_trip():
    raw = _load("clips.json")
    assert isinstance(raw, list)
    for item in raw:
        _round_trip(Clip, item)


def test_hazards_round_trip():
    raw = _load("hazards.json")
    assert isinstance(raw, list)
    for item in raw:
        dumped = _round_trip(Hazard, item)
        assert dumped["arbitrated_by"] is None
        assert dumped["auto_window"] is None


def test_testset_round_trip():
    # Imported here so pytest does not try to collect the TestSet model.
    from dh.models import TestSet

    _round_trip(TestSet, _load("testset_v0.json"))


def test_run_round_trip():
    _round_trip(Run, _load("run.json"))


def test_run_clips_round_trip():
    rows = _load_jsonl("run_clips.jsonl")
    assert rows
    for item in rows:
        dumped = _round_trip(ClipResult, item)
        assert dumped["explanation"] is None


def test_humans_round_trip():
    rows = _load_jsonl("humans.jsonl")
    assert rows
    for item in rows:
        _round_trip(HumanSession, item)


def test_tracks_round_trip():
    rows = _load_jsonl("tracks_c07.jsonl")
    assert rows
    for item in rows:
        _round_trip(Track, item)


def test_leaderboard_example_has_testset_and_rows():
    raw = _load("leaderboard.json")
    assert "testset_id" in raw
    assert "rows" in raw


def test_clip_meta_from_clip_has_no_hazard_fields():
    raw = _load("clips.json")[0]
    meta = clip_meta_from_clip(Clip.model_validate(raw))
    assert set(ClipMeta.model_fields) & _FORBIDDEN_META == set()
    assert set(ClipMeta.model_fields) == {
        "clip_id",
        "duration_s",
        "fps_sample",
        "segments",
    }
    dumped = meta.model_dump(exclude_unset=True)
    assert set(dumped) & _FORBIDDEN_META == set()
    assert dumped["clip_id"] == raw["clip_id"]
    assert dumped["duration_s"] == raw["duration_s"]
    assert dumped["fps_sample"] == raw["fps_sample"]
    assert dumped["segments"] == raw["segments"]


def test_clip_rejects_unknown_fields():
    raw = dict(_load("clips.json")[0])
    raw["hazards"] = []
    with pytest.raises(ValidationError):
        Clip.model_validate(raw)


def test_candidate_minimal_round_trip():
    raw = {
        "candidate_id": "pie_set03_c0014",
        "camera_id": "pie_cam-3",
        "original_video": "s3://example/video.mp4",
        "segments": ["s3://example/segment_001.mp4"],
        "found_by": "search",
        "status": "new",
    }
    assert Candidate.model_validate(raw).model_dump(exclude_unset=True) == raw


def test_det_round_trip():
    raw = {
        "t": 6.4,
        "frame": 192,
        "cls": "person",
        "conf": 0.82,
        "xyxy": [812, 402, 861, 540],
    }
    assert Det.model_validate(raw).model_dump(exclude_unset=True) == raw


def test_track_null_ttc_round_trips():
    raw = {
        "track_id": 4,
        "t": 16.8,
        "cls": "person",
        "xyxy": [812, 402, 861, 540],
        "risk": 0.61,
        "ttc": None,
        "t_lat": None,
    }
    assert Track.model_validate(raw).model_dump(exclude_unset=True) == raw
