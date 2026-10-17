/**
 * Label screen Phase 2: blind sit, then full labelling timeline.
 */

import { mountPlayer } from "./player.js";

/** @typedef {{ clip_id: string, duration_s: number, segments: { source: string, start_s: number, end_s: number }[], hazards?: Hazard[] }} ClipMeta */
/** @typedef {{ hazard_id: string, clip_id: string, type: string, window_start: number, window_end: number, labellers?: Record<string, number[]>, auto_window?: number[] | null, description?: string }} Hazard */

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
    auto_window: null,
    description: "EXAMPLE: pedestrian steps out between parked cars on the right",
  },
];

const HAZARD_TYPES = [
  "pedestrian_crossing",
  "vehicle_pulling_out",
  "vehicle_cut_in",
  "lead_vehicle_braking",
  "cyclist",
  "vehicle_turning_across",
  "other",
];

const LABELLERS = ["riyu", "fmd", "moses"];

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
 * @param {{ fetchJson?: (path: string, init?: RequestInit) => Promise<unknown>, getClip?: (id: string, opts?: { blind?: boolean }) => Promise<ClipMeta>, postHuman?: (body: object) => Promise<unknown>, useExamples?: boolean }} api
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
 * @param {{ fetchJson?: (path: string, init?: RequestInit) => Promise<unknown>, useExamples?: boolean }} api
 * @param {string} path
 * @param {RequestInit} init
 */
async function apiRequest(api, path, init) {
  if (typeof api.fetchJson === "function") {
    return api.fetchJson(path, init);
  }
  if (api.useExamples) {
    return null;
  }
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (!res.ok) {
    throw new Error(`${init.method ?? "GET"} ${path} failed (${res.status})`);
  }
  if (res.status === 204) {
    return null;
  }
  return res.json();
}

