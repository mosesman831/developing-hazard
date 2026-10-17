import test from 'node:test';
import assert from 'node:assert/strict';
import * as C from '../core.js';
import { parseJSONL, loadModel } from '../data.js';

const F = { w: 1920, h: 1080 };

test('xyxy format detection', () => {
  assert.equal(C.detectNormalised([{ xyxy: [0.1, 0.2, 0.5, 1.0] }]), true);
  assert.equal(C.detectNormalised([{ xyxy: [812, 402, 861, 540] }]), false);
  assert.equal(C.detectNormalised([{ xyxy: [0.1, 0.2, 0.5, 0.4] }, { xyxy: [10, 20, 30, 40] }]), false);
  assert.equal(C.detectNormalised([]), false);
  assert.deepEqual(C.normBox([960, 540, 1920, 1080], false, F), [0.5, 0.5, 1, 1]);
});

test('iou and confidence join', () => {
  assert.equal(C.iou([0, 0, 1, 1], [0, 0, 1, 1]), 1);
  assert.equal(C.iou([0, 0, 1, 1], [2, 2, 3, 3]), 0);
  const dets = [
    { t: 1.0, conf: 0.9, nb: [0.1, 0.1, 0.3, 0.5], _line: 1 },
    { t: 1.0, conf: 0.4, nb: [0.1, 0.1, 0.31, 0.5], _line: 2 },
    { t: 2.0, conf: 0.8, nb: [0.1, 0.1, 0.3, 0.5], _line: 3 },
  ];
  const ix = C.indexDets(dets);
  const j = C.joinConf({ t: 1.0, nb: [0.1, 0.1, 0.3, 0.5] }, ix);
  assert.equal(j.conf, 0.9); assert.equal(j.line, 1);
  assert.equal(C.joinConf({ t: 1.0, nb: [0.6, 0.6, 0.8, 0.9] }, ix), null, 'no overlap -> unknown, not invented');
  assert.equal(C.joinConf({ t: 5.0, nb: [0.1, 0.1, 0.3, 0.5] }, ix), null, 'no detection at that t -> unknown');
  assert.equal(C.joinConf({ t: 1.0, nb: [0.1, 0.1, 0.3, 0.5] }, C.indexDets([])), null);
});

test('streaks break on gaps', () => {
  const rows = [0, 0.2, 0.4, 2.0, 2.2].map((t) => ({ t }));
  assert.deepEqual(C.streaks(rows), [1, 2, 3, 1, 2]);
});

test('bearing and range-band mapping', () => {
  assert.equal(C.bearingDeg([0.4, 0.5, 0.6, 0.8]), 0);
  assert.ok(Math.abs(C.bearingDeg([0.0, 0.5, 0.0, 0.8]) + 78.5) < 1e-9);
  assert.ok(C.bearingDeg([0.9, 0.5, 0.95, 0.8]) > 0);
  assert.equal(C.rangeBand([0.4, 0.5, 0.5, 0.95]), 'near');
  assert.equal(C.rangeBand([0.4, 0.5, 0.5, 0.80]), 'mid');
  assert.equal(C.rangeBand([0.4, 0.5, 0.5, 0.65]), 'far');
  assert.equal(C.rangeBand([0.4, 0.5, 0.5, 1.0]), 'uncertain', 'bottom touches frame edge');
  assert.equal(C.rangeBand([0.4, 0.545, 0.5, 0.57]), 'uncertain', 'box shorter than min_box_h');
  assert.equal(C.rangeBand([0.4, 0.2, 0.5, 0.5]), 'uncertain', 'bottom above the assumed horizon');
});

test('corridor trapezoid', () => {
  assert.equal(C.inCorridor(0.5, 0.9), true);
  assert.equal(C.inCorridor(0.3, 0.55), false);
  assert.equal(C.inCorridor(0.3, 1.0), true);
  assert.equal(C.inCorridor(0.5, 0.4), false);
  assert.ok(C.corridorPolygon().length >= 6);
});

