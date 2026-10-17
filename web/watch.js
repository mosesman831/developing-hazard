/**
 * Watch screen. Recorded runs only: boxes, windows, clicks, score, risk.
 */

import { mountPlayer } from "./player.js";

const AGENT_TABS = [
  { id: "naive", label: "naive", test: (agent) => /naive/i.test(agent) },
  {
    id: "risk",
    label: "risk",
    test: (agent) => /risk/i.test(agent) && !/gate|async|cosmos/i.test(agent),
  },
  { id: "gate", label: "gate", test: (agent) => /gate/i.test(agent) },
  { id: "async", label: "async", test: (agent) => /async/i.test(agent) },
  { id: "vlm", label: "vlm", test: (agent) => /vlm/i.test(agent) },
];

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
  title.textContent = `Watch ${clipId}`;
  const note = document.createElement("p");
  note.className = "muted";
  note.textContent = "Recorded run, replayed.";
  const tabs = document.createElement("div");
  tabs.className = "agent-tabs";
  tabs.setAttribute("role", "tablist");
  const layout = document.createElement("div");
  layout.className = "watch-layout";
  const stage = document.createElement("div");
  stage.className = "watch-stage";
  const side = document.createElement("aside");
  side.className = "watch-side";
  layout.append(stage, side);
  shell.append(title, note, tabs, layout);
  el.append(shell);

  const scoreEl = document.createElement("p");
  scoreEl.className = "score";
  scoreEl.textContent = "-";
  const meterWrap = document.createElement("div");
  meterWrap.className = "risk-wrap";
  const meter = document.createElement("div");
  meter.className = "risk-meter";
  const fill = document.createElement("div");
  fill.className = "risk-fill";
  meter.append(fill);
  const readout = document.createElement("span");
  readout.className = "mono risk-readout";
  readout.textContent = "risk -";
  meterWrap.append(meter, readout);
  const weave = document.createElement("p");
  weave.className = "weave-link";
  const feed = document.createElement("ol");
  feed.className = "event-feed";
  const misses = document.createElement("section");
  misses.className = "miss-panel";
  side.append(scoreEl, meterWrap, weave, feed, misses);

  const state = {
    player: null,
    clip: null,
    tracks: [],
    runs: [],
    activeId: runId,
    row: null,
    run: null,
  };

  function riskAt(clipTime) {
    const curve = state.row && Array.isArray(state.row.risk_curve) ? state.row.risk_curve : [];
    let value = null;
    for (const point of curve) {
      if (!point || point.length < 2) {
        continue;
      }
      if (clipTime == null || Number(point[0]) <= clipTime) {
        value = Number(point[1]);
      }
    }
    return value;
  }

  function paintLive() {
    const clipTime = state.player && typeof state.player.getClipTime === "function" ? state.player.getClipTime() : null;
    const value = riskAt(clipTime);
    const height = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;
    fill.style.height = `${height}%`;
    readout.textContent = value == null ? "risk -" : `risk ${value.toFixed(2)}`;
    paintCurve(stage.querySelector(".risk-curve"), state.row, clipTime, state.clip);
    const video = state.player && state.player.getActiveVideo ? state.player.getActiveVideo() : null;
    const canvas = stage.querySelector(".box-overlay");
    if (video && canvas) {
      paintBoxes(canvas, video, state.tracks, clipTime);
    }
  }

  function showRun(nextRunId) {
    const run = state.runs.find((item) => item.run_id === nextRunId) || null;
    state.activeId = nextRunId;
    state.run = run;
    state.row = run ? (run.clips || []).find((item) => item.clip_id === clipId) || null : null;
    scoreEl.textContent = state.row ? String(state.row.clip_score) : "-";
    paintMiss(misses, state.row, nextRunId);
    paintFeed(feed, state.row, run);
    paintWeave(weave, state.row, run);
    const existing = stage.querySelector(".timeline-bar");
    const nextBar = timeline(state.clip, state.row);
    if (existing) {
      existing.replaceWith(nextBar);
    }
    for (const button of tabs.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", button.dataset.runId === nextRunId ? "true" : "false");
    }
    if (nextRunId && nextRunId !== runId) {
      const nextHash = `#/watch/${encodeURIComponent(nextRunId)}/${encodeURIComponent(clipId)}`;
      if (location.hash !== nextHash) {
        history.replaceState(null, "", nextHash);
      }
    }
    paintLive();
  }

  Promise.all([loadRuns(clipId), loadClip(clipId, api), loadTracks(clipId)])
    .then(([runs, clip, tracks]) => {
      state.runs = runs;
      state.clip = clip;
      state.tracks = tracks;
      paintTabs(tabs, runs, runId, clipId, showRun);
      const host = document.createElement("div");
      host.className = "watch-player";
      const canvas = document.createElement("canvas");
      canvas.className = "box-overlay";
      const curve = document.createElement("svg");
      curve.className = "risk-curve";
      curve.setAttribute("viewBox", "0 0 100 40");
      curve.setAttribute("aria-label", "risk curve");
      stage.append(host, canvas, curve);
      if (!clip || !clip.segments) {
        host.textContent = `Clip ${clipId} is not in the clip list.`;
      } else {
        state.player = mountPlayer(host, {
          segments: clip.segments,
          resolveVideoUrl: videoUrl,
          controls: true,
          autoplay: false,
          playOnce: true,
        });
        const video = state.player.getActiveVideo ? state.player.getActiveVideo() : null;
        if (video) {
          video.addEventListener("timeupdate", paintLive);
          if (typeof video.requestVideoFrameCallback === "function") {
            const tick = () => {
              paintLive();
              video.requestVideoFrameCallback(tick);
            };
            video.requestVideoFrameCallback(tick);
          }
        }
      }
      stage.append(timeline(clip, null));
      if (!tracks.length) {
        const empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "No tracks recorded for this clip.";
        stage.append(empty);
      }
      const initial = runs.some((item) => item.run_id === runId) ? runId : (runs[0] && runs[0].run_id) || runId;
      showRun(initial);
    })
    .catch(() => {
      stage.textContent = "Run could not be loaded.";
    });
}

