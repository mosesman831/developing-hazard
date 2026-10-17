"""DVSA-style clip scoring (SPEC 9).

Stdlib only: the pod imports this module. Click times arrive in seconds and
are converted with round(t * 1000) before the band calculation. int() is the
wrong conversion: int(2.01 * 1000) is 2009.
"""

from __future__ import annotations

SCORER_VERSION: str = "score_v1"
PATTERN_VERSION: str = "PATTERN_V1"


def hazard_points(clicks_ms: list[int], ws_ms: int, we_ms: int) -> int:
    """First click inside [ws, we] scores 5..1 by fifth of the window."""
    if we_ms <= ws_ms:
        raise ValueError("bad window")
    inside = [t for t in sorted(clicks_ms) if ws_ms <= t <= we_ms]
    if not inside:
        return 0
    band = min(4, 5 * (inside[0] - ws_ms) // (we_ms - ws_ms))  # 0..4
    return 5 - band


def pattern_flag(clicks: list[float], clip_len: float) -> tuple[bool, list[str]]:
    """PATTERN_V1. The rules see clicks and clip length only, never labels."""
    reasons = []
    c = sorted(clicks)
    if len(c) > 8:
        reasons.append("P1_too_many")
    j = 0
    for i in range(len(c)):
        while c[i] - c[j] > 2.0:
            j += 1
        if i - j + 1 > 4:
            reasons.append("P2_burst")
            break
    if len(c) >= 5:
        gaps = [b - a for a, b in zip(c, c[1:])]
        mu = sum(gaps) / len(gaps)
        sd = (sum((g - mu) ** 2 for g in gaps) / len(gaps)) ** 0.5
        if mu > 0 and sd / mu < 0.15:
            reasons.append("P3_rhythm")
    bins = max(1, int(clip_len))
    hit = {int(t) for t in c if 0 <= t < clip_len}
    if len(hit) / bins > 0.7:
        reasons.append("P4_coverage")
    return (len(reasons) > 0, reasons)


def _ms(t: float) -> int:
    return round(t * 1000)


def score_clip(clicks: list[float], hazards: list[dict], duration_s: float) -> dict:
    """Score one clip.

    clicks are clip-time seconds, in any order. hazards are hazard dicts
    (hazard_id, window_start, window_end, and the rest of the label).

    Returns clip_score, pattern, hazard_points, and a per-hazard breakdown.
    first_click is the earliest click time in seconds that falls inside the
    window under the same millisecond comparison, or None. A pattern flag
    zeroes points but still reports that click.
    """
    flag, reasons = pattern_flag(clicks, duration_s)
    clicks_ms = [_ms(t) for t in clicks]

    points_by_id: dict[str, int] = {}
    breakdown: list[dict] = []
    for hazard in hazards:
        hazard_id = hazard["hazard_id"]
        window_start = hazard["window_start"]
        window_end = hazard["window_end"]
        ws_ms = _ms(window_start)
        we_ms = _ms(window_end)
        # A bad window raises here and is not swallowed.
        raw = hazard_points(clicks_ms, ws_ms, we_ms)
        points = 0 if flag else raw
        inside = [t for t in clicks if ws_ms <= _ms(t) <= we_ms]
        first_click = min(inside) if inside else None
        points_by_id[hazard_id] = points
        breakdown.append(
            {
                "hazard_id": hazard_id,
                "window": [window_start, window_end],
                "points": points,
                "first_click": first_click,
            }
        )

    clip_total = 0 if flag else sum(points_by_id.values())
    return {
        "clip_score": clip_total,
        "pattern": {"flag": flag, "reasons": reasons},
        "hazard_points": points_by_id,
        "hazards": breakdown,
    }
