// Loaders + validation. Every input except the clip is optional; failures become "Inputs" strip entries.
import { detectNormalised, normBox, indexDets, joinConf, streaks, parseGrid } from './core.js';
import { validPose, rig, groundPoint, visibleGround, laneYaw, CAMERAS, autoCalibrate, parseVssDetections, WALL_DEFAULT } from './camera.js';
import { conditionTracks } from './stabilize.js';

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
  if (mode === 'preset') { const f = `preset:${c}:`; return { camera: () => f + 'camera', clip: f + 'clip', tracks: f + 'tracks', det: f + 'det', hazards: f + 'hazards', run: f + 'run', grid: f + 'grid' }; }
  const d = '../data/';
  return { vss: `${d}vss/${c}.detections.json`, camera: (id) => `${d}cameras/${id}.json`, clip: d + 'clips.json', tracks: `${d}tracks/${c}.jsonl`, det: `${d}det/${c}.jsonl`, hazards: d + 'hazards.json', run: runId && `${d}runs/${runId}/clips.jsonl`, grid: `${d}grid/cosmos_verify_v2/${c}.jsonl`, explain: `${d}cache/explain/${c}.json` };
}

const need = (r, keys) => keys.every((k) => r[k] !== undefined && r[k] !== null);
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const okBox = (b) => Array.isArray(b) && b.length === 4 && b.every(num) && b[2] > b[0] && b[3] > b[1];
// The frame the detector's pixel boxes are in. This is not the size of the video being played, which may be
// a smaller transcode: a det file's frame_wh row first, then the clip, then the host's guess, then the
// smallest common frame that holds every box.
const FRAMES = [[640, 360], [1280, 720], [1920, 1080], [2560, 1440], [3840, 2160]];
export function boxFrame(rows, metaRows, clip, given) {
  for (const m of metaRows) if (m && m._meta === 'frame_wh' && Array.isArray(m.wh) && m.wh.every((v) => num(v) && v > 0)) return { w: m.wh[0], h: m.wh[1], src: 'det frame_wh' };
  const c = clip && (clip.frame_wh || (num(clip.width) && num(clip.height) ? [clip.width, clip.height] : null));
  if (Array.isArray(c) && c.every((v) => num(v) && v > 0)) return { w: c[0], h: c[1], src: 'clip' };
  let mx = 0, my = 0; for (const r of rows) { mx = Math.max(mx, r.xyxy[0], r.xyxy[2]); my = Math.max(my, r.xyxy[1], r.xyxy[3]); }
  if (mx <= given.w * 1.02 && my <= given.h * 1.02) return { w: given.w, h: given.h, src: 'host' };
  const f = FRAMES.find(([w, h]) => mx <= w * 1.02 && my <= h * 1.02) || [Math.ceil(mx), Math.ceil(my)];
  return { w: f[0], h: f[1], src: 'largest box' };
}

