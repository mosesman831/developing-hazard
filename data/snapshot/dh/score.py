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


def click_time(t_trigger: float, blocking_latencies_s: list[float]) -> float:
    """SPEC 9.5. t_click = t_trigger + sum of blocking latencies."""
    return t_trigger + sum(blocking_latencies_s)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _click_times(clicks: list) -> list[float]:
    times: list[float] = []
    for click in clicks:
        if isinstance(click, dict):
            times.append(float(click["t"]))
        else:
            times.append(float(click))
    return times


def _in_window(t: float, ws: float, we: float) -> bool:
    return _ms(ws) <= _ms(t) <= _ms(we)


def aggregate(rows: list[dict]) -> dict:
    """SPEC 9.4 over clip result dicts."""
    score = sum(int(row.get("clip_score", 0)) for row in rows)
    max_score = 5 * sum(len(row.get("hazard_points", {})) for row in rows)
    pct = score / max_score if max_score else 0.0

    total_hazards = 0
    hits = 0
    hit_points: list[int] = []
    flagged = 0
    total_clicks = 0
    false_clicks = 0
    reactions: list[float] = []
    leads: list[float] = []
    latencies: list[float] = []

    for row in rows:
        pattern = row.get("pattern") or {}
        if pattern.get("flag"):
            flagged += 1

        clicks = row.get("clicks") or []
        click_times = _click_times(clicks)
        total_clicks += len(click_times)

        windows: list[tuple[float, float]] = []
        for hazard in row.get("hazards") or []:
            window = hazard.get("window")
            if window and len(window) >= 2:
                windows.append((float(window[0]), float(window[1])))

        for t in click_times:
            if not any(_in_window(t, ws, we) for ws, we in windows):
                false_clicks += 1

        for hazard in row.get("hazards") or []:
            total_hazards += 1
            points = int(hazard.get("points", 0))
            if points >= 1:
                hits += 1
                hit_points.append(points)
                window = hazard.get("window") or [0.0, 0.0]
                ws, we = float(window[0]), float(window[1])
                first_click = hazard.get("first_click")
                if first_click is not None:
                    reactions.append(float(first_click) - ws)
                    leads.append(we - float(first_click))

        for call in row.get("calls") or []:
            if isinstance(call, dict) and call.get("latency_s") is not None:
                latencies.append(float(call["latency_s"]))

    n_clips = len(rows)
    hit_rate = hits / total_hazards if total_hazards else 0.0
    mean_points_when_hit = (
        sum(hit_points) / len(hit_points) if hit_points else 0.0
    )
    pattern_rate = flagged / n_clips if n_clips else 0.0
    clicks_per_clip = total_clicks / n_clips if n_clips else 0.0
    mean_latency_s = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        "score": score,
        "max": max_score,
        "pct": pct,
        "hit_rate": hit_rate,
        "mean_points_when_hit": mean_points_when_hit,
        "pattern_rate": pattern_rate,
        "clicks_per_clip": clicks_per_clip,
        "false_clicks": false_clicks,
        "median_reaction_s": _median(reactions),
        "median_lead_s": _median(leads),
        "mean_latency_s": mean_latency_s,
    }
