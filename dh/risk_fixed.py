"""Risk features for a fixed camera over a road (CCTV, house or pole camera).

There is no ego car, so the dashcam corridor of ``dh.risk`` does not apply.
The hazard is a road user who may need to slow or steer: a person, cyclist or
dog in the road or stepping into it, close to or closing on a moving vehicle,
and two moving vehicles closing on each other.

Positions come from the camera calibration (``dh.scene``): metres on a flat
ground plane, approximate. Velocities are least-squares slopes over the last
second of a track's own ground positions. The fields and weights mirror
``dh.risk.features`` so every agent threshold means the same thing:

    in_corridor  the person is in the road (learned from where vehicles drive)
    heading_in   the person is walking toward the road from the pavement
    ttc          time to closest approach with a moving vehicle, when the paths
                 pass within ~2 m (constant velocity, like dh.risk's TTC)
    t_lat        time for the person to reach the road edge

    risk = 0.3 * in_road
         + 0.35 * max(sigmoid((3 - ttc) / 0.7), 0.8 * near)
         + 0.25 * heading_in * sigmoid((2 - t_lat) / 0.5)
         + 0.1 * class_weight
    near = sigmoid((2 - gap_m) / 0.4) for a vehicle moving faster than 1 m/s

A vehicle takes 90% of the exposure of the most exposed person it is involved with, and
two moving vehicles closing within 2.5 m score 0.6 * sigmoid((3 - ttc) / 0.7).
A moving vehicle adds 0.05 * min(1, speed / 8 m/s), so it outranks a parked one.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from dh.scene import SIZE_M, VEHICLES, Road, Rig, foot

VRU = frozenset({"person", "bicycle", "dog"})
_CLASS_WEIGHT = {"person": 1.0, "bicycle": 1.0, "motorcycle": 0.9, "car": 0.7, "bus": 0.7, "truck": 0.7, "dog": 1.0}
_HIST_S = 1.2
_VEL_S = 1.0
MOVING_MS = 1.0


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))


def _slope(samples: list[tuple[float, float]]) -> float:
    n = len(samples)
    mt = sum(t for t, _ in samples) / n
    my = sum(y for _, y in samples) / n
    vt = sum((t - mt) ** 2 for t, _ in samples)
    return 0.0 if vt == 0 else sum((t - mt) * (y - my) for t, y in samples) / vt


class FixedScene:
    """Stateful: feed every frame's live tracks in time order; returns dh.risk-style features."""

    def __init__(self, rig: Rig, frame_wh, road: Road | None = None) -> None:
        self.rig = rig
        self.frame_wh = frame_wh
        self.road = road if road is not None and road.strips else None
        self.hist: dict[int, list[tuple[float, tuple[float, float]]]] = {}

    def _ground(self, xyxy, cls=None):
        W, H = self.frame_wh
        return foot(self.rig, (xyxy[0] / W, xyxy[1] / H, xyxy[2] / W, xyxy[3] / H), cls)

    def _velocity(self, tid: int, t: float):
        win = [(ts, g) for ts, g in self.hist.get(tid, []) if ts >= t - _VEL_S]
        if len(win) < 3 or win[-1][0] - win[0][0] < 0.39:
            return (0.0, 0.0)
        return (_slope([(ts, g[0]) for ts, g in win]), _slope([(ts, g[1]) for ts, g in win]))

    def features(self, t: float, tracks) -> list[SimpleNamespace]:
        objs = []
        for tr in tracks:
            g = self._ground(tr.xyxy, tr_cls(tr))
            if g is not None:
                h = self.hist.setdefault(tr.id, [])
                h.append((t, g))
                while h and h[0][0] < t - _HIST_S:
                    h.pop(0)
            v = self._velocity(tr.id, t) if g is not None else (0.0, 0.0)
            objs.append({"tr": tr, "g": g, "v": v, "speed": math.hypot(*v)})
        out = []
        for o in objs:
            out.append(self._one(o, objs, t))
        return out

    def _one(self, o, objs, t) -> SimpleNamespace:
        tr, g, v, cls = o["tr"], o["g"], o["v"], tr_cls(o["tr"])
        risk = 0.1 * _CLASS_WEIGHT.get(cls, 0.0)
        in_road = hin = False
        ttc = t_lat = gap = other = None
        why = []
        if g is not None and cls in VRU:
            if self.road:
                in_road = self.road.contains(g, -0.3)
                edge = self.road.edge_distance(g)
                toward = self.road.toward(g, v)
                if not in_road and edge is not None and 0 < edge < 4.0 and toward > 0.5:
                    hin, t_lat = True, edge / toward
            best = 0.0
            for q in objs:
                if q is o or q["g"] is None or tr_cls(q["tr"]) not in VEHICLES or q["speed"] < MOVING_MS:
                    continue
                gp = _gap(g, q)
                c = _closest(g, v, q["g"], q["v"], 1.8 + SIZE_M.get(tr_cls(q["tr"]), (1.85, 4.6))[0] / 2)
                term = max(_sig((3.0 - c) / 0.7) if c is not None else 0.0, 0.8 * _sig((2.0 - gp) / 0.4))
                if term > best:
                    best, gap, other, ttc = term, gp, q["tr"].id, c
            risk += 0.3 * in_road + 0.35 * best + (0.25 * _sig((2.0 - t_lat) / 0.5) if hin else 0.0)
            if in_road:
                why.append("in the road")
            if hin:
                why.append(f"walking toward the road, {t_lat:.1f} s from the edge")
            if other is not None and best > 0.3:
                q = next(x for x in objs if x["tr"].id == other)
                why.append(f"{tr_cls(q['tr'])} #{other} moving {q['speed']:.1f} m/s, {gap:.1f} m away" + (f", paths cross in {ttc:.1f} s" if ttc is not None else ""))
        elif g is not None and cls in VEHICLES and o["speed"] >= MOVING_MS:
            best, src = 0.0, None
            for q in objs:
                if q is o or q["g"] is None:
                    continue
                qc = tr_cls(q["tr"])
                if qc in VRU:
                    gp = _gap(q["g"], o)
                    c = _closest(q["g"], q["v"], g, v, 1.8 + SIZE_M.get(cls, (1.85, 4.6))[0] / 2)
                    vin = self.road.contains(q["g"], -0.3) if self.road else False
                    # 90% of the person's own exposure: the person, not the car, heads the click
                    term = 0.9 * (0.35 * max(_sig((3.0 - c) / 0.7) if c is not None else 0.0, 0.8 * _sig((2.0 - gp) / 0.4)) + 0.3 * vin)
                    if term > best:
                        best, src, gap, ttc, other = term, f"{qc} #{q['tr'].id} {gp:.1f} m away" + (" in the road" if vin else ""), gp, c, q["tr"].id
                elif qc in VEHICLES and q["speed"] >= MOVING_MS:
                    c = _closest(g, v, q["g"], q["v"], 2.5)
                    term = 0.6 * _sig((3.0 - c) / 0.7) if c is not None else 0.0
                    if term > best:
                        best, src, ttc, other = term, f"{qc} #{q['tr'].id}: paths cross in {c:.1f} s", c, q["tr"].id
            # a vehicle in motion outranks a parked one with the same exposure (top-3 ties otherwise drop it)
            risk += best + 0.05 * min(1.0, o["speed"] / 8.0)
            if src and best > 0.25:
                why.append(src)
        risk = min(1.0, max(0.0, risk))
        return SimpleNamespace(
            track_id=tr.id, t=float(t), cls=cls, xyxy=[float(x) for x in tr.xyxy], vx=float(tr.vx), vy=float(tr.vy),
            h_rate=float(tr.h_rate), in_corridor=bool(in_road), heading_in=bool(hin), ttc=ttc, t_lat=t_lat, risk=risk,
            ground=g, speed_ms=o["speed"], gap_m=gap, other_id=other, why="; ".join(why),
        )


