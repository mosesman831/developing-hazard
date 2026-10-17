"""Camera analysis for any footage: dashcam or fixed (CCTV over a road).

1. ``camera_kind``   is the camera moving? Sparse optical flow on the background
                     (detection boxes masked out). A dashcam's background streams
                     past; a CCTV background stays still. A name hint (``pie_cam``)
                     only breaks a tie, e.g. a dashcam waiting at a red light.
2. ``calibrate``     fixed camera: the camera height and pitch that make every person
                     (and car) its typical real height, the same search as the web
                     panel's ``autoCalibrate``. Lens width is assumed.
3. ``learn_road``    fixed camera: the road is where vehicles drive. Moving vehicle
                     footprints on the ground give the road axis and width; pavements
                     run alongside. This becomes the 3D scenery and the "in the road"
                     test of the fixed-camera risk model.

The geometry (``rig``, ``image_to_ground``) is a line-for-line port of
``web/spatial/camera.js`` so the backend and the 3D view agree on every position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

D2R = math.pi / 180.0
MAX_RANGE_M = 150.0
# typical heights (m) for calibration; METRIC in web/spatial/models3d.js
HEIGHT_M = {"person": 1.7, "car": 1.5, "bicycle": 1.7, "motorcycle": 1.5}
SIZE_M = {"person": (0.6, 0.5), "bicycle": (0.6, 1.8), "motorcycle": (0.8, 2.1), "car": (1.85, 4.6), "truck": (2.5, 7.5), "bus": (2.6, 12.0), "dog": (0.35, 0.9)}
VEHICLES = frozenset({"car", "truck", "bus", "motorcycle"})
DASHCAM_HINTS = ("pie_cam", "dashcam", "dash_cam", "ego")
FIXED_HINTS = ("neighborhood", "neighbourhood", "cctv", "street_cam", "streets_cam", "i24", "warehouse", "smartspace", "wall")
WIDE_HFOV = 100.0                       # assumed lens for an uncalibrated fixed camera (WALL_DEFAULT)


# ---- pinhole camera, same conventions as camera.js ------------------------------------------
@dataclass
class Rig:
    c: tuple[float, float, float]
    f: tuple[float, float, float]
    r: tuple[float, float, float]
    u: tuple[float, float, float]
    tx: float
    ty: float


def rig(pose: dict, frame_wh: tuple[float, float]) -> Rig:
    y, p = pose["yaw_deg"] * D2R, pose["pitch_deg"] * D2R
    f = (math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p))
    r = (math.cos(y), 0.0, -math.sin(y))
    u = (f[1] * r[2] - f[2] * r[1], f[2] * r[0] - f[0] * r[2], f[0] * r[1] - f[1] * r[0])
    tx = math.tan(pose["hfov_deg"] * D2R / 2.0)
    return Rig((pose["x"], pose["height_m"], pose["z"]), f, r, u, tx, tx * frame_wh[1] / frame_wh[0])


def image_to_ground(R: Rig, u: float, v: float) -> tuple[float, float] | None:
    """Normalised image point (0-1) -> ground (x, z) in metres; None above the horizon or past 150 m."""
    sx, sy = (2 * u - 1) * R.tx, (1 - 2 * v) * R.ty
    d = [R.f[i] + sx * R.r[i] + sy * R.u[i] for i in range(3)]
    if d[1] >= -1e-6:
        return None
    k = -R.c[1] / d[1]
    x, z = R.c[0] + d[0] * k, R.c[2] + d[2] * k
    return None if math.hypot(x - R.c[0], z - R.c[2]) > MAX_RANGE_M else (x, z)


def world_to_image(R: Rig, P: tuple[float, float, float]) -> tuple[float, float] | None:
    d = [P[i] - R.c[i] for i in range(3)]
    zc = sum(d[i] * R.f[i] for i in range(3))
    if zc <= 1e-6:
        return None
    x = sum(d[i] * R.r[i] for i in range(3)) / zc / R.tx
    y = sum(d[i] * R.u[i] for i in range(3)) / zc / R.tx
    return ((x + 1) / 2, (1 - y * R.tx / R.ty) / 2)


def foot(R: Rig, nb, cls: str | None = None) -> tuple[float, float] | None:
    """Ground contact point of a normalised box (bottom centre, flat ground). A box cut by the bottom of the
    frame hides its contact point, so it is placed from its top edge and the class's typical height (same as
    groundPoint in web/spatial/camera.js)."""
    u = (nb[0] + nb[2]) / 2.0
    if nb[3] < 0.99 or not cls:
        return image_to_ground(R, u, nb[3])
    h = HEIGHT_M.get(cls) or {"truck": 3.3, "bus": 3.3, "dog": 0.6}.get(cls, 1.2)

    def top_at(v):
        g = image_to_ground(R, u, v)
        p = g and world_to_image(R, (g[0], h, g[1]))
        return p[1] if p else None

    lo, hi = nb[3], 3.0
    t_lo = top_at(lo)
    if t_lo is None or t_lo <= nb[1]:
        return image_to_ground(R, u, nb[3])
    for _ in range(40):
        mid = (lo + hi) / 2
        tm = top_at(mid)
        if tm is None or tm < nb[1]:
            hi = mid
        else:
            lo = mid
    return image_to_ground(R, u, (lo + hi) / 2)


# ---- 1. is the camera moving? ---------------------------------------------------------------
def camera_kind(video_path, dets: list[dict], frame_wh, *, fps_sample: int = 5, hint: str = "") -> dict:
    """-> {"kind": "dashcam"|"fixed", "flow": median background motion (fraction of width per second), "why": str}."""
    import cv2
    import numpy as np

    w, h = frame_wh
    scale = 480.0 / w
    by_t: dict[float, list] = {}
    for d in dets:
        by_t.setdefault(round(float(d["t"]), 2), []).append(d["xyxy"])
    cap = cv2.VideoCapture(str(video_path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
    step = max(1, int(round(fps / fps_sample)))
    prev, prev_t, flows, idx = None, None, [], 0
    while True:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, img = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            gray = cv2.cvtColor(cv2.resize(img, (int(w * scale), int(h * scale))), cv2.COLOR_BGR2GRAY)
            if prev is not None:
                mask = np.full(prev.shape, 255, np.uint8)
                for b in by_t.get(round(prev_t, 2), []):         # moving objects are not the background
                    x1, y1, x2, y2 = (int(v * scale) for v in b)
                    pad = 6
                    mask[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad] = 0
                pts = cv2.goodFeaturesToTrack(prev, maxCorners=400, qualityLevel=0.01, minDistance=8, mask=mask)
                if pts is not None and len(pts) >= 20:
                    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, gray, pts, None, winSize=(21, 21), maxLevel=3)
                    good = st.reshape(-1) == 1
                    if good.sum() >= 15:
                        mv = np.linalg.norm((nxt - pts).reshape(-1, 2)[good], axis=1) / (w * scale) / max(1e-3, t - prev_t)
                        flows.append(float(np.median(mv)))
            prev, prev_t = gray, t
        idx += 1
    cap.release()
    hint_l = hint.lower()
    named = "dashcam" if any(k in hint_l for k in DASHCAM_HINTS) else "fixed" if any(k in hint_l for k in FIXED_HINTS) else None
    if not flows:
        kind = named or "fixed"
        return {"kind": kind, "flow": None, "moving_share": None, "why": f"no trackable background; {'name says ' + named if named else 'assumed fixed'}"}
    flows.sort()
    med = flows[len(flows) // 2]
    moving = sum(1 for f in flows if f > 0.02) / len(flows)   # > 2% of the width per second
    if moving >= 0.3:
        kind, why = "dashcam", f"background moves in {moving:.0%} of frames (median {med:.3f} widths/s): the camera travels"
    elif moving == 0 and med < 0.008:
        kind, why = "fixed", f"background still in every frame (median {med:.4f} widths/s): a fixed camera"
    else:
        kind = named or ("dashcam" if moving > 0.1 else "fixed")
        why = f"background mostly still (moving in {moving:.0%} of frames); {'name says ' + named if named else 'treated as ' + kind}"
    return {"kind": kind, "flow": round(med, 4), "moving_share": round(moving, 3), "why": why}


# ---- 2. fixed camera: calibrate from object heights -----------------------------------------
def calibrate(dets: list[dict], frame_wh, *, hfov: float = WIDE_HFOV, min_n: int = 12) -> dict | None:
    """Height and pitch of a level camera at the origin facing +z. None when the boxes cannot fix it."""
    W, H = frame_wh
    use = []
    for d in dets:
        cls = d["cls"]
        if cls not in HEIGHT_M or float(d.get("conf", 1)) < 0.45:
            continue
        x1, y1, x2, y2 = d["xyxy"]
        nb = (x1 / W, y1 / H, x2 / W, y2 / H)
        if nb[1] <= 0.01 or nb[3] >= 0.99 or nb[0] <= 0.005 or nb[2] >= 0.995 or nb[3] - nb[1] < 0.02:
            continue                                              # cut boxes do not show the full height
        use.append((cls, nb))
    people = [u for u in use if u[0] == "person"]
    if len(people) >= 20:
        use = people + [u for u in use if u[0] != "person"][: len(people)]
    if len(use) < min_n or max(u[1][3] for u in use) - min(u[1][3] for u in use) < 0.05:
        return None
    if len(use) > 400:
        use = use[:: math.ceil(len(use) / 400)]

    def cost(Hm, P):
        R = rig({"x": 0, "z": 0, "height_m": Hm, "yaw_deg": 0, "pitch_deg": P, "hfov_deg": hfov}, frame_wh)
        e = []
        for cls, nb in use:
            g = foot(R, nb)
            top = g and world_to_image(R, (g[0], HEIGHT_M[cls], g[1]))
            e.append(abs(math.log(max(1e-4, nb[3] - top[1]) / (nb[3] - nb[1]))) if top else 3.0)
        e.sort()
        return e[len(e) // 2]                                     # median: robust to sitting people and odd cars

    best = (float("inf"), None, None)
    for P in range(2, 81, 2):
        Hm = 1.5
        while Hm <= 60:
            c = cost(Hm, P)
            if c < best[0]:
                best = (c, Hm, P)
            Hm *= 1.08
    _, h0, p0 = best
    P = p0 - 2.0
    while P <= p0 + 2.0:
        Hm = h0 * 0.9
        while Hm <= h0 * 1.1:
            c = cost(Hm, P)
            if c < best[0]:
                best = (c, Hm, P)
            Hm *= 1.01
        P += 0.25
    err, Hm, P = best
    if err > 0.35:
        return None
    return {"pose": {"x": 0.0, "z": 0.0, "height_m": round(Hm, 2), "yaw_deg": 0.0, "pitch_deg": round(P, 2), "hfov_deg": hfov, "k1": 0.0},
            "n": len(use), "err": round(err, 3), "method": "object heights (person 1.7 m, car 1.5 m)"}


# ---- 3. fixed camera: the road is where vehicles drive --------------------------------------
@dataclass
class Road:
    """One straight road (or a junction of several) on the ground plane."""
    strips: list[dict] = field(default_factory=list)     # {"c": (x, z), "axis": (ux, uz), "half_len", "half_w"}

    def contains(self, p, margin: float = 0.0) -> bool:
        return any(_in_strip(s, p, margin) for s in self.strips)

    def edge_distance(self, p) -> float | None:
        """Metres from p to the nearest road edge (negative inside)."""
        best = None
        for s in self.strips:
            dx, dz = p[0] - s["c"][0], p[1] - s["c"][1]
            along = dx * s["axis"][0] + dz * s["axis"][1]
            across = -dx * s["axis"][1] + dz * s["axis"][0]
            if abs(along) > s["half_len"]:
                continue
            d = abs(across) - s["half_w"]
            best = d if best is None else min(best, d)
        return best

    def toward(self, p, v) -> float:
        """Speed (m/s) of velocity v toward the nearest road centre line."""
        best, bd = 0.0, None
        for s in self.strips:
            dx, dz = p[0] - s["c"][0], p[1] - s["c"][1]
            across = -dx * s["axis"][1] + dz * s["axis"][0]
            vel = -v[0] * s["axis"][1] + v[1] * s["axis"][0]
            if bd is None or abs(across) < bd:
                bd, best = abs(across), (-vel if across > 0 else vel)
        return best


def _in_strip(s, p, margin):
    dx, dz = p[0] - s["c"][0], p[1] - s["c"][1]
    along = dx * s["axis"][0] + dz * s["axis"][1]
    across = -dx * s["axis"][1] + dz * s["axis"][0]
    return abs(along) <= s["half_len"] + margin and abs(across) <= s["half_w"] + margin


def learn_road(tracks: dict[int, list[tuple[float, tuple[float, float], str]]]) -> Road:
    """tracks: id -> [(t, ground (x, z), cls)]. Vehicles that moved at least 3 m define the road."""
    dirs = []                                                # (ux, uz, length, footprints)
    for samples in tracks.values():
        veh = [s[1] for s in samples if s[2] in VEHICLES]
        if len(veh) < 3:
            continue
        # principal axis of the footprints: robust to a jittery box, unlike first-to-last
        mx, mz = sum(p[0] for p in veh) / len(veh), sum(p[1] for p in veh) / len(veh)
        sxx = sum((p[0] - mx) ** 2 for p in veh)
        szz = sum((p[1] - mz) ** 2 for p in veh)
        sxz = sum((p[0] - mx) * (p[1] - mz) for p in veh)
        ang = 0.5 * math.atan2(2 * sxz, sxx - szz)
        ux, uz = math.cos(ang), math.sin(ang)
        along = sorted((p[0] - mx) * ux + (p[1] - mz) * uz for p in veh)
        trim = 0.1 if len(along) >= 10 else 0.0             # too few points to throw any away
        L = along[int((1 - trim) * (len(along) - 1))] - along[int(trim * (len(along) - 1))]
        if L < 3.0:
            continue
        dirs.append((ux, uz, L, veh))
    if not dirs:
        return Road()
    # group directions within 30 degrees (opposite lanes fold together); at most two roads (a junction)
    groups: list[list] = []
    for d in dirs:
        for g in groups:
            if abs(d[0] * g[0][0] + d[1] * g[0][1]) > math.cos(30 * D2R):
                g.append(d)
                break
        else:
            groups.append([d])
    road = Road()
    for g in sorted(groups, key=lambda g: -sum(d[2] for d in g))[:2]:
        ref = g[0]
        ux = sum((d[0] if d[0] * ref[0] + d[1] * ref[1] >= 0 else -d[0]) * d[2] for d in g)
        uz = sum((d[1] if d[0] * ref[0] + d[1] * ref[1] >= 0 else -d[1]) * d[2] for d in g)
        n = math.hypot(ux, uz) or 1.0
        ax = (ux / n, uz / n)
        near = [p for d in g for p in d[3]]                  # only this road's own vehicles
        along = sorted(p[0] * ax[0] + p[1] * ax[1] for p in near)
        across = sorted(-p[0] * ax[1] + p[1] * ax[0] for p in near)
        mid_across = across[len(across) // 2]
        lo, hi = along[int(0.02 * (len(along) - 1))], along[int(0.98 * (len(along) - 1))]
        spread = across[int(0.9 * (len(across) - 1))] - across[int(0.1 * (len(across) - 1))]
        half_w = max(3.5, min(9.0, spread / 2 + 2.0))
        mid_along = (lo + hi) / 2
        c = (mid_along * ax[0] - mid_across * ax[1], mid_along * ax[1] + mid_across * ax[0])
        road.strips.append({"c": c, "axis": ax, "half_len": (hi - lo) / 2 + 25.0, "half_w": half_w})
    return road


def scenery(road: Road) -> dict:
    """Road, pavements and a dashed centre line in the calibration-file scenery format."""
    out = {"roads": [], "sidewalks": [], "lane_lines": []}
    for s in road.strips:
        (cx, cz), (ux, uz), L, Wd = s["c"], s["axis"], s["half_len"], s["half_w"]
        nx, nz = -uz, ux

        def quad(a0, a1, b0, b1):
            return [[round(cx + ux * a + nx * b, 2), round(cz + uz * a + nz * b, 2)] for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))]

        out["roads"].append(quad(-L, L, -Wd, Wd))
        out["sidewalks"].append(quad(-L, L, Wd, Wd + 2.5))
        out["sidewalks"].append(quad(-L, L, -Wd - 2.5, -Wd))
        out["lane_lines"].append({"pts": [[round(cx - ux * L, 2), round(cz - uz * L, 2)], [round(cx + ux * L, 2), round(cz + uz * L, 2)]], "dash": True, "width": 0.12})
    return out
