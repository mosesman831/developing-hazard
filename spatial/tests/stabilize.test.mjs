// Real-footage conditioning (stabilize.js): every failure seen on PIE dashcam data has a test here.
import test from 'node:test';
import assert from 'node:assert/strict';
import { linkRows, relink, fillFromDets, smoothSeries, rateLimit, placeTracks, sampleAt, sceneWorthy, conditionTracks, STAB } from '../stabilize.js';
import { loadModel, boxFrame } from '../data.js';
import { meter } from './replay.mjs';

// deterministic noise
let seed = 7;
const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
const box = (cx, bottom, w, h) => [cx - w / 2, bottom - h, cx + w / 2, bottom];
const byIdOf = (rows) => { const m = new Map(); for (const r of rows.sort((a, b) => a.t - b.t)) { if (!m.has(r.track_id)) m.set(r.track_id, []); m.get(r.track_id).push(r); } return m; };

test('rows without ids are linked into objects by overlap over time', () => {
  const rows = [];
  for (let i = 0; i < 10; i++) rows.push({ t: i * 0.2, nb: box(0.3 + i * 0.005, 0.8, 0.1, 0.2) }, { t: i * 0.2, nb: box(0.7 - i * 0.004, 0.75, 0.05, 0.15) });
  linkRows(rows);
  const ids = new Set(rows.map((r) => r.track_id));
  assert.equal(ids.size, 2, 'two objects, not twenty');
  assert.ok(rows.filter((r) => r.nb[0] < 0.5).every((r) => r.track_id === rows[0].track_id));
});

test('one object split across tracker ids is re-joined, and its labels follow', () => {
  const rows = [];
  for (let i = 0; i < 5; i++) rows.push({ track_id: 4, t: i * 0.2, cls: 'person', nb: box(0.5 + i * 0.004, 0.8, 0.05, 0.2) });
  for (let i = 7; i < 12; i++) rows.push({ track_id: 9, t: i * 0.2, cls: 'person', nb: box(0.5 + i * 0.004, 0.8, 0.05, 0.2) });
  for (let i = 7; i < 12; i++) rows.push({ track_id: 11, t: i * 0.2, cls: 'car', nb: box(0.15, 0.9, 0.2, 0.15) });   // elsewhere, another class
  const { byId, alias } = relink(byIdOf(rows));
  assert.equal(byId.size, 2);
  assert.equal(alias.get(9), 4);
  assert.equal(alias.get(11), 11);
  assert.equal(byId.get(4).length, 10);
  assert.ok(byId.get(4).some((r) => r.orig_id === 9), 'the tracker id stays on the row for provenance');
});

test('re-joining never merges two objects seen at the same time', () => {
  const rows = [];
  for (let i = 0; i < 6; i++) rows.push({ track_id: 1, t: i * 0.2, cls: 'person', nb: box(0.5, 0.8, 0.05, 0.2) }, { track_id: 2, t: i * 0.2, cls: 'person', nb: box(0.52, 0.8, 0.05, 0.2) });
  assert.equal(relink(byIdOf(rows)).byId.size, 2);
});

test('while the tracker does not rank an object, its detections keep it in the scene', () => {
  const rows = [], dets = [];
  for (let i = 0; i < 15; i++) {
    const nb = box(0.4 + i * 0.003, 0.8, 0.06, 0.2), t = +(i * 0.2).toFixed(1);
    dets.push({ t, cls: 'person', conf: 0.8, nb, _line: i + 1 });
    if (i < 4 || i > 9) rows.push({ track_id: 3, t, cls: 'person', nb, risk: 0.5 });          // not ranked for 1.2 s
  }
  const byId = fillFromDets(byIdOf(rows), dets);
  const all = byId.get(3);
  assert.equal(all.length, 15, 'every detector frame is used');
  const filled = all.filter((r) => r.fill === 'det');
  assert.equal(filled.length, 6);
  assert.ok(filled.every((r) => r.risk === null && r.risk_held === 0.5 && r.conf === 0.8), 'no risk invented; held risk is labelled');
});

test('a detection of a different size or shape does not continue a track', () => {
  const rows = [{ track_id: 1, t: 0, cls: 'car', nb: box(0.5, 0.7, 0.04, 0.03), risk: 0.2 }];
  const dets = [{ t: 0.2, cls: 'car', conf: 0.9, nb: box(0.5, 0.71, 0.2, 0.033), _line: 1 }];      // five times wider
  assert.equal(fillFromDets(byIdOf(rows), dets).get(1).length, 1);
});

