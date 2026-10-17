// Stationary (fixed) camera geometry: a camera on a wall, a house or a pole looking at a public road.
// Pure functions, no DOM. World: metres on a flat ground plane, x right, z forward, y up.
// A calibrated pinhole camera (pose + horizontal field of view) with one radial distortion term (k1, the
// division model; negative = barrel, as on wide security cameras) maps image points on the ground to (x, z).
// Calibration file (data/cameras/<camera_id>.json):
//   { "camera_id", "kind": "fixed", "pose": { "x", "z", "height_m", "yaw_deg", "pitch_deg", "hfov_deg", "k1"? }, "scenery": {...} }
import { METRIC, resolveClass } from './models3d.js';
const D2R = Math.PI / 180;
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const MAX_RANGE_M = 150;         // beyond this a ground position is too flat to trust
// Used only when a fixed camera has no calibration and too few people to auto-calibrate: a typical
// house-mounted camera. Labelled "assumed" wherever it shows; positions from it are rough.
export const WALL_DEFAULT = { x: 0, z: 0, height_m: 4, yaw_deg: 0, pitch_deg: 20, hfov_deg: 100, k1: 0 };

export function validPose(p) {
  return !!p && ['x', 'z', 'height_m', 'yaw_deg', 'pitch_deg', 'hfov_deg'].every((k) => typeof p[k] === 'number' && Number.isFinite(p[k]))
    && p.height_m > 0 && p.hfov_deg > 1 && p.hfov_deg < 179 && (p.k1 == null || (Number.isFinite(p.k1) && Math.abs(p.k1) <= 0.6));
}
// camera centre, basis (f forward, r right, u up), tan of the half fields of view and the distortion term
export function rig(pose, frame = { w: 1920, h: 1080 }) {
  const y = pose.yaw_deg * D2R, p = pose.pitch_deg * D2R;
  const f = [Math.sin(y) * Math.cos(p), -Math.sin(p), Math.cos(y) * Math.cos(p)];
  const r = [Math.cos(y), 0, -Math.sin(y)];
  const u = [f[1] * r[2] - f[2] * r[1], f[2] * r[0] - f[0] * r[2], f[0] * r[1] - f[1] * r[0]];
  const tx = Math.tan((pose.hfov_deg * D2R) / 2), ty = tx * (frame.h / frame.w);
  return { c: [pose.x, pose.height_m, pose.z], f, r, u, tx, ty, k1: pose.k1 || 0 };
}
// distortion on coordinates normalised so the image half-width is 1: undistort (image -> pinhole), distort (back)
export const undistort = (k1, x, y) => { const s = 1 / (1 + k1 * (x * x + y * y)); return [x * s, y * s]; };
export function distort(k1, x, y) {
  const ru = Math.hypot(x, y); if (!k1 || ru < 1e-9) return [x, y];
  const q = 1 - 4 * k1 * ru * ru; if (q < 0) return null;
  const s = (1 - Math.sqrt(q)) / (2 * k1 * ru) / ru; return [x * s, y * s];
}
function ray(R, u, v) {
  const [xu, yu] = undistort(R.k1, 2 * u - 1, ((1 - 2 * v) * R.ty) / R.tx), sx = xu * R.tx, sy = yu * R.tx;
  return [0, 1, 2].map((i) => R.f[i] + sx * R.r[i] + sy * R.u[i]);
}
// normalised image point (0-1) -> ground [x, z] in metres, or null when the ray misses the ground
export function imageToGround(R, u, v) {
  const d = ray(R, u, v);
  if (d[1] >= -1e-6) return null;
  const k = -R.c[1] / d[1], x = R.c[0] + d[0] * k, z = R.c[2] + d[2] * k;
  return Math.hypot(x - R.c[0], z - R.c[2]) > MAX_RANGE_M ? null : [x, z];
}
// world point [x, y, z] -> normalised image point, or null behind the camera
export function worldToImage(R, P) {
  const d = sub(P, R.c), zc = dot(d, R.f);
  if (zc <= 1e-6) return null;
  const p = distort(R.k1, dot(d, R.r) / zc / R.tx, dot(d, R.u) / zc / R.tx);
  return p && [(p[0] + 1) / 2, (1 - (p[1] * R.tx) / R.ty) / 2];
}
// ground footprint of the image (what the camera can see), as [[x, z], ...]
export function visibleGround(R, n = 12) {
  const edge = [];
  for (let i = 0; i <= n; i++) edge.push([i / n, 1]);                      // bottom, left to right
  for (let i = n; i >= 0; i--) edge.push([1, i / n]);                      // right edge, bottom to top
  for (let i = n; i >= 0; i--) edge.push([i / n, 0]);                      // top, right to left
  for (let i = 0; i <= n; i++) edge.push([0, i / n]);                      // left edge, top to bottom
  const out = [];
  for (const [u, v] of edge) {
    let g = imageToGround(R, u, v);
    if (!g) {                                                              // ray above the horizon: clamp at max range
      const d = ray(R, u, v), L = Math.hypot(d[0], d[2]) || 1;
      g = [R.c[0] + (d[0] / L) * MAX_RANGE_M, R.c[2] + (d[2] / L) * MAX_RANGE_M];
    }
    out.push(g);
  }
  return out;
}
// bottom-centre of a normalised box -> ground contact point (flat ground assumed)
export const groundPoint = (R, nb) => imageToGround(R, (nb[0] + nb[2]) / 2, nb[3]);
// heading (deg, 0 = +z) and speed (m/s) from the track's own ground positions over the last `win` seconds
export function groundMotion(samples, t, win = 1.0) {
  const s = samples.filter((r) => r.g && r.t <= t + 1e-6 && r.t >= t - win);
  if (s.length < 2) return null;
  const a = s[0], b = s[s.length - 1], dx = b.g[0] - a.g[0], dz = b.g[1] - a.g[1], dt = b.t - a.t;
  if (dt <= 0) return null;
  return { dx, dz, speed: Math.hypot(dx, dz) / dt, heading: (Math.atan2(dx, dz) * 180) / Math.PI };
}

