// Loaders + validation. Every input except the clip is optional; failures become "Inputs" strip entries.
import { detectNormalised, normBox, indexDets, joinConf, streaks, parseGrid } from './core.js';
import { validPose, rig, groundPoint, visibleGround, CAMERAS, autoCalibrate, parseVssDetections } from './camera.js';

export function parseJSONL(text) {
  const rows = []; let bad = 0;
  text.split('\n').forEach((ln, i) => {
    if (!ln.trim()) return;
    try { const o = JSON.parse(ln); if (o && typeof o === 'object' && !Array.isArray(o)) { o._line = i + 1; rows.push(o); } else bad++; } catch { bad++; }
  });
  return { rows, bad };
}
// Dev fetcher: same contract as the app's helper (relative URL in, parsed JSON or null out). .jsonl -> {rows}.
export function devApi() {
  return {
    async getJSON(rel) {
      try {
        const r = await fetch(rel); if (!r.ok) return null;
        const txt = await r.text();
        return rel.endsWith('.jsonl') ? { __jsonl: true, ...parseJSONL(txt) } : JSON.parse(txt);
      } catch { return null; }
    },
  };
}
// Accept a plain array, {rows:[]}, or the dev jsonl wrapper; stamp _line when absent.
const asRows = (x) => {
  if (x == null) return null;
  const a = Array.isArray(x) ? x : Array.isArray(x.rows) ? x.rows : null;
  if (!a) return null;
  a.forEach((r, i) => { if (r && typeof r === 'object' && r._line == null) r._line = i + 1; });
  return a;
};

export function paths(mode, c, runId) {
  if (mode === 'app') return { vss: `api/clips/${c}/vss-detections`, camera: (id) => `api/cameras/${id}`, clip: `api/clips/${c}`, tracks: `api/clips/${c}/tracks`, det: `api/clips/${c}/det`, run: runId && `api/runs/${runId}`, grid: `api/clips/${c}/grid`, explain: `api/clips/${c}/explain` };
  if (mode === 'examples') { const e = '../contracts/examples/'; return { clip: e + 'clips.json', tracks: e + 'tracks_c07.jsonl', hazards: e + 'hazards.json', run: e + 'run_clips.jsonl' }; }
  if (mode === 'fixtures') { const f = `fixtures/SYNTHETIC_${c}.`; return { camera: () => f + 'camera.json', clip: f + 'clips.json', tracks: f + 'tracks.jsonl', det: f + 'det.jsonl', hazards: f + 'hazards.json', run: f + 'run.jsonl', grid: f + 'grid.jsonl' }; }
  const d = '../data/';
  return { vss: `${d}vss/${c}.detections.json`, camera: (id) => `${d}cameras/${id}.json`, clip: d + 'clips.json', tracks: `${d}tracks/${c}.jsonl`, det: `${d}det/${c}.jsonl`, hazards: d + 'hazards.json', run: runId && `${d}runs/${runId}/clips.jsonl`, grid: `${d}grid/cosmos_verify_v2/${c}.jsonl`, explain: `${d}cache/explain/${c}.json` };
}

const need = (r, keys) => keys.every((k) => r[k] !== undefined && r[k] !== null);
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const okBox = (b) => Array.isArray(b) && b.length === 4 && b.every(num);

