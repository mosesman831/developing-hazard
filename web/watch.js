/**
 * Watch screen v0. Boxes, windows, clicks and score come from recorded files.
 */

import { mountPlayer } from "./player.js";

/**
 * @param {HTMLElement} el
 * @param {string} runId
 * @param {string} clipId
 * @param {{ getClip?: Function, videoUrl?: Function }} api
 */
export function mountWatch(el, runId, clipId, api = {}) {
  el.replaceChildren();
  const videoUrl =
    typeof api.videoUrl === "function"
      ? api.videoUrl
      : (source) => `video?source=${encodeURIComponent(source)}`;

  const shell = document.createElement("section");
  shell.className = "watch";
  const title = document.createElement("h1");
  title.textContent = `Watch ${runId}`;
  const note = document.createElement("p");
  note.className = "muted";
  note.textContent = "Recorded run, replayed.";
  const layout = document.createElement("div");
  layout.className = "watch-layout";
  const stage = document.createElement("div");
  stage.className = "watch-stage";
  const side = document.createElement("aside");
  side.className = "watch-side";
  layout.append(stage, side);
  shell.append(title, note, layout);
  el.append(shell);

  const scoreEl = document.createElement("p");
  scoreEl.className = "score";
  scoreEl.textContent = "-";
  const feed = document.createElement("ol");
  feed.className = "event-feed";
  const meter = document.createElement("div");
  meter.className = "risk-meter";
  meter.textContent = "risk -";
  side.append(scoreEl, meter, feed);

  Promise.all([loadRun(runId), loadClip(clipId, api), loadTracks(clipId)])
    .then(([run, clip, tracks]) => {
      const row = (run.clips || []).find((item) => item.clip_id === clipId) || null;
      scoreEl.textContent = row ? String(row.clip_score) : "-";
      paintFeed(feed, row);
      paintRisk(meter, row);
      const host = document.createElement("div");
      host.className = "watch-player";
      const canvas = document.createElement("canvas");
      canvas.className = "box-overlay";
      stage.append(host, canvas, timeline(clip, row));
      if (!clip || !clip.segments) {
        host.textContent = `Clip ${clipId} is not in the clip list.`;
        return;
      }
      const player = mountPlayer(host, {
        segments: clip.segments,
        resolveVideoUrl: videoUrl,
        controls: true,
        autoplay: false,
        playOnce: true,
      });
      const video = player.getActiveVideo ? player.getActiveVideo() : null;
      if (video) {
        const draw = () => paintBoxes(canvas, video, tracks, player.getClipTime());
        video.addEventListener("timeupdate", draw);
        if (typeof video.requestVideoFrameCallback === "function") {
          const tick = () => {
            draw();
            video.requestVideoFrameCallback(tick);
          };
          video.requestVideoFrameCallback(tick);
        }
      }
      if (!tracks.length) {
        const empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "No tracks recorded for this clip.";
        stage.append(empty);
      }
    })
    .catch(() => {
      stage.textContent = "Run could not be loaded.";
    });
}

async function loadRun(runId) {
  const response = await fetch(`api/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) {
    throw new Error(String(response.status));
  }
  return response.json();
}

async function loadClip(clipId, api) {
  try {
    if (typeof api.getClip === "function") {
      return await api.getClip(clipId, { blind: false });
    }
    const response = await fetch(`api/clips/${encodeURIComponent(clipId)}`);
    if (!response.ok) {
      return null;
    }
    return response.json();
  } catch {
    return null;
  }
}

async function loadTracks(clipId) {
  try {
    const response = await fetch(`api/clips/${encodeURIComponent(clipId)}/tracks`);
    if (!response.ok) {
      return [];
    }
    const body = await response.json();
    return Array.isArray(body) ? body : [];
  } catch {
    return [];
  }
}

function paintFeed(list, row) {
  list.replaceChildren();
  if (!row) {
    const item = document.createElement("li");
    item.textContent = "No clip result in this run.";
    list.append(item);
    return;
  }
  const events = [];
  for (const click of row.clicks || []) {
    const t = typeof click === "number" ? click : click.t;
    events.push({ t, text: `${formatTime(t)} CLICK` });
  }
  for (const call of row.calls || []) {
    events.push({
      t: call.t_sent,
      text: `${formatTime(call.t_sent)} ${call.kind || "call"} ${call.verdict || ""}`.trim(),
    });
  }
  events.sort((a, b) => (b.t || 0) - (a.t || 0));
  if (!events.length) {
    const item = document.createElement("li");
    item.textContent = "No clicks in this run.";
    list.append(item);
    return;
  }
  for (const event of events) {
    const item = document.createElement("li");
    item.className = "mono";
    item.textContent = event.text;
    list.append(item);
  }
}

function paintRisk(meter, row) {
  const curve = row && Array.isArray(row.risk_curve) ? row.risk_curve : [];
  const last = curve.length ? curve[curve.length - 1] : null;
  const value = last && last.length > 1 ? last[1] : null;
  meter.textContent = value == null ? "risk -" : `risk ${Number(value).toFixed(2)}`;
}

function timeline(clip, row) {
  const bar = document.createElement("div");
  bar.className = "timeline-bar";
  const duration = clip && clip.duration_s ? clip.duration_s : 30;
  for (const hazard of (clip && clip.hazards) || []) {
    const band = document.createElement("span");
    band.className = "window-band";
    band.style.left = `${(hazard.window_start / duration) * 100}%`;
    band.style.width = `${((hazard.window_end - hazard.window_start) / duration) * 100}%`;
    bar.append(band);
  }
  for (const click of (row && row.clicks) || []) {
    const t = typeof click === "number" ? click : click.t;
    const flag = document.createElement("span");
    flag.className = "flag agent";
    flag.style.left = `${(t / duration) * 100}%`;
    bar.append(flag);
  }
  return bar;
}

function paintBoxes(canvas, video, tracks, clipTime) {
  const width = video.clientWidth;
  const height = video.clientHeight;
  if (!width || !height) {
    return;
  }
  canvas.width = width;
  canvas.height = height;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }
  context.clearRect(0, 0, width, height);
  const nativeW = video.videoWidth || width;
  const nativeH = video.videoHeight || height;
  const scaleX = width / nativeW;
  const scaleY = height / nativeH;
  const nearest = nearestTracks(tracks, clipTime);
  for (const track of nearest) {
    const box = track.xyxy;
    if (!box || box.length < 4) {
      continue;
    }
    context.strokeStyle = track.track_id != null ? "#22d3ee" : "#f5a524";
    context.lineWidth = 2;
    context.strokeRect(
      box[0] * scaleX,
      box[1] * scaleY,
      (box[2] - box[0]) * scaleX,
      (box[3] - box[1]) * scaleY,
    );
  }
}

function nearestTracks(tracks, clipTime) {
  if (!tracks.length || clipTime == null) {
    return [];
  }
  let best = tracks[0].t;
  let bestGap = Infinity;
  for (const track of tracks) {
    const gap = Math.abs(track.t - clipTime);
    if (gap < bestGap) {
      bestGap = gap;
      best = track.t;
    }
  }
  if (bestGap > 0.3) {
    return [];
  }
  return tracks.filter((track) => track.t === best).slice(0, 3);
}

function formatTime(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "-";
  }
  return `${Number(value).toFixed(2)}s`;
}
