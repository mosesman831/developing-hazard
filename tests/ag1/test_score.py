"""SPEC 9.6 and 9.7 checks for the DVSA scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dh.score import PATTERN_VERSION, SCORER_VERSION, hazard_points, pattern_flag, score_clip

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"


def _hazard(hazard_id: str, window_start: float, window_end: float) -> dict:
    return {
        "hazard_id": hazard_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def _points(clicks: list[float], window_start: float, window_end: float) -> int:
    result = score_clip(clicks, [_hazard("h1", window_start, window_end)], 30.0)
    return result["hazard_points"]["h1"]


def test_scorer_versions():
    assert SCORER_VERSION == "score_v1"
    assert PATTERN_VERSION == "PATTERN_V1"


def test_worked_example_bands():
    # Window 6.0 to 9.0. Each fifth is 0.6 s. An edge goes to the later band.
    expected = [
        (5.8, 0),
        (6.0, 5),
        (6.6, 4),
        (7.3, 3),
        (8.99, 1),
        (9.2, 0),
    ]
    for click, points in expected:
        assert _points([click], 6.0, 9.0) == points

    clicks = [5.8, 7.3, 8.99]
    result = score_clip(clicks, [_hazard("h1", 6.0, 9.0)], 30.0)
    assert clicks == [5.8, 7.3, 8.99]
    assert result["hazard_points"]["h1"] == 3
    assert result["clip_score"] == 3
    assert result["pattern"]["flag"] is False
    assert result["hazards"][0]["first_click"] == 7.3


def test_window_edges():
    # At the start, on the first inner edge, at the end, and 10 ms after.
    assert _points([6.0], 6.0, 9.0) == 5
    assert _points([6.6], 6.0, 9.0) == 4
    assert _points([9.0], 6.0, 9.0) == 1
    assert _points([9.0 + 0.010], 6.0, 9.0) == 0


def test_two_point_zero_one_seconds_rounds_to_2010_ms():
    assert round(2.01 * 1000) == 2010
    assert int(2.01 * 1000) == 2009
    # ws 2000, we 2050, click 2010. band = min(4, 5 * 10 // 50) = 1, points 4.
    assert hazard_points([2010], 2000, 2050) == 4
    assert _points([2.01], 2.0, 2.05) == 4


def test_first_click_in_the_window_counts():
    clicks = [8.99, 6.0]
    result = score_clip(clicks, [_hazard("h1", 6.0, 9.0)], 30.0)
    assert clicks == [8.99, 6.0]
    assert result["hazard_points"]["h1"] == 5
    assert result["clip_score"] == 5
    assert result["hazards"][0]["first_click"] == 6.0


def test_two_hazards_points_add():
    hazards = [
        _hazard("a", 6.0, 9.0),
        _hazard("b", 12.0, 15.0),
    ]
    result = score_clip([6.0, 12.0], hazards, 30.0)
    assert result["hazard_points"] == {"a": 5, "b": 5}
    assert result["clip_score"] == 10
    assert result["pattern"] == {"flag": False, "reasons": []}


def test_too_many_clicks_flags_p1():
    clicks = [float(i) for i in range(9)]
    flag, reasons = pattern_flag(clicks, 30.0)
    assert flag is True
    assert "P1_too_many" in reasons


def test_burst_flags_p2_alone():
    # Uneven gaps, all inside 2 s. Five clicks, so P1 does not fire.
    # cv is well above 0.15, and two occupied 1 s bins on a 30 s clip is not P4.
    clicks = [0.0, 0.05, 0.1, 0.4, 1.5]
    flag, reasons = pattern_flag(clicks, 30.0)
    assert flag is True
    assert reasons == ["P2_burst"]


def test_rhythm_flags_p3():
    clicks = [0.0, 3.0, 6.0, 9.0, 12.0]
    flag, reasons = pattern_flag(clicks, 30.0)
    assert flag is True
    assert reasons == ["P3_rhythm"]


def test_coverage_flags_p4_alone():
    clicks = [0.1, 1.1, 2.1]
    flag, reasons = pattern_flag(clicks, 3.0)
    assert flag is True
    assert reasons == ["P4_coverage"]


def test_three_spaced_clicks_are_not_flagged():
    flag, reasons = pattern_flag([6.5, 7.0, 12.0], 30.0)
    assert flag is False
    assert reasons == []
    result = score_clip([6.5, 7.0, 12.0], [_hazard("h1", 6.0, 9.0)], 30.0)
    assert result["pattern"] == {"flag": False, "reasons": []}


def test_pattern_flag_zeroes_the_clip():
    clicks = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 10.0, 14.0, 20.0]
    result = score_clip(clicks, [_hazard("h1", 6.0, 9.0)], 30.0)
    assert result["pattern"]["flag"] is True
    assert "P1_too_many" in result["pattern"]["reasons"]
    assert result["clip_score"] == 0
    assert result["hazard_points"] == {"h1": 0}
    assert result["hazards"][0]["points"] == 0
    assert result["hazards"][0]["first_click"] == 6.0


def test_bad_window_raises():
    with pytest.raises(ValueError, match="bad window"):
        hazard_points([6000], 6000, 6000)
    with pytest.raises(ValueError, match="bad window"):
        score_clip([6.0], [_hazard("h1", 6.0, 6.0)], 30.0)
    with pytest.raises(ValueError, match="bad window"):
        score_clip([], [_hazard("h1", 9.0, 6.0)], 30.0)


def test_empty_clicks_on_example_hazard():
    hazards = json.loads((EXAMPLES / "hazards.json").read_text(encoding="utf-8"))
    result = score_clip([], hazards, 30.0)
    assert set(result) == {"clip_score", "pattern", "hazard_points", "hazards"}
    assert result["clip_score"] == 0
    assert result["pattern"] == {"flag": False, "reasons": []}
    assert result["hazard_points"] == {"c07_h1": 0}
    row = result["hazards"][0]
    assert row["hazard_id"] == "c07_h1"
    assert row["window"] == [16.2, 19.0]
    assert row["points"] == 0
    assert row["first_click"] is None
