// Class models for the 3D viewport. Authored in metres, +z = front, y = up from the ground.
// One uniform scale keeps wheels and heads round. Fixed cameras use the metric height; the dashcam
// view uses the same mesh as a small glyph. The caller supplies heading.
// Part DSL:
//   b cx y cz w h d c          box (y = base)
//   t cx y cz w h d dt zs c    tapered box: top is dt deep, 90% as wide, its centre shifted zs in z
//   w cx cy cz r t c           wheel on the x axis
//   o cx cy cz r t c           octagonal plate on the z axis (signs, lamps)
//   v cx y cz r h c            upright octagonal cylinder
// Colour c: f = body paint, d = dark trim, l = light trim, g = glass, w = warm lamp (not a hazard colour).
// Parts are stacked with a small gap so the painter's sort never has two coplanar faces to fight over.
const WH = (x, z, r = 0.33, t = 0.2) => `w ${-x} ${r} ${z} ${r} ${t} d;w ${x} ${r} ${z} ${r} ${t} d;w ${-(x + t / 2 + 0.012)} ${r} ${z} ${(r * 0.42).toFixed(3)} 0.02 l;w ${x + t / 2 + 0.012} ${r} ${z} ${(r * 0.42).toFixed(3)} 0.02 l`;
const posts = (n, span, y, h, w) => Array.from({ length: n }, (_, i) => {
  const z = n === 1 ? 0 : -span / 2 + (span * i) / (n - 1);
  return `b 0 ${y} ${z.toFixed(3)} ${w} ${h} 0.07 d`;
}).join(';');