export async function loadModel({ clipId, api, frame = { w: 1920, h: 1080 }, mode = 'app', runId = null }) {
  const P = paths(mode, clipId, runId);
  const status = {};
  const set = (k, state, detail = '') => { status[k] = { state, detail }; };
  const get = async (k) => (P[k] ? api.getJSON(P[k]) : null);
  const miss = (k, hint) => set(k, 'missing', P[k] ? `${P[k]} not found. ${hint}` : `no source in "${mode}" mode. ${hint}`);

  // clip (+ hazards if the response carries them)
  let clip = null, hazards = [];
  const rc = await get('clip');
  if (rc) {
    const list = Array.isArray(rc) ? rc : rc.clip ? [rc.clip] : [rc];
    clip = list.find((c) => c && c.clip_id === clipId && Array.isArray(c.segments)) || null;
    if (!Array.isArray(rc) && Array.isArray(rc.hazards)) hazards = rc.hazards;
  }
  clip ? set('clip', 'ok', `${clip.segments.length} segments`) : set('clip', 'missing', `no clip "${clipId}" in ${P.clip}. Check ?clip= or run make clips.`);

  const hz = P.hazards ? await get('hazards') : null;
  const hzRows = asRows(hz);
  if (hzRows) hazards = hzRows.filter((h) => h.clip_id === clipId);
  const hv = hazards.filter((h) => need(h, ['window_start', 'window_end']) && num(h.window_start) && num(h.window_end));
  hazards.length || hzRows ? set('hazards', hv.length ? 'ok' : 'empty', `${hv.length} human-labelled windows`) : miss('hazards', 'Human labels come from AG2 (data/hazards.json).');

  // camera: a stationary camera needs a calibration (pose + scenery); otherwise the PIE forward dashcam is assumed
  let camera = { kind: 'dashcam', camera_id: clip && clip.camera_id || null };
  const cid = camera.camera_id;
  const cal = clip && clip.camera && typeof clip.camera === 'object' ? clip.camera : P.camera && cid ? await api.getJSON(P.camera(cid)) : null;
  if (cal && cal.kind === 'fixed' && validPose(cal.pose)) {
    const R = rig(cal.pose, frame);
    camera = { kind: 'fixed', camera_id: cid, pose: cal.pose, scenery: cal.scenery || {}, rig: R, visible: visibleGround(R) };
    set('camera', 'ok', `fixed camera ${cid}, ${cal.pose.height_m} m up, ${cal.pose.hfov_deg}° lens`);
  } else if (cal && cal.kind === 'fixed') set('camera', 'malformed', `calibration for ${cid} has no valid pose (x, z, height_m, yaw_deg, pitch_deg, hfov_deg). Showing the dashcam approximation.`);
  else if (cal && cal.kind === 'dashcam') set('camera', 'ok', 'forward dashcam');
  else if (cid && /^pie_/.test(cid)) set('camera', 'ok', `forward dashcam (${cid})`);
  else if (cid && CAMERAS[cid] && CAMERAS[cid].kind === 'fixed') set('camera', 'missing', `${cid} is a fixed camera (${CAMERAS[cid].what}) with no calibration file; trying to auto-calibrate from people in the footage.`);
  else set('camera', 'missing', `no calibration for camera ${cid || '?'}; assuming a forward dashcam. For a stationary camera add data/cameras/<camera_id>.json with kind "fixed" and a pose.`);

  // tracks
  const tr = asRows(await get('tracks'));
  let norm = false, tracks = [];
  if (tr == null) miss('tracks', 'Run make track (AG1) or merge origin/main.');
  else {
    tracks = tr.filter((r) => need(r, ['track_id', 't', 'cls', 'xyxy', 'risk']) && num(r.t) && num(r.risk) && okBox(r.xyxy));
    if (!tracks.length) set('tracks', 'malformed', `${tr.length} rows, none valid (need track_id, t, cls, xyxy, risk)`);
    else set('tracks', tracks.length < tr.length ? 'partial' : 'ok', `${tracks.length}/${tr.length} rows`);
    norm = detectNormalised(tracks);
  }
  // detections (only source of per-box confidence)
  let dr = asRows(await get('det')), detSrc = 'det';
  if (dr == null && P.vss) {                                // VSS YOLO sidecars: [{ start_s, sidecar }] or { segments: [...] }
    const v = await api.getJSON(P.vss), segs = Array.isArray(v) ? v : v && Array.isArray(v.segments) ? v.segments : null;
    if (segs) { const p = parseVssDetections(segs); dr = p.rows.map((x, i) => ({ ...x, _line: i + 1 })); detSrc = `VSS sidecars (${segs.length} segments${p.skipped ? `, ${p.skipped} unreadable entries` : ''})`; }
  }
  let dets = [], dnorm = false;
  if (dr == null) miss('det', 'Box confidence will show "?". In demo mode data/det/ is not in the snapshot.');
  else {
    dets = dr.filter((r) => need(r, ['t', 'cls', 'conf', 'xyxy']) && num(r.t) && num(r.conf) && okBox(r.xyxy));
    set('det', dets.length ? (dets.length < dr.length ? 'partial' : 'ok') : 'malformed', `${dets.length}/${dr.length} rows from ${detSrc}`);
    dnorm = detectNormalised(dets);
  }
  for (const r of tracks) { r.nb = normBox(r.xyxy, norm, frame); if (camera.rig) r.g = groundPoint(camera.rig, r.nb); }
  for (const d of dets) d.nb = normBox(d.xyxy, dnorm, frame);
  const wantFixed = camera.kind !== 'fixed' && cid && ((CAMERAS[cid] && CAMERAS[cid].kind === 'fixed') || (cal && cal.kind === 'fixed'));
  if (wantFixed) {
    const hfov = cal && cal.pose && Number.isFinite(cal.pose.hfov_deg) ? cal.pose.hfov_deg : 90;
    const ac = autoCalibrate(tracks.length ? tracks : dets, frame, { hfov });
    if (ac) {
      const R = rig(ac.pose, frame);
      camera = { kind: 'fixed', auto: ac, camera_id: cid, pose: ac.pose, scenery: (cal && cal.scenery) || {}, rig: R, visible: visibleGround(R) };
      for (const r of tracks) r.g = groundPoint(R, r.nb);
      set('camera', 'partial', `auto-calibrated ${cid} from ${ac.n} person boxes: ${ac.pose.height_m} m up, pitched ${ac.pose.pitch_deg}°, lens width assumed ${hfov}°. Approximate; a calibration file is better.`);
    } else if (!cal) set('camera', 'missing', `${cid} is a fixed camera but there are too few clear people to auto-calibrate it. Showing the dashcam approximation; add data/cameras/${cid}.json.`);
  }
  const di = indexDets(dets);
  const byId = new Map();
  for (const r of tracks.sort((a, b) => a.t - b.t)) { if (!byId.has(r.track_id)) byId.set(r.track_id, []); byId.get(r.track_id).push(r); }
  for (const rows of byId.values()) {
    const st = streaks(rows);
    rows.forEach((r, i) => { r.streak = st[i]; const j = dets.length ? joinConf(r, di) : null; r.conf = j ? j.conf : null; r.conf_src = j ? j.line : null; });
  }

  // run result
  let clicks = [], riskCurve = [], runDetail = '';
  const rr = await get('run');
  const rrRows = asRows(rr) || (rr && Array.isArray(rr.clips) ? asRows(rr.clips) : null);
  if (runId == null && mode === 'app') set('run', 'missing', 'No run selected. Add &run=<run_id>.');
  else if (!rrRows) miss('run', 'Pick a run with &run=<run_id>, or run make eval.');
  else {
    const mine = rrRows.find((r) => r.clip_id === clipId);
    if (!mine) set('run', 'empty', `run has no row for ${clipId}`);
    else {
      clicks = (mine.clicks || []).filter((c) => num(c.t)).map((c, i) => ({ ...c, _line: mine._line ?? i + 1 }));
      riskCurve = Array.isArray(mine.risk_curve) ? mine.risk_curve : [];
      runDetail = `${clicks.length} clicks`;
      set('run', 'ok', runDetail);
    }
  }
  // Cosmos grid (not in contracts/: parse defensively)
  let grid = [];
  const gr = asRows(await get('grid'));
  if (gr == null) miss('grid', 'Cosmos verdicts come from make grid (AG1).');
  else { const g = parseGrid(gr); grid = g.points; set('grid', grid.length ? 'ok' : 'malformed', `${grid.length} points${g.skipped ? `, ${g.skipped} unrecognised rows skipped` : ''}`); }
  // generated explanations (optional, cache only)
  let explain = [];
  const ex = P.explain ? await get('explain') : null;
  if (ex) {
    const list = Array.isArray(ex) ? ex : Array.isArray(ex.rows) ? ex.rows : [ex];
    explain = list.map((x) => ({ t: num(x.t) ? x.t : null, text: x.text || x.explanation || x.summary })).filter((x) => typeof x.text === 'string');
    set('explain', explain.length ? 'ok' : 'empty', `${explain.length} cached explanations`);
  } else set('explain', 'optional', 'optional: generated text appears only if data/cache/explain/ has it.');

  return { clip, camera, hazards: hv, tracks: byId, trackRows: tracks, dets, norm, dnorm, clicks, riskCurve, grid, explain, status, frame, paths: P, mode };
}
