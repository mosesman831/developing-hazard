// Software 3D viewport (canvas 2D, no library). World: x right, y up, z forward.
// Two environments:
//  - dashcam: the ego car at the origin; units are ORDINAL range bands (plan radius x U), never metres.
//  - fixed:   a calibrated stationary camera; units are approximate metres on a flat ground plane,
//             with the street scenery from the calibration file rendered around the tracked objects.
// Rendering: painter's algorithm with back-face culling, a key light plus sky/ground ambient, soft contact
// shadows, distance fog in large scenes, and glass label pills that stack instead of overlapping.
import { ASSUMED_HFOV_DEG, corridorPolygon } from './core.js';
import { modelFaces, metricDims, resolveClass, orient } from './models3d.js';
import { visibleGround } from './camera.js';

const U = 3.5, D2R = Math.PI / 180, HALF = ASSUMED_HFOV_DEG / 2, RIM = 1.12, NEAR = 0.1;
const PAL = { d: [34, 38, 44], l: [206, 212, 219], g: [58, 84, 112] };
// neutral paint and clothing, deliberately never the green / amber / red channel colours
const PAINT = [[222, 226, 230], [176, 182, 189], [112, 118, 126], [42, 46, 52], [64, 82, 108], [118, 108, 96], [146, 152, 160]];
const CLOTH = [[66, 78, 98], [96, 86, 74], [58, 62, 70], [118, 122, 132]];
const HZ = { red: '#f85149', amber: '#e3a008', grey: '#8b929c' }, ACCENT = '#8ab4ff', FOG = [21, 25, 31];
export const VIEWS = { persp: { yaw: -28, pitch: 26 }, top: { yaw: 0, pitch: 89.5 }, front: { yaw: 180, pitch: 6 }, back: { yaw: 0, pitch: 6 }, left: { yaw: -90, pitch: 6 }, right: { yaw: 90, pitch: 6 } };
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const LIGHT = norm([-0.42, 0.84, -0.34]);                  // key light: high, from front-left
const mean = (P) => { let x = 0, y = 0, z = 0; for (const p of P) { x += p[0]; y += p[1]; z += p[2]; } return [x / P.length, y / P.length, z / P.length]; };
const faceN = (f) => { const n = norm(cross(sub(f.pts[1], f.pts[0]), sub(f.pts[2], f.pts[0]))); return f.s < 0 ? [-n[0], -n[1], -n[2]] : n; };
// key light + sky/ground ambient; glass gets a little sheen when seen edge-on; fog pulls far faces to the background
function shade(c, n, view, fog, glass) {
  const amb = 0.34 + 0.2 * (n[1] * 0.5 + 0.5), k = amb + 0.6 * Math.max(0, dot(n, LIGHT)) + (glass ? 0.22 * (1 - Math.abs(dot(n, view))) : 0);
  const m = (i) => (c[i] * k * (1 - fog) + FOG[i] * fog) | 0;
  return `rgb(${m(0)},${m(1)},${m(2)})`;
}
export const world = (ang, r, y = 0) => [Math.sin(ang * D2R) * r * U, y, Math.cos(ang * D2R) * r * U];
const arc = (a0, a1, r, n = 32) => Array.from({ length: n + 1 }, (_, i) => world(a0 + ((a1 - a0) * i) / n, r));
const G3 = (p, y = 0) => [p[0], y, p[1]];
const DASH = {
  hidden: [[0, 0, 0], ...arc(HALF, 360 - HALF, RIM, 48)], fov: [[0, 0, 0], ...arc(-HALF, HALF, RIM, 48)], rim: arc(-HALF, HALF, RIM, 48),
  bands: [[0.488, 'NEAR | MID'], [0.719, 'MID | FAR'], [0.95, 'FAR']].map(([r, n]) => ({ pts: arc(-HALF, HALF, r), n, at: world(-HALF + 16, r) })),
  corridor: corridorPolygon().map((p) => world(p.ang, p.r)),
};

export function camBasis(c) {
  const cp = Math.cos(c.pitch * D2R), dir = [Math.sin(c.yaw * D2R) * cp, Math.sin(c.pitch * D2R), -Math.cos(c.yaw * D2R) * cp];
  const eye = [c.target[0] + dir[0] * c.dist, c.target[1] + dir[1] * c.dist, c.target[2] + dir[2] * c.dist];
  const f = norm(sub(c.target, eye)), r = norm(cross([0, 1, 0], f)), u = cross(f, r);
  return { eye, f, r, u };
}

