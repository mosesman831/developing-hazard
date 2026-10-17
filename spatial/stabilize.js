// Conditioning of real tracker output before anything is drawn. Pure functions, no DOM.
// Applied to every clip and every camera kind, so real dashcam footage plays without popping,
// spinning or teleporting. Nothing here is a forecast: every position shown lies between
// observed samples (or is an observed detection), and nothing is extrapolated past the last one.
//
//  1. linkRows      rows without track_id (the trimmed pod snapshot): link boxes over time by IoU
//  2. relink        one object split into several tracker ids: join fragments that touch in time and space
//  3. fillFromDets  the tracks file keeps only the top 3 per frame: while a track is not ranked, take its
//                   box from the detector (same class, best IoU), or bridge a short gap between two samples
//  4. placeTracks   per-sample placement, smoothed over +-0.4 s of observed samples (median then Gaussian),
//                   and a heading with hysteresis and a turn-rate limit, so models never spin
import { iou, bearingDeg, rangeFrac, rOfFrac, HORIZON_Y } from './core.js';
import { METRIC, resolveClass } from './models3d.js';

export const STAB = {
  linkIou: 0.3,        // box-to-box IoU that links rows without ids
  linkGap: 1.0,        // s; longest gap bridged when linking rows without ids
  relinkGap: 1.2,      // s; longest gap between two tracker ids that are one object
  fillIou: 0.3,        // IoU that chains a detection onto a track while it is not ranked
  fillGap: 2.0,        // s; longest gap filled from detections
  interpGap: 1.0,      // s; longest gap bridged by interpolating two observed boxes
  extend: 1.0,         // s; how long a track follows its detection before / after its ranked samples
  claimIou: 0.5,       // a detection matched this well to a ranked track belongs to it
  median: 1,           // samples each side in the median pass (5 fps: +-0.2 s)
  sigma: 0.2,          // s; Gaussian pass after the median (window +-2 sigma)
  runGap: 0.45,        // s; a larger gap splits smoothing runs
  fadeIn: 0.25,        // s; a track fades in instead of popping
  fadeOut: 0.45,       // s; and fades out after its last sample
  minRun: 3,           // samples; a shorter, unremarkable run stays on the video overlay but out of the 3D scene
  moveOn: { person: 0.6, bicycle: 1.2, vehicle: 1.5 },   // m/s before a heading is trusted
  turnRate: { person: 240, bicycle: 120, vehicle: 70 },  // deg/s limit on the shown heading
  oncoming: -3.0,      // m/s; a dashcam vehicle closing faster than the road is oncoming
  hold: 0.6,           // s; a heading reversal must persist this long
  maxClosing: 30,      // m/s; fastest a dashcam range estimate may change (two cars passing at ~55 km/h each)
};
const S = STAB;
const tk = (t) => Math.round(t * 100);
const GROUP = { person: 'p', bicycle: 'b', motorcycle: 'b', car: 'v', truck: 'v', bus: 'v' };
export const sameKind = (a, b) => { const x = resolveClass(a), y = resolveClass(b); return x === y || (GROUP[x] && GROUP[x] === GROUP[y]) || x === 'generic' || y === 'generic'; };
const kind = (cls) => { const c = resolveClass(cls); return c === 'person' ? 'person' : c === 'bicycle' || c === 'motorcycle' ? 'bicycle' : GROUP[c] === 'v' ? 'vehicle' : 'static'; };
const centre = (b) => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
const diag = (b) => Math.hypot(b[2] - b[0], b[3] - b[1]);
// spatial match score of two boxes a gap apart: IoU, else a centre distance in box sizes
function near(a, b, gap) {
  const o = iou(a, b);
  if (o >= 0.2) return 1 + o;
  const d = Math.hypot(centre(a)[0] - centre(b)[0], centre(a)[1] - centre(b)[1]) / Math.max(1e-3, Math.max(diag(a), diag(b)));
  const ha = a[3] - a[1], hb = b[3] - b[1], ratio = Math.max(ha, hb) / Math.max(1e-3, Math.min(ha, hb));
  return d <= 0.35 + 0.4 * gap && ratio <= 1.6 ? 1 - d : 0;
}
const majority = (rows) => { const n = new Map(); for (const r of rows) if (r.cls) n.set(r.cls, (n.get(r.cls) || 0) + 1); let best = null, bn = 0; for (const [c, k] of n) if (k > bn) { best = c; bn = k; } return best; };