function paintTabs(tabs, runs, currentId, clipId, onPick) {
  tabs.replaceChildren();
  const used = new Set();
  const buttons = [];
  for (const tab of AGENT_TABS) {
    const match = runs.find((run) => tab.test(String(run.agent || "")) && !used.has(run.run_id));
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = tab.label;
    button.dataset.runId = match ? match.run_id : "";
    if (!match) {
      button.disabled = true;
      button.title = `No recorded ${tab.label} run for ${clipId}`;
    } else {
      used.add(match.run_id);
      button.addEventListener("click", () => onPick(match.run_id));
    }
    buttons.push(button);
  }
  for (const run of runs) {
    if (used.has(run.run_id)) {
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = run.agent || run.run_id;
    button.dataset.runId = run.run_id;
    button.addEventListener("click", () => onPick(run.run_id));
    buttons.push(button);
  }
  if (!buttons.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No recorded runs.";
    tabs.append(empty);
    return;
  }
  for (const button of buttons) {
    button.setAttribute("aria-pressed", button.dataset.runId === currentId ? "true" : "false");
    tabs.append(button);
  }
}

async function loadRuns(clipId) {
  const response = await fetch("api/runs");
  if (!response.ok) {
    throw new Error(String(response.status));
  }
  const listed = await response.json();
  if (!Array.isArray(listed)) {
    return [];
  }
  const details = await Promise.all(
    listed
      .filter((run) => run && run.run_id)
      .map(async (run) => {
        const detail = await fetch(`api/runs/${encodeURIComponent(run.run_id)}`);
        if (!detail.ok) {
          return null;
        }
        const body = await detail.json();
        const clips = body.clips || [];
        if (clipId && !clips.some((item) => item.clip_id === clipId)) {
          return null;
        }
        return body;
      }),
  );
  return details.filter(Boolean);
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

function paintMiss(host, row, runId) {
  host.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = "Misses";
  host.append(heading);
  const points = row && row.hazard_points && typeof row.hazard_points === "object" ? row.hazard_points : {};
  const ids = Object.keys(points).filter((id) => points[id] === 0 || points[id] === 1);
  if (!ids.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No hazard scored 0 or 1 on this clip.";
    host.append(empty);
    return;
  }
  for (const id of ids) {
    const item = document.createElement("p");
    item.textContent = `${id}: ${points[id]} points.`;
    host.append(item);
    fetch(`api/explain/${encodeURIComponent(runId)}/${encodeURIComponent(id)}`, { method: "POST" })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        const line = document.createElement("p");
        line.className = "muted";
        line.textContent =
          body && typeof body.explanation === "string" ? body.explanation : "Not approved for display.";
        item.append(line);
      })
      .catch(() => {
        const line = document.createElement("p");
        line.className = "muted";
        line.textContent = "Not approved for display.";
        item.append(line);
      });
  }
}