/**
 * @param {HTMLElement} el
 * @param {string} clipId
 * @param {{ fetchJson?: (path: string, init?: RequestInit) => Promise<unknown>, getClip?: (id: string, opts?: { blind?: boolean }) => Promise<ClipMeta>, postHuman?: (body: object) => Promise<unknown>, useExamples?: boolean, videoUrl?: (source: string) => string }} api
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
  status.textContent = "";

  const stage = document.createElement("div");
  stage.className = "label-stage";

  el.append(title, status, stage);

  /** @type {object | null} */
  let player = null;
  /** @type {(() => void) | null} */
  let teardownKeys = null;

  let chosenLabeller = "riyu";

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

  const getClipTime = () => {
    if (typeof player?.getClipTime === "function") {
      return player.getClipTime();
    }
    if (typeof player?.currentTime === "function") {
      return player.currentTime();
    }
    const video = /** @type {HTMLElement} */ (stage.querySelector("video"));
    if (video instanceof HTMLVideoElement) {
      return video.currentTime;
    }
    return 0;
  };

  const setClipTime = (t) => {
    const clamped = Math.max(0, t);
    if (typeof player?.seek === "function") {
      player.seek(clamped);
      return;
    }
    if (typeof player?.setClipTime === "function") {
      player.setClipTime(clamped);
      return;
    }
    const video = /** @type {HTMLElement} */ (stage.querySelector("video"));
    if (video instanceof HTMLVideoElement) {
      video.currentTime = clamped;
    }
  };

  const setPlaybackHalf = () => {
    if (typeof player?.setPlaybackRate === "function") {
      player.setPlaybackRate(0.5);
      return;
    }
    const videos = stage.querySelectorAll("video");
    for (const node of videos) {
      if (node instanceof HTMLVideoElement) {
        node.playbackRate = 0.5;
      }
    }
  };

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
      status.textContent =
        "Blind sit: watch once. Space or click the video to register a hazard click.";

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

      const paintBlindTimeline = () => {
        timelineHost.replaceChildren();
        const track = document.createElement("div");
        Object.assign(track.style, {
          position: "relative",
          height: "2rem",
          background: UI.panel,
          border: `1px solid ${UI.border}`,
          borderRadius: "4px",
        });
        for (const mk of clicks) {
          const flag = document.createElement("div");
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
        timelineHost.append(track);
      };
      paintBlindTimeline();

      try {
        player = mountPlayer(playerHost, {
          segments: clipMeta.segments,
          resolveVideoUrl,
          controls: false,
          autoplay: true,
          playOnce: true,
        });
      } catch {
        status.textContent = "player.js is not on this branch yet.";
        return;
      }

      const registerClick = () => {
        clicks.push({ t: getClipTime() });
        paintBlindTimeline();
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
        if (typeof api.postHuman === "function") {
          try {
            await api.postHuman({
              name: chosenLabeller || "Anonymous",
              role: "team",
              blind: true,
              clip_id: clipId,
              clicks: clicks.map((c) => c.t),
            });
          } catch {
            /* optional */
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

    /**
     * @param {ClipMeta} clipMeta
     */
    const runLabelView = (clipMeta) => {
      stage.replaceChildren();
      status.textContent = "";

      const hazards = clipMeta.hazards?.length
        ? [...clipMeta.hazards]
        : api.useExamples
          ? [...EXAMPLE_HAZARDS]
          : [];
      let hazardIndex = 0;
      /** @type {Hazard} */
      let hazard = hazards[hazardIndex] ?? {
        hazard_id: "",
        clip_id: clipId,
        type: "other",
        window_start: Math.max(0, durationS * 0.3),
        window_end: Math.min(durationS, durationS * 0.3 + 3),
        labellers: {},
        description: "",
      };

      const ownWindow = hazard.labellers?.[chosenLabeller];
      let ws = Array.isArray(ownWindow) ? ownWindow[0] : Math.min(5, Math.max(0, durationS - 3));
      let we = Array.isArray(ownWindow) ? ownWindow[1] : Math.min(durationS, ws + 3);
      /** @type {Set<string>} */
      const sessionSaved = new Set();
      const savedKey = () => `${hazard.hazard_id || "new"}:${chosenLabeller}`;
      let hasSavedThisHazard = sessionSaved.has(savedKey()) || Array.isArray(ownWindow);

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

      const timelineWrap = document.createElement("div");
      timelineWrap.style.marginBottom = "0.75rem";

      const windowWarn = document.createElement("p");
      Object.assign(windowWarn.style, {
        color: "#f5a524",
        fontSize: "0.875rem",
        margin: "0.35rem 0 0",
        minHeight: "1.1rem",
      });

      const form = document.createElement("div");
      form.style.display = "grid";
      form.style.gap = "0.65rem";
      form.style.marginBottom = "0.75rem";

      const typeLabel = document.createElement("label");
      typeLabel.textContent = "Hazard type";
      typeLabel.style.display = "flex";
      typeLabel.style.flexDirection = "column";
      typeLabel.style.gap = "0.25rem";
      typeLabel.style.fontSize = "0.875rem";
      const typeSelect = document.createElement("select");
      for (const t of HAZARD_TYPES) {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        typeSelect.appendChild(opt);
      }
      typeSelect.value = hazard.type || "other";
      typeLabel.append(typeSelect);

      const descLabel = document.createElement("label");
      descLabel.textContent = "Description";
      descLabel.style.display = "flex";
      descLabel.style.flexDirection = "column";
      descLabel.style.gap = "0.25rem";
      descLabel.style.fontSize = "0.875rem";
      const descInput = document.createElement("input");
      descInput.type = "text";
      descInput.value = hazard.description ?? "";
      Object.assign(descInput.style, {
        background: UI.bg,
        border: `1px solid ${UI.border}`,
        color: UI.text,
        padding: "0.4rem 0.5rem",
        borderRadius: "4px",
        fontFamily: "inherit",
      });
      descLabel.append(descInput);

      const labLabel = document.createElement("label");
      labLabel.textContent = "Labeller";
      labLabel.style.display = "flex";
      labLabel.style.flexDirection = "column";
      labLabel.style.gap = "0.25rem";
      labLabel.style.fontSize = "0.875rem";
      const labSelect = document.createElement("select");
      for (const name of LABELLERS) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        labSelect.appendChild(opt);
      }
      labSelect.value = chosenLabeller;
      labLabel.append(labSelect);

      form.append(typeLabel, descLabel, labLabel);

      const actions = document.createElement("div");
      actions.style.display = "flex";
      actions.style.flexWrap = "wrap";
      actions.style.gap = "0.5rem";

      const mkBtn = (label) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = label;
        Object.assign(btn.style, {
          background: UI.bg,
          border: `1px solid ${UI.border}`,
          color: UI.text,
          padding: "0.45rem 0.75rem",
          borderRadius: "4px",
          cursor: "pointer",
          fontFamily: "inherit",
        });
        return btn;
      };

      const btnAdd = mkBtn("Add hazard");
      const btnSave = mkBtn("Save");
      const btnNoHazard = mkBtn("No hazard in this clip");
      const btnReject = mkBtn("Reject clip");
      actions.append(btnAdd, btnSave, btnNoHazard, btnReject);

      const emptyLine = document.createElement("p");
      emptyLine.style.color = UI.muted;
      emptyLine.style.fontSize = "0.875rem";
      emptyLine.textContent = hazards.length ? "" : "No hazards loaded for this clip.";

      panel.append(playerHost, timelineWrap, windowWarn, form, actions, emptyLine);
      stage.append(panel);

      try {
        player = mountPlayer(playerHost, {
          segments: clipMeta.segments,
          resolveVideoUrl,
          controls: true,
        });
        setPlaybackHalf();
      } catch {
        status.textContent = "player.js is not on this branch yet.";
        return;
      }

      /** @type {"start" | "end" | null} */
      let dragHandle = null;

      const syncWindowWarn = () => {
        const len = we - ws;
        if (len < 1 || len > 7) {
          windowWarn.textContent = `Window is ${len.toFixed(2)} s (expected 1 to 7 s). You can still save.`;
        } else {
          windowWarn.textContent = "";
        }
      };

      const riskPoints = () => {
        if (!hasSavedThisHazard) {
          return [];
        }
        const curve = hazard.risk_curve;
        if (!Array.isArray(curve)) {
          return [];
        }
        return curve
          .filter((point) => Array.isArray(point) && point.length >= 2)
          .map((point) => ({ t: Number(point[0]), v: Number(point[1]) }));
      };

      const paintLabelTimeline = () => {
        timelineWrap.replaceChildren();
        const track = document.createElement("div");
        track.className = "label-timeline-track";
        Object.assign(track.style, {
          position: "relative",
          height: "3rem",
          background: UI.bg,
          border: `1px solid ${UI.border}`,
          borderRadius: "4px",
          cursor: "pointer",
        });

        if (hasSavedThisHazard && Array.isArray(hazard.auto_window) && hazard.auto_window.length === 2) {
          const [as, ae] = hazard.auto_window;
          const auto = document.createElement("div");
          Object.assign(auto.style, {
            position: "absolute",
            top: "4px",
            bottom: "4px",
            left: `${(as / durationS) * 100}%`,
            width: `${((ae - as) / durationS) * 100}%`,
            border: `2px dashed ${UI.window}`,
            boxSizing: "border-box",
            pointerEvents: "none",
            opacity: "0.7",
          });
          track.appendChild(auto);
        }

        if (hasSavedThisHazard) {
          const others = hazard.labellers ?? {};
          for (const [name, win] of Object.entries(others)) {
            if (name === chosenLabeller || !Array.isArray(win) || win.length !== 2) {
              continue;
            }
            const outline = document.createElement("div");
            Object.assign(outline.style, {
              position: "absolute",
              top: "8px",
              bottom: "8px",
              left: `${(win[0] / durationS) * 100}%`,
              width: `${((win[1] - win[0]) / durationS) * 100}%`,
              border: `1px solid ${UI.muted}`,
              boxSizing: "border-box",
              pointerEvents: "none",
            });
            track.appendChild(outline);
          }
        }

        const band = document.createElement("div");
        Object.assign(band.style, {
          position: "absolute",
          top: "10px",
          bottom: "10px",
          left: `${(ws / durationS) * 100}%`,
          width: `${((we - ws) / durationS) * 100}%`,
          background: UI.window,
          borderRadius: "2px",
          boxSizing: "border-box",
        });
        track.appendChild(band);

        const mkHandle = (which) => {
          const h = document.createElement("div");
          h.dataset.handle = which;
          const t = which === "start" ? ws : we;
          Object.assign(h.style, {
            position: "absolute",
            top: "6px",
            bottom: "6px",
            width: "10px",
            left: `${(t / durationS) * 100}%`,
            transform: "translateX(-50%)",
            background: UI.text,
            borderRadius: "2px",
            cursor: "ew-resize",
            zIndex: "2",
          });
          h.addEventListener("pointerdown", (ev) => {
            ev.preventDefault();
            dragHandle = which;
            h.setPointerCapture(ev.pointerId);
          });
          h.addEventListener("pointerup", () => {
            dragHandle = null;
          });
          return h;
        };
        track.append(mkHandle("start"), mkHandle("end"));

        const playhead = document.createElement("div");
        Object.assign(playhead.style, {
          position: "absolute",
          top: "0",
          bottom: "0",
          width: "2px",
          background: UI.text,
          opacity: "0.5",
          pointerEvents: "none",
        });
        track.appendChild(playhead);

        const curveHost = document.createElement("canvas");
        curveHost.width = 800;
        curveHost.height = 48;
        Object.assign(curveHost.style, {
          width: "100%",
          height: "48px",
          display: hasSavedThisHazard && riskPoints().length ? "block" : "none",
          marginTop: "0.35rem",
          background: UI.bg,
          border: `1px solid ${UI.border}`,
          borderRadius: "4px",
        });
        if (hasSavedThisHazard) {
          const ctx = curveHost.getContext("2d");
          if (ctx) {
            const pts = riskPoints();
            ctx.clearRect(0, 0, curveHost.width, curveHost.height);
            ctx.strokeStyle = UI.window;
            ctx.lineWidth = 2;
            ctx.beginPath();
            for (let i = 0; i < pts.length; i++) {
              const x = (pts[i].t / durationS) * curveHost.width;
              const y = curveHost.height - pts[i].v * (curveHost.height - 8) - 4;
              if (i === 0) {
                ctx.moveTo(x, y);
              } else {
                ctx.lineTo(x, y);
              }
            }
            ctx.stroke();
          }
        }

        track.addEventListener("pointermove", (ev) => {
          if (!dragHandle) {
            return;
          }
          const rect = track.getBoundingClientRect();
          const ratio = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
          const t = ratio * durationS;
          if (dragHandle === "start") {
            ws = Math.min(t, we - 0.05);
          } else {
            we = Math.max(t, ws + 0.05);
          }
          paintLabelTimeline();
          syncWindowWarn();
        });

        track.addEventListener("click", (ev) => {
          if (dragHandle) {
            return;
          }
          const rect = track.getBoundingClientRect();
          const t = Math.min(durationS, Math.max(0, ((ev.clientX - rect.left) / rect.width) * durationS));
          const dStart = Math.abs(t - ws);
          const dEnd = Math.abs(t - we);
          if (dStart <= dEnd) {
            ws = Math.min(t, we - 0.05);
          } else {
            we = Math.max(t, ws + 0.05);
          }
          setClipTime(t);
          paintLabelTimeline();
          syncWindowWarn();
        });

        const scale = document.createElement("div");
        Object.assign(scale.style, {
          display: "flex",
          justifyContent: "space-between",
          fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
          fontSize: "0.75rem",
          color: UI.muted,
          marginTop: "0.35rem",
        });
        scale.append(document.createTextNode("0 s"), document.createTextNode(`${durationS} s`));

        timelineWrap.append(track, curveHost, scale);

        const updatePlayhead = () => {
          const t = getClipTime();
          playhead.style.left = `${(t / durationS) * 100}%`;
          requestAnimationFrame(updatePlayhead);
        };
        requestAnimationFrame(updatePlayhead);
      };

      const applyHazardToForm = () => {
        typeSelect.value = hazard.type || "other";
        descInput.value = hazard.description ?? "";
        const own = hazard.labellers?.[chosenLabeller];
        if (Array.isArray(own)) {
          ws = own[0];
          we = own[1];
          hasSavedThisHazard = true;
        } else {
          ws = Math.min(5, Math.max(0, durationS - 3));
          we = Math.min(durationS, ws + 3);
          hasSavedThisHazard = sessionSaved.has(savedKey());
        }
        paintLabelTimeline();
        syncWindowWarn();
      };

      labSelect.addEventListener("change", () => {
        chosenLabeller = labSelect.value;
        applyHazardToForm();
      });

      applyHazardToForm();

      btnSave.addEventListener("click", async () => {
        status.textContent = "Saving…";
        const body = {
          labeller: chosenLabeller,
          ws,
          we,
          type: typeSelect.value,
          description: descInput.value,
        };
        try {
          let saved;
          if (hazard.hazard_id) {
            saved = await apiRequest(api, `api/hazards/${encodeURIComponent(hazard.hazard_id)}`, {
              method: "PUT",
              body: JSON.stringify(body),
            });
          } else {
            saved = await apiRequest(api, "api/hazards", {
              method: "POST",
              body: JSON.stringify({ clip_id: clipId, ...body }),
            });
          }
          if (saved && typeof saved === "object") {
            hazard = /** @type {Hazard} */ (saved);
            hazards[hazardIndex] = hazard;
            sessionSaved.add(savedKey());
            hasSavedThisHazard = true;
          } else if (api.useExamples) {
            hazard = {
              ...hazard,
              hazard_id: hazard.hazard_id || `${clipId}_h1`,
              labellers: { ...hazard.labellers, [chosenLabeller]: [ws, we] },
              type: body.type,
              description: body.description,
            };
            sessionSaved.add(savedKey());
            hasSavedThisHazard = true;
          }
          applyHazardToForm();
          status.textContent = "Saved.";
        } catch (err) {
          status.textContent = err instanceof Error ? err.message : String(err);
        }
      });

      btnAdd.addEventListener("click", async () => {
        status.textContent = "Adding hazard…";
        const body = {
          clip_id: clipId,
          labeller: chosenLabeller,
          ws,
          we,
          type: typeSelect.value,
          description: descInput.value,
        };
        try {
          const created = await apiRequest(api, "api/hazards", {
            method: "POST",
            body: JSON.stringify(body),
          });
          if (created && typeof created === "object") {
            hazards.push(/** @type {Hazard} */ (created));
            hazardIndex = hazards.length - 1;
            hazard = hazards[hazardIndex];
            sessionSaved.add(savedKey());
            hasSavedThisHazard = true;
          } else if (api.useExamples) {
            const next = {
              hazard_id: `${clipId}_h${hazards.length + 1}`,
              clip_id: clipId,
              type: body.type,
              window_start: ws,
              window_end: we,
              labellers: { [chosenLabeller]: [ws, we] },
              description: body.description,
            };
            hazards.push(next);
            hazardIndex = hazards.length - 1;
            hazard = next;
            sessionSaved.add(savedKey());
            hasSavedThisHazard = true;
          }
          applyHazardToForm();
          status.textContent = "Hazard added.";
        } catch (err) {
          status.textContent = err instanceof Error ? err.message : String(err);
        }
      });

      const postClipStatus = async (clipStatus) => {
        status.textContent = "Updating clip…";
        try {
          await apiRequest(api, `api/clips/${encodeURIComponent(clipId)}/status`, {
            method: "POST",
            body: JSON.stringify({ status: clipStatus }),
          });
          status.textContent = clipStatus === "no_hazard" ? "Marked no hazard." : "Clip rejected.";
        } catch (err) {
          status.textContent = err instanceof Error ? err.message : String(err);
        }
      };

      btnNoHazard.addEventListener("click", () => void postClipStatus("no_hazard"));
      btnReject.addEventListener("click", () => void postClipStatus("rejected"));

      const onKey = (ev) => {
        if (ev.code === "KeyJ") {
          ev.preventDefault();
          setClipTime(getClipTime() - 0.2);
        } else if (ev.code === "KeyL") {
          ev.preventDefault();
          setClipTime(getClipTime() + 0.2);
        } else if (ev.code === "KeyP") {
          ev.preventDefault();
          if (typeof player?.togglePlay === "function") {
            player.togglePlay();
          } else if (typeof player?.pause === "function" && typeof player?.play === "function") {
            /* no state API */
          }
        }
      };
      window.addEventListener("keydown", onKey);
      teardownKeys = () => window.removeEventListener("keydown", onKey);
    };

    runBlindSit(clipBlind);
  })();
}
