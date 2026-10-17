"""SPEC 9.7 pattern rules and click_time (9.5)."""

from __future__ import annotations

from dh.score import click_time, pattern_flag, score_clip


def _hazard(hazard_id: str, window_start: float, window_end: float) -> dict:
    return {
        "hazard_id": hazard_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def test_click_time_sums_blocking_latencies():
    assert click_time(1.0, [0.4, 0.5]) == 1.9


def test_too_many_clicks_flags_p1():
    clicks = [float(i) for i in range(9)]
    flag, reasons = pattern_flag(clicks, 30.0)
    assert flag is True
    assert "P1_too_many" in reasons


def test_burst_flags_p2_alone():
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


def test_pattern_flag_zeroes_the_clip():
    clicks = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 10.0, 14.0, 20.0]
    result = score_clip(clicks, [_hazard("h1", 6.0, 9.0)], 30.0)
    assert result["pattern"]["flag"] is True
    assert "P1_too_many" in result["pattern"]["reasons"]
    assert result["clip_score"] == 0
    assert result["hazard_points"] == {"h1": 0}
