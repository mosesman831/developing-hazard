// Pure functions only. No DOM, no fetch. Everything here is an approximation from one camera.
export const ASSUMED_HFOV_DEG = 157; // PIE lens [SPEC S28]; approximate
export const HORIZON_Y = 0.55;       // assumed horizon, = corridor top (SPEC 19)
export const CORRIDOR = { bottom: [0.25, 0.75], top: [0.42, 0.58], topY: 0.55 }; // SPEC 7.6 / 19
export const THRESHOLDS = {
  confOk: 0.6,        // ring green at/above this (ours)
  minStreak: 5,       // consecutive samples for a "stable" track (ours)
  streakGap: 0.35,    // s; larger gap breaks a streak (5 fps = 0.2 s)
  riskAmber: 0.4,     // SPEC 19 theta_down
  riskRed: 0.6,       // SPEC 19 theta_up
  minBoxH: 0.035,     // SPEC 19 min_box_h
  edgeEps: 0.01,      // box within 1% of the frame edge
  iouMin: 0.5,        // detection join
  showGap: 0.3,       // s; hide a track with no sample this recent (occlusion)
  motionWin: 1.0,     // s of observed past motion
  cosmosHold: 0.5,    // s a grid verdict tints its track (SPEC 19 grid_step_s)
};
const T = THRESHOLDS;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

// ---- boxes ------------------------------------------------------------
export function detectNormalised(rows) {
  let n = 0;
  for (const r of rows) for (const v of r.xyxy || []) { if (v > 1.0) return false; n++; }
  return n > 0;
}
export function normBox(xyxy, norm, frame) {
  const [w, h] = norm ? [1, 1] : [frame.w, frame.h];
  return [xyxy[0] / w, xyxy[1] / h, xyxy[2] / w, xyxy[3] / h];
}
export function iou(a, b) {
  const iw = Math.min(a[2], b[2]) - Math.max(a[0], b[0]);
  const ih = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
  if (iw <= 0 || ih <= 0) return 0;
  const i = iw * ih, u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i;
  return u > 0 ? i / u : 0;
}
const tkey = (t) => Math.round(t * 100);
// Confidence = best-IoU detection (>= iouMin) at the same t.
// null = unknown, never invented.
export function indexDets(dets) {
  const by = new Map();
  for (const d of dets) { const k = tkey(d.t); if (!by.has(k)) by.set(k, []); by.get(k).push(d); }
  return by;
}
export function joinConf(track, detIndex) {
  const k0 = tkey(track.t);
  let best = null, bi = 0;
  for (const k of [k0, k0 - 1, k0 + 1]) for (const d of detIndex.get(k) || []) {
    const v = iou(track.nb, d.nb);
    if (v >= T.iouMin && v > bi) { bi = v; best = d; }
  }
  return best ? { conf: best.conf, iou: bi, line: best._line } : null;
}
// consecutive-sample count ending at each row; input rows of ONE track sorted by t
export function streaks(rows) {
  const out = []; let n = 0;
  rows.forEach((r, i) => { n = i > 0 && r.t - rows[i - 1].t <= T.streakGap ? n + 1 : 1; out.push(n); });
  return out;
}

// ---- geometry ---------------------------------------------------------
// Equidistant-fisheye assumption: bearing is linear in x across the assumed field of view.
export function bearingDeg(nb) { return clamp(((nb[0] + nb[2]) / 2 - 0.5) * ASSUMED_HFOV_DEG, -ASSUMED_HFOV_DEG / 2, ASSUMED_HFOV_DEG / 2); }
export function rangeFrac(y2) { return clamp((y2 - HORIZON_Y) / (1 - HORIZON_Y), 0, 1); }
export function edgeTouch(nb) { const e = T.edgeEps; return nb[0] <= e || nb[1] <= e || nb[2] >= 1 - e || nb[3] >= 1 - e; }
export function rangeBand(nb) {
  if (nb[3] >= 1 - T.edgeEps || nb[3] - nb[1] < T.minBoxH || nb[3] <= HORIZON_Y) return 'uncertain';
  const f = rangeFrac(nb[3]);
  return f >= 0.66 ? 'near' : f >= 0.33 ? 'mid' : 'far';
}
export function inCorridor(x, y, c = CORRIDOR) {
  if (y < c.topY || y > 1) return false;
  const f = (y - c.topY) / (1 - c.topY);
  return x >= c.top[0] + (c.bottom[0] - c.top[0]) * f && x <= c.top[1] + (c.bottom[1] - c.top[1]) * f;
}
export function inFov(deg) { return Math.abs(deg) <= ASSUMED_HFOV_DEG / 2 + 1e-9; }
// Bird's-eye polar placement. r is a fraction of the view radius: ordinal band centres, never metres.
const BAND_R = { near: 0.37, mid: 0.6, far: 0.83, uncertain: 0.98 };
export const rOfFrac = (f) => 0.95 - 0.7 * f; // continuous; used only for the corridor outline
export function birdPlace(nb) {
  const ang = bearingDeg(nb), band = rangeBand(nb);
  return { ang, band, r: BAND_R[band], visible: inFov(ang) };
}
export function polar(cx, cy, R, ang, r) { const a = ang * Math.PI / 180; return [cx + R * r * Math.sin(a), cy - R * r * Math.cos(a)]; }
// Corridor outline as [{ang, r}] points.
export function corridorPolygon(c = CORRIDOR, steps = 6) {
  const L = [], Rr = [];
  for (let i = 0; i <= steps; i++) {
    const f = i / steps, y = c.topY + (1 - c.topY) * f;
    const xl = c.top[0] + (c.bottom[0] - c.top[0]) * f, xr = c.top[1] + (c.bottom[1] - c.top[1]) * f;
    const r = rOfFrac(rangeFrac(y));
    L.push({ ang: (xl - 0.5) * ASSUMED_HFOV_DEG, r }); Rr.push({ ang: (xr - 0.5) * ASSUMED_HFOV_DEG, r });
  }
  return L.concat(Rr.reverse());
}