// ---- 1. rows without ids --------------------------------------------------------------------
// Greedy best-IoU association frame to frame. Ids are display ids, numbered from 1, and say so.
export function linkRows(rows) {
  const steps = new Map();
  for (const r of rows) { const k = tk(r.t); if (!steps.has(k)) steps.set(k, []); steps.get(k).push(r); }
  const live = []; let next = 1;
  for (const k of [...steps.keys()].sort((a, b) => a - b)) {
    const here = steps.get(k), t = k / 100, pairs = [];
    for (let i = live.length - 1; i >= 0; i--) if (t - live[i].t > S.linkGap) live.splice(i, 1);
    here.forEach((r, i) => live.forEach((L, j) => { const s = near(L.nb, r.nb, t - L.t); if (s >= 1 + S.linkIou || (s > 0 && s < 1 && t - L.t > 0.25)) pairs.push([s, i, j]); }));
    pairs.sort((a, b) => b[0] - a[0]);
    const ui = new Set(), uj = new Set();
    for (const [, i, j] of pairs) { if (ui.has(i) || uj.has(j)) continue; ui.add(i); uj.add(j); here[i].track_id = live[j].id; live[j].nb = here[i].nb; live[j].t = t; }
    here.forEach((r, i) => { if (!ui.has(i)) { r.track_id = next++; live.push({ id: r.track_id, nb: r.nb, t }); } });
  }
  return rows;
}

// ---- 2. one object, several tracker ids -----------------------------------------------------
// -> { byId, alias: Map(original id -> shown id) }. Rows keep their original id in `orig_id`.
export function relink(byId) {
  const frags = [...byId.entries()].map(([id, rows]) => ({ id, rows, a: rows[0], b: rows[rows.length - 1], cls: majority(rows) }));
  const pairs = [];
  for (const A of frags) for (const B of frags) {
    if (A === B) continue;
    const gap = B.a.t - A.b.t;
    if (gap <= 0.05 || gap > S.relinkGap || !sameKind(A.cls, B.cls)) continue;
    const s = near(A.b.nb, B.a.nb, gap);
    if (s > 0) pairs.push({ A, B, s: s - 0.15 * gap });
  }
  pairs.sort((x, y) => y.s - x.s);
  const nextOf = new Map(), prevOf = new Map();
  const head = (f) => { while (prevOf.has(f)) f = prevOf.get(f); return f; };
  for (const { A, B } of pairs) {
    if (nextOf.has(A) || prevOf.has(B) || head(A) === head(B)) continue;   // chains stay in time order, no cycles
    nextOf.set(A, B); prevOf.set(B, A);
  }
  const out = new Map(), alias = new Map();
  for (const f of frags) {
    if (prevOf.has(f)) continue;
    const rows = []; let g = f;
    while (g) { for (const r of g.rows) { r.orig_id = g.id; r.track_id = f.id; rows.push(r); } alias.set(g.id, f.id); g = nextOf.get(g); }
    rows.sort((x, y) => x.t - y.t);
    const cls = majority(rows);
    for (const r of rows) if (!r.cls || sameKind(r.cls, cls)) r.cls = cls;
    out.set(f.id, rows);
  }
  return { byId: out, alias };
}