test('ring and fill are independent channels', () => {
  const ring = C.ringState({ conf: 0.3, streak: 8, band: 'mid', edge: false });
  assert.equal(ring.state, 'amber');
  const fill = C.fillState({ risk: 0.8, heading_in: true });
  assert.equal(fill.state, 'red');
  // same risk, different confidence -> same fill, different ring
  assert.equal(C.fillState({ risk: 0.8 }).state, C.fillState({ risk: 0.8 }).state);
  assert.equal(C.ringState({ conf: 0.9, streak: 8, band: 'near', edge: false }).state, 'green');
  assert.equal(C.ringState({ conf: null, streak: 8, band: 'near', edge: false }).state, 'amber', 'unknown conf is amber');
  assert.equal(C.ringState({ conf: 0.9, streak: 2, band: 'near', edge: false }).state, 'amber', 'short track');
  assert.equal(C.ringState({ conf: 0.9, streak: 9, band: 'near', edge: true }).state, 'amber', 'frame edge');
  assert.equal(C.fillState({ risk: 0.1 }).state, 'grey');
  assert.equal(C.fillState({ risk: 0.45 }).state, 'amber');
  assert.equal(C.fillState({ risk: 0.1, heading_in: true }).state, 'amber');
  assert.equal(C.fillState({ risk: 0.1, inHazard: true }).state, 'red');
  assert.equal(C.fillState({ risk: 0.1, cosmosYes: true }).state, 'red');
});

test('hatched space is never red', () => {
  assert.equal(C.fillState({ risk: 0.99, inHazard: true, visible: false }).state, 'hatch');
  for (let x1 = 0; x1 <= 1; x1 += 0.05) {
    const p = C.birdPlace([x1, 0.6, Math.min(1, x1 + 0.1), 0.9]);
    assert.equal(p.visible, true, 'camera-derived bearings are always inside the FOV wedge');
  }
  assert.equal(C.inFov(80), false);
});

test('cosmos is_hazard rule (SPEC A.1)', () => {
  const base = { act: 'yes', motion: 'moving_into_our_path', where: 'unclear', our_car: 'moving' };
  assert.equal(C.isHazardVerdict(base), true);
  assert.equal(C.isHazardVerdict({ ...base, our_car: 'stopped' }), false);
  assert.equal(C.isHazardVerdict({ ...base, act: 'unclear' }), false);
  assert.equal(C.isHazardVerdict({ ...base, motion: 'stationary', where: 'in_our_lane' }), true);
  assert.equal(C.isHazardVerdict({ ...base, motion: 'stationary' }), false);
});

test('grid parsing is defensive', () => {
  const g = C.parseGrid([
    { t: 1, where: 'in_our_lane', motion: 'stationary', our_car: 'moving', act: 'yes', object: 'car', latency_s: 0.9 },
    { grid_t: 2, answer: { where: 'unclear', motion: 'moving_into_our_path', our_car: 'moving', act: 'yes' }, track_id: 4 },
    { weird: true }, null, { t: 'x', act: 'yes' },
  ]);
  assert.equal(g.points.length, 2); assert.equal(g.skipped, 3);
  assert.equal(g.points[1].track_id, 4); assert.equal(g.points[1].is_hazard, true);
});

