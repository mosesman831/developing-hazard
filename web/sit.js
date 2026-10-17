/**
 * Sit screen (SPEC 16.5). Start stays disabled until every segment is a blob URL.
 */

import { mountPlayer } from "./player.js";

/**
 * @param {HTMLElement} el
 * @param {string} clipId
 * @param {{ getClip?: Function, postHuman?: Function, videoUrl?: Function }} api
 */
export function mountSit(el, clipId, api = {}) {
  el.replaceChildren();
  const videoUrl =
    typeof api.videoUrl === "function"
      ? api.videoUrl
      : (source) => `video?source=${encodeURIComponent(source)}`;

  const shell = document.createElement("section");
  shell.className = "sit";

  const title = document.createElement("h1");
  title.textContent = `Sit ${clipId}`;

  const form = document.createElement("form");
  form.className = "sit-form";
  form.innerHTML = `
    <label>Name <input name="name" type="text" autocomplete="name" placeholder="Anonymous"></label>
    <label>Role
      <select name="role">
        <option value="judge">judge</option>
        <option value="guest" selected>guest</option>
        <option value="team">team</option>
      </select>
    </label>
    <label class="sit-seen"><input name="seen" type="checkbox"> Have you seen this clip before?</label>
  `;

  const ready = document.createElement("p");
  ready.className = "muted";
  ready.textContent = "Start stays off until every segment is ready.";

  const start = document.createElement("button");
  start.type = "button";
  start.textContent = "Start";
  start.disabled = true;

  const stage = document.createElement("div");
  stage.className = "sit-stage";
  const timeline = document.createElement("div");
  timeline.className = "timeline";
  const result = document.createElement("div");
  result.className = "sit-result";

  shell.append(title, form, ready, start, stage, timeline, result);
  el.append(shell);

  const clicks = [];
  let player = null;
  let blobUrls = [];
  let durationS = 30;
  let onKey = null;

  function paintFlags() {
    timeline.replaceChildren();
    const bar = document.createElement("div");
    bar.className = "timeline-bar";
    for (const click of clicks) {
      const flag = document.createElement("span");
      flag.className = "flag human";
      const left = durationS > 0 ? (click.t / durationS) * 100 : 0;
      flag.style.left = `${Math.min(100, Math.max(0, left))}%`;
      flag.title = `${click.t.toFixed(2)}s`;
      bar.append(flag);
    }
    timeline.append(bar);
  }

  function finish(clipMeta) {
    if (onKey) {
      window.removeEventListener("keydown", onKey);
      onKey = null;
    }
    const data = new FormData(form);
    const name = String(data.get("name") || "").trim() || "Anonymous";
    const role = String(data.get("role") || "guest");
    const seen = form.querySelector('input[name="seen"]').checked;
    const body = {
      name,
      role,
      blind: !seen,
      clip_id: clipId,
      clicks: clicks.map((click) => click.t),
    };
    const post =
      typeof api.postHuman === "function"
        ? api.postHuman(body)
        : fetch("api/human", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }).then((res) => {
            if (!res.ok) {
              throw new Error(String(res.status));
            }
            return res.json();
          });
    post
      .then((scored) => renderScore(result, scored, clipMeta))
      .catch(() => {
        result.textContent = "Score could not be saved.";
      });
    loadAgents(result, clipId);
  }

  function begin(clipMeta) {
    start.disabled = true;
    stage.replaceChildren();
    const host = document.createElement("div");
    stage.append(host);
    const bySource = new Map(clipMeta.segments.map((segment, index) => [segment.source, blobUrls[index]]));
    player = mountPlayer(host, {
      segments: clipMeta.segments,
      resolveVideoUrl: (source) => bySource.get(source) || videoUrl(source),
      controls: false,
      autoplay: true,
      playOnce: true,
    });
    const register = () => {
      const t = typeof player.getClipTime === "function" ? player.getClipTime() : 0;
      clicks.push({ t });
      paintFlags();
    };
    onKey = (event) => {
      if (event.code !== "Space" || event.repeat) {
        return;
      }
      event.preventDefault();
      register();
    };
    window.addEventListener("keydown", onKey);
    host.addEventListener("click", register);
    if (typeof player.on === "function") {
      player.on("ended", () => finish(clipMeta));
    }
    shell.focus();
  }

  shell.tabIndex = -1;

  start.addEventListener("click", () => {
    shell.focus();
  });

  loadClip(clipId, api)
    .then(async (clipMeta) => {
      durationS = Number(clipMeta.duration_s) || 30;
      const segments = clipMeta.segments || [];
      if (!segments.length) {
        ready.textContent = "This clip has no segments.";
        return;
      }
      const urls = [];
      for (let index = 0; index < segments.length; index += 1) {
        ready.textContent = `Segment ${index + 1} of ${segments.length} ready.`;
        const response = await fetch(videoUrl(segments[index].source));
        if (!response.ok) {
          ready.textContent = `Segment ${index + 1} did not load (${response.status}). Start stays off.`;
          return;
        }
        const blob = await response.blob();
        urls.push(URL.createObjectURL(blob));
      }
      blobUrls = urls;
      ready.textContent = `${segments.length} segments ready.`;
      start.disabled = false;
      start.addEventListener(
        "click",
        () => {
          begin(clipMeta);
        },
        { once: true },
      );
    })
    .catch(() => {
      ready.textContent = "Clip could not be loaded. Start stays off.";
    });

  return () => {
    if (onKey) {
      window.removeEventListener("keydown", onKey);
    }
    for (const url of blobUrls) {
      URL.revokeObjectURL(url);
    }
  };
}