// ---- cameras in the VAST Builders Challenge corpus (vast-data/vast-builders-challenge, ARCHITECTURE_REFERENCE.md) ----
// kind only; none of these ship a calibration, so fixed ones are auto-calibrated or need a hand-made file.
export const CAMERAS = {
  'pie_cam-3': { kind: 'dashcam', what: 'PIE forward dashcam, Toronto' },
  'i24_cam-1': { kind: 'fixed', what: 'I-24 overhead highway multi-cam, Nashville' },
  'neighborhood_cam-1': { kind: 'fixed', what: 'private neighbourhood camera (wide lens)' },
  'sf_streets_cam-1': { kind: 'fixed', what: 'San Francisco street camera 1' }, 'sf_streets_cam-2': { kind: 'fixed', what: 'San Francisco street camera 2' },
  'sf_streets_cam-3': { kind: 'fixed', what: 'San Francisco street camera 3' }, 'sf_streets_cam-4': { kind: 'fixed', what: 'San Francisco street camera 4' },
  'sdg_warehouse_cam-2': { kind: 'fixed', what: 'warehouse ceiling / aisle camera' },
  'smartspace_cam-1': { kind: 'fixed', what: 'indoor smart-space camera' },
};

// ---- auto-calibration from people in the footage ----
// A standing person is about PERSON_H tall. For a level camera (no roll) at height h and pitch p, each
// person box's bottom fixes a ground point and its height fixes how big 1.7 m looks there. We search the
// (height, pitch) pair that best explains every person box. Lens width cannot be recovered this way, so
// it is an input (assumed when unknown). Yaw and position are arbitrary: the camera sits at the origin.
export const PERSON_H = 1.7;
export function autoCalibrate(rows, frame = { w: 1920, h: 1080 }, { hfov = 90, k1 = 0, minN = 20 } = {}) {
  let use = rows.filter((r) => r.cls === 'person' && r.nb && r.nb[1] > 0.01 && r.nb[3] < 0.99 && r.nb[3] - r.nb[1] > 0.012 && (r.conf == null || r.conf >= 0.5));
  if (use.length < minN) return null;
  const ys = use.map((r) => r.nb[3]);
  if (Math.max(...ys) - Math.min(...ys) < 0.08) return null;              // people at one depth cannot fix the geometry
  if (use.length > 300) { const k = Math.ceil(use.length / 300); use = use.filter((_, i) => i % k === 0); }
  const cost = (H, P) => {
    const R = rig({ x: 0, z: 0, height_m: H, yaw_deg: 0, pitch_deg: P, hfov_deg: hfov, k1 }, frame), e = [];
    for (const r of use) {
      const g = imageToGround(R, (r.nb[0] + r.nb[2]) / 2, r.nb[3]), top = g && worldToImage(R, [g[0], PERSON_H, g[1]]);
      e.push(top ? Math.abs(Math.log(Math.max(1e-4, r.nb[3] - top[1]) / (r.nb[3] - r.nb[1]))) : 3);
    }
    e.sort((a, b) => a - b); return e[e.length >> 1];                       // median: robust to sitting, partial or mislabelled people
  };
  let best = { c: Infinity };
  for (let P = 1; P <= 80; P += 1) for (let H = 1; H <= 90; H *= 1.07) { const c = cost(H, P); if (c < best.c) best = { c, H, P }; }
  for (let P = best.P - 1; P <= best.P + 1; P += 0.1) for (let H = best.H * 0.92; H <= best.H * 1.08; H *= 1.005) { const c = cost(H, P); if (c < best.c) best = { c, H, P }; }
  if (!Number.isFinite(best.c) || best.c > 0.35) return null;               // > ~40% median size error: do not pretend
  return { pose: { x: 0, z: 0, height_m: +best.H.toFixed(2), yaw_deg: 0, pitch_deg: +best.P.toFixed(1), hfov_deg: hfov, k1 }, n: use.length, err: +best.c.toFixed(3), method: 'person heights' };
}

