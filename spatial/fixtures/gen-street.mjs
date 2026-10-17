// Generates SYNTHETIC_c98.*: a stationary street camera (UI work only; every number is made up).
// node spatial/fixtures/gen-street.mjs
// Ground truth lives in metres; boxes are produced by projecting each object's 3D box through the same
// pinhole camera the panel uses, so the round trip image -> ground can be checked by eye.
import { writeFileSync } from 'node:fs';
import { rig, worldToImage } from '../camera.js';
import { METRIC } from '../models3d.js';
const D = new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const W = 1920, H = 1080;
const pose = { x: -10.5, z: -14, height_m: 18, yaw_deg: 11, pitch_deg: 33, hfov_deg: 72 };
const R = rig(pose, { w: W, h: H });

// ---- scenery: a 4-lane avenue along +z, pavements, buildings, lamp posts, trees, a zebra crossing
const Z0 = -30, Z1 = 170;
const rect = (x0, x1, z0, z1) => [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
const buildings = [];
for (let z = Z0; z < Z1; z += 26) {
  buildings.push({ footprint: rect(13, 28, z, z + 22), height_m: 14 + ((z * 7) % 13) });
  buildings.push({ footprint: rect(-34, -19, z + 6, z + 26), height_m: 10 + ((z * 5) % 11) });
}
const scenery = {
  roads: [rect(-7.2, 7.2, Z0, Z1)],
  sidewalks: [rect(-13, -7.2, Z0, Z1), rect(7.2, 13, Z0, Z1)],
  medians: [rect(-0.4, 0.4, Z0, 36), rect(-0.4, 0.4, 48, Z1)],
  lane_lines: [{ pts: [[-3.6, Z0], [-3.6, Z1]], dash: true }, { pts: [[3.6, Z0], [3.6, Z1]], dash: true },
    { pts: [[-7.05, Z0], [-7.05, Z1]], width: 0.12 }, { pts: [[7.05, Z0], [7.05, Z1]], width: 0.12 }],
  crossings: [{ a: [-7.2, 42], b: [7.2, 42], width: 4 }],
  buildings,
  poles: Array.from({ length: 13 }, (_, i) => ({ at: [-8.2, Z0 + 6 + i * 15], height_m: 7.5, arm_deg: 90 })),
  trees: Array.from({ length: 16 }, (_, i) => ({ at: [10.5, Z0 + 4 + i * 12], height_m: 6.5 })),
};
writeFileSync(D + 'SYNTHETIC_c98.camera.json', JSON.stringify({ camera_id: 'SYNTHETIC_street_cam', kind: 'fixed', pose, scenery }, null, 1));

// ---- objects: [id, cls, x, z0, speed (m/s along +z), t0, t1]
const movers = [
  [1, 'car', 5.4, 2, 9, 0, 30], [2, 'truck', 1.8, -4, 6, 0, 30], [3, 'car', 1.8, 30, 7.5, 0, 30], [4, 'motorcycle', 3.4, -10, 11, 4, 22],
  [5, 'car', -1.8, 140, -8.5, 0, 30], [6, 'bus', -5.4, 150, -6, 6, 30], [7, 'car', -5.4, 70, -7, 0, 14], [9, 'person', 9.6, 10, 1.3, 0, 30],
  [10, 'person', -9.8, 60, -1.1, 0, 30], [11, 'car', 5.4, 110, 0, 0, 30],
];
const tracks = [], dets = [];
const corners = (x, z, [w, l, h], yaw) => {
  const s = Math.sin(yaw), c = Math.cos(yaw), out = [];
  for (const y of [0, h]) for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) out.push([x + (a * w / 2) * c + (b * l / 2) * s, y, z - (a * w / 2) * s + (b * l / 2) * c]);
  return out;
};
function emit(id, cls, t, x, z, yaw, extra, conf) {
  const P = corners(x, z, METRIC[cls], yaw).map((p) => worldToImage(R, p));
  if (P.some((p) => !p)) return;
  let [u0, v0, u1, v1] = [Math.min(...P.map((p) => p[0])), Math.min(...P.map((p) => p[1])), Math.max(...P.map((p) => p[0])), Math.max(...P.map((p) => p[1]))];
  if (u1 < 0 || u0 > 1 || v1 < 0 || v0 > 1) return;
  [u0, v0, u1, v1] = [Math.max(0, u0), Math.max(0, v0), Math.min(1, u1), Math.min(1, v1)];
  if ((v1 - v0) < 0.012) return;
  const xyxy = [u0 * W, v0 * H, u1 * W, v1 * H].map(Math.round);
  tracks.push({ track_id: id, t, cls, xyxy, vx: 0, vy: 0, h_rate: 0, in_corridor: false, heading_in: false, ttc: null, t_lat: null, risk: 0.12, ...extra });
  if (conf != null) dets.push({ t, frame: Math.round(t * 30), cls, conf, xyxy: xyxy.map((v, i) => v + (i % 2 ? 1 : -1)) });
}
for (let i = 0; i <= 150; i++) {
  const t = +(i * 0.2).toFixed(1);
  for (const [id, cls, x, z0, v, t0, t1] of movers) {
    if (t < t0 || t > t1) continue;
    // traffic loops through the 150 m stretch the camera sees; each lap is a new track id (no teleporting tracks)
    const raw = z0 + v * (t - t0) + 10, lap = Math.floor(raw / 150), z = raw - lap * 150 - 10, tid = id + 100 * (lap + 2);
    const dist = Math.hypot(x - pose.x, z - pose.z);
    const conf = id === 4 ? 0.48 : id === 6 && t < 9 ? null : +Math.max(0.35, 0.97 - dist / 160).toFixed(2);
    emit(v ? tid : id, cls, t, x, z, v < 0 ? Math.PI : 0, { risk: id === 4 && t > 8 && t < 14 ? 0.47 : 0.12 }, conf);
  }
  // 8: pedestrian crossing the avenue on the zebra, 14 s .. 25 s (the labelled hazard)
  if (t >= 14 && t <= 25) {
    const x = -10 + 1.45 * (t - 14), onRoad = x > -7.2 && x < 7.2;
    const risk = +Math.min(0.82, 0.15 + Math.max(0, x + 7.2) * 0.06).toFixed(2);
    emit(8, 'person', t, x, 42.5, Math.PI / 2, { risk, heading_in: onRoad, in_corridor: x > -3.6 && x < 3.6 }, 0.88);
  }
}
const jl = (a) => a.map((r) => JSON.stringify(r)).join('\n') + '\n';
const seg = (i) => ({ source: `s3://SYNTHETIC/c98_${i + 1}.mp4`, start_s: i * 5, end_s: i * 5 + 5 });
writeFileSync(D + 'SYNTHETIC_c98.tracks.jsonl', jl(tracks));
writeFileSync(D + 'SYNTHETIC_c98.det.jsonl', jl(dets));
writeFileSync(D + 'SYNTHETIC_c98.clips.json', JSON.stringify([{ clip_id: 'c98', camera_id: 'SYNTHETIC_street_cam', segments: [0, 1, 2, 3, 4, 5].map(seg), duration_s: 30 }]));
writeFileSync(D + 'SYNTHETIC_c98.hazards.json', JSON.stringify([{ hazard_id: 'c98_h1', clip_id: 'c98', type: 'pedestrian_crossing', window_start: 15.2, window_end: 19.0, agreed: true, track_id: 8, description: 'SYNTHETIC pedestrian crosses the avenue on the zebra' }]));
writeFileSync(D + 'SYNTHETIC_c98.run.jsonl', jl([{ run_id: 'SYNTHETIC', clip_id: 'c98', clicks: [{ t: 16.8, t_trigger: 16.2, latency_s: 0.6, reason: 'risk 0.61' }], risk_curve: [] }]));
writeFileSync(D + 'SYNTHETIC_c98.grid.jsonl', jl([{ t: 16.0, track_id: 8, where: 'in_our_lane', motion: 'moving_into_our_path', our_car: 'moving', act: 'yes', object: 'pedestrian', latency_s: 0.9 }]));
console.log('tracks', tracks.length, 'dets', dets.length);
