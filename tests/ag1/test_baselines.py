"""Baseline random clickers (Appendix E and F)."""

from __future__ import annotations

from dh.baselines import matched_chance, random_at_k, random_clicks
from dh.score import score_clip


def _sample_clip() -> dict:
    return {
        "duration_s": 30.0,
        "hazards": [
            {
                "hazard_id": "h1",
                "window_start": 6.0,
                "window_end": 9.0,
            }
        ],
    }


def test_matched_chance_k20_pattern_zeroes_clip():
    assert matched_chance([20], [_sample_clip()], n=50, seed=0) == 0.0


def test_random_at_k_zero_is_zero():
    assert random_at_k(0, [_sample_clip()], n=20, seed=0) == 0.0


def test_single_click_beats_zero_on_average():
    inside = random_at_k(1, [_sample_clip()], n=200, seed=1)
    assert inside > random_at_k(0, [_sample_clip()], n=200, seed=1)


def test_seeded_random_clicks_repeat():
    import random

    rng_a = random.Random(7)
    rng_b = random.Random(7)
    assert random_clicks(4, 30.0, rng_a) == random_clicks(4, 30.0, rng_b)


def test_random_clicks_sorted_and_empty():
    import random

    assert random_clicks(0, 10.0, random.Random(0)) == []
    times = random_clicks(3, 10.0, random.Random(0))
    assert times == sorted(times)
    assert all(0.0 <= t < 10.0 for t in times)


def test_matched_chance_inside_window_can_score():
    clip = _sample_clip()
    # One click fixed in the window should beat chance at k=0.
    got = matched_chance([1], [clip], n=100, seed=99)
    assert got > 0.0
    assert score_clip([7.0], clip["hazards"], clip["duration_s"])["clip_score"] > 0
