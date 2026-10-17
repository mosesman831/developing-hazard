"""IoU tracker and track export (SPEC 7.5, Appendix C)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

_HISTORY_S = 0.6
_DECIMALS = 3

_ROW_KEYS = (
    "track_id",
    "t",
    "cls",
    "xyxy",
    "vx",
    "vy",
    "h_rate",
    "in_corridor",
    "heading_in",
    "ttc",
    "t_lat",
    "risk",
)
_REQUIRED_KEYS = ("track_id", "t", "cls", "xyxy", "risk")


@dataclass
class LiveTrack:
    """A track seen on this frame, with centre velocity and scale rate."""

    id: int
    cls: str
    t: float
    xyxy: list[float]  # same units as the detection (pixels)
    vx: float  # px/s of centre x
    vy: float
    h: float
    h_rate: float  # d(log h)/dt
    cx: float
    cy: float


class _HistTrack:
    def __init__(self, tid: int, cls: str, t: float, xyxy: list[float]) -> None:
        self.id = tid
        self.cls = cls
        self.hist: list[tuple[float, list[float]]] = [(t, list(xyxy))]
        self.misses = 0

    def predict(self, t: float) -> list[float]:
        """Move each corner at its recent constant velocity."""
        last_t, last_box = self.hist[-1]
        window = _window(self.hist, t)
        if len(window) < 2:
            return list(last_box)
        dt = t - last_t
        predicted: list[float] = []
        for corner in range(4):
            slope = _slope([(sample_t, box[corner]) for sample_t, box in window])
            predicted.append(last_box[corner] + slope * dt)
        return predicted

    def live(self, t: float) -> LiveTrack:
        xyxy = list(self.hist[-1][1])
        vx, vy, h, h_rate, cx, cy = _kinematics(self.hist, t)
        return LiveTrack(
            id=self.id,
            cls=self.cls,
            t=t,
            xyxy=xyxy,
            vx=vx,
            vy=vy,
            h=h,
            h_rate=h_rate,
            cx=cx,
            cy=cy,
        )


def _window(
    hist: list[tuple[float, list[float]]], t_now: float
) -> list[tuple[float, list[float]]]:
    earliest = t_now - _HISTORY_S
    return [(t, box) for t, box in hist if t >= earliest]


def _slope(samples: list[tuple[float, float]]) -> float:
    """Least-squares slope of y against t. Zero when the fit is undefined."""
    n = len(samples)
    if n < 2:
        return 0.0
    mean_t = sum(t for t, _ in samples) / n
    mean_y = sum(y for _, y in samples) / n
    var_t = sum((t - mean_t) ** 2 for t, _ in samples)
    if var_t == 0.0:
        return 0.0
    cov = sum((t - mean_t) * (y - mean_y) for t, y in samples)
    return cov / var_t


def _centre(xyxy: list[float]) -> tuple[float, float]:
    return (xyxy[0] + xyxy[2]) / 2.0, (xyxy[1] + xyxy[3]) / 2.0


def _height(xyxy: list[float]) -> float:
    return xyxy[3] - xyxy[1]


def _kinematics(
    hist: list[tuple[float, list[float]]], t_now: float
) -> tuple[float, float, float, float, float, float]:
    xyxy = hist[-1][1]
    cx, cy = _centre(xyxy)
    h = _height(xyxy)
    window = _window(hist, t_now)
    if len(window) < 2:
        return 0.0, 0.0, h, 0.0, cx, cy
    vx = _slope([(t, _centre(box)[0]) for t, box in window])
    vy = _slope([(t, _centre(box)[1]) for t, box in window])
    log_h: list[tuple[float, float]] = []
    for t, box in window:
        height = _height(box)
        if height > 0.0:
            log_h.append((t, math.log(height)))
    h_rate = _slope(log_h) if len(log_h) >= 2 else 0.0
    return vx, vy, h, h_rate, cx, cy


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_w = min(ax2, bx2) - max(ax1, bx1)
    inter_h = min(ay2, by2) - max(ay1, by1)
    if inter_w <= 0.0 or inter_h <= 0.0:
        return 0.0
    inter = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def _cls_xyxy(det) -> tuple[str, list[float]]:
    if isinstance(det, dict):
        cls = det["cls"]
        raw = det["xyxy"]
    else:
        cls = det.cls
        raw = det.xyxy
    return str(cls), [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])]


class IoUTracker:
    """Greedy same-class IoU association with constant-velocity corners."""

    def __init__(self, iou_min: float = 0.3, max_misses: int = 3) -> None:
        self.iou_min = iou_min
        self.max_misses = max_misses
        self._tracks: list[_HistTrack] = []
        self._next_id = 1

    def update(self, t: float, dets: list) -> list[LiveTrack]:
        """Associate detections at time t and return tracks seen on this frame.

        Dets have .cls and .xyxy (len 4), or are dicts with those keys.
        Match same class only. Predict box corners with constant velocity.
        IoU >= iou_min assigns the det. Unmatched tracks gain a miss.
        Drop tracks with misses > max_misses. New tracks get ids starting at 1.
        Return only tracks with misses == 0.
        Velocities: least-squares slope of cx, cy, and log(h) over history
        with t >= current_t - 0.6. If fewer than 2 samples, velocity and
        h_rate are 0.
        """
        unmatched = [_cls_xyxy(det) for det in dets]
        for tr in self._tracks:
            pred = tr.predict(t)
            best_i: int | None = None
            best_score = -1.0
            for i, (cls, xyxy) in enumerate(unmatched):
                score = _iou(pred, xyxy) if cls == tr.cls else -1.0
                if best_i is None or score > best_score:
                    best_i = i
                    best_score = score
            matched = (
                best_i is not None
                and unmatched[best_i][0] == tr.cls
                and best_score >= self.iou_min
            )
            if matched and best_i is not None:
                tr.hist.append((t, list(unmatched[best_i][1])))
                tr.misses = 0
                del unmatched[best_i]
            else:
                tr.misses += 1
        self._tracks = [tr for tr in self._tracks if tr.misses <= self.max_misses]
        for cls, xyxy in unmatched:
            self._tracks.append(_HistTrack(self._next_id, cls, t, xyxy))
            self._next_id += 1
        return [tr.live(t) for tr in self._tracks if tr.misses == 0]


def select_top(rows: list[dict], k: int = 3) -> list[dict]:
    """Group by t rounded to 3 decimals. Keep the k highest risk.

    Ties on risk keep the earlier row. The result is ordered by t, then track_id.
    """
    grouped: dict[float, list[dict]] = {}
    for row in rows:
        key = round(float(row["t"]), _DECIMALS)
        grouped.setdefault(key, []).append(row)
    kept: list[dict] = []
    limit = k if k > 0 else 0
    for group in grouped.values():
        ranked = sorted(group, key=lambda row: float(row["risk"]), reverse=True)
        kept.extend(ranked[:limit])
    kept.sort(key=lambda row: (float(row["t"]), row["track_id"]))
    return kept


def _round_numbers(value):
    if isinstance(value, float):
        return round(value, _DECIMALS)
    if isinstance(value, (list, tuple)):
        return [_round_numbers(item) for item in value]
    return value


_OVERLAY_KEYS = ("t", "xyxy")


def _round_xyxy(xyxy, digits: int) -> list:
    if digits <= 0:
        return [int(round(float(value))) for value in xyxy]
    return [round(float(value), digits) for value in xyxy]


def thin_tracks(
    rows: list[dict],
    *,
    every_n: int = 1,
    top_k: int = 3,
    coord_digits: int = 0,
    keys: tuple[str, ...] = _OVERLAY_KEYS,
) -> list[dict]:
    """Keep every Nth frame for the overlay file.

    Frames are the sorted unique timestamps. A kept frame keeps the top_k
    highest risks; a tie keeps the earlier row. xyxy is rounded to
    coord_digits (0 stores ints). Only ``keys`` are copied. The default is
    t and xyxy, which is the schema the watch overlay already draws.
    """
    if every_n < 1:
        raise ValueError("every_n must be >= 1")
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if coord_digits < 0:
        raise ValueError("coord_digits must be >= 0")

    grouped: dict[float, list[dict]] = {}
    for row in rows:
        key = round(float(row["t"]), _DECIMALS)
        grouped.setdefault(key, []).append(row)

    kept: list[dict] = []
    for index, t_key in enumerate(sorted(grouped)):
        if index % every_n != 0:
            continue
        ranked = sorted(
            grouped[t_key],
            key=lambda row: float(row.get("risk", 0.0)),
            reverse=True,
        )
        t_out: int | float = int(t_key) if t_key == int(t_key) else t_key
        for row in ranked[:top_k]:
            box = _round_xyxy(row["xyxy"], coord_digits)
            out: dict = {}
            for key in keys:
                if key == "t":
                    out["t"] = t_out
                elif key == "xyxy":
                    out["xyxy"] = box
                elif key in row:
                    out[key] = row[key]
            kept.append(out)
    return kept


def write_tracks(
    clip_id: str,
    rows: list[dict],
    data_dir: str = "data",
    *,
    thin: dict | None = None,
) -> Path:
    """Write data/tracks/<clip_id>.jsonl. Round every float to 3 decimals.

    Each row must include track_id, t, cls, xyxy, risk. Include vx, vy, h_rate,
    in_corridor, heading_in, ttc, t_lat when present. Create the directory.

    Pass ``thin`` to thin_tracks (every_n, top_k, coord_digits, keys). Thinned
    rows are written with compact separators and only the keys that remain.
    """
    key_order: tuple[str, ...] | None = None
    if thin is not None:
        rows = thin_tracks(rows, **thin)
        key_order = tuple(thin.get("keys", _OVERLAY_KEYS))
    path = Path(data_dir) / "tracks" / f"{clip_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for row in rows:
        if key_order is None:
            missing = [key for key in _REQUIRED_KEYS if key not in row]
            if missing:
                raise KeyError(missing[0])
            out = {}
            for key in _ROW_KEYS:
                if key in _REQUIRED_KEYS or key in row:
                    out[key] = _round_numbers(row[key])
            lines.append(json.dumps(out))
            continue
        if "t" not in row or "xyxy" not in row:
            raise KeyError("t" if "t" not in row else "xyxy")
        out = {}
        for key in key_order:
            if key in row:
                out[key] = _round_numbers(row[key])
        lines.append(json.dumps(out, separators=(",", ":")))
    text = ("\n".join(lines) + "\n") if lines else ""
    path.write_text(text, encoding="utf-8")
    return path


def _det_time(det) -> float:
    if isinstance(det, dict):
        return float(det["t"])
    return float(det.t)


def _feature_row(feat) -> dict:
    return {key: getattr(feat, key) for key in _ROW_KEYS}


def run_clip(dets: list, frame_wh: tuple[float, float]) -> list[dict]:
    """Group dets by t, track them, and keep the top 3 risks per frame.

    Calls dh.risk.features on each live track.
    """
    from dh.risk import features

    by_t: dict[float, list] = {}
    for det in dets:
        t = _det_time(det)
        by_t.setdefault(t, []).append(det)
    tracker = IoUTracker()
    rows: list[dict] = []
    for t in sorted(by_t):
        for live in tracker.update(t, by_t[t]):
            rows.append(_feature_row(features(live, frame_wh)))
    return select_top(rows)