test('smoothing removes jitter and single-frame outliers without lag', () => {
  const ts = [], vs = [];
  for (let i = 0; i < 50; i++) { ts.push(i * 0.2); vs.push(10 + i * 0.5 + rnd() * 0.6 + (i === 20 ? 8 : 0)); }
  const s = smoothSeries(ts, vs);
  assert.ok(Math.abs(s[20] - (10 + 20 * 0.5)) < 0.6, 'the outlier is gone');
  const err = s.slice(5, 45).reduce((a, v, k) => a + Math.abs(v - (10 + (k + 5) * 0.5)), 0) / 40;
  assert.ok(err < 0.2, `mean error ${err}`);
  const r = rateLimit([0, 0.2, 0.4, 0.6], [40, 40, 20, 20], 30);
  for (let i = 1; i < 4; i++) assert.ok(Math.abs(r[i] - r[i - 1]) <= 30 * 0.2 + 1e-9);
});

test('dashcam plan: close boxes cut by the bottom edge stay near, and placement is continuous', () => {
  const rows = [];
  for (let i = 0; i < 20; i++) rows.push({ track_id: 1, t: i * 0.2, cls: 'car', nb: box(0.3, Math.min(1, 0.9 + i * 0.01), 0.3, 0.25) });
  const byId = placeTracks(byIdOf(rows), { kind: 'dashcam' });
  const pr = byId.get(1).map((r) => r.pr);
  assert.ok(pr.every((v) => v < 0.4), 'never thrown to the far rim');
  for (let i = 1; i < pr.length; i++) assert.ok(Math.abs(pr[i] - pr[i - 1]) < 0.05);
});

test('headings: a noisy walker never spins, and a reversal must persist', () => {
  const rows = [];
  for (let i = 0; i < 40; i++) rows.push({ track_id: 1, t: i * 0.2, cls: 'person', g: [i * 0.25 + rnd() * 0.3, 10 + rnd() * 0.3] });   // walking +x, noisy
  const byId = new Map([[1, rows]]);
  placeTracks(byId, { kind: 'fixed', rig: {} }, { groundPoint: null });
  const yaw = rows.map((r) => r.yaw);
  for (let i = 1; i < yaw.length; i++) assert.ok(Math.abs(((yaw[i] - yaw[i - 1] + 540) % 360) - 180) <= STAB.turnRate.person * 0.2 + 1e-6);
  assert.ok(rows.slice(10).every((r) => Math.abs(r.yaw - 90) < 35), 'faces the way it walks');
});

test('sampling fades a track in and out instead of popping, and never extrapolates', () => {
  const rows = [0, 0.2, 0.4, 0.6, 0.8].map((t, i) => ({ t, nb: box(0.5, 0.8, 0.1, 0.2), pa: i, pr: 0.5, seg0: 0, runN: 5 }));
  assert.equal(sampleAt(rows, -0.01), null, 'nothing before the first sample');
  assert.ok(sampleAt(rows, 0).alpha < 0.5, 'starts faint');
  assert.equal(sampleAt(rows, 0.4).alpha, 1);
  assert.equal(sampleAt(rows, 0.5).row.pa, 2.5, 'between samples: interpolated');
  const after = sampleAt(rows, 1.0);
  assert.equal(after.row.pa, 4, 'after the last sample: held, not moved');
  assert.ok(after.alpha < 1 && after.alpha > 0);
  assert.equal(sampleAt(rows, 0.8 + STAB.fadeOut + 0.01), null);
});

test('a one-sample blink stays out of the scene unless it carries risk, a label or the selection', () => {
  assert.equal(sceneWorthy({ runN: 1, runRisk: 0.1 }), false);
  assert.equal(sceneWorthy({ runN: 1, runRisk: 0.7 }), true);
  assert.equal(sceneWorthy({ runN: 1, runRisk: 0.1 }, { selected: true }), true);
  assert.equal(sceneWorthy({ runN: 1, runRisk: 0.1, seg0: 2, runEnd: 2 }, { labelled: (a, b) => a <= 3 && b >= 1 }), true);
  assert.equal(sceneWorthy({ runN: 4, runRisk: 0 }), true);
});

test('pixel boxes are normalised by the detector frame, not the played video', () => {
  assert.deepEqual(boxFrame([], [{ _meta: 'frame_wh', wh: [1920, 1080] }], null, { w: 1280, h: 720 }), { w: 1920, h: 1080, src: 'det frame_wh' });
  assert.equal(boxFrame([{ xyxy: [100, 100, 1900, 1070] }], [], null, { w: 1280, h: 720 }).w, 1920, 'a 720p transcode does not shrink 1080p boxes');
  assert.equal(boxFrame([{ xyxy: [10, 10, 600, 400] }], [], null, { w: 1920, h: 1080 }).src, 'host');
});