def tr_cls(tr) -> str:
    return str(tr.cls)


def _gap(p, veh) -> float:
    """Ground gap (m) from point p to a vehicle's footprint, oriented along its motion."""
    w, length = SIZE_M.get(tr_cls(veh["tr"]), (1.85, 4.6))
    c, (vx, vz) = veh["g"], veh["v"]
    s = math.hypot(vx, vz)
    if s < 0.3:
        return max(0.0, math.hypot(p[0] - c[0], p[1] - c[1]) - w / 2 - 0.3)
    ux, uz = vx / s, vz / s
    dx, dz = p[0] - c[0], p[1] - c[1]
    along, across = dx * ux + dz * uz, -dx * uz + dz * ux
    return max(0.0, math.hypot(max(0.0, abs(along) - length / 2), max(0.0, abs(across) - w / 2)) - 0.3)


def _closest(p, vp, q, vq, reach: float) -> float | None:
    """Time (s) until p and q are closest at constant velocity, when they pass within `reach` metres."""
    d = (p[0] - q[0], p[1] - q[1])
    w = (vp[0] - vq[0], vp[1] - vq[1])
    ww = w[0] ** 2 + w[1] ** 2
    if ww < 0.25:
        return None
    tc = -(d[0] * w[0] + d[1] * w[1]) / ww
    if tc <= 0 or tc > 6.0:
        return None
    miss = math.hypot(d[0] + w[0] * tc, d[1] + w[1] * tc)
    return tc if miss <= reach else None
