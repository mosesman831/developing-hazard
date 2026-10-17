"""Verdict grid helpers (SPEC 12.3). Offline stub until Phase 3 Cosmos fill."""

from __future__ import annotations


def grid_times(
    samples: list[tuple[float, float]],
    duration_s: float,
    step_s: float = 0.5,
    risk_min: float = 0.3,
    dev_every_s: float = 3.0,
    include_dev_points: bool = True,
) -> list[float]:
    """Risk-threshold grid points plus optional dev check points every 3 s."""
    times: set[float] = set()
    for t, raw_scene_risk in samples:
        if raw_scene_risk >= risk_min:
            snapped = round(t / step_s) * step_s
            times.add(snapped)
    if include_dev_points:
        t = 0.0
        while t < duration_s:
            times.add(t)
            t += dev_every_s
    return sorted(times)


def lookup(points: list[dict], t: float) -> dict | None:
    """Latest point with point['t'] <= t. None if none."""
    best: dict | None = None
    for point in points:
        pt = float(point["t"])
        if pt <= t and (best is None or pt > float(best["t"])):
            best = point
    return best


def main() -> None:
    print("grid: offline stub, cosmos fill is phase 3")


if __name__ == "__main__":
    main()