// ---- 3. fill the samples a track was not ranked for ---------------------------------------
// dets: rows with t, cls, conf, nb, _line. Filled rows carry `fill` ('det' | 'interp') and no risk of their own.
export function fillFromDets(byId, dets) {
  const at = new Map();
  for (const d of dets) { const k = tk(d.t); if (!at.has(k)) at.set(k, []); at.get(k).push(d); }
  const keys = [...at.keys()].sort((a, b) => a - b);
  const claimed = new Set();
  for (const rows of byId.values()) for (const r of rows) {           // ranked rows own their detection
    let best = null, bi = S.claimIou; for (const d of at.get(tk(r.t)) || []) { const o = iou(r.nb, d.nb); if (o >= bi) { bi = o; best = d; } }
    if (best) claimed.add(best);
  }
  const between = (t0, t1) => { const out = []; for (const k of keys) if (k > tk(t0) && k < tk(t1)) out.push(k); return out; };
  // a detection continues the track only if it overlaps it and keeps roughly its size and shape
  const shapeOk = (a, b) => {
    const ha = a[3] - a[1], hb = b[3] - b[1], wa = a[2] - a[0], wb = b[2] - b[0];
    const rh = hb / Math.max(1e-4, ha), ar = (wb / Math.max(1e-4, hb)) / (wa / Math.max(1e-4, ha));
    return rh > 0.7 && rh < 1.45 && ar > 0.65 && ar < 1.55;
  };
  const take = (k, prev, cls) => {
    let best = null, bi = S.fillIou;
    for (const d of at.get(k) || []) { if (claimed.has(d) || !sameKind(d.cls, cls) || !shapeOk(prev, d.nb)) continue; const o = iou(prev, d.nb); if (o > bi) { bi = o; best = d; } }
    return best;
  };
  const row = (src, t, nb, d, how) => ({ track_id: src.track_id, orig_id: src.orig_id ?? src.track_id, t: +t.toFixed(3), cls: src.cls, nb, xyxy: null, fill: how, risk: null,
    conf: d ? d.conf : null, conf_src: d ? d._line : null, det_line: d ? d._line : null, _line: null });
  const order = [...byId.values()].sort((a, b) => b.length - a.length);   // long tracks pick first
  for (const rows of order) {
    const add = [], cls = rows[0].cls;
    for (let i = 1; i < rows.length; i++) {
      const a = rows[i - 1], b = rows[i], gap = b.t - a.t;
      if (gap <= 0.3 || gap > S.fillGap) continue;
      let prev = a.nb, pt = a.t; const got = [];
      for (const k of between(a.t, b.t)) { const d = take(k, prev, cls); if (!d) break; claimed.add(d); got.push(row(a, k / 100, d.nb, d, 'det')); prev = d.nb; pt = k / 100; }
      add.push(...got);
      if (b.t - pt > 0.3 && b.t - a.t <= S.interpGap + 0.3) {        // bridge the rest between two observed boxes
        for (const k of between(pt, b.t)) { const f = (k / 100 - pt) / (b.t - pt); add.push(row(a, k / 100, prev.map((v, j) => v + (b.nb[j] - v) * f), null, 'interp')); }
      }
    }
    // follow the detector a little before the first and after the last ranked sample
    for (const dir of [1, -1]) {
      const end = dir > 0 ? rows[rows.length - 1] : rows[0]; let prev = end.nb;
      const ks = keys.filter((k) => (dir > 0 ? k > tk(end.t) && k <= tk(end.t + S.extend) : k < tk(end.t) && k >= tk(end.t - S.extend)));
      if (dir < 0) ks.reverse();
      for (const k of ks) { const d = take(k, prev, cls); if (!d) break; claimed.add(d); add.push(row(end, k / 100, d.nb, d, 'det')); prev = d.nb; }
    }
    if (add.length) { rows.push(...add); rows.sort((x, y) => x.t - y.t); }
  }
  // a filled row shows the nearest ranked risk, labelled as held (the tracker did not rank it then)
  for (const rows of byId.values()) {
    let last = null;
    for (const r of rows) { if (!r.fill) last = r; else if (last) { r.risk_held = last.risk; r.held_from = last.t; } }
    let nextR = null;
    for (let i = rows.length - 1; i >= 0; i--) { const r = rows[i]; if (!r.fill) nextR = r; else if (r.risk_held == null && nextR) { r.risk_held = nextR.risk; r.held_from = nextR.t; } }
  }
  return byId;
}