// ---- the two independent channels -------------------------------------
// Ring = perception confidence (from detections). Never uses risk.
export function ringState({ conf, streak, band, edge }) {
  const why = [];
  if (conf == null) why.push('confidence unknown (no matching detection)');
  else if (conf < T.confOk) why.push(`conf ${conf.toFixed(2)} < ${T.confOk}`);
  if (streak < T.minStreak) why.push(`seen ${streak} sample${streak === 1 ? '' : 's'} < ${T.minStreak}`);
  if (band === 'uncertain') why.push('range uncertain');
  if (edge) why.push('at frame edge');
  return { state: why.length ? 'amber' : 'green', why };
}
export function isHazardVerdict(a) {
  return a.act === 'yes' && (a.motion === 'moving_into_our_path' || a.where === 'in_our_lane') && a.our_car !== 'stopped'; // SPEC A.1
}
// Fill = hazard assessment (pipeline risk, human label, Cosmos). Never uses confidence.
export function fillState({ risk, heading_in, inHazard, cosmosYes, visible = true }) {
  if (!visible) return { state: 'hatch', why: ['not visible to camera'] };
  const why = [];
  if (inHazard) why.push('inside a human-labelled hazard window');
  if (cosmosYes) why.push('Cosmos verdict: act=yes and SPEC A.1 rule');
  if (risk != null && risk >= T.riskRed) why.push(`risk ${risk.toFixed(2)} >= ${T.riskRed}`);
  if (why.length) return { state: 'red', why };
  if (risk != null && risk >= T.riskAmber) why.push(`risk ${risk.toFixed(2)} >= ${T.riskAmber}`);
  if (heading_in) why.push('heading_in');
  return why.length ? { state: 'amber', why } : { state: 'grey', why: [] };
}

// ---- motion (observed past only; never extrapolated) ------------------
export function observedMotion(samples, t) {
  const s = samples.filter((r) => r.t <= t + 1e-6 && r.t >= t - T.motionWin);
  if (s.length < 2) return null;
  const p = (r) => [(r.nb[0] + r.nb[2]) / 2, r.nb[3]];
  return { from: p(s[0]), to: p(s[s.length - 1]), n: s.length };
}
// latest sample at/before t, or null when the track has dropped out (occlusion stays visible as a gap)
export function activeSample(samples, t) {
  let lo = 0, hi = samples.length - 1, i = -1;          // binary search: last sample with t' <= t
  while (lo <= hi) { const m = (lo + hi) >> 1; if (samples[m].t <= t + 1e-6) { i = m; lo = m + 1; } else hi = m - 1; }
  const best = i >= 0 ? samples[i] : null;
  return best && t - best.t <= T.showGap ? best : null;
}

