"""Window proposer (SPEC 7.7, Appendix D)."""

from __future__ import annotations

import json

import pytest

from dh.windows import propose, write_proposal


def _row(
    track_id: int,
    t: float,
    risk: float,
    heading_in: bool = False,
    in_corridor: bool = False,
) -> dict:
    return {
        "track_id": track_id,
        "t": t,
        "risk": risk,
        "heading_in": heading_in,
        "in_corridor": in_corridor,
    }


def test_peak_below_06_returns_none():
    tracks = [
        _row(1, 0.0, 0.5, heading_in=True, in_corridor=True),
        _row(1, 0.2, 0.55, heading_in=True, in_corridor=True),
        _row(1, 0.4, 0.59, heading_in=True, in_corridor=True),
    ]
    assert propose(tracks, duration_s=10.0) is None


def test_three_heading_in_frames_set_onset_near_first_of_them():
    tracks = [
        _row(7, 0.0, 0.2),
        _row(7, 1.0, 0.65, heading_in=True),
        _row(7, 1.2, 0.7, heading_in=True),
        _row(7, 1.4, 0.75, heading_in=True),
        _row(7, 2.0, 0.8, heading_in=True, in_corridor=True),
    ]
    out = propose(tracks, duration_s=10.0)
    assert out is not None
    assert out["track_id"] == 7
    assert out["window"][0] == pytest.approx(1.0)
    assert out["confidence"] == 1.0


def test_window_longer_than_7s_is_clamped_and_confidence_is_04():
    tracks = [
        _row(2, 0.0, 0.7, heading_in=True),
        _row(2, 0.2, 0.72, heading_in=True),
        _row(2, 0.4, 0.74, heading_in=True),
        _row(2, 12.0, 0.9, in_corridor=True),
    ]
    out = propose(tracks, duration_s=20.0)
    assert out is not None
    assert out["confidence"] == 0.4
    ws, we = out["window"]
    assert we - ws == pytest.approx(7.0)
    assert ws == pytest.approx(0.0)
    assert we == pytest.approx(7.0)


def test_write_proposal_round_trips_json_in_tmp_path(tmp_path):
    proposal = {
        "track_id": 3,
        "window": [1.234567, 8.7654321],
        "confidence": 1.0,
    }
    path = write_proposal("clip_a", proposal, data_dir=str(tmp_path))
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == {
        "clip_id": "clip_a",
        "track_id": 3,
        "window": [1.235, 8.765],
        "confidence": 1.0,
    }

    none_path = write_proposal("clip_b", None, data_dir=str(tmp_path))
    none_loaded = json.loads(none_path.read_text(encoding="utf-8"))
    assert none_loaded == {
        "clip_id": "clip_b",
        "track_id": None,
        "window": None,
        "confidence": 0,
    }