// ---- 4. smoothing -------------------------------------------------------------------------
// Robust zero-phase smoothing of one scalar series (median, then Gaussian in time), run by run.
export function smoothSeries(ts, vs, { med = S.median, sigma = S.sigma, runGap = S.runGap } = {}) {
  const out = vs.slice(), n = ts.length;
  let s = 0;
  while (s < n) {
    let e = s; while (e + 1 < n && ts[e + 1] - ts[e] <= runGap) e++;
    const m = [];
    for (let i = s; i <= e; i++) {
      const w = []; for (let j = Math.max(s, i - med); j <= Math.min(e, i + med); j++) if (Number.isFinite(vs[j])) w.push(vs[j]);
      w.sort((a, b) => a - b); m[i] = w.length ? w[w.length >> 1] : vs[i];
    }
    for (let i = s; i <= e; i++) {
      let sw = 0, sv = 0;
      for (let j = i; j >= s && ts[i] - ts[j] <= 2 * sigma; j--) { const w = Math.exp(-((ts[i] - ts[j]) ** 2) / (2 * sigma * sigma)); sw += w; sv += w * m[j]; }
      for (let j = i + 1; j <= e && ts[j] - ts[i] <= 2 * sigma; j++) { const w = Math.exp(-((ts[j] - ts[i]) ** 2) / (2 * sigma * sigma)); sw += w; sv += w * m[j]; }
      out[i] = sw ? sv / sw : m[i];
    }
    s = e + 1;
  }
  return out;
}
// Clamp how fast a series may change (units per second). A forward and a backward pass are averaged, so
// the result does not lag the video. Used on dashcam range, where a tiny far box can halve in a frame.
export function rateLimit(ts, vs, maxRate, runGap = S.runGap) {
  const pass = (order) => { const o = vs.slice(); for (let n = 1; n < order.length; n++) { const i = order[n], j = order[n - 1], dt = Math.abs(ts[i] - ts[j]); if (dt > runGap || !Number.isFinite(o[j]) || !Number.isFinite(o[i])) continue; const lim = maxRate * dt; o[i] = Math.max(o[j] - lim, Math.min(o[j] + lim, o[i])); } return o; };
  const idx = vs.map((_, i) => i), f = pass(idx), b = pass(idx.slice().reverse());
  return vs.map((v, i) => (Number.isFinite(f[i]) && Number.isFinite(b[i]) ? (f[i] + b[i]) / 2 : v));
}
const wrap = (a) => ((((a + 180) % 360) + 360) % 360) - 180;
export const angLerp = (a, b, f) => a + wrap(b - a) * f;

// Dashcam size cue (camera.js appearancePoint uses the same model): range from how tall the box is for its
// class, bearing from where it sits across the frame. Truncated boxes are marked, not trusted.
function sizeRange(nb, cls, hfov) {
  const h = (METRIC[resolveClass(cls)] || METRIC.generic)[2];
  const boxH = Math.max(0.02, Math.min(0.9, nb[3] - nb[1])), vfov = ((hfov * 9) / 16) * (Math.PI / 180);
  return Math.max(1.8, Math.min(42, h / (2 * Math.tan(Math.min(1.15, boxH * vfov) / 2))));
}
const cut = (nb) => nb[1] <= 0.005 || nb[3] >= 0.995;

