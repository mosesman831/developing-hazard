/**
 * Label screen v0 (Phase 1): blind sit, then labelling timeline.
 * Imports AG3's segment player; expects mountPlayer(host, options).
 */

import { mountPlayer } from "./player.js";

/** @typedef {{ clip_id: string, duration_s: number, segments: { source: string, start_s: number, end_s: number }[], hazards?: Hazard[] }} ClipMeta */
/** @typedef {{ hazard_id: string, clip_id: string, type: string, window_start: number, window_end: number, labellers?: Record<string, number[]>, description?: string }} Hazard */

const EXAMPLE_CLIP = {
  clip_id: "c07",
  duration_s: 30.0,
  segments: [
    {
      source:
        "s3://TEAM-vss-chunks-segments/segments/EXAMPLE_set03_video_chunk_0014_segment_001_of_006.mp4",
      start_s: 0.0,
      end_s: 5.0,
    },
    {
      source:
        "s3://TEAM-vss-chunks-segments/segments/EXAMPLE_set03_video_chunk_0014_segment_002_of_006.mp4",
      start_s: 5.0,
      end_s: 10.0,
    },
    {
      source:
        "s3://TEAM-vss-chunks-segments/segments/EXAMPLE_set03_video_chunk_0014_segment_003_of_006.mp4",
      start_s: 10.0,
      end_s: 15.0,
    },
    {
      source:
        "s3://TEAM-vss-chunks-segments/segments/EXAMPLE_set03_video_chunk_0014_segment_004_of_006.mp4",
      start_s: 15.0,
      end_s: 20.0,
    },
    {
      source:
        "s3://TEAM-vss-chunks-segments/segments/EXAMPLE_set03_video_chunk_0014_segment_005_of_006.mp4",
      start_s: 20.0,
      end_s: 25.0,
    },
    {
      source:
        "s3://TEAM-vss-chunks-segments/segments/EXAMPLE_set03_video_chunk_0014_segment_006_of_006.mp4",
      start_s: 25.0,
      end_s: 30.0,
    },
  ],
};

const EXAMPLE_HAZARDS = [
  {
    hazard_id: "c07_h1",
    clip_id: "c07",
    type: "pedestrian_crossing",
    window_start: 16.2,
    window_end: 19.0,
    labellers: {
      riyu: [16.0, 19.1],
      fmd: [16.4, 18.9],
    },
    description: "EXAMPLE: pedestrian steps out between parked cars on the right",
  },
];

const UI = {
  bg: "#0d0f12",
  panel: "#15181d",
  border: "#262a31",
  text: "#e6e8eb",
  muted: "#8b929c",
  window: "#f5a524",
  humanClick: "#e879f9",
};

/** @param {string} clipId @param {boolean} [blind] */
function exampleClipFor(clipId, blind) {
  const base = { ...EXAMPLE_CLIP, clip_id: clipId };
  if (blind) {
    return { ...base, hazards: [] };
  }
  return {
    ...base,
    hazards: EXAMPLE_HAZARDS.filter((h) => h.clip_id === clipId || clipId === "c07"),
  };
}

/**
 * @param {string} clipId
 * @param {{ fetchJson?: (path: string) => Promise<unknown>, getClip?: (id: string, opts?: { blind?: boolean }) => Promise<ClipMeta>, useExamples?: boolean }} api
 * @param {{ blind?: boolean }} opts
 */
async function loadClip(clipId, api, opts = {}) {
  if (api?.useExamples) {
    return exampleClipFor(clipId, opts.blind);
  }
  if (typeof api?.getClip === "function") {
    return api.getClip(clipId, opts);
  }
  const blindQ = opts.blind ? "?blind=1" : "";
  const path = `api/clips/${encodeURIComponent(clipId)}${blindQ}`;
  if (typeof api?.fetchJson === "function") {
    return /** @type {Promise<ClipMeta>} */ (api.fetchJson(path));
  }
  return exampleClipFor(clipId, opts.blind);
}

/**
 * @param {HTMLElement} host
 * @param {number} durationS
 * @param {{ start: number, end: number, style?: Partial<CSSStyleDeclaration>, className?: string }[]} bands
 * @param {{ t: number }[]} clickMarkers
 */