// ---- static scenery geometry for a fixed camera (built once per calibration) ----
const isPoly = (p) => Array.isArray(p) && p.length >= 3 && p.every((q) => Array.isArray(q) && q.length >= 2 && q.every(Number.isFinite));
function boxFaces(cx, cz, w, d, y0, y1, yaw = 0) {
  const s = Math.sin(yaw * D2R), c = Math.cos(yaw * D2R), P = (dx, y, dz) => [cx + dx * c + dz * s, y, cz - dx * s + dz * c];
  const v = []; for (const y of [y0, y1]) for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) v.push(P((a * w) / 2, y, (b * d) / 2));
  return orient([[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]].map((f) => f.map((i) => v[i])));
}
function cylFaces(cx, cz, r, y0, y1, n = 8) {
  const v = []; for (const y of [y0, y1]) for (let i = 0; i < n; i++) { const a = ((i + 0.5) * 2 * Math.PI) / n; v.push([cx + Math.cos(a) * r, y, cz + Math.sin(a) * r]); }
  const F = [[...Array(n).keys()].map((i) => i + n)]; for (let i = 0; i < n; i++) F.push([i, (i + 1) % n, ((i + 1) % n) + n, i + n]);
  return orient(F.map((f) => f.map((i) => v[i])));
}
// thin ground quads along a polyline; dashed lines are 3 m on, 6 m off
function stripe(pts, w, dash) {
  const out = [];
  for (let i = 1; i < pts.length; i++) {
    const [a, b] = [pts[i - 1], pts[i]], L = Math.hypot(b[0] - a[0], b[1] - a[1]); if (!L) continue;
    const ux = (b[0] - a[0]) / L, uz = (b[1] - a[1]) / L, nx = (-uz * w) / 2, nz = (ux * w) / 2;
    for (let s = 0; s < L; s += dash ? 9 : L) {
      const e = Math.min(L, s + (dash ? 3 : L)), p = [a[0] + ux * s, a[1] + uz * s], q = [a[0] + ux * e, a[1] + uz * e];
      out.push([[p[0] + nx, 0.02, p[1] + nz], [q[0] + nx, 0.02, q[1] + nz], [q[0] - nx, 0.02, q[1] - nz], [p[0] - nx, 0.02, p[1] - nz]]);
    }
  }
  return out;
}
export function buildScenery(sc = {}) {
  const flat = [], solid = [], pts = [];
  const add = (list, fill, stroke = null, y = 0.01) => { for (const p of list || []) if (isPoly(p)) { flat.push({ pts: p.map((q) => G3(q, y)), fill, stroke }); pts.push(...p); } };
  add(sc.sidewalks, '#363a41', '#4b5058', 0.01); add(sc.roads, '#24272c', null, 0.015); add(sc.medians, '#2f3338', '#454a52', 0.02);
  for (const l of sc.lane_lines || []) if (Array.isArray(l.pts) && l.pts.length > 1) for (const q of stripe(l.pts, l.width || 0.15, !!l.dash)) flat.push({ pts: q, fill: 'rgba(228,231,235,.78)' });
  for (const c of sc.crossings || []) {
    if (!c.a || !c.b) continue;
    const L = Math.hypot(c.b[0] - c.a[0], c.b[1] - c.a[1]), ux = (c.b[0] - c.a[0]) / L, uz = (c.b[1] - c.a[1]) / L, w = c.width || 4;
    for (let s = 0.5; s < L; s += 1.2) { const p = [c.a[0] + ux * s, c.a[1] + uz * s]; flat.push(...stripe([[p[0] - (uz * w) / 2, p[1] + (ux * w) / 2], [p[0] + (uz * w) / 2, p[1] - (ux * w) / 2]], 0.6, false).map((q) => ({ pts: q, fill: 'rgba(228,231,235,.76)' }))); }
  }
  for (const b of sc.buildings || []) {
    if (!isPoly(b.footprint)) continue;
    const h = b.height_m || 12, F = b.footprint; pts.push(...F);
    const walls = [];
    for (let i = 0; i < F.length; i++) {
      const p = F[i], q = F[(i + 1) % F.length], deco = [], L = Math.hypot(q[0] - p[0], q[1] - p[1]);
      // ribbon windows, one band per floor, drawn straight after their wall so painter order holds
      if (L > 4) for (let y = 3; y + 1.6 < h - 0.8; y += 3.5) { const a = 1 / L, P = (f) => [p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f]; deco.push([G3(P(a), y), G3(P(1 - a), y), G3(P(1 - a), y + 1.5), G3(P(a), y + 1.5)]); }
      walls.push({ pts: [G3(p), G3(q), G3(q, h), G3(p, h)], deco });
    }
    const roof = { pts: F.map((p) => G3(p, h)) };
    orient([...walls, roof].map((f) => f.pts)).forEach((o, i) => { const f = i < walls.length ? walls[i] : roof; solid.push({ ...f, s: o.s, base: f === roof ? [70, 74, 81] : [96, 100, 108] }); });
  }
  for (const p of sc.poles || []) {
    if (!Array.isArray(p.at)) continue;
    const [x, z] = p.at, h = p.height_m || 7, a = (p.arm_deg ?? 90) * D2R, ax = x + Math.sin(a) * 1.4, az = z + Math.cos(a) * 1.4;
    for (const f of cylFaces(x, z, 0.1, 0, h, 6)) solid.push({ ...f, base: [72, 77, 84] });
    for (const f of boxFaces((x + ax) / 2, (z + az) / 2, 0.08, 1.4, h - 0.12, h, p.arm_deg ?? 90)) solid.push({ ...f, base: [72, 77, 84] });
    for (const f of boxFaces(ax, az, 0.32, 0.55, h - 0.32, h - 0.08, p.arm_deg ?? 90)) solid.push({ ...f, base: [214, 206, 172] });
  }
  for (const t of sc.trees || []) {
    if (!Array.isArray(t.at)) continue;
    const [x, z] = t.at, h = t.height_m || 6;
    for (const f of cylFaces(x, z, 0.16, 0, h * 0.45, 6)) solid.push({ ...f, base: [88, 74, 62] });
    for (const f of cylFaces(x, z, h * 0.27, h * 0.38, h * 0.82)) solid.push({ ...f, base: [56, 84, 62] });
    for (const f of cylFaces(x, z, h * 0.17, h * 0.82, h)) solid.push({ ...f, base: [62, 92, 68] });
  }
  const xs = pts.map((p) => p[0]), zs = pts.map((p) => p[1]);
  const bounds = pts.length ? [Math.min(...xs) - 10, Math.max(...xs) + 10, Math.min(...zs) - 10, Math.max(...zs) + 10] : null;
  return { flat, solid, bounds };
}
// clip a 2D polygon [[x,z]] to an axis-aligned rect [x0,x1,z0,z1]
function clipRect(P, [x0, x1, z0, z1]) {
  for (const [ax, lim, keep] of [[0, x0, 1], [0, x1, -1], [1, z0, 1], [1, z1, -1]]) {
    const out = [];
    for (let i = 0; i < P.length; i++) {
      const a = P[i], b = P[(i + 1) % P.length], ia = (a[ax] - lim) * keep >= 0, ib = (b[ax] - lim) * keep >= 0;
      if (ia) out.push(a);
      if (ia !== ib) { const k = (lim - a[ax]) / (b[ax] - a[ax]); out.push([a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]); }
    }
    P = out; if (!P.length) break;
  }
  return P;
}

