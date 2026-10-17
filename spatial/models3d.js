// Low-poly class models for the 3D viewport. Generic shapes, not to scale, orientation not measured.
// Part DSL, hundredths of a band unit, +z = front, y = up from the ground:
//   b cx y cz w h d c          box (y = base)
//   t cx y cz w h d dt zs c    tapered box: top is dt deep, 90% as wide, its centre shifted zs in z (cabins, windscreens)
//   w cx cy cz r t c           wheel / disc on the x axis      o cx cy cz r t c   disc on the z axis (plates)
//   v cx y cz r h c            upright octagonal cylinder (heads, poles)
// Colour c: f = body paint, d = dark trim, l = light trim, g = glass.
// Parts are stacked rather than overlapped, so the painter's sort never has two coplanar faces to fight over.
const WH = (x, z, r = 6, t = 5) => `w -${x} ${r} ${z} ${r} ${t} d;w ${x} ${r} ${z} ${r} ${t} d;w -${x + t / 2 + 0.3} ${r} ${z} ${r * 0.5} 0.6 l;w ${x + t / 2 + 0.3} ${r} ${z} ${r * 0.5} 0.6 l`;
const SRC = {
  person: 'b -3.2 0 0 4.6 17 6 d;b 3.2 0 0 4.6 17 6 d;b 0 17 0 12 4 7 d;t 0 21 0 13 13 7.5 6.5 0 f;b -8.4 21.5 0 3.2 12 3.8 f;b 8.4 21.5 0 3.2 12 3.8 f;v 0 34 0 1.8 1.6 l;v 0 35.6 0 3.6 6 l;v 0 41.6 0 3.7 1.6 d',
  car: `b 0 3.5 0 35 3.5 63 d;b 0 7 0 36 9 64 f;t 0 16 -2 33 9.5 34 19 -3 g;b 0 25.5 -4.5 29 1.2 18 f;b -11 11 32.4 8 2.5 0.8 l;b 11 11 32.4 8 2.5 0.8 l;${WH(16.5, 20)};${WH(16.5, -20)}`,
  truck: `b 0 4 -6 34 4 76 d;b 0 8 31 38 11 20 f;t 0 19 31 37 9 20 17 -1.5 g;b 0 28 30.2 33 2 16 f;b 0 8 -12 42 38 62 l;b -11 12 41.4 7 2.5 0.8 l;b 11 12 41.4 7 2.5 0.8 l;${WH(17, 31, 7)};${WH(17, -26, 7)};${WH(17, -38, 7)}`,
  bus: `b 0 3 0 41 3 97 d;b 0 6 0 42 14 98 f;b 0 20 0 42 11 98 g;b 0 31 0 42 8 98 f;b 0 39 -10 30 3 40 l;b -13 9 49.4 7 3 0.8 l;b 13 9 49.4 7 3 0.8 l;${WH(17, 32, 7)};${WH(17, -32, 7)}`,
  motorcycle: 'w 0 7.5 17 7.5 4 d;w 0 7.5 -17 7.5 4 d;b 0 5 0 9 8 14 d;t 0 13 4 9 5 12 9 0 f;b 0 15 -9 9 3 14 d;b 0 9 15 2.5 16 2.5 l;b 0 25 14 20 2 2 l;b 0 20 17.5 5 4 2 l',
  bicycle: 'w 0 8 16 8 1.5 d;w 0 8 -16 8 1.5 d;b 0 7 -8 2 2 16 f;b 0 9 2 2 2 18 f;b 0 9 -4 2 13 2 f;b 0 21 4 2 2 16 f;b 0 12 13 2 12 2 f;b 0 22 -5 5 1.6 8 d;b 0 24 13 16 1.6 1.6 l',
  dog: 't 0 7 0 8 7 18 16 0 f;b -2.8 0 6 2 7 2 d;b 2.8 0 6 2 7 2 d;b -2.8 0 -6 2 7 2 d;b 2.8 0 -6 2 7 2 d;b 0 11 10.5 6 6 6 f;b 0 11.5 14.5 3.4 3 2 d;b 0 12 -10.5 1.4 1.4 5 f',
  'traffic light': 'v 0 0 0 1.4 40 d;b 0 40 0 8 22 6 d;o 0 55 3.4 2.2 0.8 g;o 0 48 3.4 2.2 0.8 g;o 0 41 3.4 2.2 0.8 g',
  'stop sign': 'v 0 0 0 1.2 31 d;o 0 38 0 10 1 l',
  generic: 'b 0 0 0 20 16 20 f;b 0 16 0 16 4 16 l',
};
export const ALIAS = { pedestrian: 'person', lorry: 'truck', van: 'car', motorbike: 'motorcycle', cyclist: 'bicycle', bike: 'bicycle', train: 'bus', coach: 'bus', cat: 'dog', traffic_light: 'traffic light', stop_sign: 'stop sign' };
export const resolveClass = (c) => { const k = String(c || '').toLowerCase(); const a = ALIAS[k] || k; return SRC[a] ? a : 'generic'; };
const K = 0.0135;                                          // hundredths x 1.35 display scale (dashcam glyph size)
const MODELS = {};
for (const [k, s] of Object.entries(SRC)) MODELS[k] = s.split(';').map((p) => { const [t, ...n] = p.split(' '); const c = n.pop(); return { t, n: n.map((v) => v * K), c }; });

