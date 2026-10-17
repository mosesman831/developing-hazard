// Glitch meter for real footage. Loads each clip through loadModel (the same path the panel uses), steps
// the clock at 30 fps and counts what a viewer would see as glitches in the 3D view:
//   hard pops   an object appearing or vanishing at more than half opacity (fades are fine)
//   teleports   a model moving further in one video frame than the scene allows
//   flips       a model turning more than 45 degrees in one video frame
//   rim jumps   a large, close box drawn at the far edge of the dashcam plan
// Usage:
//   node spatial/tests/replay.mjs <dataDir> [clip ...]          dataDir holds clips.json, tracks/, det/
//   node spatial/tests/replay.mjs <dataDir> --follow            the same clips in the metric dashcam street view
//   node spatial/tests/replay.mjs --presets                     the recorded hazard presets (dashcam, metric)
// Exit code 1 when any clip exceeds the limits in LIMITS, so it can gate a merge.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadModel, parseJSONL } from '../data.js';
import { sampleAt, sceneWorthy } from '../stabilize.js';
import { world } from '../view3d.js';

export const LIMITS = { hardPops: 0, teleports: 0, flips: 0, rimJumps: 0 };
const FPS = 30;
const here = path.dirname(fileURLToPath(import.meta.url));

// follow: open every dashcam clip in the metric street view the dev page's presets use
const FOLLOW_POSE = { x: 0, z: 0, height_m: 1.35, yaw_deg: 0, pitch_deg: 5, hfov_deg: 100, k1: -0.12 };
function fileApi(root, follow = false) {
  return {
    async getJSON(rel) {
      const p = path.join(root, rel.replace(/^\.\.\/data\//, ''));
      if (!fs.existsSync(p)) return null;
      const txt = fs.readFileSync(p, 'utf8');
      const v = p.endsWith('.jsonl') ? { __jsonl: true, ...parseJSONL(txt) } : JSON.parse(txt);
      if (follow && path.basename(p) === 'clips.json') for (const c of v) c.camera = { kind: 'fixed', follow: 'video', pose: FOLLOW_POSE };
      return v;
    },
  };
}

export function meter(model) {
  const fixed = model.camera.kind === 'fixed', dur = model.clip ? (model.clip.duration_s || model.clip.segments.at(-1).end_s) : 30;
  const m = { objects: model.tracks.size, hardPops: 0, softPops: 0, teleports: 0, flips: 0, rimJumps: 0, maxStep: 0, meanStep: 0, maxTurn: 0 };
  const prev = new Map(); let steps = 0, sum = 0;
  for (let k = 0; k <= Math.round(dur * FPS); k++) {
    const t = k / FPS, seen = new Set();
    for (const [id, rows] of model.tracks) {
      const s = sampleAt(rows, t);
      if (!s || !sceneWorthy(s.row, { labelled: (t0, t1) => model.hazards.some((z) => z.track_id === id && z.window_start <= t1 && z.window_end >= t0) })) continue;
      seen.add(id);
      const r = s.row;
      let pos, yaw;
      if (fixed) { const g = r.gs || r.g; if (!g) continue; pos = g; yaw = r.yaw ?? 0; }
      else { const w = world(r.pa, r.pr); pos = [w[0] / 3.5 * 10, w[2] / 3.5 * 10]; yaw = r.pa;   // plan radius x10
        if (r.pr > 0.9 && r.nb[3] - r.nb[1] > 0.15 && r.nb[3] > 0.6) m.rimJumps++; }
      const p = prev.get(id);
      if (!p) { if (s.alpha >= 0.5) m.hardPops++; else m.softPops++; }
      else {
        const step = Math.hypot(pos[0] - p.pos[0], pos[1] - p.pos[1]), turn = Math.abs(((((yaw - p.yaw) % 360) + 540) % 360) - 180);
        steps++; sum += step; m.maxStep = Math.max(m.maxStep, step); m.maxTurn = Math.max(m.maxTurn, turn);
        if (step > (fixed ? 1.5 : 1.0)) m.teleports++;        // fixed: 1.5 m in 1/30 s is 160 km/h; plan: a tenth of the radius
        if (turn > 45) m.flips++;
      }
      prev.set(id, { pos, yaw, alpha: s.alpha });
    }
    for (const [id, p] of prev) if (!seen.has(id)) { if (p.alpha >= 0.5) m.hardPops++; else m.softPops++; prev.delete(id); }
  }
  m.meanStep = +(sum / Math.max(1, steps)).toFixed(3); m.maxStep = +m.maxStep.toFixed(2); m.maxTurn = +m.maxTurn.toFixed(1);
  return m;
}
const over = (m) => Object.entries(LIMITS).filter(([k, v]) => m[k] > v).map(([k]) => k);

async function presets() {
  const { PRESETS } = await import('../presets.js');
  const out = [];
  for (const p of PRESETS) {
    const d = JSON.parse(fs.readFileSync(path.join(here, '..', 'presets-data', p.id + '.json'), 'utf8'));
    const api = { async getJSON(rel) {
      if (rel.endsWith('clip')) return [{ clip_id: p.id, camera_id: 'pie_cam-3', duration_s: d.duration_s || 30, camera: { kind: 'fixed', follow: 'video', pose: d.pose }, segments: [0, 1, 2, 3, 4, 5].map((i) => ({ source: p.video, start_s: i * 5, end_s: i * 5 + 5 })) }];
      if (rel.endsWith('tracks')) return { rows: d.tracks.map((r) => ({ ...r })) };
      if (rel.endsWith('det')) return { rows: (d.dets || []).map((r) => ({ ...r })) };
      return null;
    } };
    const model = await loadModel({ clipId: p.id, api, mode: 'preset' });
    out.push({ clip: 'preset:' + p.id, mode: 'dashcam metric', ...meter(model) });
  }
  return out;
}
async function dataDir(root, only, follow) {
  const clips = JSON.parse(fs.readFileSync(path.join(root, 'clips.json'), 'utf8'));
  const out = [];
  for (const c of clips) {
    if (only.length && !only.includes(c.clip_id)) continue;
    const model = await loadModel({ clipId: c.clip_id, api: fileApi(root, follow), mode: 'dev' });
    out.push({ clip: c.clip_id, mode: follow ? 'dashcam metric' : model.camera.kind, tracks: model.status.tracks ? model.status.tracks.state : '-', ...meter(model) });
  }
  return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const follow = process.argv.includes('--follow'), args = process.argv.slice(2).filter((a) => a !== '--follow');
  const rows = args[0] === '--presets' ? await presets() : await dataDir(args[0], args.slice(1), follow);
  console.table(rows);
  const bad = rows.filter((r) => over(r).length);
  for (const r of bad) console.log(`OVER LIMIT ${r.clip}: ${over(r).join(', ')}`);
  console.log(bad.length ? `${bad.length}/${rows.length} clips over the glitch limits` : `all ${rows.length} clips within the glitch limits`);
  process.exitCode = bad.length ? 1 : 0;
}