export function createView3D(canvas, { onPick = () => {}, onChange = () => {} } = {}) {
  const g = canvas.getContext('2d');
  const cam = { ...VIEWS.persp, target: [0, 0, 1.5], dist: 5.6, ortho: false, view: 'persp', lock: false };
  const opt = { grid: true, fov: true, path: true, labels: true, scenery: true };
  let scene = { objects: [] }, env = { kind: 'dashcam' }, envKey = '', SCN = null, home = { target: [0, 0, 1.5], dist: 5.6 }, zoom = [2, 30];
  let picks = [], cube = [], B, W = 0, H = 0, raf = 0, FONT = { sans: 'system-ui, sans-serif', mono: 'ui-monospace, monospace' };
  const readFonts = () => { const cs = getComputedStyle(canvas); FONT = { sans: cs.getPropertyValue('--sans').trim() || FONT.sans, mono: cs.getPropertyValue('--mono').trim() || FONT.mono }; };
  const hatch = (() => { const c = document.createElement('canvas'); c.width = c.height = 7; const x = c.getContext('2d');
    x.fillStyle = '#111317'; x.fillRect(0, 0, 7, 7); x.strokeStyle = '#1d2026'; x.lineWidth = 1.6; x.beginPath(); x.moveTo(-2, 9); x.lineTo(9, -2); x.stroke(); return g.createPattern(c, 'repeat'); })();
  const spaced = (px) => { if ('letterSpacing' in g) g.letterSpacing = px; };

  // ---- projection with near-plane clipping ----
  function basis() {
    if (cam.lock && env.rig) { const R = env.rig, k = Math.min(W / (2 * R.tx), H / (2 * R.ty)); return { eye: R.c, f: R.f, r: R.r, u: R.u, k, ortho: false }; }
    return { ...camBasis(cam), k: H * 1.25, ortho: cam.ortho, s: H / (cam.dist * 0.9) };
  }
  const toCam = (p) => { const v = sub(p, B.eye); return [dot(v, B.r), dot(v, B.u), dot(v, B.f)]; };
  const scr = (c) => { const s = B.ortho ? B.s : B.k / c[2]; return [W / 2 + c[0] * s, H / 2 - c[1] * s, c[2]]; };
  const proj = (p) => { const c = toCam(p); return !B.ortho && c[2] < NEAR ? null : scr(c); };
  function clipNear(C, close) {
    if (B.ortho) return C;
    const out = [], n = C.length;
    for (let i = 0; i < (close ? n : n - 1); i++) {
      const a = C[i], b = C[(i + 1) % n], ia = a[2] >= NEAR, ib = b[2] >= NEAR;
      if (ia) out.push(a);
      if (ia !== ib) { const k = (NEAR - a[2]) / (b[2] - a[2]); out.push([a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, NEAR]); }
    }
    if (!close && C[n - 1][2] >= NEAR) out.push(C[n - 1]);
    return out;
  }
  const path = (pts) => { g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); };
  function poly(P3, fill, stroke, lw = 1, dash = null, close = true) {
    const C = clipNear(P3.map(toCam), close); if (C.length < 2) return null;
    const P = C.map(scr); path(P); if (close) g.closePath();
    if (fill) { g.fillStyle = fill; g.fill(); }
    if (stroke) { g.setLineDash(dash || []); g.lineWidth = lw; g.strokeStyle = stroke; g.stroke(); g.setLineDash([]); }
    return P;
  }
  // ground annotation in small spaced capitals
  function note(p3, s, color = '#626a75', size = 9) {
    const p = proj(p3); if (!p) return;
    g.font = `600 ${size}px ${FONT.sans}`; spaced('1.2px'); g.fillStyle = color; g.fillText(s, p[0] + 4, p[1] - 6); spaced('0px');
  }
  // soft contact shadow: three widening, fading copies of the footprint, pushed away from the light
  function shadow(foot, c, h) {
    const sx = (-LIGHT[0] / LIGHT[1]) * h * 0.35, sz = (-LIGHT[2] / LIGHT[1]) * h * 0.35;
    for (const [k, a] of [[1.0, 0.24], [1.18, 0.12], [1.38, 0.06]]) poly(foot.map((p) => [c[0] + (p[0] - c[0]) * k + sx, 0.03, c[2] + (p[2] - c[2]) * k + sz]), `rgba(0,0,0,${a})`, null);
  }

  // ---- environments ----
  function setEnv(e) {
    const key = e && e.kind === 'fixed' ? JSON.stringify(e.pose) + (e.scenery ? Object.keys(e.scenery).length : 0) : 'dashcam';
    if (key === envKey) { env = e || env; return; }
    envKey = key; env = e && e.kind === 'fixed' ? e : { kind: 'dashcam' };
    if (env.kind === 'fixed') {
      SCN = buildScenery(env.scenery);
      const R = env.rig, vis = env.visible || visibleGround(R);
      const ground = vis.filter((p) => Math.hypot(p[0] - R.c[0], p[1] - R.c[2]) < 120);
      const cx = ground.reduce((s, p) => s + p[0], 0) / (ground.length || 1), cz = ground.reduce((s, p) => s + p[1], 0) / (ground.length || 1);
      SCN.bounds = SCN.bounds || [cx - 60, cx + 60, cz - 60, cz + 60];
      SCN.bounds = [Math.min(SCN.bounds[0], R.c[0] - 10), Math.max(SCN.bounds[1], R.c[0] + 10), Math.min(SCN.bounds[2], R.c[2] - 10), Math.max(SCN.bounds[3], R.c[2] + 10)];
      SCN.visible = clipRect(vis, SCN.bounds);
      SCN.corners = visibleGround(R, 1).filter((_, i) => i % 2 === 0);
      home = { target: [cx, 0, cz], dist: 70 }; zoom = [6, 400];
      api.setView('camera');
    } else { SCN = null; home = { target: [0, 0, 1.5], dist: 5.6 }; zoom = [2, 30]; api.setView('persp'); }
  }
  function drawDashGround() {
    poly(DASH.hidden, hatch, null);
    if (opt.fov) poly(DASH.fov, 'rgba(138,180,255,.045)', null);
    if (opt.grid) for (let i = -4; i <= 4; i++) {
      poly([[i, 0, -1.2], [i, 0, 4.4]], null, i ? 'rgba(255,255,255,.045)' : 'rgba(239,107,99,.4)', 1, null, false);
      if (i >= -1) poly([[-4, 0, i], [4, 0, i]], null, i ? 'rgba(255,255,255,.045)' : 'rgba(110,160,255,.4)', 1, null, false);
    }
    for (const b of DASH.bands) { if (poly(b.pts, null, 'rgba(255,255,255,.12)', 1, [3, 5], false) && opt.labels) note(b.at, b.n); }
    if (opt.path) { poly(DASH.corridor, 'rgba(138,180,255,.10)', 'rgba(138,180,255,.75)', 1.25, [6, 4]); if (opt.labels) note(world(0, 0.5, 0.01), 'PROJECTED PATH  ·  ASSUMED STRAIGHT', '#9dbcf0'); }
    if (opt.fov) {
      for (const a of [-HALF, HALF]) poly([[0, 0.28, 0], world(a, RIM)], null, 'rgba(138,180,255,.5)', 1, [2, 3], false);
      poly(DASH.rim, null, 'rgba(138,180,255,.5)', 1, [2, 3], false);
      if (opt.labels) for (const s of [-1, 1]) note(world(s * (HALF + 8), 1.0), 'NOT VISIBLE TO CAMERA', '#4c535d');
    }
  }
  function drawFixedGround() {
    const [x0, x1, z0, z1] = SCN.bounds, rect = [[x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1]];
    poly(rect, '#191c21', null);
    if (opt.scenery) for (const f of SCN.flat) poly(f.pts, f.fill, f.stroke, 1);
    if (opt.grid) {
      for (let x = Math.ceil(x0 / 10) * 10; x <= x1; x += 10) poly([[x, 0.03, z0], [x, 0.03, z1]], null, 'rgba(255,255,255,.045)', 1, null, false);
      for (let z = Math.ceil(z0 / 10) * 10; z <= z1; z += 10) poly([[x0, 0.03, z], [x1, 0.03, z]], null, 'rgba(255,255,255,.045)', 1, null, false);
    }
    if (opt.fov && SCN.visible.length > 2) {
      // even-odd: everything inside the scene rect but outside the camera's ground footprint is hatched
      const outer = clipNear(rect.map(toCam), true).map(scr), inner = clipNear(SCN.visible.map((p) => toCam(G3(p, 0.04))), true).map(scr);
      if (outer.length > 2) {
        g.beginPath(); for (const ring of [outer, inner]) ring.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
        g.globalAlpha = 0.8; g.fillStyle = hatch; g.fill('evenodd'); g.globalAlpha = 1;
      }
      poly(SCN.visible.map((p) => G3(p, 0.05)), null, 'rgba(138,180,255,.55)', 1.25, [6, 4]);
    }
  }

  // ---- labels: glass pills with a status dot and a leader line; stacked so they never overlap ----
  function labels(list) {
    const placed = [];
    list.sort((a, b) => a.z - b.z);                                             // nearest first keeps its spot
    for (const L of list) {
      g.font = `600 11.5px ${FONT.sans}`; const wn = g.measureText(L.name).width;
      g.font = `500 10.5px ${FONT.mono}`; const wm = L.meta ? g.measureText(L.meta).width + 8 : 0;
      const w = 22 + wn + wm + 10, h = 22;
      let x = L.x - w / 2, y = L.y - h - 14;
      for (let i = 0; i < 4 && placed.some((r) => x < r.x + r.w + 4 && x + w + 4 > r.x && y < r.y + r.h + 3 && y + h + 3 > r.y); i++) y -= h + 4;
      placed.push({ x, y, w, h });
      g.strokeStyle = 'rgba(255,255,255,.28)'; g.lineWidth = 1; path([[L.x, L.y - 2], [L.x, y + h]]); g.stroke();
      g.save();
      if (L.sel) { g.shadowColor = 'rgba(138,180,255,.55)'; g.shadowBlur = 14; }
      g.fillStyle = 'rgba(16,19,25,.82)'; g.beginPath(); g.roundRect(x, y, w, h, 11); g.fill();
      g.restore();
      g.strokeStyle = L.sel ? ACCENT : 'rgba(255,255,255,.13)'; g.lineWidth = 1; g.beginPath(); g.roundRect(x + 0.5, y + 0.5, w - 1, h - 1, 10.5); g.stroke();
      g.fillStyle = L.dot; g.beginPath(); g.arc(x + 11, y + h / 2, 3.5, 0, 7); g.fill();
      g.textBaseline = 'middle'; g.font = `600 11.5px ${FONT.sans}`; g.fillStyle = '#eef1f5'; g.fillText(L.name, x + 20, y + h / 2 + 0.5);
      if (L.meta) { g.font = `500 10.5px ${FONT.mono}`; g.fillStyle = '#a6aeb8'; g.fillText(L.meta, x + 20 + wn + 8, y + h / 2 + 0.5); }
      g.textBaseline = 'alphabetic';
    }
  }

  function draw() {
    raf = 0;
    const dpr = window.devicePixelRatio || 1; W = canvas.clientWidth; H = canvas.clientHeight;
    if (!W || !H) return;
    if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); }
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.lineJoin = 'round'; g.lineCap = 'round';
    const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, '#1b2029'); bg.addColorStop(0.55, '#14181e'); bg.addColorStop(1, '#0f1216');
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const glow = g.createRadialGradient(W * 0.5, H * 0.05, 0, W * 0.5, H * 0.05, W * 0.7); glow.addColorStop(0, 'rgba(138,180,255,.07)'); glow.addColorStop(1, 'rgba(138,180,255,0)');
    g.fillStyle = glow; g.fillRect(0, 0, W, H);
    B = basis();
    const fixed = env.kind === 'fixed', fogNear = fixed ? 55 : 1e9, fogFar = fixed ? 240 : 2e9;
    fixed ? drawFixedGround() : drawDashGround();

    // gather solids: scenery, the camera mast or the ego car, then tracked objects
    const faces = [];
    if (fixed && opt.scenery) for (const f of SCN.solid) faces.push(f);
    if (fixed && !cam.lock) {                                                  // the camera's own mast and housing (not drawn from inside it)
      const R = env.rig;
      for (const f of cylFaces(R.c[0], R.c[2], 0.14, 0, R.c[1] - 0.3, 6)) faces.push({ ...f, base: [72, 77, 84] });
      for (const f of boxFaces(R.c[0], R.c[2], 0.5, 0.9, R.c[1] - 0.35, R.c[1] + 0.15, env.pose.yaw_deg)) faces.push({ ...f, base: [214, 218, 224] });
    }
    let ego = null;
    if (!fixed) { ego = modelFaces('car', [0, 0, -0.32], 0); for (const f of ego.faces) faces.push({ ...f, base: f.c === 'f' ? [214, 218, 224] : PAL[f.c], glass: f.c === 'g', edge: true }); shadow(ego.bounds.foot, [0, 0, -0.32], ego.bounds.h); }
    picks = [];
    for (const o of scene.objects) {
      o._base = fixed ? [o.pos[0], 0, o.pos[1]] : world(o.ang, o.r);
      const m = modelFaces(o.cls, o._base, fixed ? o.heading : o.ang, fixed ? metricDims(o.cls) : null);
      const person = resolveClass(o.cls) === 'person', paint = (person ? CLOTH : PAINT)[Math.abs(o.id | 0) % (person ? CLOTH.length : PAINT.length)];
      for (const f of m.faces) faces.push({ ...f, base: f.c === 'f' ? paint : PAL[f.c], glass: f.c === 'g', edge: true });
      o._h = m.bounds.h; o._foot = m.bounds.foot;
      if (o.hz !== 'grey') poly(o._foot.map((p) => [o._base[0] + (p[0] - o._base[0]) * 1.22, 0.04, o._base[2] + (p[2] - o._base[2]) * 1.22]), o.hz === 'red' ? 'rgba(248,81,73,.24)' : 'rgba(227,160,8,.2)', null);
      shadow(o._foot, o._base, o._h);
    }
    // cull back faces, light, fog and sort far to near
    const vis = [];
    for (const f of faces) {
      const c = mean(f.pts), v = sub(c, B.eye), n = f.n || faceN(f), d = Math.hypot(...v) || 1, vd = B.ortho ? B.f : [v[0] / d, v[1] / d, v[2] / d];
      if (dot(n, vd) > 0.02) continue;
      const fog = Math.min(0.55, Math.max(0, (d - fogNear) / (fogFar - fogNear)));
      vis.push({ f, z: dot(v, B.f), fill: shade(f.base, n, vd, fog, f.glass), dfill: f.deco ? shade([36, 46, 58], n, vd, fog, true) : null });
    }
    vis.sort((a, b) => b.z - a.z);
    for (const { f, fill, dfill } of vis) if (poly(f.pts, fill, f.edge ? 'rgba(0,0,0,.18)' : null, 0.5) && f.deco) for (const q of f.deco) poly(q, dfill, null);
    if (fixed && opt.fov && !cam.lock) {
      for (const p of SCN.corners) poly([env.rig.c, G3(p, 0.05)], null, 'rgba(138,180,255,.4)', 1, [2, 3], false);
    }

    // 3D boxes over everything: base (and its X) = hazard, top + uprights = confidence; accent glow when selected
    const tags = [];
    for (const o of scene.objects) {
      const c = o._base, pad = 1.06, h = o._h * 1.04;
      const bot = o._foot.map((p) => [c[0] + (p[0] - c[0]) * pad, 0.04, c[2] + (p[2] - c[2]) * pad]), top = bot.map((p) => [p[0], h, p[2]]);
      const hz = HZ[o.hz] || HZ.grey, ring = o.sel ? ACCENT : o.ring, dash = o.amber && !o.sel ? [5, 4] : null, lw = o.sel ? 2.2 : 1.5;
      poly(bot, null, hz, 1.5); g.globalAlpha = 0.55; poly([bot[0], bot[2]], null, hz, 1, null, false); poly([bot[1], bot[3]], null, hz, 1, null, false); g.globalAlpha = 1;
      g.save(); if (o.sel) { g.shadowColor = 'rgba(138,180,255,.7)'; g.shadowBlur = 10; }
      for (let i = 0; i < 4; i++) poly([bot[i], top[i]], null, ring, lw, dash, false);
      poly(top, o.sel ? 'rgba(138,180,255,.08)' : null, ring, lw, dash);
      g.restore();
      if (o.motion) {
        const a = proj([c[0], 0.06, c[2]]), b = proj([c[0] + o.motion[0], 0.06, c[2] + o.motion[1]]);
        if (a && b && Math.hypot(b[0] - a[0], b[1] - a[1]) > 4) {
          const an = Math.atan2(b[1] - a[1], b[0] - a[0]);
          g.strokeStyle = g.fillStyle = 'rgba(238,241,245,.9)'; g.lineWidth = 1.6; path([a, b]); g.stroke();
          path([b, [b[0] - 8 * Math.cos(an - 0.42), b[1] - 8 * Math.sin(an - 0.42)], [b[0] - 8 * Math.cos(an + 0.42), b[1] - 8 * Math.sin(an + 0.42)]]); g.closePath(); g.fill();
        }
      }
      const tp = proj([c[0], h, c[2]]);
      if (tp) { picks.push({ id: o.id, x: tp[0], y: tp[1] + 8 }); tags.push({ x: tp[0], y: tp[1], z: tp[2], name: o.label, meta: o.meta, dot: o.ring, sel: o.sel }); }
    }
    if (opt.labels) {
      if (ego) { const p = proj([0, ego.bounds.h, -0.32]); if (p) tags.push({ x: p[0], y: p[1], z: p[2], name: 'Ego', meta: 'camera', dot: '#c9d1d9' }); }
      if (fixed && !cam.lock) { const p = proj([env.rig.c[0], env.rig.c[1] + 0.4, env.rig.c[2]]); if (p) tags.push({ x: p[0], y: p[1], z: p[2], name: 'Camera', meta: env.camera_id || '', dot: '#c9d1d9' }); }
      labels(tags);
    }
    if (fixed && cam.lock) drawFrame();
    if (!scene.objects.length && scene.empty) {
      g.font = `500 13px ${FONT.sans}`; const w = g.measureText(scene.empty).width + 32;
      g.fillStyle = 'rgba(16,19,25,.86)'; g.strokeStyle = 'rgba(255,255,255,.12)'; g.beginPath(); g.roundRect(W / 2 - w / 2, H / 2 - 18, w, 36, 18); g.fill(); g.stroke();
      g.fillStyle = '#c3cad3'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(scene.empty, W / 2, H / 2); g.textAlign = 'start'; g.textBaseline = 'alphabetic';
    }
    drawGizmo(); drawCube();
    onChange(state());
  }
  // in camera view, mask everything outside the video frame and mark its corners
  function drawFrame() {
    const R = env.rig, fw = B.k * R.tx * 2, fh = B.k * R.ty * 2, x = (W - fw) / 2, y = (H - fh) / 2;
    g.fillStyle = 'rgba(9,11,14,.7)'; g.beginPath(); g.rect(0, 0, W, H); g.rect(x, y, fw, fh); g.fill('evenodd');
    g.strokeStyle = 'rgba(236,239,243,.8)'; g.lineWidth = 2;
    for (const [cx, cy, sx, sy] of [[x, y, 1, 1], [x + fw, y, -1, 1], [x, y + fh, 1, -1], [x + fw, y + fh, -1, -1]]) { path([[cx + sx * 20, cy], [cx, cy], [cx, cy + sy * 20]]); g.stroke(); }
    g.font = `600 10px ${FONT.sans}`; spaced('1.4px'); const s = `CAMERA VIEW  ·  ${env.camera_id || ''}`, w = g.measureText(s).width + 20;
    g.fillStyle = 'rgba(16,19,25,.82)'; g.beginPath(); g.roundRect(x + 10, y + 10, w, 22, 11); g.fill();
    g.fillStyle = '#dfe4ea'; g.textBaseline = 'middle'; g.fillText(s, x + 20, y + 21.5); g.textBaseline = 'alphabetic'; spaced('0px');
  }
  // glass disc behind the axis triad and the view cube
  function disc(cx, cy, r) { g.fillStyle = 'rgba(20,24,30,.55)'; g.beginPath(); g.arc(cx, cy, r, 0, 7); g.fill(); g.strokeStyle = 'rgba(255,255,255,.08)'; g.lineWidth = 1; g.stroke(); }
  function drawGizmo() {
    const o = [44, H - 44], L = 24;
    disc(o[0], o[1], 36);
    const axes = [[[1, 0, 0], '#ef6b63', 'X'], [[0, 1, 0], '#6cc070', 'Y'], [[0, 0, 1], '#6ea0ff', 'Z']].map(([v, c, n]) => ({ c, n, x: o[0] + dot(v, B.r) * L, y: o[1] - dot(v, B.u) * L, z: dot(v, B.f) }));
    for (const a of axes.sort((p, q) => q.z - p.z)) {
      g.strokeStyle = a.c; g.lineWidth = 2; path([o, [a.x, a.y]]); g.stroke();
      g.fillStyle = a.c; g.beginPath(); g.arc(a.x, a.y, 7.5, 0, 7); g.fill();
      g.fillStyle = '#0f1216'; g.font = `700 9px ${FONT.sans}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(a.n, a.x, a.y + 0.5); g.textAlign = 'start'; g.textBaseline = 'alphabetic';
    }
  }
  function drawCube() {
    const C = [W - 62, 62], S = 24, P = (p) => [C[0] + dot(p, B.r) * S, C[1] - dot(p, B.u) * S];
    disc(C[0], C[1], 50);
    cube = [];
    for (const [n, nv, view] of [['TOP', [0, 1, 0], 'top'], ['FRONT', [0, 0, 1], 'front'], ['BACK', [0, 0, -1], 'back'], ['RIGHT', [1, 0, 0], 'right'], ['LEFT', [-1, 0, 0], 'left']]) {
      if (dot(nv, B.f) >= -0.05) continue;
      const a = nv.findIndex((x) => x), t1 = [0, 0, 0], t2 = [0, 0, 0]; t1[(a + 1) % 3] = 1; t2[(a + 2) % 3] = 1;
      const pts = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([i, j]) => P([nv[0] + t1[0] * i + t2[0] * j, nv[1] + t1[1] * i + t2[1] * j, nv[2] + t1[2] * i + t2[2] * j]));
      const c = P(nv), on = cam.view === view;
      path(pts); g.closePath(); g.fillStyle = on ? '#3d64a3' : shade([74, 82, 94], nv, B.f, 0, false); g.fill();
      g.strokeStyle = on ? 'rgba(170,200,255,.9)' : 'rgba(220,226,234,.35)'; g.lineWidth = 1; g.stroke();
      g.fillStyle = '#eef1f5'; g.font = `700 8px ${FONT.sans}`; spaced('0.6px'); g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(n, c[0], c[1] + 0.5); g.textAlign = 'start'; g.textBaseline = 'alphabetic'; spaced('0px');
      cube.push({ view, pts });
    }
  }
  const inPoly = (x, y, P) => { let c = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) if ((P[i][1] > y) !== (P[j][1] > y) && x < ((P[j][0] - P[i][0]) * (y - P[i][1])) / (P[j][1] - P[i][1]) + P[i][0]) c = !c; return c; };
  const sched = () => { if (!raf) raf = requestAnimationFrame(draw); };
  function state() {
    const lk = cam.lock && env.pose;
    return { view: cam.view, yaw: Math.round(lk ? env.pose.yaw_deg : ((-cam.yaw % 360) + 540) % 360 - 180), pitch: Math.round(lk ? env.pose.pitch_deg : cam.pitch), ortho: cam.ortho && !cam.lock, env: env.kind };
  }
  // leave the locked camera view for an orbit that starts from the same viewpoint
  function unlock() {
    if (!cam.lock) return;
    const R = env.rig, p = Math.asin(-R.f[1]), d = R.c[1] / Math.max(0.05, Math.sin(p));
    Object.assign(cam, { lock: false, yaw: -env.pose.yaw_deg, pitch: (p * 180) / Math.PI, dist: d, target: [R.c[0] + R.f[0] * d, 0, R.c[2] + R.f[2] * d] });
  }

  // ---- input: left-drag orbit, right/shift-drag pan, wheel zoom, click pick, double-click home ----
  let drag = null;
  const down = (e) => { drag = { x: e.clientX, y: e.clientY, moved: false, pan: e.button === 2 || e.shiftKey }; canvas.setPointerCapture(e.pointerId); };
  const move = (e) => {
    if (!drag) { const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top; canvas.style.cursor = cube.some((c) => inPoly(x, y, c.pts)) || picks.some((p) => Math.hypot(p.x - x, p.y - y) < 28) ? 'pointer' : ''; return; }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true; else return;
    drag.x = e.clientX; drag.y = e.clientY; unlock(); B = basis();
    if (drag.pan) { const k = cam.dist / H; for (let i = 0; i < 3; i++) cam.target[i] += -dx * k * B.r[i] + dy * k * B.u[i]; }
    else { cam.yaw += dx * 0.4; cam.pitch = Math.max(2, Math.min(89.5, cam.pitch + dy * 0.3)); }
    cam.view = 'custom'; sched();
  };
  const up = (e) => {
    if (!drag) return; const was = drag; drag = null;
    if (was.moved) return;
    const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const f = cube.find((c) => inPoly(x, y, c.pts)); if (f) { api.setView(f.view); return; }
    let best = null, bd = 28; for (const p of picks) { const d = Math.hypot(p.x - x, p.y - y); if (d < bd) { bd = d; best = p; } }
    if (best) onPick(best.id);
  };
  const wheel = (e) => { e.preventDefault(); unlock(); if (cam.view === 'camera') cam.view = 'custom'; cam.dist = Math.max(zoom[0], Math.min(zoom[1], cam.dist * Math.exp(e.deltaY * 0.001))); sched(); };
  const ctxm = (e) => e.preventDefault();
  canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerup', up);
  canvas.addEventListener('wheel', wheel, { passive: false }); canvas.addEventListener('contextmenu', ctxm);
  canvas.addEventListener('dblclick', () => api.frame());
  const ro = new ResizeObserver(sched); ro.observe(canvas);
  readFonts();
  if (document.fonts) document.fonts.ready.then(() => { readFonts(); sched(); });

  const api = {
    render(s) { setEnv(s.env); scene = s; sched(); },
    redraw() { readFonts(); sched(); },
    setView(v) {
      if (v === 'camera') { if (env.kind !== 'fixed') return; Object.assign(cam, { lock: true, view: 'camera', ortho: false }); sched(); return; }
      const p = VIEWS[v]; if (!p) return;
      Object.assign(cam, p, { view: v, lock: false, target: [...home.target], dist: v === 'top' ? home.dist * 1.25 : home.dist }); sched();
    },
    toggle(k, on) { opt[k] = on ?? !opt[k]; sched(); return opt[k]; },
    setOrtho(on) { unlock(); cam.ortho = on ?? !cam.ortho; sched(); return cam.ortho; },
    frame() { if (env.kind === 'fixed') api.setView('camera'); else { cam.target = [...home.target]; cam.dist = home.dist; sched(); } },
    get options() { return { ...opt }; },
    get camera() { return state(); },
    destroy() { ro.disconnect(); },
  };
  return api;
}
