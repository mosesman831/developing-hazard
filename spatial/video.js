// Two-<video> segment player (6 x 5 s segments) or one local mp4. Emits clip time = segment start + mediaTime.
export function createPlayer(box, { onTime = () => {}, onError = () => {}, onMeta = () => {} } = {}) {
  box.classList.add('sp-video');
  const vids = [0, 1].map(() => { const v = document.createElement('video'); v.muted = true; v.playsInline = true; v.preload = 'auto'; box.appendChild(v); return v; });
  let cur = 0, segs = [], idx = 0, want = null;
  const act = () => vids[cur];
  const show = () => vids.forEach((v, i) => { v.style.visibility = i === cur ? 'visible' : 'hidden'; });
  const clipT = () => (segs[idx] ? segs[idx].start : 0) + act().currentTime;
  const emit = () => onTime(clipT());
  const bind = (v, i) => {
    v.addEventListener('error', () => { if (i === cur) onError(`video error (segment ${idx + 1}): ${(v.error && v.error.message) || 'cannot load ' + (v.currentSrc || 'source')}`); });
    v.addEventListener('loadedmetadata', () => { if (i === cur) { onMeta({ w: v.videoWidth, h: v.videoHeight }); if (want != null) { v.currentTime = want; want = null; } } });
    v.addEventListener('timeupdate', () => { if (i === cur) emit(); });
    v.addEventListener('seeked', () => { if (i === cur) emit(); });
    v.addEventListener('ended', () => { if (i === cur && idx + 1 < segs.length) { idx++; cur = 1 - cur; show(); act().play().catch(() => {}); preload(idx + 1); } });
    if ('requestVideoFrameCallback' in v) { const loop = () => { if (i === cur) emit(); v.requestVideoFrameCallback(loop); }; v.requestVideoFrameCallback(loop); }
  };
  vids.forEach(bind);
  function preload(i) { if (segs[i]) { const o = vids[1 - cur]; o.src = segs[i].url; o.load(); } }
  function goto(i, t) {
    idx = i; want = t; const v = act(); v.src = segs[i].url; v.load(); preload(i + 1);
  }
  show();
  return {
    el: box,
    video: act,
    // segs: [{url, start, end}]; a single local file is one segment from 0.
    loadSegments(list) { segs = list; if (segs.length) goto(0, 0); },
    loadFile(file) { segs = [{ url: URL.createObjectURL(file), start: 0, end: Infinity }]; goto(0, 0); },
    seek(t) {
      const i = segs.findIndex((s) => t >= s.start && t < s.end);
      if (i < 0) return;
      if (i === idx && act().src) act().currentTime = t - segs[i].start; else goto(i, t - segs[i].start);
    },
    toggle() { const v = act(); v.paused ? v.play().catch(() => {}) : v.pause(); },
    get time() { return clipT(); },
    get loaded() { return segs.length > 0; },
  };
}
// Build segment urls from a clip. Relative URL via the app's /video?source= proxy (SPEC 11.1).
export function segmentUrls(clip, base = 'video?source=') {
  return (clip.segments || []).map((s) => ({ url: base + encodeURIComponent(s.source), start: s.start_s, end: s.end_s }));
}