async function loadClip(clipId, api) {
  if (typeof api.getClip === "function") {
    return api.getClip(clipId, { blind: true });
  }
  const response = await fetch(`api/clips/${encodeURIComponent(clipId)}?blind=1`);
  if (!response.ok) {
    throw new Error(String(response.status));
  }
  return response.json();
}

function renderScore(host, scored, clipMeta) {
  host.replaceChildren();
  const card = document.createElement("div");
  card.className = "score-card";
  const score = document.createElement("p");
  score.className = "score";
  score.textContent = String(scored.clip_score);
  const pattern = document.createElement("p");
  const flagged = Boolean(scored.pattern && scored.pattern.flag);
  pattern.textContent = flagged
    ? `Pattern: ${(scored.pattern.reasons || []).join(", ") || "flagged"}`
    : "No pattern flag.";
  if (flagged) {
    pattern.className = "pattern-flag";
  }
  card.append(score, pattern);
  const hazards = scored.hazards || [];
  if (!hazards.length && clipMeta && clipMeta.hazards) {
    /* blind response should still include windows from the server */
  }
  for (const hazard of hazards) {
    const line = document.createElement("p");
    line.className = "mono";
    const window = hazard.window || [];
    const first = hazard.first_click == null ? "-" : hazard.first_click;
    line.textContent = `${hazard.hazard_id} ${window[0]}–${window[1]} points ${hazard.points} first ${first}`;
    card.append(line);
  }
  host.append(card);
}

async function loadAgents(host, clipId) {
  let runs = [];
  try {
    const response = await fetch("api/runs");
    if (response.ok) {
      runs = await response.json();
    }
  } catch {
    return;
  }
  const block = document.createElement("div");
  block.className = "agent-scores";
  const heading = document.createElement("h2");
  heading.textContent = "Agents on this clip";
  block.append(heading);
  let any = false;
  for (const run of runs) {
    if (!run.run_id) {
      continue;
    }
    try {
      const response = await fetch(`api/runs/${encodeURIComponent(run.run_id)}`);
      if (!response.ok) {
        continue;
      }
      const detail = await response.json();
      const row = (detail.clips || []).find((item) => item.clip_id === clipId);
      if (!row) {
        continue;
      }
      any = true;
      const line = document.createElement("p");
      line.className = "mono";
      const times = (row.clicks || [])
        .map((click) => (typeof click === "number" ? click : click.t))
        .filter((value) => value != null);
      line.textContent = `${run.agent || run.run_id}: ${row.clip_score} clicks ${times.join(", ") || "-"}`;
      block.append(line);
    } catch {
      /* skip this run */
    }
  }
  if (!any) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No recorded agent run for this clip.";
    block.append(empty);
  }
  host.append(block);
}