test('events: each provenance, with why lines from real fields', () => {
  const mk = (t, o) => ({ track_id: 4, cls: 'person', t, risk: 0.1, vx: -40, in_corridor: false, heading_in: false, ttc: null, t_lat: null, _line: 1, ...o });
  const tracks = new Map([[4, [mk(16.0), mk(16.2, { heading_in: true, t_lat: 1.6 }), mk(16.4, { heading_in: true, in_corridor: true, risk: 0.61, ttc: 3.8 }), mk(16.6, { heading_in: true, in_corridor: true, risk: 0.7 })]]]);
  const grid = C.parseGrid([{ t: 16.5, where: 'in_our_lane', motion: 'moving_into_our_path', our_car: 'moving', act: 'yes', object: 'pedestrian', latency_s: 0.9 }]).points;
  const ev = C.buildEvents({ tracks, grid,
    hazards: [{ window_start: 16.2, window_end: 19, type: 'pedestrian_crossing', description: 'ped steps out', track_id: 4, agreed: true }],
    clicks: [{ t: 16.9, t_trigger: 16.4, latency_s: 0.5, reason: 'risk 0.61' }],
    explain: [{ t: 17, text: 'Late because...' }] });
  const provs = new Set(ev.map((e) => e.prov));
  for (const p of ['MEASURED', 'MODEL', 'HUMAN', 'AGENT', 'GENERATED']) assert.ok(provs.has(p), p);
  assert.equal(ev.filter((e) => e.title.includes('entered the projected path')).length, 1);
  assert.equal(ev.filter((e) => e.prov === 'MODEL' && e.title.includes('risk 0.61')).length, 1, 'one crossing, not one per sample');
  const r = ev.find((e) => e.prov === 'MODEL' && e.title.includes('risk 0.61'));
  assert.match(r.why, /ttc=3.80 s/); assert.match(r.why, /heading_in=true/);
  assert.ok(ev.every((e, i) => i === 0 || ev[i - 1].t <= e.t));
  assert.ok(!JSON.stringify(ev).toLowerCase().includes('collision'));
  assert.equal(C.seekTime({ t: 16.4 }), 15.4); assert.equal(C.seekTime({ t: 0.3 }), 0);
});

test('events: empty input is fine', () => assert.deepEqual(C.buildEvents(), []));

test('observed motion is past only; dropouts hide a track', () => {
  const s = [10, 10.2, 10.4, 10.6].map((t, i) => ({ t, nb: [0.5 + i * 0.01, 0.5, 0.6 + i * 0.01, 0.8] }));
  assert.equal(C.observedMotion(s, 10.0), null, 'one sample -> no arrow');
  const m = C.observedMotion(s, 10.4);
  assert.equal(m.n, 3); assert.ok(m.to[0] > m.from[0]);
  assert.equal(C.observedMotion(s, 10.4).from[0] < C.observedMotion(s, 10.4).to[0], true);
  assert.equal(C.activeSample(s, 10.5).t, 10.4);
  assert.equal(C.activeSample(s, 12.0), null, 'gap -> not drawn');
  assert.equal(C.activeSample(s, 9.0), null);
});

test('malformed jsonl and missing inputs degrade, not throw', async () => {
  const p = parseJSONL('{"a":1}\nnot json\n\n[1,2]\n{"b":2}');
  assert.equal(p.rows.length, 2); assert.equal(p.bad, 2); assert.equal(p.rows[1]._line, 5);
  const empty = { getJSON: async () => null };
  const m = await loadModel({ clipId: 'c07', api: empty, mode: 'dev' });
  assert.equal(m.clip, null); assert.equal(m.trackRows.length, 0);
  for (const k of ['clip', 'tracks', 'det', 'grid', 'hazards']) assert.equal(m.status[k].state, 'missing', k);
  const junk = { getJSON: async () => ({ rows: [{ nope: 1 }] }) };
  const m2 = await loadModel({ clipId: 'c07', api: junk, mode: 'dev' });
  assert.equal(m2.status.tracks.state, 'malformed'); assert.equal(m2.status.det.state, 'malformed');
});

test('loadModel joins confidence and leaves unmatched unknown', async () => {
  const files = {
    '../data/clips.json': [{ clip_id: 'c1', segments: [{ start_s: 0, end_s: 5 }] }],
    '../data/tracks/c1.jsonl': { rows: [
      { track_id: 1, t: 1, cls: 'person', xyxy: [100, 500, 200, 700], risk: 0.5 },
      { track_id: 2, t: 1, cls: 'car', xyxy: [900, 500, 1000, 600], risk: 0.1 }] },
    '../data/det/c1.jsonl': { rows: [{ t: 1, frame: 30, cls: 'person', conf: 0.77, xyxy: [102, 500, 200, 702] }] },
  };
  const m = await loadModel({ clipId: 'c1', api: { getJSON: async (u) => files[u] ?? null }, mode: 'dev' });
  assert.equal(m.tracks.get(1)[0].conf, 0.77);
  assert.equal(m.tracks.get(2)[0].conf, null);
  assert.equal(m.status.det.state, 'ok');
});