function paintTimeline(host, durationS, bands, clickMarkers = []) {
  host.replaceChildren();
  const track = document.createElement("div");
  track.className = "label-timeline-track";
  Object.assign(track.style, {
    position: "relative",
    height: "2rem",
    background: UI.panel,
    border: `1px solid ${UI.border}`,
    borderRadius: "4px",
    overflow: "hidden",
  });

  for (const band of bands) {
    const el = document.createElement("div");
    el.className = band.className ?? "label-timeline-band";
    const left = (band.start / durationS) * 100;
    const width = ((band.end - band.start) / durationS) * 100;
    Object.assign(el.style, {
      position: "absolute",
      top: "0",
      bottom: "0",
      left: `${left}%`,
      width: `${Math.max(width, 0.4)}%`,
      background: UI.window,
      opacity: band.style?.opacity ?? "0.85",
      border: band.style?.border ?? "none",
      boxSizing: "border-box",
      pointerEvents: "none",
      ...band.style,
    });
    track.appendChild(el);
  }

  for (const mk of clickMarkers) {
    const flag = document.createElement("div");
    flag.className = "label-timeline-click";
    Object.assign(flag.style, {
      position: "absolute",
      top: "2px",
      bottom: "2px",
      width: "3px",
      left: `${(mk.t / durationS) * 100}%`,
      background: UI.humanClick,
      transform: "translateX(-50%)",
    });
    track.appendChild(flag);
  }

  const scale = document.createElement("div");
  scale.className = "label-timeline-scale";
  Object.assign(scale.style, {
    display: "flex",
    justifyContent: "space-between",
    fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
    fontSize: "0.75rem",
    color: UI.muted,
    marginTop: "0.35rem",
  });
  scale.textContent = "";
  scale.append(document.createTextNode("0 s"));
  scale.append(document.createTextNode(`${durationS} s`));

  host.append(track, scale);
}

/**
 * @param {HTMLElement} el
 * @param {string} clipId
 * @param {{ fetchJson?: (path: string) => Promise<unknown>, getClip?: (id: string, opts?: { blind?: boolean }) => Promise<ClipMeta>, postHuman?: (body: object) => Promise<unknown>, useExamples?: boolean, videoUrl?: (source: string) => string }} api
 */