function paintFeed(list, row, run) {
  list.replaceChildren();
  if (!row) {
    const item = document.createElement("li");
    item.textContent = "No clip result in this run.";
    list.append(item);
    return;
  }
  const events = [];
  const curve = Array.isArray(row.risk_curve) ? row.risk_curve : [];
  const last = curve.length ? curve[curve.length - 1] : null;
  if (last && last.length > 1) {
    events.push({ t: Number(last[0]), text: `${formatTime(last[0])} risk ${Number(last[1]).toFixed(2)}` });
  }
  for (const click of row.clicks || []) {
    const t = typeof click === "number" ? click : click.t;
    const reason = click && typeof click.reason === "string" && click.reason ? ` ${click.reason}` : "";
    events.push({ t, text: `${formatTime(t)} CLICK${reason}` });
  }
  for (const call of row.calls || []) {
    const kind = call.kind || "call";
    events.push({ t: call.t_sent, text: `${formatTime(call.t_sent)} asking ${kind}...`, call });
    const latency = Number(call.latency_s);
    const doneAt = Number(call.t_sent) + (Number.isNaN(latency) ? 0 : latency);
    const verdict = call.verdict || "no verdict";
    const latencyText = Number.isNaN(latency) ? "" : ` (${latency.toFixed(2)}s)`;
    events.push({
      t: doneAt,
      text: `${formatTime(doneAt)} ${kind}${latencyText}: ${verdict}`,
      call,
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
    if (event.call && (event.call.kind === "cosmos" || event.call.kind === "vlm" || event.call.kind === "llm")) {
      item.append(document.createTextNode(" "));
      item.append(weaveAnchor(event.call.weave_url || (run && run.weave_url) || ""));
    }
    list.append(item);
  }
}

function paintWeave(host, row, run) {
  host.replaceChildren();
  const calls = (row && row.calls) || [];
  const cosmos = calls.filter((call) => call && (call.kind === "cosmos" || call.kind === "vlm" || call.kind === "llm"));
  if (!cosmos.length) {
    const href = weaveHref(run && run.weave_url);
    if (href) {
      host.append(weaveAnchor(href));
    } else {
      host.className = "weave-link muted";
      host.textContent = "No Weave trace for this run.";
    }
    return;
  }
  host.className = "weave-link";
  host.textContent = "";
}

function weaveAnchor(value) {
  const href = weaveHref(value);
  if (!href) {
    const span = document.createElement("span");
    span.className = "muted";
    span.textContent = "No Weave URL on this call.";
    return span;
  }
  const link = document.createElement("a");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "Open in Weave";
  return link;
}

function weaveHref(value) {
  if (typeof value !== "string") {
    return "";
  }
  if (value.startsWith("https://") || value.startsWith("http://")) {
    return value;
  }
  return "";
}

function paintCurve(svg, row, clipTime, clip) {
  if (!svg) {
    return;
  }
  const curve = row && Array.isArray(row.risk_curve) ? row.risk_curve : [];
  const duration = clip && clip.duration_s ? Number(clip.duration_s) : 30;
  svg.replaceChildren();
  if (!curve.length || !duration) {
    return;
  }
  const points = curve
    .filter((point) => point && point.length > 1)
    .map((point) => {
      const x = (Number(point[0]) / duration) * 100;
      const y = 38 - Math.max(0, Math.min(1, Number(point[1]))) * 36;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", points.join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "#ffffff");
  line.setAttribute("stroke-width", "1.5");
  svg.append(line);
  if (clipTime != null) {
    const playhead = document.createElementNS("http://www.w3.org/2000/svg", "line");
    const x = (Number(clipTime) / duration) * 100;
    playhead.setAttribute("x1", String(x));
    playhead.setAttribute("x2", String(x));
    playhead.setAttribute("y1", "0");
    playhead.setAttribute("y2", "40");
    playhead.setAttribute("stroke", "#e6e8eb");
    playhead.setAttribute("stroke-width", "0.4");
    svg.append(playhead);
  }
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
    context.strokeStyle = "#ffffff";
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