test('trimmed snapshot rows (t and xyxy only) still give objects, classes from detections, unknown risk', async () => {
  const tracks = [], det = [{ _meta: 'frame_wh', wh: [1920, 1080] }];
  for (let i = 0; i < 20; i++) {
    const t = +(i * 0.2).toFixed(1), a = [800 + i * 4, 600, 900 + i * 4, 900], b = [200, 700, 500, 950];
    tracks.push({ t, xyxy: a }, { t, xyxy: b });
    det.push({ t, frame: i * 6, cls: 'person', conf: 0.9, xyxy: a }, { t, frame: i * 6, cls: 'car', conf: 0.95, xyxy: b });
  }
  const files = { clip: [{ clip_id: 'x', camera_id: 'pie_cam-3', segments: [{ source: 's', start_s: 0, end_s: 5 }] }], tracks: { rows: tracks }, det: { rows: det } };
  const api = { async getJSON(u) { return u.endsWith('clips.json') ? files.clip : u.includes('/tracks/') ? files.tracks : u.includes('/det/') ? files.det : null; } };
  const m = await loadModel({ clipId: 'x', api, mode: 'dev' });
  assert.equal(m.status.tracks.state, 'partial');
  assert.match(m.status.tracks.detail, /no track_id, cls, risk/);
  assert.equal(m.tracks.size, 2);
  assert.deepEqual([...m.tracks.values()].map((r) => r[0].cls).sort(), ['car', 'person']);
  assert.ok([...m.tracks.values()].every((rs) => rs.every((r) => r.risk === null)));
});

test('a jittery, fragmented, top-3 dashcam track plays with no pops, teleports or spins', async () => {
  // a car approaching on the right, a pedestrian crossing; noisy boxes, the tracker drops and renumbers them
  const tracks = [], det = [];
  let id = 1;
  for (let i = 0; i < 150; i++) {
    const t = +(i * 0.2).toFixed(1);
    const car = box(0.7 + i * 0.001 + rnd() * 0.01, 0.62 + i * 0.002 + rnd() * 0.01, 0.06 + i * 0.0008, 0.05 + i * 0.0007 + rnd() * 0.006);
    const ped = box(0.2 + i * 0.004 + rnd() * 0.01, 0.75 + rnd() * 0.01, 0.03, 0.12 + rnd() * 0.01);
    det.push({ t, cls: 'car', conf: 0.9, xyxy: car, _line: det.length + 1 }, { t, cls: 'person', conf: 0.8, xyxy: ped, _line: det.length + 2 });
    if (i % 25 === 0) id += 2;                                         // the tracker renumbers every 5 s
    if (i % 7 !== 3) tracks.push({ track_id: id, t, cls: 'car', xyxy: car, risk: 0.3 });   // drops out of the top 3 now and then
    if (i % 5 !== 1) tracks.push({ track_id: id + 1, t, cls: 'person', xyxy: ped, risk: 0.5 });
  }
  const api = { async getJSON(u) { return u.endsWith('clips.json') ? [{ clip_id: 'n', camera_id: 'pie_cam-3', duration_s: 30, segments: [{ source: 's', start_s: 0, end_s: 30 }] }] : u.includes('/tracks/') ? { rows: tracks } : u.includes('/det/') ? { rows: det } : null; } };
  for (const follow of [false, true]) {
    const a2 = follow ? { async getJSON(u) { const v = await api.getJSON(u); if (u.endsWith('clips.json')) v[0].camera = { kind: 'fixed', follow: 'video', pose: { x: 0, z: 0, height_m: 1.35, yaw_deg: 0, pitch_deg: 5, hfov_deg: 100 } }; return v; } } : api;
    const m = await loadModel({ clipId: 'n', api: a2, mode: 'dev' });
    const g = meter(m);
    assert.equal(m.tracks.size, 2, 'renumbered fragments are one car and one person');
    assert.deepEqual([g.hardPops, g.teleports, g.flips, g.rimJumps], [0, 0, 0, 0], JSON.stringify(g));
  }
});

test('conditioning is a no-op on clean data', () => {
  const rows = [];
  for (let i = 0; i < 10; i++) rows.push({ track_id: 1, t: i * 0.2, cls: 'car', nb: box(0.5, 0.8, 0.1, 0.1), risk: 0.2 });
  const c = conditionTracks(rows, [], { kind: 'dashcam' });
  assert.equal(c.byId.size, 1); assert.equal(c.joined, 0); assert.equal(c.filled, 0); assert.equal(c.linked, false);
});