test('3D view: placement and camera basis', async () => {
  const V = await import('../view3d.js');
  assert.deepEqual(V.world(0, 1).map((v) => +v.toFixed(6)), [0, 0, 3.5]);
  assert.ok(V.world(90, 1)[0] > 3.49, '+bearing is to the right (+x)');
  for (const k of Object.keys(V.VIEWS)) {
    const b = V.camBasis({ ...V.VIEWS[k], dist: 5, target: [0, 0, 1.5] });
    const d = (a, c) => a[0] * c[0] + a[1] * c[1] + a[2] * c[2];
    assert.ok(Math.abs(d(b.f, b.r)) < 1e-9 && Math.abs(d(b.f, b.u)) < 1e-9 && Math.abs(d(b.r, b.u)) < 1e-9, k + ' orthogonal');
    assert.ok(b.u[1] > 0, k + ' keeps up as up');
  }
  assert.ok(V.camBasis({ ...V.VIEWS.top, dist: 5, target: [0, 0, 0] }).eye[1] > 4.9, 'top view is above');
  assert.ok(V.camBasis({ ...V.VIEWS.persp, dist: 5, target: [0, 0, 0] }).eye[2] < 0, 'default view is behind the ego car');
});

test('3D class models: every class builds, aliases resolve, unknown -> generic', async () => {
  const M = await import('../models3d.js');
  for (const c of [...M.CLASSES, 'lorry', 'pedestrian', 'motorbike', 'van', 'giraffe', undefined]) {
    const m = M.modelFaces(c, [1, 0, 2], 30);
    assert.ok(m.faces.length >= 6, String(c));
    assert.ok(m.faces.every((f) => f.pts.every((p) => p.every(Number.isFinite))), String(c) + ' finite');
    assert.ok(m.bounds.h > 0 && m.bounds.foot.length === 4);
  }
  assert.equal(M.resolveClass('Lorry'), 'truck');
  assert.equal(M.resolveClass('pedestrian'), 'person');
  assert.equal(M.resolveClass('motorbike'), 'motorcycle');
  assert.equal(M.resolveClass('giraffe'), 'generic');
  assert.ok(M.modelFaces('person', [0, 0, 0], 0).bounds.h > M.modelFaces('car', [0, 0, 0], 0).bounds.h, 'person taller than car glyph');
  const len = (m) => Math.abs(m.bounds.foot[2][2] - m.bounds.foot[0][2]);
  assert.ok(len(M.modelFaces('bus', [0, 0, 0], 0)) > len(M.modelFaces('car', [0, 0, 0], 0)), 'bus longer than car');
  const car = M.modelFaces('car', [0, 0, 0], 0, M.METRIC.car);
  assert.ok(Math.abs(len(car) - 4.6) < 1e-9 && Math.abs(car.bounds.h - 1.5) < 1e-9, 'metric dims stretch the model to real size');
});

test('fixed camera: pinhole round trip, horizon, visible ground, motion', async () => {
  const K = await import('../camera.js');
  const pose = { x: -15, z: -8, height_m: 16, yaw_deg: 24, pitch_deg: 30, hfov_deg: 74 };
  assert.equal(K.validPose(pose), true);
  assert.equal(K.validPose({ ...pose, height_m: -1 }), false);
  assert.equal(K.validPose({ x: 0 }), false);
  const R = K.rig(pose, { w: 1920, h: 1080 });
  for (const g of [[0, 20], [5, 60], [-6, 10], [3, 100]]) {
    const uv = K.worldToImage(R, [g[0], 0, g[1]]);
    if (!uv || uv[0] < 0 || uv[0] > 1 || uv[1] < 0 || uv[1] > 1) continue;
    const back = K.imageToGround(R, uv[0], uv[1]);
    assert.ok(Math.hypot(back[0] - g[0], back[1] - g[1]) < 1e-6, 'image -> ground inverts ground -> image');
  }
  const c = K.imageToGround(R, 0.5, 0.5);
  assert.ok(c && Math.abs(Math.hypot(c[0] - pose.x, c[1] - pose.z) - 16 / Math.tan(30 * Math.PI / 180)) < 1e-6, 'optical axis hits the ground at h / tan(pitch)');
  assert.equal(K.imageToGround(K.rig({ ...pose, pitch_deg: 10 }), 0.5, 0.0), null, 'a ray above the horizon has no ground point');
  assert.equal(K.worldToImage(R, [pose.x, 0, pose.z - 50]), null, 'behind the camera');
  const vis = K.visibleGround(R);
  assert.ok(vis.length > 8 && vis.every((p) => p.every(Number.isFinite)));
  const rows = [0, 0.5, 1].map((t) => ({ t, g: [0, 10 + 8 * t] }));
  const m = K.groundMotion(rows, 1);
  assert.ok(Math.abs(m.speed - 8) < 1e-9 && Math.abs(m.heading) < 1e-9, 'heading 0 = +z');
  assert.equal(K.groundMotion(rows.slice(0, 1), 0), null);
});

