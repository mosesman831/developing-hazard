// Spatial Hazard View: approximate plan + 3D viewport, evidence-backed event log, box overlay.
// mountSpatial(el, ctx) -> { setTime(t), select(sel), setMode(m), setFrame(f), destroy() }
import * as C from './core.js';
import { loadModel } from './data.js';
import { createView3D } from './view3d.js';
import { groundMotion, proximityEvents } from './camera.js';
import { metricDims } from './models3d.js';
import { sampleAt, sceneWorthy } from './stabilize.js';

const NS = 'http://www.w3.org/2000/svg';
function h(tag, attrs = {}, ...kids) {
  const svg = tag === 'svg' || attrs.svg;
  const e = svg ? document.createElementNS(NS, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'svg' || v == null || v === false) continue;
    if (k === 'class') e.setAttribute('class', v); else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (k === 'text') e.textContent = v; else e.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c != null) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}
const S = (tag, attrs, ...k) => h(tag, { svg: 1, ...attrs }, ...k);
const f2 = (v) => (typeof v === 'number' ? v.toFixed(2) : '-');
const FILL = { red: 'rgba(248,81,73,.30)', amber: 'rgba(227,160,8,.24)', grey: 'rgba(139,146,156,.12)' };
const RING = { green: '#3fb950', amber: '#e3a008' };
const HZC = { red: '#f85149', amber: '#e3a008', grey: '#8b929c' };
const PROV = { MEASURED: '#6ea0ff', MODEL: '#bc8cff', HUMAN: '#3fb950', AGENT: '#e3a008', GENERATED: '#98a0aa' };
const STATE_CLS = { ok: 'ok', partial: 'warn', empty: 'warn', missing: 'bad', malformed: 'bad', optional: 'opt' };
// 16 px stroke icons, one per tool, so every control reads at a glance
const ICON = {
  camera: 'M2 5h8v6H2zM10 7.2l4-2v5.6l-4-2', persp: 'M8 2l5 3v6l-5 3-5-3V5zM3 5l5 3 5-3M8 8v6', top: 'M2.5 2.5h11v11h-11zM8 6.5v3M6.5 8h3',
  front: 'M3 3h10v10H3zM3 9h10', side: 'M3 3h10v10H3zM9 3v10', ortho: 'M3.5 3v10M8 3v10M12.5 3v10', frame: 'M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3M8 6.5v3M6.5 8h3',
  grid: 'M2 2h12v12H2zM6 2v12M10 2v12M2 6h12M2 10h12', fov: 'M8 14L2.5 4.5a10 10 0 0111 0z', path: 'M5.5 14L7 2M10.5 14L9 2',
  labels: 'M3 3h10v7H8.5L6 12.5V10H3z', scenery: 'M1.5 14h13M3 14V8l3-2v8M8 14V4l4-2v12', plan: 'M8 14L2.5 4.5a10 10 0 0111 0zM8 14V7', cube: 'M8 2l5 3v6l-5 3-5-3V5zM3 5l5 3 5-3M8 8v6',
};
const icon = (k) => S('svg', { viewBox: '0 0 16 16', 'aria-hidden': 'true' }, S('path', { d: ICON[k] }));
const LOGO = () => S('svg', { viewBox: '0 0 20 20', 'aria-hidden': 'true' },
  S('path', { d: 'M10 17 L2.5 5.5 A11 11 0 0 1 17.5 5.5 Z', fill: 'rgba(138,180,255,.22)', stroke: '#8ab4ff', 'stroke-width': 1.4, 'stroke-linejoin': 'round' }),
  S('circle', { cx: 12.6, cy: 8.2, r: 2.1, fill: '#f85149' }), S('circle', { cx: 7.6, cy: 10.4, r: 1.5, fill: '#3fb950' }));
const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
function ensureStyles() {
  const href = new URL('./style.css', import.meta.url).href;
  if ([...document.querySelectorAll('link[rel="stylesheet"]')].some((l) => l.href === href)) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  link.dataset.spatialCss = '1';
  document.head.append(link);
}