// Heading with hysteresis and a turn-rate limit, from the smoothed ground track (past 0.6 s only).
// egoAt(t) -> forward flow of static things (m/s, negative while driving) or null; only for a dashcam.
function headings(rows, cls, { egoAt = null, initial = () => 0 } = {}) {
  const k = kind(cls), on = S.moveOn[k] ?? S.moveOn.vehicle, rate = S.turnRate[k] ?? S.turnRate.vehicle;
  let shown = null, want = null, since = null, prevT = null;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    let j = i; while (j > 0 && r.t - rows[j - 1].t <= 0.6 + 1e-6 && rows[j].t - rows[j - 1].t <= S.runGap) j--;
    let target = null;
    if (j < i && r.gs && rows[j].gs) {
      const dt = r.t - rows[j].t, vx = (r.gs[0] - rows[j].gs[0]) / dt, vz = (r.gs[1] - rows[j].gs[1]) / dt;
      r.wv = egoAt ? null : [vx, vz];                    // observed ground velocity over the past 0.6 s
      if (egoAt) {
        const ego = egoAt(r.t), wz = ego == null ? 0 : vz - ego;
        if (ego != null) r.wv = [vx, wz];
        if (k === 'vehicle') target = ego != null && wz < S.oncoming ? 180 : ego != null && wz > -1 ? 0 : null;
        else if (k !== 'static' && Math.hypot(vx, ego == null ? 0 : wz) > on) target = (Math.atan2(vx, ego == null ? 0 : wz) * 180) / Math.PI;
      } else if (k !== 'static' && Math.hypot(vx, vz) > on) target = (Math.atan2(vx, vz) * 180) / Math.PI;
    }
    if (shown == null) shown = target ?? initial(r);
    if (target != null) {
      // a reversal (> 120 deg) must persist before it is shown; small changes follow at once
      if (Math.abs(wrap(target - shown)) > 120) { if (want == null || Math.abs(wrap(target - want)) > 45) { want = target; since = r.t; } if (r.t - since < S.hold) target = null; }
      else want = null;
    }
    if (target != null && prevT != null) { const lim = rate * Math.max(0.05, r.t - prevT); shown = wrap(shown + Math.max(-lim, Math.min(lim, wrap(target - shown)))); }
    else if (target != null) shown = target;
    r.yaw = shown; prevT = r.t;
  }
}