function ring(n, r, at) { return Array.from({ length: n }, (_, i) => { const a = ((i + 0.5) * 2 * Math.PI) / n; return at(Math.cos(a) * r, Math.sin(a) * r); }); }
function extrude(a, b) {                                   // two matching rings -> caps + sides
  const n = a.length, F = [a.slice().reverse(), b];
  for (let i = 0; i < n; i++) F.push([a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]]);
  return F;
}
function prism(t, [cx, cy, cz, r, h]) {
  if (t === 'v') return extrude(ring(8, r, (u, w) => [cx + u, cy, cz + w]), ring(8, r, (u, w) => [cx + u, cy + h, cz + w]));
  const s = h / 2;
  if (t === 'w') return extrude(ring(10, r, (u, w) => [cx - s, cy + u, cz + w]), ring(10, r, (u, w) => [cx + s, cy + u, cz + w]));
  return extrude(ring(8, r, (u, w) => [cx + u, cy + w, cz - s]), ring(8, r, (u, w) => [cx + u, cy + w, cz + s]));
}
function box([cx, y, cz, w, h, d, dt = d, zs = 0], taper = 1) {
  const v = [];
  for (const [yy, ww, dd, zz] of [[y, w, d, cz], [y + h, w * taper, dt, cz + zs]]) for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) v.push([cx + (a * ww) / 2, yy, zz + (b * dd) / 2]);
  return [[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]].map((f) => f.map((i) => v[i]));   // no bottom face
}
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const mean = (P) => P.reduce((s, p) => [s[0] + p[0] / P.length, s[1] + p[1] / P.length, s[2] + p[2] / P.length], [0, 0, 0]);
// s = +1 when the face's winding normal already points away from its part's centre, else -1 (used for lighting and culling)
export function orient(faces) {
  const c = mean(faces.flat());
  return faces.map((pts) => { const n = cross(sub(pts[1], pts[0]), sub(pts[2], pts[0])), m = sub(mean(pts), c); return { pts, s: n[0] * m[0] + n[1] * m[1] + n[2] * m[2] >= 0 ? 1 : -1 }; });
}
// local geometry is built once per class
const CACHE = {};
function local(cls) {
  if (CACHE[cls]) return CACHE[cls];
  const faces = [], b = { x0: 0, x1: 0, z0: 0, z1: 0, h: 0 };
  for (const p of MODELS[cls]) {
    const fs = p.t === 'b' ? box(p.n) : p.t === 't' ? box(p.n, 0.9) : prism(p.t, p.n);
    for (const f of orient(fs)) {
      for (const [x, y, z] of f.pts) { b.x0 = Math.min(b.x0, x); b.x1 = Math.max(b.x1, x); b.z0 = Math.min(b.z0, z); b.z1 = Math.max(b.z1, z); b.h = Math.max(b.h, y); }
      faces.push({ ...f, c: p.c });
    }
  }
  return (CACHE[cls] = { faces, b });
}
// -> { faces: [{pts (world), s, c}], bounds: {h, foot} } placed at base [x,0,z], rotated by yaw (deg, +z = away from ego)
// `dims` [width, length, height] in metres stretches the model to a real class size (fixed-camera scenes)
export function modelFaces(cls, base, yaw, dims = null) {
  const { faces, b } = local(resolveClass(cls)), s = Math.sin((yaw * Math.PI) / 180), co = Math.cos((yaw * Math.PI) / 180);
  const k = dims ? [dims[0] / (b.x1 - b.x0), dims[2] / b.h, dims[1] / (b.z1 - b.z0)] : [1, 1, 1];
  const T = ([x, y, z]) => { x *= k[0]; y *= k[1]; z *= k[2]; return [base[0] + x * co + z * s, y, base[2] - x * s + z * co]; };
  const foot = [[b.x0, 0, b.z0], [b.x1, 0, b.z0], [b.x1, 0, b.z1], [b.x0, 0, b.z1]].map(T);
  return { faces: faces.map((f) => ({ pts: f.pts.map(T), s: f.s, c: f.c })), bounds: { h: b.h * k[1], foot } };
}
export const CLASSES = Object.keys(SRC);
// typical real sizes [width, length, height] in metres, used only to size the generic models
export const METRIC = { person: [0.6, 0.5, 1.75], car: [1.85, 4.6, 1.5], truck: [2.5, 7.5, 3.3], bus: [2.6, 12, 3.3], motorcycle: [0.8, 2.1, 1.4], bicycle: [0.6, 1.8, 1.6], dog: [0.35, 0.9, 0.6], 'traffic light': [0.4, 0.4, 4.5], 'stop sign': [0.8, 0.1, 2.4], generic: [1.2, 1.2, 1.2] };
export const metricDims = (cls) => METRIC[resolveClass(cls)];