const SRC = {
  // shoulder yoke, gap between the legs, feet proud of the shins
  person: [
    'b -0.09 0 0.04 0.13 0.07 0.24 d', 'b 0.09 0 0.04 0.13 0.07 0.24 d',
    'b -0.08 0.08 0 0.12 0.76 0.16 d', 'b 0.08 0.08 0 0.12 0.76 0.16 d',
    'b 0 0.85 0 0.32 0.16 0.2 d',
    't 0 1.02 0 0.36 0.38 0.2 0.16 0 f',
    'b 0 1.41 0 0.48 0.08 0.16 f',
    'b -0.27 0.96 0.02 0.09 0.46 0.1 f', 'b 0.27 0.96 0.02 0.09 0.46 0.1 f',
    'v 0 1.5 0 0.055 0.06 l',
    'v 0 1.56 0 0.11 0.16 l',
    'v 0 1.72 0 0.112 0.05 d',
  ].join(';'),
  car: [
    'b 0 0.26 0 1.7 0.16 4.15 d',
    'b 0 0.43 0.05 1.78 0.42 4.25 f',
    'b 0 0.84 1.15 1.7 0.16 1.45 f',
    'b 0 0.86 -1.55 1.66 0.28 1.05 f',
    't 0 0.86 -0.2 1.58 0.48 2.05 1.15 -0.08 g',
    'b 0 1.35 -0.28 1.42 0.08 1.75 f',
    'b 0 1.44 -0.28 1.2 0.04 1.5 d',
    'b -0.55 0.55 2.16 0.32 0.12 0.06 l', 'b 0.55 0.55 2.16 0.32 0.12 0.06 l',
    'b 0 0.46 2.18 0.72 0.14 0.04 d',
    'b -0.62 0.55 -2.12 0.28 0.1 0.04 d', 'b 0.62 0.55 -2.12 0.28 0.1 0.04 d',
    WH(0.78, 1.38), WH(0.78, -1.32),
  ].join(';'),
  // cab in front, cargo bed behind, three axles
  truck: [
    'b 0 0.42 -0.4 2.2 0.28 6.6 d',
    'b 0 0.72 2.15 2.28 1.15 2.15 f',
    't 0 1.55 2.05 2.1 0.72 1.7 1.05 -0.05 g',
    'b 0 2.28 2.0 1.95 0.1 1.55 f',
    'b 0 1.15 -1.15 2.45 2.05 4.35 d',
    'b 0 3.18 -1.15 2.2 0.08 4.1 l',
    'b -0.55 0.85 3.22 0.28 0.12 0.05 l', 'b 0.55 0.85 3.22 0.28 0.12 0.05 l',
    WH(1.05, 2.15, 0.5, 0.24), WH(1.05, -0.85, 0.5, 0.24), WH(1.05, -2.15, 0.5, 0.24),
  ].join(';'),
  // glass band with pillars, so the side reads as windows rather than one slab
  bus: [
    'b 0 0.28 0 2.45 0.22 11.4 d',
    'b 0 0.52 0 2.5 0.72 11.5 f',
    'b 0 1.26 0 2.48 1.22 11.15 g',
    posts(9, 10.2, 1.28, 1.16, 2.56),
    'b 0 2.5 0 2.5 0.62 11.5 f',
    'b 0 3.14 0 2.35 0.12 11.2 d',
    'b -0.7 0.7 5.78 0.36 0.16 0.06 l', 'b 0.7 0.7 5.78 0.36 0.16 0.06 l',
    'b 0 0.85 5.55 1.3 0.7 0.04 g',
    WH(1.05, 3.5, 0.5, 0.24), WH(1.05, -3.5, 0.5, 0.24),
  ].join(';'),
  motorcycle: [
    'w 0 0.32 0.62 0.32 0.08 d', 'w 0 0.32 -0.62 0.32 0.08 d',
    'w 0 0.32 0.62 0.14 0.02 l', 'w 0 0.32 -0.62 0.14 0.02 l',
    'b 0 0.34 0 0.12 0.16 1.15 d',
    'b 0 0.52 0.15 0.28 0.16 0.55 f',
    'b 0 0.62 -0.35 0.22 0.1 0.4 d',
    'b 0 0.48 0.72 0.04 0.55 0.04 l',
    'b 0 0.95 0.55 0.55 0.04 0.08 l',
    'b 0 0.78 -0.05 0.32 0.36 0.28 f',
    'v 0 1.12 0.02 0.1 0.18 l',
    'b -0.2 0.82 0.12 0.08 0.28 0.08 f', 'b 0.2 0.82 0.12 0.08 0.28 0.08 f',
  ].join(';'),
  bicycle: [
    'w 0 0.34 0.58 0.34 0.04 d', 'w 0 0.34 -0.52 0.34 0.04 d',
    'b 0 0.36 -0.15 0.04 0.04 0.85 f',
    'b 0 0.55 0.15 0.04 0.04 0.7 f',
    'b 0 0.4 -0.15 0.04 0.42 0.04 f',
    'b 0 0.78 0.05 0.04 0.04 0.55 f',
    'b 0 0.42 0.55 0.04 0.4 0.04 f',
    'b 0 0.84 -0.15 0.12 0.05 0.28 d',
    'b 0 1.05 0.42 0.42 0.03 0.04 l',
    'b 0 0.78 -0.02 0.28 0.34 0.22 f',
    'v 0 1.1 0.02 0.09 0.16 l',
    'b 0 0.7 0.28 0.16 0.1 0.16 d',
  ].join(';'),
  dog: [
    'b -0.08 0 0.16 0.06 0.22 0.06 d', 'b 0.08 0 0.16 0.06 0.22 0.06 d',
    'b -0.08 0 -0.16 0.06 0.22 0.06 d', 'b 0.08 0 -0.16 0.06 0.22 0.06 d',
    't 0 0.2 0 0.22 0.2 0.55 0.28 0.04 f',
    'b 0 0.32 0.34 0.16 0.16 0.18 f',
    'b 0 0.34 0.46 0.08 0.08 0.12 d',
    'b -0.06 0.4 0.36 0.05 0.08 0.02 d', 'b 0.06 0.4 0.36 0.05 0.08 0.02 d',
    'b 0 0.36 -0.32 0.04 0.04 0.16 f',
  ].join(';'),
  // lamps stay off the hazard palette: two dark, one warm
  'traffic light': [
    'v 0 0 0 0.06 3.55 d',
    'b 0 3.5 0 0.32 0.95 0.22 d',
    'o 0 4.15 0.13 0.09 0.04 d',
    'o 0 3.9 0.13 0.09 0.04 w',
    'o 0 3.65 0.13 0.09 0.04 d',
  ].join(';'),
  'stop sign': [
    'v 0 0 0 0.04 1.85 d',
    'o 0 2.05 -0.03 0.4 0.025 d',
    'o 0 2.05 0.02 0.32 0.03 l',
  ].join(';'),
  generic: 'b 0 0 0 1.05 0.85 1.05 f;b 0 0.88 0 0.82 0.22 0.82 l',
};

export const ALIAS = { pedestrian: 'person', lorry: 'truck', van: 'car', motorbike: 'motorcycle', cyclist: 'bicycle', bike: 'bicycle', train: 'bus', coach: 'bus', cat: 'dog', traffic_light: 'traffic light', stop_sign: 'stop sign' };
export const resolveClass = (c) => { const k = String(c || '').toLowerCase(); const a = ALIAS[k] || k; return SRC[a] ? a : 'generic'; };

const MODELS = {};
for (const [k, s] of Object.entries(SRC)) MODELS[k] = s.split(';').filter(Boolean).map((p) => { const [t, ...n] = p.trim().split(/\s+/); const c = n.pop(); return { t, n: n.map(Number), c }; });