// rows of every track, sorted by t. camera: { kind, follow, rig?, hfov } . groundPoint(nb) for a calibrated fixed camera.
// Sets on every row: dashcam -> pa (bearing deg), pr (plan radius 0-1, continuous, same scale as the bands);
// fixed -> gs [x, z] smoothed ground position and yaw (deg). Also seg0 (start of the visible run) on every row.
export function placeTracks(byId, camera, { groundPoint = null, initialYaw = null } = {}) {
  const dash = camera.kind !== 'fixed', follow = camera.follow === 'video', hfov = camera.hfov || 157;
  for (const rows of byId.values()) {
    const ts = rows.map((r) => r.t);
    // runs: stretches with no gap longer than fadeOut. seg0 = when the run started, runN = its sample count
    // runRisk = the highest risk in the run, runEnd = its last sample, so whether a run is shown is decided once
    let seg0 = rows.length ? rows[0].t : 0, from = 0;
    const close = (to) => { let mx = 0; for (let j = from; j < to; j++) mx = Math.max(mx, rows[j].risk ?? rows[j].risk_held ?? 0); for (let j = from; j < to; j++) Object.assign(rows[j], { runN: to - from, runRisk: mx, runEnd: rows[to - 1].t }); };
    rows.forEach((r, i) => {
      if (i && r.t - rows[i - 1].t > S.fadeOut) { close(i); seg0 = r.t; from = i; }
      r.seg0 = seg0;
    });
    if (rows.length) close(rows.length);
    if (dash) {
      // nearness from the box bottom against the assumed horizon; a box cut by the bottom edge is as near as
      // the scale goes, a box whose bottom is above the horizon as far (both stay marked "range uncertain")
      const fr = rows.map((r) => (r.nb[3] >= 0.99 ? 1 : r.nb[3] <= HORIZON_Y ? 0 : rangeFrac(r.nb[3])));
      const pa = smoothSeries(ts, rows.map((r) => bearingDeg(r.nb))), pf = smoothSeries(ts, fr);
      rows.forEach((r, i) => { r.pa = pa[i]; r.pr = rOfFrac(Math.max(0, Math.min(1, pf[i]))); });
      continue;
    }
    if (follow) {
      // bearing and log-range smoothed separately: range noise from box height is multiplicative
      const b = rows.map((r) => (((r.nb[0] + r.nb[2]) / 2 - 0.5) * hfov)), lr = rows.map((r) => Math.log(sizeRange(r.nb, r.cls, hfov)));
      const cutAt = rows.map((r) => cut(r.nb));
      // a truncated box only bounds the range from above: replace it by its run's neighbours where they exist
      const lrc = lr.map((v, i) => (cutAt[i] ? NaN : v));
      const hasGood = lrc.some(Number.isFinite);
      const bs = smoothSeries(ts, b), ls = smoothSeries(ts, hasGood ? lrc.map((v, i) => (Number.isFinite(v) ? v : nearestFinite(lrc, ts, i, lr[i]))) : lr);
      // closing faster than two cars passing (30 m/s) is the size cue failing on a tiny box, not motion
      const Rs = rateLimit(ts, ls.map(Math.exp), S.maxClosing);
      rows.forEach((r, i) => { const R = Rs[i], a = (bs[i] * Math.PI) / 180; r.gs = [R * Math.sin(a), R * Math.cos(a)]; r.g = r.gs; });
    } else {
      const raw = rows.map((r) => r.g || (groundPoint ? groundPoint(r.nb, r.cls) : null));
      const xs = smoothSeries(ts, raw.map((g) => (g ? g[0] : NaN))), zs = smoothSeries(ts, raw.map((g) => (g ? g[1] : NaN)));
      rows.forEach((r, i) => { r.gs = raw[i] && Number.isFinite(xs[i]) && Number.isFinite(zs[i]) ? [xs[i], zs[i]] : null; });
    }
  }
  if (dash) return byId;
  const egoAt = follow ? egoFlow(byId) : null;
  for (const rows of byId.values()) headings(rows, rows[0] && rows[0].cls, { egoAt, initial: (r) => (initialYaw && r.gs ? initialYaw(r.gs) : 0) });
  return byId;
}
function nearestFinite(arr, ts, i, fallback) {
  let best = fallback, bd = 0.61;
  for (let j = 0; j < arr.length; j++) if (Number.isFinite(arr[j]) && Math.abs(ts[j] - ts[i]) < bd) { bd = Math.abs(ts[j] - ts[i]); best = Math.min(arr[j], fallback); }
  return best;
}
// forward flow of things that do not move on their own (cars beside the road, signs, lights), per 5 fps step,
// median across them and over +-1 s. null where nothing static is in view.
export function egoFlow(byId) {
  const per = new Map();
  for (const rows of byId.values()) {
    const c = resolveClass(rows[0] && rows[0].cls), stat = c === 'traffic light' || c === 'stop sign';
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i]; if (!r.gs) continue;
      if (!stat && !(GROUP[c] === 'v' && Math.abs(r.gs[0]) >= 1.4)) continue;
      let j = i; while (j > 0 && r.t - rows[j - 1].t <= 0.6 + 1e-6) j--;
      if (j === i || !rows[j].gs || r.t - rows[j].t < 0.15) continue;
      const k = tk(r.t); if (!per.has(k)) per.set(k, []); per.get(k).push((r.gs[1] - rows[j].gs[1]) / (r.t - rows[j].t));
    }
  }
  const keys = [...per.keys()].sort((a, b) => a - b), med = (a) => { const s = a.slice().sort((x, y) => x - y); return s[s.length >> 1]; };
  const raw = new Map(keys.filter((k) => per.get(k).length >= 2).map((k) => [k, med(per.get(k))]));
  const cache = new Map();
  return (t) => {
    const k = tk(t); if (cache.has(k)) return cache.get(k);
    const w = []; for (const [kk, v] of raw) if (Math.abs(kk - k) <= 100) w.push(v);
    const v = w.length ? med(w) : null; cache.set(k, v); return v;
  };
}