// ---- VSS (VAST video search) YOLO detection sidecars -> det rows ----
// GET /api/v1/videos/detections?source=<segment> returns a per-segment JSON sidecar. Its schema is not
// documented in the challenge repo, so this accepts the common shapes and skips what it cannot read.
// `segments` = [{ start_s, sidecar }] so detection times become clip time.
export function parseVssDetections(segments, fps = 30) {
  const rows = []; let skipped = 0;
  const num = (v) => typeof v === 'number' && Number.isFinite(v);
  for (const { start_s = 0, sidecar } of segments) {
    const frames = Array.isArray(sidecar) ? sidecar : sidecar && (sidecar.frames || sidecar.detections_by_frame || sidecar.results) || [];
    const f0 = sidecar && num(sidecar.fps) ? sidecar.fps : fps;
    for (const fr of frames) {
      const t = [fr.t, fr.time, fr.timestamp, fr.pts_time].find(num) ?? (num(fr.frame ?? fr.frame_idx ?? fr.frame_index) ? (fr.frame ?? fr.frame_idx ?? fr.frame_index) / f0 : null);
      const objs = fr.detections || fr.objects || fr.boxes || [];
      if (t == null || !Array.isArray(objs)) { skipped++; continue; }
      for (const o of objs) {
        const cls = o.class_name || o.label || o.cls || o.name || (typeof o.class === 'string' ? o.class : null);
        const conf = [o.conf, o.confidence, o.score].find(num);
        let b = o.xyxy || o.bbox || o.box;
        if (b && !Array.isArray(b)) b = [b.x1 ?? b.left, b.y1 ?? b.top, b.x2 ?? b.right, b.y2 ?? b.bottom];
        if (o.xywh && Array.isArray(o.xywh)) { const [x, y, w, h] = o.xywh; b = [x - w / 2, y - h / 2, x + w / 2, y + h / 2]; }
        if (!cls || conf == null || !Array.isArray(b) || b.length !== 4 || !b.every(num)) { skipped++; continue; }
        rows.push({ t: +(start_s + t).toFixed(3), frame: Math.round((start_s + t) * f0), cls, conf, xyxy: b });
      }
    }
  }
  return { rows, skipped };
}

// ---- what a wall camera can measure: a vulnerable road user close to a moving vehicle ----
// Ground gap between a person or cyclist and the footprint of a vehicle moving faster than MOVING_MS, from the
// calibrated positions and typical class sizes. One MEASURED event per encounter (a pair apart for more than
// 1 s starts a new one). A measurement for review, not a risk score: the fill colour stays the pipeline's.
export const NEAR_M = 2.0, MOVING_MS = 1.0;
const VRU = new Set(['person', 'bicycle']), VEH = new Set(['car', 'truck', 'bus', 'motorcycle']);
export function proximityEvents(tracks) {
  const at = new Map(), motion = new Map();
  for (const [id, rows] of tracks) for (const r of rows) {
    if (!r.g) continue;
    const k = Math.round(r.t * 100); if (!at.has(k)) at.set(k, []); at.get(k).push({ id, r });
    motion.set(r, groundMotion(rows, r.t));
  }
  const open = new Map(), out = [];
  for (const k of [...at.keys()].sort((a, b) => a - b)) {
    const here = at.get(k), t = k / 100;
    for (const p of here) {
      if (!VRU.has(resolveClass(p.r.cls))) continue;
      for (const v of here) {
        const cls = resolveClass(v.r.cls), m = motion.get(v.r);
        if (!VEH.has(cls) || !m || m.speed < MOVING_MS) continue;
        // the person's position in the vehicle's frame (x across, z along its observed heading)
        const [w, l] = METRIC[cls], a = (m.heading * Math.PI) / 180, dx = p.r.g[0] - v.r.g[0], dz = p.r.g[1] - v.r.g[1];
        const lx = dx * Math.cos(a) - dz * Math.sin(a), lz = dx * Math.sin(a) + dz * Math.cos(a);
        const gap = Math.max(0, Math.hypot(Math.max(0, Math.abs(lx) - w / 2), Math.max(0, Math.abs(lz) - l / 2)) - 0.3);
        if (gap > NEAR_M) continue;
        const key = p.id + '|' + v.id, o = open.get(key);
        if (o && t - o.last <= 1.0) { o.last = t; if (gap < o.ev.min) { o.ev.min = gap; o.ev.minT = t; } continue; }
        const ev = { t, prov: 'MEASURED', track_id: p.id, src: { file: 'tracks', line: p.r._line }, gap, min: gap, minT: t, speed: m.speed,
          title: `${p.r.cls} #${p.id} within ${gap.toFixed(1)} m of moving ${v.r.cls} #${v.id}` };
        open.set(key, { last: t, ev }); out.push(ev);
      }
    }
  }
  for (const e of out) e.why = `ground gap ${e.gap.toFixed(1)} m (calibrated flat ground, typical vehicle size; approximate); vehicle moving ${e.speed.toFixed(1)} m/s over the last 1 s; closest ${e.min.toFixed(1)} m at ${e.minT.toFixed(2)} s`;
  return out;
}
