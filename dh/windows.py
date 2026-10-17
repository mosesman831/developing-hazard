"""Hazard window proposer (SPEC 7.7, Appendix D)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

_DECIMALS = 3
_ONSET_RUN = 3
_ONSET_BACK_S = 0.4
_PEAK_FALLBACK_ONSET_S = 3.0
_MIN_LEN_S = 1.0
_MAX_LEN_S = 7.0
_PEAK_RISK_MIN = 0.6


def propose(tracks: list[dict], duration_s: float) -> dict | None:
    """Appendix D.

    ``tracks`` are rows with track_id, t, risk, heading_in, in_corridor.

    Hazard track: highest peak risk, and that peak must be >= 0.6, else None.

    Onset: first time heading_in or in_corridor stays true for 3 consecutive rows
    of that track, then onset = that row's t - 0.4 (5 fps). If never,
    onset = peak.t - 3.

    End: first row with t > onset and in_corridor True; else the peak row.

    Clamp to [0, duration_s]. If length is outside 1 to 7 seconds, confidence 0.4
    and clamp length into [1, 7] without exceeding duration_s. Else confidence 1.0.

    Return {"track_id": int, "window": [ws, we], "confidence": float}.

    Assumption: in_corridor is the inner corridor. heading_in or in_corridor counts
    as the outer-margin onset test, because dh.risk does not emit a separate
    outer-margin flag.
    """
    if not tracks:
        return None

    by_id: dict[int, list[dict]] = defaultdict(list)
    for row in tracks:
        by_id[int(row["track_id"])].append(row)
    for states in by_id.values():
        states.sort(key=lambda s: float(s["t"]))

    best_tid: int | None = None
    best_peak: dict | None = None
    best_peak_risk = -1.0
    for tid, states in by_id.items():
        peak = max(states, key=lambda s: float(s["risk"]))
        if float(peak["risk"]) < _PEAK_RISK_MIN:
            continue
        risk = float(peak["risk"])
        if risk > best_peak_risk:
            best_peak_risk = risk
            best_tid = tid
            best_peak = peak

    if best_tid is None or best_peak is None:
        return None

    states = by_id[best_tid]
    onset: float | None = None
    run = 0
    for row in states:
        if row["heading_in"] or row["in_corridor"]:
            run += 1
        else:
            run = 0
        if run >= _ONSET_RUN:
            onset = float(row["t"]) - _ONSET_BACK_S
            break

    if onset is None:
        onset = float(best_peak["t"]) - _PEAK_FALLBACK_ONSET_S

    end_row = best_peak
    for row in states:
        if float(row["t"]) > onset and row["in_corridor"]:
            end_row = row
            break

    ws = max(0.0, onset)
    we = min(float(duration_s), float(end_row["t"]))

    conf = 1.0
    if not (_MIN_LEN_S <= we - ws <= _MAX_LEN_S):
        conf = 0.4
        we = min(ws + _MAX_LEN_S, max(we, ws + _MIN_LEN_S))
        we = min(we, float(duration_s))

    return {
        "track_id": best_tid,
        "window": [ws, we],
        "confidence": conf,
    }


def _round_window(window: list[float] | None) -> list[float] | None:
    if window is None:
        return None
    return [round(float(window[0]), _DECIMALS), round(float(window[1]), _DECIMALS)]


def write_proposal(clip_id: str, proposal: dict | None, data_dir: str = "data") -> Path:
    """Write data/proposals/<clip_id>.json. Include clip_id.

    If proposal is None, write
    {"clip_id", "window": null, "confidence": 0, "track_id": null}.

    Round window ends to 3 decimals.
    """
    path = Path(data_dir) / "proposals" / f"{clip_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if proposal is None:
        payload = {
            "clip_id": clip_id,
            "window": None,
            "confidence": 0,
            "track_id": None,
        }
    else:
        window = _round_window(proposal["window"])
        payload = {
            "clip_id": clip_id,
            "track_id": proposal["track_id"],
            "window": window,
            "confidence": proposal["confidence"],
        }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