// ---- sampling at a clip time ----------------------------------------------------------------
// -> { row, alpha } with box, placement and heading interpolated between the two samples around t.
// Before a run's first sample: nothing. After the last: held and fading out over fadeOut, never moved.
export function sampleAt(rows, t) {
  let lo = 0, hi = rows.length - 1, i = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (rows[m].t <= t + 1e-6) { i = m; lo = m + 1; } else hi = m - 1; }
  if (i < 0) return null;
  const r = rows[i], next = rows[i + 1], gap = t - r.t;
  const fadeIn = Math.min(1, 0.35 + (0.65 * Math.max(0, t - (r.seg0 ?? r.t))) / S.fadeIn);
  if (!next || next.t - r.t > S.fadeOut) {
    const alpha = Math.max(0, 1 - gap / S.fadeOut) * fadeIn;
    return alpha < 0.04 ? null : { row: r, alpha };
  }
  const f = gap / (next.t - r.t);
  if (f <= 1e-6) return { row: r, alpha: fadeIn };
  const L = (a, b) => (a != null && b != null ? a + (b - a) * f : a);
  const out = { ...r, nb: r.nb.map((v, k) => v + (next.nb[k] - v) * f) };
  if (r.pa != null) { out.pa = L(r.pa, next.pa); out.pr = L(r.pr, next.pr); }
  if (r.gs && next.gs) out.gs = [L(r.gs[0], next.gs[0]), L(r.gs[1], next.gs[1])];
  if (r.g && next.g) out.g = [L(r.g[0], next.g[0]), L(r.g[1], next.g[1])];
  if (r.yaw != null && next.yaw != null) out.yaw = angLerp(r.yaw, next.yaw, f);
  return { row: out, alpha: fadeIn };
}

// A run of one or two samples is a blink: draw it in the scene only when it matters. Decided per run
// (peak risk, a label overlapping the run), never per frame, so it cannot pop in halfway through.
// labelled(t0, t1) -> true when a human hazard window for this track overlaps [t0, t1].
export const sceneWorthy = (row, { labelled = null, selected = false, riskAmber = 0.4 } = {}) =>
  selected || (row.runN ?? S.minRun) >= S.minRun || (row.runRisk ?? row.risk ?? 0) >= riskAmber || (!!labelled && labelled(row.seg0 ?? row.t, row.runEnd ?? row.t));

// whole pipeline for loadModel. rows: track rows with nb; dets: det rows with nb.
export function conditionTracks(rows, dets, camera, opts = {}) {
  const linked = !rows.some((r) => r.track_id != null);
  if (linked) linkRows(rows.sort((a, b) => a.t - b.t));
  let byId = new Map();
  for (const r of rows.sort((a, b) => a.t - b.t)) { if (!byId.has(r.track_id)) byId.set(r.track_id, []); byId.get(r.track_id).push(r); }
  // classes for rows that came without one: the detection under the box, else the track's majority
  if (rows.some((r) => !r.cls) && dets.length) {
    const at = new Map(); for (const d of dets) { const k = tk(d.t); if (!at.has(k)) at.set(k, []); at.get(k).push(d); }
    for (const r of rows) if (!r.cls) { let best = null, bi = 0.5; for (const d of at.get(tk(r.t)) || []) { const o = iou(r.nb, d.nb); if (o > bi) { bi = o; best = d; } } if (best) r.cls = best.cls; }
  }
  for (const rs of byId.values()) { const c = majority(rs) || 'object'; for (const r of rs) if (!r.cls) r.cls = c; }
  const before = byId.size;
  const rl = relink(byId); byId = rl.byId;
  if (dets.length) fillFromDets(byId, dets);
  placeTracks(byId, camera, opts);
  const filled = [...byId.values()].reduce((n, rs) => n + rs.filter((r) => r.fill).length, 0);
  return { byId, alias: rl.alias, linked, joined: before - byId.size, filled };
}