export async function loadModel({ clipId, api, frame = { w: 1920, h: 1080 }, mode = 'app', runId = null }) {
  const P = paths(mode, clipId, runId);
  const status = {};
  const set = (k, state, detail = '') => { status[k] = { state, detail }; };
  const get = async (k) => (P[k] ? api.getJSON(P[k]) : null);
  const miss = (k, hint) => set(k, 'missing', P[k] ? `${P[k]} not found. ${hint}` : `no source in "${mode}" mode. ${hint}`);

  // clip (+ hazards if the response carries them)
  let clip = null, hazards = [], hazardsGiven = false;
  const rc = await get('clip');
  if (rc) {
    const list = Array.isArray(rc) ? rc : rc.clip ? [rc.clip] : [rc];
    clip = list.find((c) => c && c.clip_id === clipId && Array.isArray(c.segments)) || null;
    if (!Array.isArray(rc) && Array.isArray(rc.hazards)) { hazards = rc.hazards; hazardsGiven = true; }   // [] = no labels yet, not missing
  }
  clip ? set('clip', 'ok', `${clip.segments.length} segments`) : set('clip', 'missing', `no clip "${clipId}" in ${P.clip}. Check ?clip= or run make clips.`);

  const hz = P.hazards ? await get('hazards') : null;
  const hzRows = asRows(hz);
  if (hzRows) hazards = hzRows.filter((h) => h.clip_id === clipId);
  const hv = hazards.filter((h) => need(h, ['window_start', 'window_end']) && num(h.window_start) && num(h.window_end));
  hazards.length || hzRows || hazardsGiven ? set('hazards', hv.length ? 'ok' : 'empty', hv.length ? `${hv.length} human-labelled windows` : 'no human labels for this clip yet (label it on #/label to score agents)') : miss('hazards', 'Human labels come from AG2 (data/hazards.json).');

  // camera: a fixed camera on a wall, house or pole looking at the road is the default. Only a camera known to
  // move with a car (PIE's pie_cam-3, or a calibration / clip saying kind "dashcam") uses the ego-car model.
  const cid = (clip && clip.camera_id) || null;
  const cal = clip && clip.camera && typeof clip.camera === 'object' ? clip.camera : P.camera && cid ? await api.getJSON(P.camera(cid)) : null;
  const dashcam = (cal && cal.kind === 'dashcam') || (!cal && !!cid && !!CAMERAS[cid] && CAMERAS[cid].kind === 'dashcam');
  let camera = { kind: dashcam ? 'dashcam' : 'fixed', camera_id: cid };
  const fixCam = (pose, extra) => { const R = rig(pose, frame); camera = { kind: 'fixed', camera_id: cid, pose, scenery: (cal && cal.scenery) || {}, rig: R, visible: visibleGround(R), follow: (cal && cal.follow) || null, ...extra }; };
  if (dashcam) set('camera', 'ok', cal ? 'camera moves with a car (dashcam)' : `camera moves with a car: ${CAMERAS[cid].what}`);
  else if (cal && validPose(cal.pose)) {
    // a file written by the backend says how it got the pose: measured, auto-calibrated or assumed
    const how = cal.assumed ? 'assumed' : cal.auto ? 'auto' : 'file';
    fixCam(cal.pose, how === 'assumed' ? { assumed: true } : how === 'auto' ? { auto: cal.auto } : {});
    const lens = `${cal.pose.height_m} m up, ${cal.pose.pitch_deg}° down, ${cal.pose.hfov_deg}° lens${cal.pose.k1 ? `, distortion k1 ${cal.pose.k1}` : ''}`;
    if (how === 'file') set('camera', 'ok', `fixed camera ${cid || ''}, ${lens}`);
    else set('camera', 'partial', how === 'auto' ? `fixed camera ${cid || ''}, auto-calibrated from ${cal.auto.n || '?'} object views: ${lens}. Approximate.` : `fixed camera ${cid || ''}: too few objects to calibrate, so a house camera is assumed (${lens}). Positions are rough; add a calibration file.`);
  }

  // tracks. The contract row is track_id, t, cls, xyxy, risk; the pod snapshot trims rows to t and xyxy,
  // so only those two are required. Missing ids are linked in the viewer, missing classes come from the
  // detections, missing risk stays unknown. The Inputs strip says which.
  const tr = asRows(await get('tracks'));
  let norm = false, tracks = [], trackNote = '';
  if (tr == null) miss('tracks', 'Run make track (AG1) or merge origin/main.');
  else {
    const boxes = tr.filter((r) => num(r.t) && okBox(r.xyxy));
    const anyId = boxes.some((r) => r.track_id != null);
    tracks = boxes.filter((r) => !anyId || Number.isInteger(r.track_id));
    for (const r of tracks) { if (!num(r.risk)) r.risk = null; if (typeof r.cls !== 'string' || !r.cls) r.cls = null; }
    const lacks = ['track_id', 'cls', 'risk'].filter((k) => tracks.length && tracks.every((r) => r[k] == null));
    if (lacks.length) trackNote = `rows carry no ${lacks.join(', ')}`;
    if (!tracks.length) set('tracks', tr.length ? 'malformed' : 'empty', tr.length ? `${tr.length} rows, none valid (need t and a 4-number xyxy)` : 'the tracks file is empty: AG1 found nothing to track in this clip');
    else set('tracks', tracks.length < tr.length || lacks.length ? 'partial' : 'ok', `${tracks.length}/${tr.length} rows${trackNote ? '; ' + trackNote : ''}`);
    norm = detectNormalised(tracks);
  }
  // detections (only source of per-box confidence)
  let dr = asRows(await get('det')), detSrc = 'det';
  if (dr == null && P.vss) {                                // VSS YOLO sidecars: [{ start_s, sidecar }] or { segments: [...] }
    const v = await api.getJSON(P.vss), segs = Array.isArray(v) ? v : v && Array.isArray(v.segments) ? v.segments : null;
    if (segs) { const p = parseVssDetections(segs); dr = p.rows.map((x, i) => ({ ...x, _line: i + 1 })); detSrc = `VSS sidecars (${segs.length} segments${p.skipped ? `, ${p.skipped} unreadable entries` : ''})`; }
  }
  let dets = [], dnorm = false;
  const metaRows = dr ? dr.filter((r) => r && r._meta) : [];
  if (dr == null) miss('det', 'Box confidence will show "?". In demo mode data/det/ is not in the snapshot.');
  else {
    const body = dr.filter((r) => !r._meta);
    dets = body.filter((r) => need(r, ['t', 'cls', 'conf', 'xyxy']) && num(r.t) && num(r.conf) && okBox(r.xyxy));
    set('det', dets.length ? (dets.length < body.length ? 'partial' : 'ok') : body.length ? 'malformed' : 'empty', `${dets.length}/${body.length} rows from ${detSrc}`);
    dnorm = detectNormalised(dets);
  }
  const boxF = boxFrame([...(norm ? [] : tracks), ...(dnorm ? [] : dets)], metaRows, clip, frame);
  for (const r of tracks) r.nb = normBox(r.xyxy, norm, boxF);
  for (const d of dets) d.nb = normBox(d.xyxy, dnorm, boxF);
  // a fixed camera without a usable calibration: auto-calibrate from people, else assume a typical house camera
  if (camera.kind === 'fixed' && !camera.rig) {
    const given = (cal && cal.pose) || {}, name = cid || 'this camera', file = `data/cameras/${cid || '<camera_id>'}.json`;
    const hfov = Number.isFinite(given.hfov_deg) ? given.hfov_deg : WALL_DEFAULT.hfov_deg, k1 = Number.isFinite(given.k1) ? given.k1 : 0;
    const bad = cal ? `${file} has no valid pose (x, z, height_m, yaw_deg, pitch_deg, hfov_deg); ` : '';
    const ac = autoCalibrate(tracks.some((r) => r.cls) ? tracks : dets, frame, { hfov, k1 });
    if (ac) {
      fixCam(ac.pose, { auto: ac });
      set('camera', cal ? 'malformed' : 'partial', `${bad}auto-calibrated ${name} from ${ac.n} person boxes: ${ac.pose.height_m} m up, ${ac.pose.pitch_deg}° down, lens width assumed ${hfov}°. Approximate; a calibration file is better.`);
    } else {
      fixCam({ ...WALL_DEFAULT, hfov_deg: hfov, k1 }, { assumed: true });
      set('camera', cal ? 'malformed' : 'partial', `${bad}${clip ? `no calibration for ${name} and too few clear people to auto-calibrate` : 'no clip, so no camera'}: assuming a house-mounted camera (${WALL_DEFAULT.height_m} m up, ${WALL_DEFAULT.pitch_deg}° down, ${hfov}° lens). Positions are rough; add ${file}.`);
    }
  }
  const follow = camera.follow === 'video';
  if (camera.rig && !follow) for (const r of tracks) r.g = groundPoint(camera.rig, r.nb, r.cls);
  // confidence for the tracker's own rows: the best-IoU detection at the same t (never invented)
  const di = indexDets(dets);
  for (const r of tracks) { const j = dets.length ? joinConf(r, di) : null; r.conf = j ? j.conf : null; r.conf_src = j ? j.line : null; }
  // condition the tracks for display: link, re-join split ids, follow unranked objects in the detections,
  // smooth placement, steady headings (stabilize.js). Applied the same way to every clip.
  const cond = conditionTracks(tracks, dets, camera, {
    groundPoint: camera.rig && !follow ? (nb, cls) => groundPoint(camera.rig, nb, cls) : null,
    initialYaw: camera.rig && !follow ? (pos) => laneYaw(camera.scenery, camera.rig, pos) : null,
  });
  const byId = cond.byId;
  for (const rows of byId.values()) { const st = streaks(rows); rows.forEach((r, i) => { r.streak = st[i]; }); }
  if (tracks.length && status.tracks) {
    const bits = [cond.linked ? `ids linked in the viewer (${byId.size} objects)` : null, cond.joined ? `${cond.joined} split ids re-joined` : null,
      cond.filled ? `${cond.filled} unranked samples followed in the detections` : null].filter(Boolean);
    if (bits.length) status.tracks.detail += '; ' + bits.join('; ');
  }
  // hazard labels and Cosmos rows name the tracker's ids; point them at the shown id
  const shown = (id) => (Number.isInteger(id) && cond.alias.has(id) ? cond.alias.get(id) : id);
  for (const h of hv) if (Number.isInteger(h.track_id)) { h.track_id_orig = h.track_id; h.track_id = shown(h.track_id); }

  // run result
  let clicks = [], riskCurve = [], runDetail = '', runExplanation = null;
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
      runExplanation = typeof mine.explanation === 'string' && mine.explanation ? mine.explanation : null;
      runDetail = `${clicks.length} clicks`;
      set('run', 'ok', runDetail);
    }
  }
  // Cosmos grid (not in contracts/: parse defensively)
  let grid = [];
  const gr = asRows(await get('grid'));
  if (gr == null) mode === 'preset' ? set('grid', 'optional', 'no Cosmos verdicts on a preview clip') : miss('grid', 'Cosmos verdicts come from make grid (AG1).');
  else {
    const g = parseGrid(gr); grid = g.points;
    for (const p of grid) if (Number.isInteger(p.track_id)) { p.track_id_orig = p.track_id; p.track_id = shown(p.track_id); }
    set('grid', grid.length ? 'ok' : gr.length ? 'malformed' : 'empty', `${grid.length} points${g.skipped ? `, ${g.skipped} unrecognised rows skipped` : ''}`);
  }
  // generated explanations (optional, cache only)
  let explain = [];
  const ex = P.explain ? await get('explain') : null;
  if (ex) {
    const list = Array.isArray(ex) ? ex : Array.isArray(ex.rows) ? ex.rows : [ex];
    explain = list.map((x) => ({ t: num(x.t) ? x.t : null, text: x.text || x.explanation || x.summary })).filter((x) => typeof x.text === 'string');
    set('explain', explain.length ? 'ok' : 'empty', `${explain.length} cached explanations`);
  } else set('explain', 'optional', 'optional: generated text appears only if data/cache/explain/ has it.');

  // events describe what the tracker reported, so they read only its ranked rows
  const ranked = new Map([...byId].map(([id, rows]) => [id, rows.filter((r) => !r.fill)]).filter(([, rows]) => rows.length));
  return { clip, camera, hazards: hv, tracks: byId, ranked, trackRows: tracks, dets, norm, dnorm, clicks, riskCurve, runExplanation, grid, explain, status, frame, boxFrame: boxF, paths: P, mode };
}
