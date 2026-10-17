"""Image-space corridor and risk features (SPEC 7.6).

Image y grows downward. The ego corridor is a trapezoid: the bottom edge
runs from bottom_x0 to bottom_x1 at y = 1, and the top edge runs from
top_x0 to top_x1 at y = top_y. Those numbers are fractions of the frame.
The trapezoid is the region with y >= top_y and x between the edges
interpolated at that height.

Assumption: v_min is 0.01 times the frame width, in pixels per second.
Lateral motion at or below that speed is not treated as heading in.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import dh.config as config

_CLASS_WEIGHT = {
    "person": 1.0,
    "bicycle": 1.0,
    "motorcycle": 0.9,
    "car": 0.7,
    "bus": 0.7,
    "truck": 0.7,
    "dog": 1.0,
}

_W_INSIDE = 0.3
_W_TTC = 0.35
_W_LAT = 0.25
_W_CLASS = 0.1
_T_TTC = 3.0
_S_TTC = 0.7
_T_LAT = 2.0
_S_LAT = 0.5
_V_MIN_WIDTH_FRACTION = 0.01


def _sigmoid(x: float) -> float:
    """Logistic function, stable for large positive and negative inputs."""
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _corridor(corridor: dict | None) -> dict:
    if corridor is None:
        return config.corridor
    return corridor


def _v_min(frame_wh) -> float:
    return _V_MIN_WIDTH_FRACTION * float(frame_wh[0])


def _sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def _edges(y_norm: float, corridor: dict) -> tuple[float, float]:
    top_y = float(corridor["top_y"])
    denom = 1.0 - top_y
    frac = 0.0 if denom == 0.0 else (y_norm - top_y) / denom
    left = float(corridor["top_x0"]) + frac * (
        float(corridor["bottom_x0"]) - float(corridor["top_x0"])
    )
    right = float(corridor["top_x1"]) + frac * (
        float(corridor["bottom_x1"]) - float(corridor["top_x1"])
    )
    return left, right


def _bottom_centre(xyxy) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    bottom_y = y1 if y1 >= y2 else y2
    return (x1 + x2) / 2.0, bottom_y


def in_corridor(xyxy, frame_wh, corridor=None) -> bool:
    """True when the box bottom-centre lies inside the ego trapezoid.

    xyxy is in pixels. y grows downward, so the bottom of the box is the
    larger y.
    """
    corridor = _corridor(corridor)
    width = float(frame_wh[0])
    height = float(frame_wh[1])
    if width == 0.0 or height == 0.0:
        return False
    bcx, bcy = _bottom_centre(xyxy)
    x_norm = bcx / width
    y_norm = bcy / height
    if y_norm < float(corridor["top_y"]) or y_norm > 1.0:
        return False
    left, right = _edges(y_norm, corridor)
    lo, hi = (left, right) if left <= right else (right, left)
    return lo <= x_norm <= hi


def heading_in(cx, cy, vx, frame_wh, corridor=None) -> bool:
    """True when the centre is moving towards the corridor centre line.

    Assumption: v_min is 0.01 times the frame width, in pixels per second.
    A track whose absolute lateral speed is at or below v_min is not heading
    in. A track left of the centre line with positive vx is heading in, and
    a track right of the centre line with negative vx is heading in.

    cx and cy are pixels. vx is pixels per second. The comparison uses
    cx as a fraction of frame width against the corridor centre at cy.
    """
    corridor = _corridor(corridor)
    width = float(frame_wh[0])
    height = float(frame_wh[1])
    if width == 0.0 or height == 0.0:
        return False
    speed = float(vx)
    if abs(speed) <= _v_min(frame_wh):
        return False
    left, right = _edges(float(cy) / height, corridor)
    corridor_cx = (left + right) / 2.0
    return _sign(float(cx) / width - corridor_cx) != _sign(speed)


def _lateral_time(xyxy, vx, frame_wh, corridor: dict, is_heading: bool):
    speed = abs(float(vx))
    if (not is_heading) or speed <= _v_min(frame_wh):
        return None
    width = float(frame_wh[0])
    height = float(frame_wh[1])
    if width == 0.0 or height == 0.0:
        return None
    bcx, bcy = _bottom_centre(xyxy)
    left, right = _edges(bcy / height, corridor)
    distance = min(abs(bcx - left * width), abs(bcx - right * width))
    return distance / speed


def features(track, frame_wh, corridor=None) -> SimpleNamespace:
    """SPEC 7.6 risk features for one live track.

    TTC is 1 / h_rate when h_rate > 0, else None, because
    dh/dt = h * d(log h)/dt. h_rate is already the 0.6 s slope, so TTC is
    not smoothed again.

    t_lat is the pixel distance from the bottom-centre x to the nearest
    corridor edge, divided by abs(vx). It is set only when the track is
    heading in and abs(vx) > v_min. Otherwise it is None.

    risk = 0.3 * inside
         + 0.35 * sigmoid((3.0 - ttc) / 0.7) when ttc is not None, else 0
         + 0.25 * heading_in * sigmoid((2.0 - t_lat) / 0.5) when t_lat is
           not None, else 0
         + 0.1 * class_weight

    class_weight: person 1, bicycle 1, motorcycle 0.9, car 0.7, bus 0.7,
    truck 0.7, dog 1, else 0. Risk is clamped to [0, 1].
    """
    corridor = _corridor(corridor)
    xyxy = [float(v) for v in track.xyxy]
    inside = in_corridor(xyxy, frame_wh, corridor)
    hin = heading_in(track.cx, track.cy, track.vx, frame_wh, corridor)
    h_rate = float(track.h_rate)
    ttc = (1.0 / h_rate) if h_rate > 0.0 else None
    t_lat = _lateral_time(xyxy, track.vx, frame_wh, corridor, hin)
    class_weight = _CLASS_WEIGHT.get(track.cls, 0.0)
    risk = _W_INSIDE * (1.0 if inside else 0.0)
    if ttc is not None:
        risk += _W_TTC * _sigmoid((_T_TTC - ttc) / _S_TTC)
    if t_lat is not None:
        risk += _W_LAT * (1.0 if hin else 0.0) * _sigmoid((_T_LAT - t_lat) / _S_LAT)
    risk += _W_CLASS * class_weight
    risk = min(1.0, max(0.0, risk))
    track_id = track.id if hasattr(track, "id") else track.track_id
    return SimpleNamespace(
        track_id=track_id,
        t=float(track.t),
        cls=track.cls,
        xyxy=xyxy,
        vx=float(track.vx),
        vy=float(track.vy),
        h_rate=h_rate,
        in_corridor=inside,
        heading_in=hin,
        ttc=ttc,
        t_lat=t_lat,
        risk=risk,
    )


def scene_risk(feats) -> float:
    """Highest track risk, or 0 when there are no tracks."""
    if not feats:
        return 0.0
    return max(feat["risk"] if isinstance(feat, dict) else feat.risk for feat in feats)