export function mountLabel(el, clipId, api = {}) {
  if (typeof el.__labelCleanup === "function") {
    el.__labelCleanup();
  }
  el.replaceChildren();
  Object.assign(el.style, {
    background: UI.bg,
    color: UI.text,
    fontFamily: '"IBM Plex Sans", system-ui, sans-serif',
    padding: "1rem",
    maxWidth: "960px",
  });

  const title = document.createElement("h1");
  title.className = "label-title";
  Object.assign(title.style, { fontSize: "1.25rem", fontWeight: "600", margin: "0 0 0.5rem" });
  title.textContent = `Label ${clipId}`;

  const status = document.createElement("p");
  status.className = "label-status";
  Object.assign(status.style, { color: UI.muted, margin: "0 0 1rem", minHeight: "1.25rem" });
  status.textContent = "Loading clip…";

  const stage = document.createElement("div");
  stage.className = "label-stage";

  el.append(title, status, stage);

  /** @type {object | null} */
  let player = null;
  /** @type {(() => void) | null} */
  let teardownKeys = null;

  const cleanup = () => {
    if (teardownKeys) {
      teardownKeys();
      teardownKeys = null;
    }
    if (player && typeof player.destroy === "function") {
      player.destroy();
    }
    player = null;
  };

  el.__labelCleanup = cleanup;

  const resolveVideoUrl =
    typeof api.videoUrl === "function"
      ? api.videoUrl
      : (source) => `video?source=${encodeURIComponent(source)}`;

  void (async () => {
    let clipBlind;
    try {
      clipBlind = await loadClip(clipId, api, { blind: true });
    } catch (err) {
      status.textContent = `Could not load clip: ${err instanceof Error ? err.message : String(err)}`;
      return;
    }

    const durationS = clipBlind.duration_s ?? EXAMPLE_CLIP.duration_s;

    /** @param {ClipMeta} clipMeta */
    const runBlindSit = (clipMeta) => {
      stage.replaceChildren();
      status.textContent = "Blind sit: watch once. Space or click the video to register a hazard click.";

      const panel = document.createElement("section");
      panel.className = "label-blind";
      Object.assign(panel.style, {
        background: UI.panel,
        border: `1px solid ${UI.border}`,
        borderRadius: "6px",
        padding: "1rem",
      });

      const hint = document.createElement("p");
      hint.style.color = UI.muted;
      hint.style.marginTop = "0";
      hint.textContent = "No controls. One viewing only.";

      const playerHost = document.createElement("div");
      playerHost.className = "label-player-host";
      Object.assign(playerHost.style, { maxWidth: "960px", margin: "0.75rem 0" });

      const timelineHost = document.createElement("div");
      timelineHost.className = "label-blind-timeline";
      timelineHost.style.marginTop = "0.75rem";

      panel.append(hint, playerHost, timelineHost);
      stage.append(panel);

      const clicks = [];
      paintTimeline(timelineHost, durationS, [], clicks);

      try {
        player = mountPlayer(playerHost, {
          segments: clipMeta.segments,
          resolveVideoUrl,
          controls: false,
          autoplay: true,
          playOnce: true,
        });
      } catch (err) {
        status.textContent = `Player not ready (${err instanceof Error ? err.message : String(err)}). Merge AG3 player.js.`;
        return;
      }

      const registerClick = () => {
        const t =
          typeof player?.getClipTime === "function"
            ? player.getClipTime()
            : typeof player?.currentTime === "function"
              ? player.currentTime()
              : 0;
        clicks.push({ t });
        paintTimeline(timelineHost, durationS, [], clicks);
      };

      const onKey = (ev) => {
        if (ev.code !== "Space" || ev.repeat) return;
        ev.preventDefault();
        registerClick();
      };
      window.addEventListener("keydown", onKey);
      playerHost.addEventListener("click", registerClick);

      const finishBlind = async () => {
        window.removeEventListener("keydown", onKey);
        playerHost.removeEventListener("click", registerClick);
        status.textContent = "Blind sit complete. Open labelling view.";
        if (typeof api.postHuman === "function" && clicks.length) {
          try {
            await api.postHuman({
              name: "Anonymous",
              role: "team",
              blind: true,
              clip_id: clipId,
              clicks: clicks.map((c) => c.t),
            });
          } catch {
            /* scoring optional in v0 */
          }
        }
        cleanup();
        const clipLabel = await loadClip(clipId, api, { blind: false });
        runLabelView(clipLabel);
      };

      if (typeof player.on === "function") {
        player.on("ended", finishBlind);
      } else if (typeof player.onEnded === "function") {
        player.onEnded(finishBlind);
      } else {
        status.textContent += " (Waiting for player ended callback.)";
      }
    };

    /** @param {ClipMeta} clipMeta */
    const runLabelView = (clipMeta) => {
      stage.replaceChildren();
      status.textContent = "Labelling view (v0): timeline only. Save and handles land in Phase 2.";

      const panel = document.createElement("section");
      panel.className = "label-edit";
      Object.assign(panel.style, {
        background: UI.panel,
        border: `1px solid ${UI.border}`,
        borderRadius: "6px",
        padding: "1rem",
      });

      const playerHost = document.createElement("div");
      playerHost.className = "label-player-host";
      Object.assign(playerHost.style, { maxWidth: "960px", marginBottom: "0.75rem" });

      const timelineHost = document.createElement("div");
      timelineHost.className = "label-edit-timeline";

      const metaLine = document.createElement("p");
      metaLine.style.color = UI.muted;
      metaLine.style.fontSize = "0.875rem";
      metaLine.textContent =
        "Risk curve and auto window appear after you save (Phase 2). YOLO overlay hidden until save.";

      panel.append(playerHost, timelineHost, metaLine);
      stage.append(panel);

      try {
        player = mountPlayer(playerHost, {
          segments: clipMeta.segments,
          resolveVideoUrl,
          controls: true,
        });
      } catch (err) {
        status.textContent = `Player not ready (${err instanceof Error ? err.message : String(err)}).`;
        return;
      }

      const hazards = clipMeta.hazards?.length ? clipMeta.hazards : EXAMPLE_HAZARDS;
      const bands = hazards.map((h) => ({
        start: h.window_start,
        end: h.window_end,
        className: "label-window-agreed",
      }));
      paintTimeline(timelineHost, durationS, bands);

      const onKey = (ev) => {
        if (ev.code === "KeyP") {
          ev.preventDefault();
          if (typeof player?.togglePlay === "function") player.togglePlay();
          else if (typeof player?.play === "function" && typeof player?.pause === "function") {
            /* no state API: noop in v0 */
          }
        }
      };
      window.addEventListener("keydown", onKey);
      teardownKeys = () => window.removeEventListener("keydown", onKey);
    };

    runBlindSit(clipBlind);
  })();
}