function ring(n, r, at) { return Array.from({ length: n }, (_, i) => { const a = ((i + 0.5) * 2 * Math.PI) / n; return at(Math.cos(a) * r, Math.sin(a) * r); }); }
function extrude(a, b) {
  const n = a.length, F = [a.slice().reverse(), b];
  for (let i = 0; i < n; i++) F.push([a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]]);
  return F;
}
function prism(t, [cx, cy, cz, r, h]) {
  if (t === 'v') return extrude(ring(8, r, (u, w) => [cx + u, cy, cz + w]), ring(8, r, (u, w) => [cx + u, cy + h, cz + w]));
  const s = h / 2;
  if (t === 'w') return extrude(ring(12, r, (u, w) => [cx - s, cy + u, cz + w]), ring(12, r, (u, w) => [cx + s, cy + u, cz + w]));
  return extrude(ring(8, r, (u, w) => [cx + u, cy + w, cz - s]), ring(8, r, (u, w) => [cx + u, cy + w, cz + s]));
}
function box([cx, y, cz, w, h, d, dt = d, zs = 0], taper = 1) {
  const v = [];
  for (const [yy, ww, dd, zz] of [[y, w, d, cz], [y + h, w * taper, dt, cz + zs]]) for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) v.push([cx + (a * ww) / 2, yy, zz + (b * dd) / 2]);
  return [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]].map((f) => f.map((i) => v[i]));
}
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const mean = (P) => P.reduce((s, p) => [s[0] + p[0] / P.length, s[1] + p[1] / P.length, s[2] + p[2] / P.length], [0, 0, 0]);
export function orient(faces) {
  const c = mean(faces.flat());
  return faces.map((pts) => { const n = cross(sub(pts[1], pts[0]), sub(pts[2], pts[0])), m = sub(mean(pts), c); return { pts, s: n[0] * m[0] + n[1] * m[1] + n[2] * m[2] >= 0 ? 1 : -1 }; });
}
const CACHE = {};
function local(cls) {
  if (CACHE[cls]) return CACHE[cls];
  const faces = [], b = { x0: Infinity, x1: -Infinity, z0: Infinity, z1: -Infinity, h: 0 };
  for (const p of MODELS[cls]) {
    const fs = p.t === 'b' ? box(p.n) : p.t === 't' ? box(p.n, 0.9) : prism(p.t, p.n);
    for (const f of orient(fs)) {
      for (const [x, y, z] of f.pts) { b.x0 = Math.min(b.x0, x); b.x1 = Math.max(b.x1, x); b.z0 = Math.min(b.z0, z); b.z1 = Math.max(b.z1, z); b.h = Math.max(b.h, y); }
      faces.push({ ...f, c: p.c });
    }
  }
  return (CACHE[cls] = { faces, b });
}
const GLYPH = 0.52 / 1.75;                       // dashcam: a person is the old glyph height; other classes keep their proportions
// -> { faces: [{pts (world), s, c}], bounds: {h, foot} } at base [x,0,z], yaw degrees, +z = forward.
// `dims` [width, length, height] in metres sets one scale from height (fixed cameras). Wheels stay round.
// Dashcam passes null and uses GLYPH, the same metres-to-glyph factor for every class.
export function modelFaces(cls, base, yaw, dims = null) {
  const { faces, b } = local(resolveClass(cls)), s = Math.sin((yaw * Math.PI) / 180), co = Math.cos((yaw * Math.PI) / 180);
  const kh = dims ? dims[2] / (b.h || 1) : GLYPH;
  const T = ([x, y, z]) => { x *= kh; y *= kh; z *= kh; return [base[0] + x * co + z * s, y, base[2] - x * s + z * co]; };
  const foot = [[b.x0, 0, b.z0], [b.x1, 0, b.z0], [b.x1, 0, b.z1], [b.x0, 0, b.z1]].map(T);
  return { faces: faces.map((f) => ({ pts: f.pts.map(T), s: f.s, c: f.c })), bounds: { h: b.h * kh, foot } };
}
export const CLASSES = Object.keys(SRC);
export const METRIC = { person: [0.6, 0.5, 1.75], car: [1.85, 4.6, 1.5], truck: [2.5, 7.5, 3.3], bus: [2.6, 12, 3.3], motorcycle: [0.8, 2.1, 1.4], bicycle: [0.6, 1.8, 1.6], dog: [0.35, 0.9, 0.6], 'traffic light': [0.4, 0.4, 4.5], 'stop sign': [0.8, 0.1, 2.4], generic: [1.2, 1.2, 1.2] };
export const metricDims = (cls) => METRIC[resolveClass(cls)];