test('loadModel: a fixed-camera calibration switches to ground positions', async () => {
  const pose = { x: 0, z: 0, height_m: 10, yaw_deg: 0, pitch_deg: 10, hfov_deg: 60 };
  const files = {
    'fixtures/SYNTHETIC_cx.clips.json': [{ clip_id: 'cx', camera_id: 'cam9', segments: [{ start_s: 0, end_s: 5 }] }],
    'fixtures/SYNTHETIC_cx.camera.json': { camera_id: 'cam9', kind: 'fixed', pose, scenery: {} },
    'fixtures/SYNTHETIC_cx.tracks.jsonl': { rows: [{ track_id: 1, t: 0, cls: 'car', xyxy: [900, 500, 1000, 600], risk: 0.1 }, { track_id: 2, t: 0, cls: 'car', xyxy: [900, 10, 1000, 60], risk: 0.1 }] },
  };
  const m = await loadModel({ clipId: 'cx', mode: 'fixtures', api: { getJSON: async (u) => files[u] ?? null } });
  assert.equal(m.camera.kind, 'fixed'); assert.equal(m.status.camera.state, 'ok');
  assert.ok(Array.isArray(m.tracks.get(1)[0].g), 'ground point below the horizon');
  assert.equal(m.tracks.get(2)[0].g, null, 'box above the horizon has no ground point');
  const bad = await loadModel({ clipId: 'cx', mode: 'fixtures', api: { getJSON: async (u) => (u.endsWith('camera.json') ? { kind: 'fixed', pose: {} } : files[u] ?? null) } });
  assert.equal(bad.camera.kind, 'dashcam'); assert.equal(bad.status.camera.state, 'malformed');
});

test('auto-calibration recovers a street camera from person boxes (synthetic c98)', async () => {
  const K = await import('../camera.js');
  const { readFileSync } = await import('node:fs');
  const rows = readFileSync(new URL('../fixtures/SYNTHETIC_c98.tracks.jsonl', import.meta.url), 'utf8').trim().split('\n').map((l) => JSON.parse(l))
    .map((r) => ({ ...r, nb: [r.xyxy[0] / 1920, r.xyxy[1] / 1080, r.xyxy[2] / 1920, r.xyxy[3] / 1080] }));
  const c = K.autoCalibrate(rows, { w: 1920, h: 1080 }, { hfov: 72 });
  assert.ok(c, 'calibrates');
  assert.ok(Math.abs(c.pose.pitch_deg - 33) < 3, `pitch ${c.pose.pitch_deg} vs 33`);
  assert.ok(Math.abs(c.pose.height_m - 18) / 18 < 0.25, `height ${c.pose.height_m} vs 18 (within 25%)`);
  assert.equal(K.autoCalibrate(rows.filter((r) => r.cls !== 'person'), { w: 1920, h: 1080 }), null, 'no people, no calibration');
  assert.equal(K.CAMERAS['neighborhood_cam-1'].kind, 'fixed'); assert.equal(K.CAMERAS['pie_cam-3'].kind, 'dashcam');
});