// ---- Cosmos grid + events ---------------------------------------------
const pick = (r) => {
  for (const k of ['answer', 'parsed', 'out', 'verdict']) if (r && r[k] && typeof r[k] === 'object') return r[k];
  return r;
};
export function parseGrid(rows) {
  const points = []; let skipped = 0;
  for (const r of rows) {
    const a = pick(r);
    const t = r && [r.t, r.grid_t, r.t_sent].find((v) => typeof v === 'number');
    if (t === undefined || !a || !('act' in a || 'motion' in a || 'where' in a)) { skipped++; continue; }
    const p = { t, track_id: Number.isInteger(r.track_id) ? r.track_id : null, where: a.where ?? '?', motion: a.motion ?? '?', our_car: a.our_car ?? '?', act: a.act ?? '?', object: a.object ?? '', latency_s: typeof r.latency_s === 'number' ? r.latency_s : null, _line: r._line };
    p.is_hazard = isHazardVerdict(p);
    points.push(p);
  }
  return { points: points.sort((x, y) => x.t - y.t), skipped };
}
const f2 = (v) => (typeof v === 'number' ? v.toFixed(2) : '-');
const fs = (v) => (v == null ? '-' : f2(v) + ' s');
const nm = (r) => `${r.cls}#${r.track_id}`;
// tracks: Map track_id -> rows sorted by t. Each event carries provenance + the fields that fired.
// egoPath false (a fixed camera): skip in_corridor / heading_in events, which describe a dashcam's own path
export function buildEvents({ tracks = new Map(), hazards = [], clicks = [], grid = [], explain = [], extra = [], egoPath = true } = {}) {
  const ev = [...extra];                                   // e.g. proximity measurements from a fixed camera
  for (const [id, rows] of tracks) {
    rows.forEach((r, i) => {
      const prev = i > 0 && r.t - rows[i - 1].t <= T.streakGap ? rows[i - 1] : null;
      const src = { file: 'tracks', line: r._line };
      if (egoPath && r.in_corridor && !(prev && prev.in_corridor))
        ev.push({ t: r.t, prov: 'MEASURED', track_id: id, src, title: `${nm(r)} entered the projected path at ${f2(r.t)} s`,
          why: 'in_corridor=true (box bottom-centre inside the assumed-straight path, SPEC 7.6)' });
      if (egoPath && r.heading_in && !(prev && prev.heading_in))
        ev.push({ t: r.t, prov: 'MEASURED', track_id: id, src, title: `${nm(r)} heading toward the path at ${f2(r.t)} s`,
          why: `heading_in=true; vx=${f2(r.vx)}; t_lat=${fs(r.t_lat)}` });
      if (r.risk >= T.riskRed && !(prev && prev.risk >= T.riskRed))
        ev.push({ t: r.t, prov: 'MODEL', track_id: id, src, title: `${nm(r)} risk ${f2(r.risk)} (heuristic, SPEC 7.6)`,
          why: `risk=${f2(r.risk)} >= ${T.riskRed}; in_corridor=${!!r.in_corridor}; heading_in=${!!r.heading_in}; ttc=${fs(r.ttc)}; t_lat=${fs(r.t_lat)}; may need to slow or steer` });
    });
  }
  for (const h of hazards)
    ev.push({ t: h.window_start, prov: 'HUMAN', track_id: Number.isInteger(h.track_id) ? h.track_id : null, src: { file: 'hazards', line: h._line },
      title: `Human label ${f2(h.window_start)}-${f2(h.window_end)} s: ${(h.description || h.type || '').replace(/^EXAMPLE:\s*/, '')}`,
      why: `human label (${h.type || 'untyped'})${h.agreed ? ', both labellers agreed' : ''}` });
  for (const c of clicks)
    ev.push({ t: c.t, prov: 'AGENT', track_id: null, src: { file: 'run', line: c._line },
      title: `Agent click at ${f2(c.t)} s${c.reason ? ': ' + c.reason : ''}`,
      why: `t_trigger=${fs(c.t_trigger)}; latency=${fs(c.latency_s)}` });
  for (const g of grid)
    ev.push({ t: g.t, prov: 'MODEL', track_id: g.track_id, src: { file: 'grid', line: g._line }, hazard: g.is_hazard,
      title: `Cosmos${g.latency_s != null ? ` (${f2(g.latency_s)} s)` : ''}: ${g.motion}, act=${g.act}${g.object ? ' - ' + g.object : ''}`,
      why: `where=${g.where}; motion=${g.motion}; our_car=${g.our_car}; act=${g.act} -> ${g.is_hazard ? 'hazard' : 'not hazard'} by the SPEC A.1 rule` });
  for (const x of explain)
    ev.push({ t: x.t ?? 0, prov: 'GENERATED', track_id: null, src: { file: 'explain', line: null }, title: x.text, why: 'LLM-written explanation, not a measurement' });
  ev.sort((a, b) => a.t - b.t || a.prov.localeCompare(b.prov));
  ev.forEach((e, i) => { e.id = 'e' + i; });
  return ev;
}
export const seekTime = (e) => Math.max(0, Math.round((e.t - 1.0) * 1000) / 1000);
