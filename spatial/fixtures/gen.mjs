// Generates SYNTHETIC_c99.* (UI work only; numbers are made up and must never be shown as real).
// node spatial/fixtures/gen.mjs
import { writeFileSync } from 'node:fs';
const W = 1920, H = 1080, D = new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const px = (b) => [b[0] * W, b[1] * H, b[2] * W, b[3] * H].map((v) => Math.round(v));
const lerp = (a, b, f) => a + (b - a) * f;
const tracks = [], dets = [];
const emit = (id, cls, t, nb, extra, conf) => {
  tracks.push({ track_id: id, t, cls, xyxy: px(nb), ...extra });
  if (conf != null) dets.push({ t, frame: Math.round(t * 30), cls, conf, xyxy: px(nb).map((v, i) => v + (i % 2 ? 1 : 2)) });
};
for (let i = 0; i <= 150; i++) {
  const t = +(i * 0.2).toFixed(1);
  // 1 pedestrian crossing into the path, t 12..24 (right to centre)
  if (t >= 12 && t <= 24) {
    const f = (t - 12) / 12, cx = lerp(0.8, 0.5, f), y2 = lerp(0.62, 0.8, f), h = lerp(0.12, 0.2, f);
    const nb = [cx - 0.02, y2 - h, cx + 0.02, y2];
    const inC = t >= 18.4, hi = t >= 14.2;
    const risk = +Math.min(0.78, 0.12 + 0.055 * (t - 12) * 1.2).toFixed(2);
    emit(1, 'person', t, nb, { vx: -41, vy: 3, h_rate: 0.2, in_corridor: inC, heading_in: hi, ttc: hi ? +(4.5 - (t - 14) * 0.2).toFixed(1) : null, t_lat: hi && !inC ? +(2.4 - (t - 14.2) * 0.4).toFixed(1) : null, risk }, 0.85);
  }
  // 2 parked car at the left edge, whole clip
  emit(2, 'car', t, [0.08, 0.5, 0.2, 0.68], { vx: 0, vy: 0, h_rate: 0, in_corridor: false, heading_in: false, ttc: null, t_lat: null, risk: 0.14 }, 0.78);
  // 3 far low-confidence vehicle, 2 s occlusion gap at 21..23
  if (!(t > 21 && t < 23)) emit(3, 'car', t, [0.48, 0.5, 0.52, 0.575], { vx: 0, vy: 0, h_rate: 0.05, in_corridor: false, heading_in: false, ttc: null, t_lat: null, risk: 0.22 }, t < 5 ? null : 0.42);
  // 4 bicycle touching the right frame edge, 26..29
  // 5 lorry (0..5.8), 6 motorbike (6..11.8), 7 bus (24..25.8): fill the third slot, max 3 tracks at once
  const still = { vx: 0, vy: 0, h_rate: 0, in_corridor: false, heading_in: false, ttc: null, t_lat: null };
  if (t < 6) emit(5, 'truck', t, [0.26, 0.42, 0.4, 0.66], { ...still, risk: 0.18 }, 0.81);
  else if (t < 12) emit(6, 'motorcycle', t, [lerp(0.7, 0.6, (t - 6) / 6), 0.55, lerp(0.74, 0.64, (t - 6) / 6), 0.7], { ...still, vx: -20, heading_in: t > 9, risk: t > 9 ? 0.45 : 0.25 }, 0.66);
  else if (t >= 24 && t < 26) emit(7, 'bus', t, [0.6, 0.38, 0.76, 0.64], { ...still, risk: 0.2 }, 0.88);
  if (t >= 26 && t <= 29) emit(4, 'bicycle', t, [0.94, 0.62, 1.0, 0.9], { vx: 12, vy: 0, h_rate: 0, in_corridor: false, heading_in: false, ttc: null, t_lat: null, risk: 0.3 }, 0.55);
}
// top-3 per frame is respected: at most 3 tracks coexist (1,2,3).
const jl = (a) => a.map((r) => JSON.stringify(r)).join('\n') + '\n';
const seg = (i) => ({ source: `s3://SYNTHETIC/c99_${i + 1}.mp4`, start_s: i * 5, end_s: i * 5 + 5 });
writeFileSync(D + 'SYNTHETIC_c99.tracks.jsonl', jl(tracks));
writeFileSync(D + 'SYNTHETIC_c99.det.jsonl', jl(dets));
writeFileSync(D + 'SYNTHETIC_c99.clips.json', JSON.stringify([{ clip_id: 'c99', camera_id: 'SYNTHETIC', camera: { kind: 'dashcam' }, segments: [0, 1, 2, 3, 4, 5].map(seg), duration_s: 30 }]));
writeFileSync(D + 'SYNTHETIC_c99.hazards.json', JSON.stringify([{ hazard_id: 'c99_h1', clip_id: 'c99', type: 'pedestrian_crossing', window_start: 16.2, window_end: 19.0, agreed: true, track_id: 1, description: 'SYNTHETIC pedestrian steps out from the right' }]));
writeFileSync(D + 'SYNTHETIC_c99.run.jsonl', jl([{ run_id: 'SYNTHETIC', clip_id: 'c99', clicks: [{ t: 17.9, t_trigger: 17.4, latency_s: 0.5, reason: 'risk 0.61' }], risk_curve: [] }]));
writeFileSync(D + 'SYNTHETIC_c99.grid.jsonl', jl([
  { t: 17.0, track_id: 1, where: 'at_lane_edge_or_kerb', motion: 'moving_into_our_path', our_car: 'moving', act: 'yes', object: 'pedestrian', latency_s: 0.9 },
  { t: 17.5, track_id: 1, where: 'in_our_lane', motion: 'moving_into_our_path', our_car: 'moving', act: 'yes', object: 'pedestrian', latency_s: 1.1 },
  { t: 9.0, track_id: 2, where: 'on_pavement', motion: 'stationary', our_car: 'moving', act: 'no', object: 'parked car', latency_s: 0.8 },
]));
console.log('tracks', tracks.length, 'dets', dets.length);