test('VSS detection sidecars parse in several shapes, with clip time', async () => {
  const K = await import('../camera.js');
  const p = K.parseVssDetections([
    { start_s: 5, sidecar: { fps: 10, frames: [{ frame: 10, detections: [{ class_name: 'car', confidence: 0.9, bbox: [1, 2, 3, 4] }] }] } },
    { start_s: 10, sidecar: [{ t: 0.5, objects: [{ label: 'person', score: 0.7, xywh: [10, 10, 4, 8] }, { label: 'x' }] }] },
    { start_s: 0, sidecar: { results: [{ time: 1, boxes: [{ cls: 'bus', conf: 0.5, box: { x1: 0, y1: 0, x2: 5, y2: 5 } }] }, { nope: 1 }] } },
    { start_s: 0, sidecar: null },
  ]);
  assert.equal(p.rows.length, 3); assert.equal(p.skipped, 2);
  assert.deepEqual(p.rows.map((r) => r.t), [6, 10.5, 1]);
  assert.deepEqual(p.rows[1].xyxy, [8, 6, 12, 14]);
});

test('loadModel auto-calibrates a known fixed camera that has no calibration file', async () => {
  const { readFileSync } = await import('node:fs');
  const rd = (f) => readFileSync(new URL('../fixtures/' + f, import.meta.url), 'utf8');
  const files = {
    'fixtures/SYNTHETIC_c98.clips.json': [{ clip_id: 'c98', camera_id: 'neighborhood_cam-1', segments: [{ start_s: 0, end_s: 30 }] }],
    'fixtures/SYNTHETIC_c98.tracks.jsonl': parseJSONL(rd('SYNTHETIC_c98.tracks.jsonl')),
  };
  const m = await loadModel({ clipId: 'c98', mode: 'fixtures', api: { getJSON: async (u) => files[u] ?? null } });
  assert.equal(m.camera.kind, 'fixed'); assert.ok(m.camera.auto && m.camera.auto.n >= 20);
  assert.equal(m.status.camera.state, 'partial'); assert.match(m.status.camera.detail, /auto-calibrated/);
  assert.ok(m.trackRows.some((r) => Array.isArray(r.g)));
});

test('app mode reads the routes exactly as the merged AG3 server returns them', async () => {
  // shapes from dh/api/clips.py and dh/api/runs.py on main (2026-10-17): clip + embedded hazards, tracks as a plain array, run detail with clips[]
  const routes = {
    'api/clips/c07': { clip_id: 'c07', camera_id: 'pie_cam-3', segments: [{ source: 's3://x/seg1.mp4', start_s: 0, end_s: 5 }], duration_s: 30,
      hazards: [{ hazard_id: 'c07_h1', clip_id: 'c07', type: 'pedestrian_crossing', window_start: 20.5, window_end: 24, track_id: null, agreed: false, description: 'A pedestrian crosses' }] },
    'api/clips/c07/tracks': [{ track_id: 4, t: 16.8, cls: 'person', xyxy: [812, 402, 861, 540], risk: 0.61, in_corridor: false, heading_in: true }],
    'api/runs/r1': { run_id: 'r1', agent: 'yolo_risk', clips: [{ run_id: 'r1', clip_id: 'c07', clicks: [{ t: 21.0, reason: 'risk 0.61' }], risk_curve: [[0, 0]] }] },
  };
  const m = await loadModel({ clipId: 'c07', runId: 'r1', mode: 'app', api: { getJSON: async (u) => routes[u] ?? null } });
  assert.equal(m.status.clip.state, 'ok'); assert.equal(m.status.hazards.state, 'ok'); assert.equal(m.hazards.length, 1);
  assert.equal(m.status.camera.state, 'ok'); assert.equal(m.camera.kind, 'dashcam');
  assert.equal(m.status.tracks.state, 'ok'); assert.equal(m.tracks.get(4)[0]._line, 1);
  assert.equal(m.status.run.state, 'ok'); assert.equal(m.clicks.length, 1);
  for (const k of ['det', 'grid']) assert.equal(m.status[k].state, 'missing', `${k} has no route on main yet`);
  assert.equal(m.status.explain.state, 'optional');
  const ev = (await import('../core.js')).buildEvents({ tracks: m.tracks, hazards: m.hazards, clicks: m.clicks });
  assert.deepEqual(ev.map((e) => e.prov).sort(), ['AGENT', 'HUMAN', 'MEASURED', 'MODEL']);
});
