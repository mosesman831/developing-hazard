"""Random click baselines (SPEC 7.10.7, Appendix E). Stdlib only."""

from __future__ import annotations

import random

from dh import config
from dh.score import score_clip


def random_clicks(k: int, duration_s: float, rng) -> list[float]:
    """k times uniform in [0, duration_s), sorted. k=0 -> []."""
    if k <= 0:
        return []
    return sorted(rng.uniform(0.0, duration_s) for _ in range(k))


def random_at_k(
    k: int,
    clips: list[dict],
    n: int | None = None,
    seed: int = 0,
) -> float:
    """Average score_clip pct over n draws (default dh.config.random_draws_per_k)."""
    draws = n if n is not None else config.random_draws_per_k
    total_hazards = sum(len(clip.get("hazards") or []) for clip in clips)
    if total_hazards == 0:
        return 0.0
    max_score = 5 * total_hazards
    rng = random.Random(seed)
    total_pct = 0.0
    for _ in range(draws):
        clip_score = 0
        for clip in clips:
            duration_s = float(clip["duration_s"])
            hazards = clip.get("hazards") or []
            times = random_clicks(k, duration_s, rng)
            clip_score += score_clip(times, hazards, duration_s)["clip_score"]
        total_pct += clip_score / max_score
    return total_pct / draws


def matched_chance(
    clicks_per_clip: list[int],
    clips: list[dict],
    n: int = 1000,
    seed: int = 0,
) -> float:
    """Appendix E: random clicker at the agent's click count per clip."""
    rng = random.Random(seed)
    max_score = sum(5 * len(clip.get("hazards") or []) for clip in clips)
    if max_score == 0:
        return 0.0
    got = 0.0
    for k, clip in zip(clicks_per_clip, clips):
        duration_s = float(clip["duration_s"])
        hazards = clip.get("hazards") or []
        for _ in range(n):
            times = random_clicks(k, duration_s, rng)
            got += score_clip(times, hazards, duration_s)["clip_score"] / n
    return got / max_score
