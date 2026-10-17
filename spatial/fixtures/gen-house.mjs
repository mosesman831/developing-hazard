// Generates SYNTHETIC_c97.*: a house-mounted camera looking across a front yard at a residential road
// (UI work only; every number is made up). Modelled on the neighbourhood camera in the challenge corpus:
// mounted ~3.6 m up on a house wall, wide barrel-distorted lens, 2048x1154 frames.
// node spatial/fixtures/gen-house.mjs
// Boxes come from projecting each object's 3D box through the same distorted camera the panel uses.
import { writeFileSync } from 'node:fs';
import { rig, worldToImage } from '../camera.js';
import { METRIC } from '../models3d.js';
const D = new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const FRAME = { w: 2048, h: 1154 };
const pose = { x: 0, z: 0, height_m: 3.6, yaw_deg: 6, pitch_deg: 15, hfov_deg: 112, k1: -0.22 };
const R = rig(pose, FRAME);

// ---- scenery: our house behind the camera, a front yard and driveway, a 2-lane road running left to right,
// pavements, houses and trees across the road, a street light
const rect = (x0, x1, z0, z1) => [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
const scenery = {
  roads: [rect(-70, 70, 12, 19)],
  sidewalks: [rect(-70, 70, 10, 12), rect(-70, 70, 19, 21.5), rect(-1.8, 1.8, 0, 10)],
  lane_lines: [{ pts: [[-70, 15.5], [70, 15.5]], dash: true }, { pts: [[-70, 12.06], [70, 12.06]], width: 0.12 }, { pts: [[-70, 18.94], [70, 18.94]], width: 0.12 }],
  buildings: [{ footprint: rect(-7, 7, -11, -0.3), height_m: 6.5 },
    ...[[-46, -34], [-30, -18], [-14, -2], [2, 14], [18, 30], [34, 46]].map(([a, b], i) => ({ footprint: rect(a, b, 25, 34), height_m: 6.5 + (i % 3) * 1.2 }))],
  poles: [{ at: [-14, 10.6], height_m: 7, arm_deg: 0 }, { at: [26, 10.6], height_m: 7, arm_deg: 0 }],
  trees: [...[-38, -24, -9, 6, 21, 37].map((x) => ({ at: [x, 20.9], height_m: 7.5 })), { at: [-21, 10.9], height_m: 6 }, { at: [17, 10.9], height_m: 5.5 }],
};
writeFileSync(D + 'SYNTHETIC_c97.camera.json', JSON.stringify({ camera_id: 'SYNTHETIC_house_cam', kind: 'fixed', pose, scenery }, null, 1));

// ---- objects: [id, cls, path(t) -> [x, z], t0, t1, yaw (rad, 0 = +z)]
const E = Math.PI / 2, W = -Math.PI / 2, N = Math.PI;
const movers = [
  [1, 'car', (t) => [-60 + 9 * (t - 2), 13.8], 2, 16, E],              // eastbound, near lane
  [2, 'car', (t) => [60 - 7 * (t - 8), 17.2], 8, 26, W],               // westbound, far lane: passes the crossing pedestrian
  [3, 'car', () => [9, 13.2], 0, 30, E],                               // parked at the near kerb
  [4, 'truck', (t) => [60 - 6 * (t - 19), 17.2], 19, 30, W],           // van / lorry, far lane
  [5, 'person', (t) => (t < 13 ? [-14 + 1.3 * t, 11] : [2.9, 11 + 1.4 * (t - 13)]), 0, 21, 0],   // walks along, then crosses
  [6, 'bicycle', (t) => [-50 + 4.5 * (t - 18), 12.9], 18, 30, E],      // cyclist, near lane
  [7, 'person', (t) => [30 - 1.1 * t, 20.4], 0, 30, W],                // walker on the far pavement
];
const tracks = [], dets = [];
const corners = (x, z, [w, l, h], yaw) => {
  const s = Math.sin(yaw), c = Math.cos(yaw), out = [];
  for (const y of [0, h]) for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) out.push([x + (a * w / 2) * c + (b * l / 2) * s, y, z - (a * w / 2) * s + (b * l / 2) * c]);
  return out;
};
const r3 = (v) => +v.toFixed(3);
for (let i = 0; i <= 150; i++) {
  const t = +(i * 0.2).toFixed(1);
  for (const [id, cls, at, t0, t1, yaw0] of movers) {
    if (t < t0 || t > t1) continue;
    const [x, z] = at(t), yaw = id === 5 && t >= 13 ? 0 : id === 5 ? E : yaw0;
    const P = corners(x, z, METRIC[cls], yaw).map((p) => worldToImage(R, p));
    if (P.some((p) => !p)) continue;
    let [u0, v0, u1, v1] = [Math.min(...P.map((p) => p[0])), Math.min(...P.map((p) => p[1])), Math.max(...P.map((p) => p[0])), Math.max(...P.map((p) => p[1]))];
    if (u1 < 0 || u0 > 1 || v1 < 0 || v0 > 1) continue;
    [u0, v0, u1, v1] = [Math.max(0, u0), Math.max(0, v0), Math.min(1, u1), Math.min(1, v1)];
    if (v1 - v0 < 0.015) continue;
    const xyxy = [u0, v0, u1, v1].map(r3);                            // normalised 0-1, as in the pod snapshot (SPEC 6.4)
    const crossing = id === 5 && t >= 13;
    const risk = crossing ? +Math.min(0.84, 0.2 + 0.11 * (t - 13)).toFixed(2) : id === 6 ? 0.32 : 0.1;
    tracks.push({ track_id: id, t, cls, xyxy, vx: 0, vy: 0, h_rate: 0, in_corridor: false, heading_in: crossing, ttc: null, t_lat: null, risk });
    const conf = id === 7 ? 0.52 : id === 6 ? 0.71 : +(0.93 - Math.hypot(x, z) / 120).toFixed(2);
    if (!(id === 4 && t < 21)) dets.push({ t, frame: Math.round(t * 30), cls, conf, xyxy: xyxy.map((v, k) => r3(v + (k % 2 ? 0.001 : -0.001))) });
  }
}
const jl = (a) => a.map((r) => JSON.stringify(r)).join('\n') + '\n';
const seg = (i) => ({ source: `s3://SYNTHETIC/c97_${i + 1}.mp4`, start_s: i * 5, end_s: i * 5 + 5 });
writeFileSync(D + 'SYNTHETIC_c97.tracks.jsonl', jl(tracks));
writeFileSync(D + 'SYNTHETIC_c97.det.jsonl', jl(dets));
writeFileSync(D + 'SYNTHETIC_c97.clips.json', JSON.stringify([{ clip_id: 'c97', camera_id: 'SYNTHETIC_house_cam', segments: [0, 1, 2, 3, 4, 5].map(seg), duration_s: 30 }]));
writeFileSync(D + 'SYNTHETIC_c97.hazards.json', JSON.stringify([{ hazard_id: 'c97_h1', clip_id: 'c97', type: 'pedestrian_crossing', window_start: 14.0, window_end: 17.4, agreed: true, track_id: 5, description: 'SYNTHETIC pedestrian crosses in front of an oncoming car' }]));
writeFileSync(D + 'SYNTHETIC_c97.run.jsonl', jl([{ run_id: 'SYNTHETIC', clip_id: 'c97', clicks: [{ t: 15.4, t_trigger: 14.9, latency_s: 0.5, reason: 'risk 0.42' }], risk_curve: [] }]));
writeFileSync(D + 'SYNTHETIC_c97.grid.jsonl', jl([{ t: 15.0, track_id: 5, where: 'in_our_lane', motion: 'moving_into_our_path', our_car: 'moving', act: 'yes', object: 'pedestrian', latency_s: 0.9 }]));
console.log('tracks', tracks.length, 'dets', dets.length, 'ids', [...new Set(tracks.map((r) => r.track_id))].join(','));