export function mountSpatial(el, ctx) {
  ensureStyles();
  const dbg = !!ctx.debug, uid = Math.random().toString(36).slice(2, 8);
  let model = null, t = 0, sel = null, raf = 0, dead = false, frame = ctx.frame || { w: 1920, h: 1080 };
  let mode = ctx.view3d === false ? '2d' : (ctx.initialMode || '3d');
  const off = new Set();                                   // hidden provenances
  let events = [], cur = -1;
  const memo = {};                                         // last-rendered keys, so panels only rebuild on change
  let last3d = '';                                         // skip a 3D rebuild when the actors have not moved
  const changed = (k, v) => (memo[k] === v ? false : ((memo[k] = v), true));
  const fixed = () => !!model && model.camera.kind === 'fixed';

  // ---- skeleton: real layout immediately, filled in as data arrives ----
  const sources = h('div', { class: 'sp-sources', role: 'list', 'aria-label': 'Inputs' }, h('span', { class: 'sp-in' }, h('i'), 'loading inputs'));
  const note = h('div', { class: 'sp-note', hidden: true, role: 'status' });
  const svg = S('svg', { class: 'sp-bird', viewBox: '0 0 600 400', role: 'img', 'aria-label': 'Approximate plan view' });
  const c3 = h('canvas', { class: 'sp-3d', tabindex: 0, 'aria-label': '3D viewport: drag to orbit, right-drag to pan, wheel to zoom, double-click to reset' });
  const v3 = createView3D(c3, { onPick: (id) => choose({ kind: 'track', id }, true), onChange: () => drawStatus() });
  const outliner = h('div', { class: 'sp-outliner', role: 'tree', 'aria-label': 'Scene outliner' });
  const detail = h('div', { class: 'sp-detail', 'aria-live': 'polite' });
  const chips = h('div', { class: 'sp-chips', role: 'group', 'aria-label': 'Filter events by provenance' });
  const list = h('ul', { class: 'sp-events', 'aria-label': 'Event log' }, h('li', { class: 'sp-empty', text: 'Loading events' }));
  const dbgLine = dbg ? h('div', { class: 'sp-dbg', text: 'debug: hover an item for its source line' }) : null;
  const stat = { t: h('b'), mode: h('span'), cam: h('span'), sel: h('span') };
  const disc = h('span', { class: 'sp-disc', text: 'Approximate positions from a single camera, no depth sensor. Range bands are ordinal, not distances.' });
  const status = h('footer', { class: 'sp-status' }, stat.t, stat.mode, stat.cam, stat.sel, disc);
  const vpTag = h('div', { class: 'sp-vp-tag sp-glass', text: 'Ordinal units, not metres' });

  const btn = (ic, label, title, fn, cls = '') => h('button', { type: 'button', class: 'sp-tb ' + cls, title, 'aria-label': label, onclick: fn }, icon(ic), h('span', { text: label }));
  const modeBtns = { '2d': btn('plan', 'Plan', 'Plan view (V toggles)', () => setMode('2d')), '3d': btn('cube', '3D', '3D viewport (V toggles)', () => setMode('3d')) };
  const viewBtns = Object.fromEntries([['camera', 'camera', 'Camera', 'Camera view: the video viewpoint (C)'], ['persp', 'persp', 'Persp', 'Perspective'], ['top', 'top', 'Top', 'Top view'], ['front', 'front', 'Front', 'Front view'], ['right', 'side', 'Side', 'Side view']]
    .map(([k, ic, n, tt]) => [k, btn(ic, n, tt, () => v3.setView(k), 'lb')]));
  const orthoBtn = btn('ortho', 'Ortho', 'Orthographic projection (O)', () => setPressed(orthoBtn, v3.setOrtho()), 'lb');
  const setPressed = (b, on) => { b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); };
  const togBtn = (k, ic, n) => { const b = btn(ic, n, `Show or hide ${n.toLowerCase()}`, () => { setPressed(b, v3.toggle(k)); memo.out = null; sched(); }, 'on ico'); b.setAttribute('aria-pressed', 'true'); return b; };
  const sceneryBtn = togBtn('scenery', 'scenery', 'Scenery');
  const togs = { grid: togBtn('grid', 'grid', 'Grid'), fov: togBtn('fov', 'fov', 'FOV'), path: togBtn('path', 'path', 'Path'), labels: togBtn('labels', 'labels', 'Labels'), scenery: sceneryBtn };
  const v3Tools = h('div', { class: 'sp-tools' },
    h('div', { class: 'sp-grp', role: 'group', 'aria-label': 'Camera presets' }, ...Object.values(viewBtns)),
    h('div', { class: 'sp-grp', role: 'group', 'aria-label': 'Projection' }, orthoBtn, btn('frame', 'Frame', 'Reset the camera (F, or double-click the view)', () => v3.frame(), 'lb')),
    h('div', { class: 'sp-grp', role: 'group', 'aria-label': 'Layers' }, ...Object.values(togs)));
  const legend = h('details', { class: 'sp-legend sp-glass' },
    h('summary', { text: 'Legend' }),
    h('div', { class: 'sp-lg' },
      h('div', { class: 'sp-lg-h', text: 'Ground ring = confidence' }),
      h('span', {}, h('i', { class: 'ring g' }), 'conf ≥ 0.6, seen ≥ 5 samples'), h('span', {}, h('i', { class: 'ring a' }), 'low or unknown conf, short, at an edge'),
      h('div', { class: 'sp-lg-h', text: 'Ground disc = hazard' }),
      h('span', {}, h('i', { class: 'fill r' }), 'risk ≥ 0.6, human label, Cosmos'), h('span', {}, h('i', { class: 'fill m' }), 'risk 0.4 – 0.6, heading in'),
      h('span', {}, h('i', { class: 'hatch' }), 'not visible to the camera'),
      h('span', { text: 'A box is drawn only around the selected track' })));
  const pane = (title, body, extra = null, cls = '') => h('section', { class: 'sp-pane ' + cls, 'aria-label': title }, h('header', { class: 'sp-ph' }, h('span', { class: 'sp-pt', text: title }), extra), body);

  el.classList.add('sp');
  if (ctx.aurora !== false) el.classList.add('sp-aurora');  // glass needs something behind it; a host with its own backdrop passes aurora: false
  el.replaceChildren(...[ctx.banner ? h('div', { class: 'sp-banner', role: 'alert', text: ctx.banner }) : null,
    h('header', { class: 'sp-head' },
      h('div', { class: 'sp-brand' }, h('span', { class: 'sp-mark' }, LOGO()), h('span', { class: 'sp-word' }, h('em', { text: 'Spatial' }), 'Hazard View')),
      h('nav', { class: 'sp-crumbs sp-glass', 'aria-label': 'Clip' }, h('span', { text: `clip ${ctx.clipId}` }), ctx.runId ? h('span', { text: `run ${ctx.runId}` }) : null), sources),
    note,
    h('div', { class: 'sp-stage' },
      pane('Outliner', outliner, null, 'sp-outpane'),
      h('section', { class: 'sp-pane sp-vpane', 'aria-label': 'Viewport' },
        h('header', { class: 'sp-ph' }, h('div', { class: 'sp-grp', role: 'group', 'aria-label': 'View mode' }, modeBtns['2d'], modeBtns['3d']), v3Tools),
        h('div', { class: 'sp-viewport' }, svg, c3, vpTag, legend)),
      h('div', { class: 'sp-dock' }, pane('Properties', detail), pane('Event log', list, chips, 'sp-evpane'))),
    dbgLine, status].filter(Boolean));
  // material ripple on every pressable surface (skipped when the user prefers reduced motion)
  const ripple = (e) => {
    const b = e.target.closest('.sp-tb,.sp-chip,.sp-ev,.sp-oi.l2,.sp-oi.tog'); if (!b || reduced()) return;
    const r = b.getBoundingClientRect(), s = Math.max(r.width, r.height) * 2.2;
    const d = h('span', { class: 'sp-ripple', style: `width:${s}px;height:${s}px;left:${e.clientX - r.left - s / 2}px;top:${e.clientY - r.top - s / 2}px` });
    b.appendChild(d); d.addEventListener('animationend', () => d.remove());
  };
  el.addEventListener('pointerdown', ripple);
  const vpEl = el.querySelector('.sp-viewport');
  legend.querySelector('summary').addEventListener('click', () => { legend.dataset.user = '1'; });
  const legendFit = new ResizeObserver(() => { if (!legend.dataset.user) legend.open = vpEl.clientHeight >= 480; });
  legendFit.observe(vpEl);
  function setMode(m) {
    mode = m; el.dataset.mode = fixed() ? '3d' : m;
    if (fixed()) { v3.setView(m === '2d' ? 'top' : 'persp'); setPressed(orthoBtn, v3.setOrtho(m === '2d')); }
    viewBtns.camera.hidden = sceneryBtn.hidden = !fixed();
    togs.path.hidden = !!fixed();
    last3d = '';
    for (const [k, b] of Object.entries(modeBtns)) setPressed(b, k === m);
    v3Tools.hidden = m !== '3d' && !fixed();
    sched();
  }

  // ---- overlay canvas on the host video ----
  // The canvas never takes pointer events, so the host's own video controls keep working under it.
  // Clicks reach it through the host element and only select when they land on a box.
  let canvas = null, cx2 = null, boxes = [], vHost = null;
  const vEl = ctx.videoEl || null;
  // the video showing now: a segment player swaps between two <video> elements in the same host
  const liveVideo = () => {
    const v = typeof ctx.getVideo === 'function' ? ctx.getVideo() : null;
    if (v) return v;
    if (!vHost) return vEl;
    const vids = [...vHost.querySelectorAll('video')].filter((x) => x.offsetParent !== null && getComputedStyle(x).visibility !== 'hidden');
    return vids[0] || vEl;
  };
  const onHostClick = (e) => { if (!canvas) return; const hit = hitTest(e); if (hit) { e.preventDefault(); e.stopPropagation(); choose({ kind: 'track', id: hit.id }, true); } };
  const onHostMove = (e) => {
    if (!canvas) return; const hit = hitTest(e);
    vHost.style.cursor = hit ? 'pointer' : '';
    if (dbg) dbgLine.textContent = hit ? srcText(hit.row) : 'debug: hover a box';
  };
  if (vEl && vEl.parentElement) {
    vHost = vEl.parentElement;
    if (getComputedStyle(vHost).position === 'static') vHost.style.position = 'relative';
    canvas = h('canvas', { class: 'sp-overlay', 'aria-hidden': 'true' });
    vHost.appendChild(canvas); cx2 = canvas.getContext('2d');
    vHost.addEventListener('click', onHostClick, true);
    vHost.addEventListener('mousemove', onHostMove);
  }
  const fontVar = (k, d) => getComputedStyle(el).getPropertyValue(k).trim() || d;
  // where the picture is drawn, in canvas pixels: the video element's own box, letterboxed to its aspect
  function videoRect() {
    const v = liveVideo(), cr = canvas.getBoundingClientRect(), vr = v ? v.getBoundingClientRect() : cr;
    const bx = vr.width ? vr.left - cr.left : 0, by = vr.height ? vr.top - cr.top : 0, W = vr.width || cr.width, H = vr.height || cr.height;
    const vw = (v && v.videoWidth) || frame.w, vh = (v && v.videoHeight) || frame.h, s = Math.min(W / vw, H / vh);
    return { x: bx + (W - vw * s) / 2, y: by + (H - vh * s) / 2, w: vw * s, h: vh * s };
  }
  function hitTest(e) {
    const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (y > r.height - 44) return null;                    // leave the native control bar alone
    return [...boxes].reverse().find((b) => x >= b.x1 && x <= b.x2 && y >= b.y1 && y <= b.y2) || null;
  }
  const srcText = (row) => `${row.fill ? (row.fill === 'det' ? `det line ${row.det_line} (not ranked by the tracker at this time)` : 'bridged between two tracker samples') : `tracks line ${row._line}`}${row.orig_id != null && row.orig_id !== row.track_id ? `; tracker id ${row.orig_id}` : ''}; conf ${row.conf == null ? 'unknown' : f2(row.conf) + (row.conf_src != null ? ' (det line ' + row.conf_src + ')' : '')}; streak ${row.streak}; risk ${row.risk == null ? (row.risk_held != null ? f2(row.risk_held) + ' held' : '?') : f2(row.risk)}`;
  const isSel = (id) => !!sel && sel.kind === 'track' && sel.id === id;
  const confTxt = (row) => (row.conf == null ? 'conf ?' : f2(row.conf));

  // ---- derived per-track state at time t ----
  function state(id, row) {
    const nb = row.nb, band = fixed() ? (row.gs || row.g ? 'ground' : 'uncertain') : C.rangeBand(nb);
    // plan placement: the smoothed, continuous position (stabilize.js); the band still names the range
    const place = fixed() ? { visible: true } : { ang: row.pa ?? C.bearingDeg(nb), r: row.pr ?? C.birdPlace(nb).r, band, visible: C.inFov(row.pa ?? C.bearingDeg(nb)) };
    const ring = C.ringState({ conf: row.conf, streak: row.streak, band, edge: C.edgeTouch(nb) });
    const inHazard = model.hazards.some((z) => z.track_id === id && t >= z.window_start && t <= z.window_end);
    const cosmosYes = model.grid.some((g) => g.is_hazard && g.track_id === id && t >= g.t && t < g.t + C.THRESHOLDS.cosmosHold);
    const risk = row.risk ?? row.risk_held ?? null;
    const fill = C.fillState({ risk, heading_in: row.fill ? false : row.heading_in, inHazard, cosmosYes, visible: place.visible });
    if (row.risk == null && row.risk_held != null && fill.why.length) fill.why = fill.why.map((w) => (w.startsWith('risk') ? `${w} (held from ${f2(row.held_from)} s: the tracker did not rank this object at this time)` : w));
    if (row.risk == null && row.risk_held == null && !row.fill) fill.why.push('risk not in the tracks file');
    return { ring, fill, place, band };
  }
  const actives = () => {
    const out = [];
    if (!model) return out;
    for (const [id, rows] of model.tracks) {
      const s = sampleAt(rows, t);
      if (!s) continue;
      out.push({ id, row: s.row, alpha: s.alpha, ...state(id, s.row) });
    }
    return dropTwins(out);
  };
  // One object can carry two track ids at the same moment (glare splits a car at night). Two same-kind boxes
  // that mostly cover each other are one object: keep the better observed (confidence, then run length).
  const KIND = { person: 'p', bicycle: 'b', motorcycle: 'b', car: 'v', truck: 'v', bus: 'v', van: 'v' };
  function dropTwins(act) {
    const score = (a) => (a.row.conf ?? 0) + 0.001 * (a.row.runN ?? 0);
    const kept = [];
    for (const a of [...act].sort((x, y) => score(y) - score(x))) {
      const k = KIND[a.row.cls] || a.row.cls, b = a.row.nb;
      const twin = kept.find((o) => {
        if ((KIND[o.row.cls] || o.row.cls) !== k || isSel(a.id)) return false;
        const c = o.row.nb, ix = Math.min(b[2], c[2]) - Math.max(b[0], c[0]), iy = Math.min(b[3], c[3]) - Math.max(b[1], c[1]);
        return ix > 0 && iy > 0 && (ix * iy) / Math.min((b[2] - b[0]) * (b[3] - b[1]), (c[2] - c[0]) * (c[3] - c[1])) >= 0.7;
      });
      if (!twin) kept.push(a);
    }
    return act.filter((a) => kept.includes(a));
  }
  // observed motion over the last second, as a unit [dx, dz] in the plan (never a forecast)
  function motion(id) {
    const rows = model.tracks.get(id), now = sampleAt(rows, t), then = sampleAt(rows, t - C.THRESHOLDS.motionWin);
    if (!now || !then || now.row.pa == null || then.row.pa == null) return null;
    const w = (r) => { const a = (r.pa * Math.PI) / 180; return [Math.sin(a) * r.pr, Math.cos(a) * r.pr]; };
    const p0 = w(then.row), p1 = w(now.row), d = [p1[0] - p0[0], p1[1] - p0[1]], L = Math.hypot(...d);
    return L > 0.02 ? d.map((v) => v / L) : null;
  }
  // observed ground motion over the last second, [dx, dz] in metres (fixed cameras; never a forecast)
  function groundStep(id) {
    const rows = model.tracks.get(id), now = sampleAt(rows, t), then = sampleAt(rows, t - C.THRESHOLDS.motionWin);
    const a = then && (then.row.gs || then.row.g), b = now && (now.row.gs || now.row.g);
    return a && b ? [b[0] - a[0], b[1] - a[1]] : null;
  }

  // ---- video overlay: same two channels, glass label pills ----
  function drawOverlay(act) {
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.25), W = canvas.clientWidth, H = canvas.clientHeight;
    // resizing a canvas reallocates it, so only do it when the rounded size really changes
    if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); }
    cx2.setTransform(dpr, 0, 0, dpr, 0, 0); cx2.clearRect(0, 0, W, H);
    const v = videoRect(), sans = fontVar('--sans', 'system-ui'), mono = fontVar('--mono', 'monospace'); boxes = [];
    for (const a of act) {
      const [x1, y1, x2, y2] = [v.x + a.row.nb[0] * v.w, v.y + a.row.nb[1] * v.h, v.x + a.row.nb[2] * v.w, v.y + a.row.nb[3] * v.h];
      const s = isSel(a.id), col = s ? '#8ab4ff' : RING[a.ring.state];
      cx2.save(); cx2.globalAlpha = a.alpha == null ? 1 : a.alpha;
      cx2.fillStyle = FILL[a.fill.state] || FILL.grey; cx2.fillRect(x1, y1, x2 - x1, y2 - y1);
      cx2.save(); if (s) { cx2.shadowColor = 'rgba(138,180,255,.7)'; cx2.shadowBlur = 10; }
      cx2.lineWidth = s ? 2.5 : 1.8; cx2.setLineDash(a.ring.state === 'amber' && !s ? [6, 4] : []);
      cx2.strokeStyle = col; cx2.beginPath(); cx2.roundRect(x1, y1, x2 - x1, y2 - y1, 3); cx2.stroke(); cx2.restore();
      const name = `${a.row.cls} #${a.id}`, meta = confTxt(a.row);
      cx2.font = `600 11.5px ${sans}`; const wn = cx2.measureText(name).width; cx2.font = `500 10.5px ${mono}`; const wm = cx2.measureText(meta).width;
      const w = wn + wm + 36, ly = y1 - 26 < 0 ? y2 + 4 : y1 - 26;
      cx2.fillStyle = 'rgba(16,19,25,.84)'; cx2.beginPath(); cx2.roundRect(x1, ly, w, 22, 11); cx2.fill();
      cx2.strokeStyle = s ? '#8ab4ff' : 'rgba(255,255,255,.14)'; cx2.lineWidth = 1; cx2.stroke();
      cx2.fillStyle = col; cx2.beginPath(); cx2.arc(x1 + 11, ly + 11, 3.5, 0, 7); cx2.fill();
      cx2.textBaseline = 'middle'; cx2.font = `600 11.5px ${sans}`; cx2.fillStyle = '#eef1f5'; cx2.fillText(name, x1 + 20, ly + 11.5);
      cx2.font = `500 10.5px ${mono}`; cx2.fillStyle = '#a6aeb8'; cx2.fillText(meta, x1 + 28 + wn, ly + 11.5);
      cx2.restore();
      boxes.push({ x1, y1, x2, y2, id: a.id, row: a.row });
    }
  }

  // ---- 2D plan (SVG) ----
  const VB = { w: 600, h: 400, cx: 300, cy: 372, R: 340 };
  const P = (ang, r) => C.polar(VB.cx, VB.cy, VB.R, ang, r);
  const half = C.ASSUMED_HFOV_DEG / 2;
  const T = (x, y, s, cls = 'sp-t', anchor) => S('text', { x, y, class: cls, 'text-anchor': anchor }, s);
  {
    const sector = (r) => { const [x1, y1] = P(-half, r), [x2, y2] = P(half, r); return `M${VB.cx},${VB.cy} L${x1},${y1} A${VB.R * r},${VB.R * r} 0 0 1 ${x2},${y2} Z`; };
    const g = S('g', {});
    g.append(S('defs', {}, S('pattern', { id: 'sp-hatch-' + uid, width: 7, height: 7, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, S('rect', { width: 7, height: 7, fill: '#111317' }), S('line', { x1: 0, y1: 0, x2: 0, y2: 7, stroke: '#1d2026', 'stroke-width': 2.4 }))),
      S('rect', { width: VB.w, height: VB.h, fill: `url(#sp-hatch-${uid})` }), S('path', { d: sector(1.0), class: 'sp-wedge' }),
      T(16, 46, 'NOT VISIBLE TO CAMERA'), T(VB.w - 16, 46, 'NOT VISIBLE TO CAMERA', 'sp-t', 'end'));
    for (const [r, name] of [[0.488, 'NEAR | MID'], [0.719, 'MID | FAR'], [0.95, 'FAR']]) {
      const [x1, y1] = P(-half, r), [x2, y2] = P(half, r);
      g.append(S('path', { d: `M${x1},${y1} A${VB.R * r},${VB.R * r} 0 0 1 ${x2},${y2}`, class: 'sp-arc' }), T(P(0, r)[0] + 6, P(0, r)[1] - 5, name));
    }
    for (const a of [0, -39, 39]) { const [x, y] = P(a, 1); g.append(S('line', { x1: VB.cx, y1: VB.cy, x2: x, y2: y, class: 'sp-ray' })); }
    g.append(S('polygon', { points: C.corridorPolygon().map((p) => P(p.ang, p.r).join(',')).join(' '), class: 'sp-corr' }),
      T(VB.cx, VB.cy - VB.R * 0.2, 'PROJECTED PATH · ASSUMED STRAIGHT', 'sp-t sp-corr-t', 'middle'),
      S('rect', { x: VB.cx - 9, y: VB.cy - 14, width: 18, height: 28, rx: 5, class: 'sp-ego' }), T(VB.cx, VB.cy + 24, 'EGO', 'sp-t', 'middle'));
    svg.append(g);
  }
  const dyn = S('g', {});
  svg.append(dyn);
  // the scene skips one- and two-sample blinks unless they carry risk, a label or the selection
  const inScene = (a) => sceneWorthy(a.row, { selected: isSel(a.id), riskAmber: C.THRESHOLDS.riskAmber,
    labelled: (t0, t1) => model.hazards.some((z) => z.track_id === a.id && z.window_start <= t1 && z.window_end >= t0) });
  function drawBird(all) {
    const act = all.filter(inScene);
    dyn.replaceChildren();
    if (!model || !model.trackRows.length) { dyn.append(T(VB.cx, 190, model ? 'No tracks for this clip. Run make track or merge origin/main.' : 'Loading tracks', 'sp-empty-t', 'middle')); return; }
    for (const a of [...act].sort((x, y) => isSel(x.id) - isSel(y.id))) {           // selected draws last
      const [x, y] = P(a.place.ang, a.place.r), s = isSel(a.id), d = motion(a.id);
      const grp = S('g', { class: 'sp-mark', opacity: a.alpha < 1 ? a.alpha.toFixed(2) : null, onclick: () => choose({ kind: 'track', id: a.id }, true) });
      if (d) { const L = 34, ex = x + d[0] * L, ey = y - d[1] * L; grp.append(S('line', { x1: x, y1: y, x2: ex, y2: ey, class: 'sp-arrow' }), S('circle', { cx: ex, cy: ey, r: 3, class: 'sp-arrow-h' })); }
      grp.append(S('circle', { cx: x, cy: y, r: s ? 14 : 11, fill: (FILL[a.fill.state] || FILL.grey).replace(/[\d.]+\)$/, '.85)'), stroke: s ? '#8ab4ff' : RING[a.ring.state], 'stroke-width': s ? 3.5 : 2.5, 'stroke-dasharray': a.ring.state === 'amber' && !s ? '5 4' : null }),
        T(x + 18, y + 4, `${a.row.cls} #${a.id}${a.band === 'uncertain' ? ' · range ?' : ''}`, 'sp-lab'));
      if (dbg) grp.append(S('title', {}, srcText(a.row)));
      dyn.append(grp);
    }
    if (act.length) dyn.append(T(VB.w - 16, VB.h - 14, 'ARROWS: OBSERVED PAST 1 S, NOT A FORECAST', 'sp-t', 'end'));
  }

  function push3D(env, objects, empty) {
    const key = empty + '|' + (env && env.kind) + '|' + objects.map((o) => [o.id, o.cls, o.heading ?? '', o.ang ?? '', o.r ?? '', Array.isArray(o.pos) ? o.pos.map((v) => Number(v).toFixed(2)).join(',') : '', (o.alpha ?? 1).toFixed(2), o.sel ? 1 : 0, o.hz, o.ring, o.motion ? o.motion.map((v) => Number(v).toFixed(2)).join(',') : ''].join(':')).join('|');
    if (key === last3d) return;
    last3d = key;
    v3.render({ env, objects, empty });
  }
  function seatBehind(p, cls, yaw) {
    const R = model.camera.rig, dims = metricDims(cls);
    if (!R || !dims) return p;
    const rx = p[0] - R.c[0], rz = p[1] - R.c[2], L = Math.hypot(rx, rz);
    if (L < 0.5) return p;
    const ux = rx / L, uz = rz / L, a = (yaw * Math.PI) / 180, rel = Math.abs(Math.sin(a) * ux + Math.cos(a) * uz);
    const depth = (rel * dims[1] + Math.sqrt(Math.max(0, 1 - rel * rel)) * dims[0]) / 2;
    return [p[0] + ux * depth, p[1] + uz * depth];
  }
  // ground distance from a track to the nearest other road user in view (fixed cameras; approximate)
  function nearestOther(id, g) {
    let best = null;
    for (const b of actives()) {
      const q = b.row.gs || b.row.g;
      if (b.id === id || !q) continue;
      const d = Math.hypot(q[0] - g[0], q[1] - g[1]);
      if (!best || d < best.d) best = { d, label: `${b.row.cls} #${b.id}` };
    }
    return best;
  }
  // ---- 3D ----
  // Positions and headings are precomputed per sample (stabilize.js) and interpolated here, so the
  // models glide with the video. Arrows are the observed past second; for a dashcam the camera's own
  // forward flow is estimated from static things beside the road and taken out; with none in view, no arrow.
  function draw3D(all) {
    const act = all.filter(inScene);
    const meta = (a) => confTxt(a.row) + (a.band === 'uncertain' && !fixed() ? ' · range ?' : '');
    if (fixed()) {
      const objects = [];
      const dash = model.camera.follow === 'video';
      for (const a of act) {
        const contact = a.row.gs || a.row.g;
        if (!contact) continue;                            // ray above the horizon: no ground position
        // the box bottom is the near edge the camera sees: seat the model behind it, along the view ray,
        // by half its footprint depth for its heading, so side-by-side cars do not overlap
        const pos = dash ? contact : seatBehind(contact, a.row.cls, a.row.yaw ?? 0);
        // dashcam: velocity over the past 0.6 s with the road's own flow taken out; wall camera: the past 1 s
        const step = dash ? a.row.wv : groundStep(a.id);
        const motion = step && Math.hypot(step[0], step[1]) > (dash ? 0.8 : 0.3) ? step : null;
        objects.push({ id: a.id, cls: a.row.cls, pos, heading: a.row.yaw ?? 0, alpha: a.alpha ?? 1, ring: RING[a.ring.state], amber: a.ring.state === 'amber', hz: a.fill.state,
          sel: isSel(a.id), motion, label: `${a.row.cls} #${a.id}`, meta: meta(a) });
      }
      push3D(model.camera, objects, model.trackRows.length ? '' : 'No tracks for this clip yet. Run make track, or merge origin/main.');
      return;
    }
    const objects = act.map((a) => {
      const d = motion(a.id);
      return { id: a.id, cls: a.row.cls, ang: a.place.ang, r: a.place.r, alpha: a.alpha ?? 1, ring: RING[a.ring.state], amber: a.ring.state === 'amber', hz: a.fill.state,
        sel: isSel(a.id), motion: d && [d[0] * 0.45, d[1] * 0.45], label: `${a.row.cls} #${a.id}`, meta: meta(a) };
    });
    push3D({ kind: 'dashcam' }, objects, !model ? 'Loading tracks' : model.trackRows.length ? '' : 'No tracks for this clip yet. Run make track, or merge origin/main.');
  }

  // ---- panels (rebuilt only when their key changes) ----
  const swatch = (a) => h('i', { class: 'sp-sw', style: a ? `border-color:${RING[a.ring.state]};border-style:${a.ring.state === 'amber' ? 'dashed' : 'solid'};background:${FILL[a.fill.state]}` : null });
  function drawOutliner(act) {
    const on = new Map(act.map((a) => [a.id, a])), o = v3.options;
    const key = [model ? model.tracks.size : -1, sel && sel.id, o.fov, o.path, o.scenery, fixed(), ...act.map((a) => `${a.id}${a.ring.state}${a.fill.state}${confTxt(a.row)}`)].join('|');
    if (!changed('out', key)) return;
    const row = (label, cls, fn, lead = null, meta = null, tail = null) => h('div', { class: 'sp-oi ' + cls, role: 'treeitem', tabindex: fn ? 0 : null, onclick: fn, onkeydown: fn ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); } } : null },
      lead, h('span', { class: 'sp-oi-l', text: label }), meta ? h('span', { class: 'sp-oi-m', text: meta }) : null, tail);
    const sw = (v) => h('span', { class: 'sp-eye' + (v ? ' on' : ''), role: 'switch', 'aria-checked': String(v) });
    const tog = (k) => () => { setPressed(togs[k], v3.toggle(k)); memo.out = null; sched(); };
    const kids = fixed()
      ? [row('Scene', 'root'), row(`Camera ${model.camera.camera_id || '(wall-mounted)'}`, 'l1 tog', () => { setMode('3d'); v3.setView('camera'); }, icon('camera'), `${model.camera.assumed ? '~' : ''}${model.camera.pose.height_m} m`),
        row('Visible ground', 'l1 tog', tog('fov'), icon('fov'), null, sw(o.fov)), row('Scenery', 'l1 tog', tog('scenery'), icon('scenery'), null, sw(o.scenery))]
      : [row('Scene', 'root'), row('Ego car', 'l1', null, icon('camera'), 'camera'), row(`FOV ${C.ASSUMED_HFOV_DEG}°`, 'l1 tog', tog('fov'), icon('fov'), null, sw(o.fov)), row('Projected path', 'l1 tog', tog('path'), icon('path'), null, sw(o.path))];
    kids.push(row('Tracks', 'root', null, null, model ? `${act.length} / ${model.tracks.size}` : '-'));
    if (model) for (const [id, rows] of model.tracks) {
      const a = on.get(id);
      kids.push(row(`${rows[0].cls} #${id}`, 'l2' + (isSel(id) ? ' sel' : '') + (a ? '' : ' dim'), () => choose({ kind: 'track', id }, true), swatch(a), a ? confTxt(a.row) : 'not seen'));
    }
    outliner.replaceChildren(...kids);
  }
  function drawStatus() {
    const c = v3.camera;
    stat.t.textContent = `${f2(t)} s`;
    stat.mode.textContent = fixed() ? (model.camera.follow === 'video' ? 'DASHCAM STREET' : 'WALL CAMERA') : mode === '3d' ? '3D' : 'PLAN';
    stat.cam.textContent = fixed() && c.view === 'camera' ? `camera view · yaw ${c.yaw}° · pitch ${c.pitch}°` : mode === '3d' || fixed() ? `${c.view} · yaw ${c.yaw}° · pitch ${c.pitch}° · ${c.ortho ? 'ortho' : 'persp'}` : 'top-down · ordinal';
    stat.sel.textContent = sel ? (sel.kind === 'track' ? `track #${sel.id}` : 'event') : 'no selection';
  }
  let sparkCursor = null, sparkX = null;
  function drawDetail(act) {
    const ok = sel && sel.kind === 'track' && model && model.tracks.has(sel.id);
    const a = ok ? act.find((x) => x.id === sel.id) : null;
    const key = ok ? [sel.id, a ? [a.ring.state, a.fill.state, a.band, a.row.t].join() : 'gone'].join('|') : `none${sel ? sel.id : ''}${!!model}`;
    if (sparkCursor && sparkX) sparkCursor.setAttribute('x1', sparkX(t)), sparkCursor.setAttribute('x2', sparkX(t));
    if (!changed('detail', key)) return;
    sparkCursor = sparkX = null;
    if (!ok) { detail.replaceChildren(h('div', { class: 'sp-empty', text: sel ? 'This event has no track. Pick a track in the viewport, outliner or video.' : 'Select a track in the viewport, outliner or video, or an event in the log.' })); return; }
    const rows = model.tracks.get(sel.id), r0 = rows[0], W = 300, H = 58, t0 = r0.t, t1 = rows[rows.length - 1].t;
    sparkX = (tt) => ((Math.min(t1, Math.max(t0, tt)) - t0) / Math.max(0.001, t1 - t0)) * W;
    sparkCursor = S('line', { x1: sparkX(t), x2: sparkX(t), y1: 0, y2: H, class: 'sp-cursor' });
    const r = a && a.row, tile = (label, value, unit = '') => h('div', { class: 'sp-tile' }, h('b', {}, value, unit ? h('small', { text: unit }) : null), h('span', { text: label }));
    let tiles = [];
    if (a) {
      tiles = [tile('Confidence', r.conf == null ? '?' : f2(r.conf)), tile(r.risk == null && r.risk_held != null ? 'Risk (held)' : 'Risk', r.risk == null ? (r.risk_held != null ? f2(r.risk_held) : '?') : f2(r.risk))];
      if (fixed()) {
        const m = groundMotion(rows, t), p = model.camera.pose;
        const gp = r.gs || r.g;
        const near = gp ? nearestOther(sel.id, gp) : null;
        tiles.push(tile('From camera', gp ? Math.hypot(gp[0] - p.x, gp[1] - p.z).toFixed(1) : '-', gp ? 'm' : ''), tile('Observed speed', m ? m.speed.toFixed(1) : '-', m ? 'm/s' : ''), tile(near ? `Nearest: ${near.label}` : 'Nearest road user', near ? near.d.toFixed(1) : '-', near ? 'm' : ''));
      } else tiles.push(tile('Range band', a.band), tile('Bearing', `${a.place.ang >= 0 ? '+' : ''}${a.place.ang.toFixed(0)}`, '°'));
    }
    const why = (c, label, text) => h('li', { style: `--c:${c}` }, h('span', {}, h('b', { text: label + ' ' }), text));
    const rk = rows.filter((q) => typeof q.risk === 'number');           // the tracker's own risk only
    const pts = (rk.length ? rk : [{ t: t0, risk: 0 }, { t: t1, risk: 0 }]).map((q) => `${sparkX(q.t).toFixed(1)},${(H - q.risk * H).toFixed(1)}`);
    detail.replaceChildren(
      h('div', { class: 'sp-dt' }, h('h3', {}, r0.cls, h('small', { text: `#${sel.id}` })),
        a ? h('span', { class: 'sp-pill', style: `--c:${RING[a.ring.state]}`, text: a.ring.state === 'green' ? 'well observed' : 'poorly observed' }) : null,
        a ? h('span', { class: 'sp-pill', style: `--c:${HZC[a.fill.state]}`, text: a.fill.state === 'red' ? 'hazard' : a.fill.state === 'amber' ? 'watch' : 'calm' }) : null),
      a ? h('div', { class: 'sp-tiles' }, tiles) : null,
      h('ul', { class: 'sp-why' },
        a ? [why(RING[a.ring.state], 'Outline', a.ring.state === 'green' ? 'confidence ≥ 0.6 and seen in ≥ 5 samples' : a.ring.why.join('; ')),
          why(HZC[a.fill.state], 'Fill', a.fill.why.length ? a.fill.why.join('; ') : 'risk below 0.4'),
          fixed() && (r.gs || r.g) ? why('#8ab4ff', 'Ground', `${(r.gs || r.g)[0].toFixed(1)}, ${(r.gs || r.g)[1].toFixed(1)} m ${model.camera.follow === 'video' ? 'from box size for a typical ' + r.cls : 'from the calibration (flat ground)'}; smoothed over ±0.4 s of observed samples, approximate`) : null,
          r.fill ? why('#646c77', 'Source', r.fill === 'det' ? 'detector box: the tracker did not rank this object at this time' : 'bridged between two tracker samples less than 1 s apart') : null]
          : why('#646c77', 'Now', 'no sample at this time: dropped out or not yet seen'),
        why('#646c77', 'Samples', `${rows.length} between ${f2(t0)} and ${f2(t1)} s (${rk.length} ranked by the tracker)`)),
      h('div', { class: 'sp-spark-h' }, h('span', { text: rk.length ? 'Risk over time' : 'Risk over time: not in the tracks file' }), h('span', { text: `threshold ${C.THRESHOLDS.riskRed}` })),
      S('svg', { viewBox: `0 0 ${W} ${H}`, class: 'sp-spark', preserveAspectRatio: 'none', role: 'img', 'aria-label': `Risk of ${r0.cls} ${sel.id} over time` },
        S('defs', {}, S('linearGradient', { id: 'sp-grad-' + uid, x1: 0, y1: 0, x2: 0, y2: 1 }, S('stop', { offset: '0', 'stop-color': '#e3a008', 'stop-opacity': '.35' }), S('stop', { offset: '1', 'stop-color': '#e3a008', 'stop-opacity': '0' }))),
        S('path', { d: `M${pts[0].split(',')[0]},${H} L${pts.join(' L')} L${pts[pts.length - 1].split(',')[0]},${H} Z`, fill: `url(#sp-grad-${uid})` }),
        S('line', { x1: 0, x2: W, y1: H * 0.4, y2: H * 0.4, class: 'sp-thr' }), S('polyline', { points: pts.join(' '), class: 'sp-line' }), sparkCursor));
  }

  function drawChips() {
    const n = (p) => events.filter((e) => e.prov === p).length;
    chips.replaceChildren(...Object.keys(PROV).map((p) => h('button', { type: 'button', class: 'sp-chip' + (off.has(p) ? ' off' : ''), style: `--c:${PROV[p]}`, 'aria-pressed': String(!off.has(p)), title: `Show or hide ${p.toLowerCase()} events`,
      onclick: () => { off.has(p) ? off.delete(p) : off.add(p); drawChips(); drawEvents(); } }, h('span', { class: 'lbl', text: p }), model ? h('span', { class: 'sp-n', text: n(p) }) : null)));
  }
  function drawEvents() {
    if (!model) return;
    const vis = events.filter((e) => !off.has(e.prov));
    const anyInput = model.trackRows.length || model.hazards.length || model.grid.length || (model.status.run && model.status.run.state === 'ok');
    if (!vis.length) { list.replaceChildren(h('li', { class: 'sp-empty', text: events.length ? 'Every provenance is filtered out. Turn a filter back on above.' : anyInput ? `No events: no track crossed risk ${C.THRESHOLDS.riskRed}, and there are no labels, Cosmos verdicts or agent clicks for this clip.` : 'No events: tracks, labels, grid and run results are all missing. See the inputs above.' })); return; }
    list.replaceChildren(...vis.map((e) => h('li', { class: 'sp-ev', 'data-id': e.id, tabindex: 0, title: dbg ? `${e.src.file} line ${e.src.line}` : null,
      onclick: () => choose({ kind: 'event', id: e.id, track: e.track_id }, true), onkeydown: (k) => { if (k.key === 'Enter') choose({ kind: 'event', id: e.id, track: e.track_id }, true); } },
      h('span', { class: 'sp-time', text: f2(e.t) }), h('span', { class: 'sp-badge', style: `--c:${PROV[e.prov]}`, text: e.prov }), h('span', { class: 'sp-et', text: e.title }), h('div', { class: 'sp-ewhy', text: e.why }))));
    markCurrent(true); markSelected(false);
  }
  function markCurrent(force) {
    let lo = 0, hi = events.length - 1, c = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (events[m].t <= t + 1e-6) { c = m; lo = m + 1; } else hi = m - 1; }
    if (c === cur && !force) return; cur = c;
    const id = c >= 0 ? events[c].id : null;
    for (const li of list.children) li.classList.toggle('now', li.dataset.id === id);
  }
  function markSelected(scroll = true) {
    let first = null;
    for (const li of list.children) {
      const e = events.find((x) => x.id === li.dataset.id); if (!e) continue;
      const on = !!sel && ((sel.kind === 'event' && sel.id === e.id) || (sel.kind === 'track' && e.track_id === sel.id) || sel.event === e.id);
      li.classList.toggle('sel', on); if (on && !first) first = li;
    }
    if (scroll && first) first.scrollIntoView({ block: 'nearest', behavior: reduced() ? 'auto' : 'smooth' });
  }

  // The overlay and the 3D view follow every video frame. The 3D scene is only skipped a frame when its last
  // draw took longer than a frame budget, so a slow machine degrades smoothly instead of stuttering.
  let drawn3 = -1, cost3 = 0, clock = 0;
  function render(ts) {
    raf = 0; if (dead) return;
    const act = actives();
    drawOverlay(act);
    const now = ts || performance.now();
    if (mode === '2d' && !fixed()) drawBird(act);
    else if (now - drawn3 >= Math.min(80, Math.max(0, cost3 * 1.5))) { const a = performance.now(); draw3D(act); v3.flush(); cost3 = cost3 * 0.8 + (performance.now() - a) * 0.2; drawn3 = now; }
    else sched();                                          // skipped: come back next frame
    drawDetail(act); drawOutliner(act); drawStatus(); if (model) markCurrent();
  }
  const sched = () => { if (!raf) raf = requestAnimationFrame(render); };
  // A host can hand over its clock: the panel then reads it every frame while the video plays, so it can
  // never fall behind a host that misses a timeupdate (for example after a segment swap).
  function tick() {
    clock = 0; if (dead) return;
    const v = liveVideo();
    try { const tt = ctx.getClipTime(); if (Number.isFinite(tt) && tt !== t) { t = tt; sched(); } } catch { /* host not ready */ }
    if (v && !v.paused && !v.ended) clock = requestAnimationFrame(tick);
  }
  const wake = () => { if (!clock && !dead && typeof ctx.getClipTime === 'function') clock = requestAnimationFrame(tick); };
  const wakeEvents = ['play', 'playing', 'seeked', 'timeupdate', 'loadeddata'];
  if (vHost && typeof ctx.getClipTime === 'function') { for (const e of wakeEvents) vHost.addEventListener(e, wake, true); wake(); }
  if (document.fonts) document.fonts.ready.then(() => { v3.redraw(); sched(); });

  // ---- selection (two-way) ----
  function choose(s, user) {
    sel = s;
    if (user && s.kind === 'event') {
      const e = events.find((x) => x.id === s.id);
      if (e) { if (e.track_id != null) sel = { kind: 'track', id: e.track_id, event: e.id }; ctx.onSeek && ctx.onSeek(C.seekTime(e)); }
    }
    drawn3 = -1; markSelected(); sched();
    if (user && ctx.onSelect) ctx.onSelect(s.kind === 'event' ? { kind: 'event', id: s.id, t } : { kind: 'track', id: s.id, t });
  }
  // keys: V plan/3D, C camera view, O ortho, F frame, [ ] events, Esc clear. P and Space stay free for the host (SPEC 16.1).
  const onKey = (ev) => {
    if (ev.target && /input|textarea|select/i.test(ev.target.tagName) || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key === 'Escape') { sel = null; markSelected(); sched(); return; }
    const k = ev.key.toLowerCase();
    if (k === 'v') { setMode(mode === '3d' ? '2d' : '3d'); return; }
    if (k === 'c' && fixed()) { setMode('3d'); v3.setView('camera'); return; }
    if (k === 'o' && (mode === '3d' || fixed())) { setPressed(orthoBtn, v3.setOrtho()); return; }
    if (k === 'f' && (mode === '3d' || fixed())) { v3.frame(); return; }
    if (ev.key !== '[' && ev.key !== ']') return;
    const vis = events.filter((e) => !off.has(e.prov)); if (!vis.length) return;
    const next = ev.key === ']' ? vis.find((e) => e.t > t + 0.05) || vis[vis.length - 1] : [...vis].reverse().find((e) => e.t < t - 0.05) || vis[0];
    choose({ kind: 'event', id: next.id, track: next.track_id }, true);
  };
  document.addEventListener('keydown', onKey);

  // ---- load ----
  async function load() {
    drawChips();
    const m = await loadModel({ clipId: ctx.clipId, api: ctx.api, frame, mode: ctx.mode || 'app', runId: ctx.runId || null });
    if (dead) return;
    model = m;
    // a run that did not click still says why (the run row's explanation): one AGENT event at the clip end
    const end = m.clip ? Number(m.clip.duration_s || m.clip.segments.at(-1).end_s) || 0 : 0;
    const quiet = m.runExplanation && !m.clicks.length && m.status.run && m.status.run.state === 'ok'
      ? [{ t: end, prov: 'AGENT', track_id: null, src: { file: 'run', line: null }, title: 'Agent did not click', why: m.runExplanation }] : [];
    events = C.buildEvents({ tracks: m.ranked, hazards: m.hazards, clicks: m.clicks, grid: m.grid, explain: m.explain, extra: [...quiet, ...(m.camera.kind === 'fixed' && m.camera.follow !== 'video' ? proximityEvents(m.ranked) : [])], egoPath: m.camera.kind !== 'fixed' || m.camera.follow === 'video' });
    sources.replaceChildren(...Object.entries(m.status).map(([k, v]) => h('span', { class: 'sp-in ' + STATE_CLS[v.state], role: 'listitem', title: `${k}: ${v.detail}` }, h('i'), k)));
    const notes = Object.entries(m.status).filter(([, v]) => v.state !== 'ok' && v.state !== 'optional');
    note.hidden = !notes.length;
    note.replaceChildren(...notes.slice(0, 3).map(([k, v]) => h('div', {}, h('b', { text: k }), v.detail)), ...(notes.length > 3 ? [h('div', { class: 'sp-muted', text: `+${notes.length - 3} more: hover the input chips above` })] : []));
    for (const k in memo) memo[k] = null;
    last3d = '';
    if (fixed()) {
      if (m.camera.follow === 'video') {
        vpTag.textContent = 'Metres · from box size, approximate';
        disc.textContent = 'Dashcam, one camera, no depth sensor. Range is guessed from how big each box is for a typical object of its class, smoothed over ±0.4 s of observed samples. Positions are approximate.';
      } else {
        vpTag.textContent = m.camera.assumed ? 'Metres · assumed camera pose, rough' : m.camera.auto ? 'Metres · auto-calibrated, approximate' : 'Metres · from calibration, approximate';
        disc.textContent = 'One fixed camera (wall, house or pole), flat ground assumed. Positions approximate, smoothed over ±0.4 s of observed samples; vehicle sizes are typical, not measured.';
      }
    } else {
      disc.textContent = 'Approximate positions from a single camera, no depth sensor. Range bands are ordinal, not distances. Positions smoothed over ±0.4 s of observed samples.';
    }
    setMode(mode);
    drawChips(); drawEvents(); sched();
    ctx.onLoaded && ctx.onLoaded(m);
  }
  setMode(mode);
  load();

  return {
    setTime(tt) { if (tt !== t) { t = tt; sched(); } },
    setMode,
    select(s) { choose(s, false); },
    // the played video's size only changes how the overlay is letterboxed; boxes stay in the detector's frame
    setFrame(f) { if (f && f.w && f.h && (f.w !== frame.w || f.h !== frame.h)) { frame = { w: f.w, h: f.h }; sched(); } },
    get model() { return model; },
    destroy() {
      dead = true; cancelAnimationFrame(raf); cancelAnimationFrame(clock); document.removeEventListener('keydown', onKey); el.removeEventListener('pointerdown', ripple); legendFit.disconnect();
      if (vHost) { vHost.removeEventListener('click', onHostClick, true); vHost.removeEventListener('mousemove', onHostMove); for (const e of wakeEvents) vHost.removeEventListener(e, wake, true); vHost.style.cursor = ''; }
      if (canvas) canvas.remove(); v3.destroy(); el.replaceChildren();
    },
  };
}
