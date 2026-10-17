/**
 * Gapless multi-segment clip player (two <video> elements, swap on segment ended).
 */

/**
 * @param {HTMLElement} host
 * @param {{ segments?: { source: string, start_s: number, end_s: number }[], resolveVideoUrl: (source: string) => string, controls?: boolean, autoplay?: boolean, playOnce?: boolean }} options
 */
export function mountPlayer(host, options) {
  const {
    segments = [],
    resolveVideoUrl,
    controls = false,
    autoplay = false,
    playOnce = false,
  } = options;

  host.replaceChildren();
  host.classList.add("player-host");

  if (!segments.length) {
    const empty = document.createElement("div");
    empty.className = "player-empty";
    empty.textContent = "No segments yet.";
    host.append(empty);
    return stubPlayer();
  }

  let segmentIndex = 0;
  let activeSlot = 0;
  let latestMediaTime = null;
  let rVfcHandle = null;
  const endedListeners = [];

  const videoA = document.createElement("video");
  const videoB = document.createElement("video");
  const videos = [videoA, videoB];

  for (const v of videos) {
    v.playsInline = true;
    v.preload = "auto";
    if (controls) {
      v.controls = true;
    }
    host.append(v);
  }

  function activeVideo() {
    return videos[activeSlot];
  }

  function inactiveVideo() {
    return videos[1 - activeSlot];
  }

  function segmentDuration(seg) {
    return Math.max(0, seg.end_s - seg.start_s);
  }

  function cancelRvfc() {
    const v = activeVideo();
    if (rVfcHandle != null && typeof v.cancelVideoFrameCallback === "function") {
      try {
        v.cancelVideoFrameCallback(rVfcHandle);
      } catch {
        /* ignore */
      }
    }
    rVfcHandle = null;
  }

  function scheduleRvfc() {
    const v = activeVideo();
    if (typeof v.requestVideoFrameCallback !== "function") {
      return;
    }
    const tick = (_now, metadata) => {
      if (v !== activeVideo()) {
        return;
      }
      if (metadata && typeof metadata.mediaTime === "number") {
        latestMediaTime = metadata.mediaTime;
      }
      rVfcHandle = v.requestVideoFrameCallback(tick);
    };
    rVfcHandle = v.requestVideoFrameCallback(tick);
  }

  function setVisibility() {
    for (let i = 0; i < videos.length; i++) {
      videos[i].classList.toggle("player-hidden", i !== activeSlot);
    }
  }

  function loadSegmentInto(video, index) {
    const seg = segments[index];
    video.src = resolveVideoUrl(seg.source);
    video.currentTime = 0;
  }

  function fireEnded() {
    for (const fn of endedListeners) {
      try {
        fn();
      } catch {
        /* ignore listener errors */
      }
    }
  }

  function onSegmentEnded() {
    const isLast = segmentIndex >= segments.length - 1;
    if (isLast) {
      if (playOnce) {
        fireEnded();
        return;
      }
      segmentIndex = 0;
    } else {
      segmentIndex += 1;
    }

    const next = inactiveVideo();
    loadSegmentInto(next, segmentIndex);
    cancelRvfc();
    latestMediaTime = null;

    const playNext = () => {
      activeSlot = 1 - activeSlot;
      setVisibility();
      scheduleRvfc();
      const v = activeVideo();
      const p = v.play();
      if (p && typeof p.catch === "function") {
        p.catch(() => {});
      }
    };

    if (next.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      playNext();
    } else {
      next.addEventListener("canplay", playNext, { once: true });
    }
  }

  for (const v of videos) {
    v.addEventListener("ended", () => {
      if (v === activeVideo()) {
        onSegmentEnded();
      }
    });
  }

  loadSegmentInto(videoA, 0);
  loadSegmentInto(videoB, segments.length > 1 ? 1 : 0);
  setVisibility();
  scheduleRvfc();

  if (autoplay) {
    const p = activeVideo().play();
    if (p && typeof p.catch === "function") {
      p.catch(() => {});
    }
  }

  function clipOffsetTime() {
    const seg = segments[segmentIndex];
    const local =
      latestMediaTime != null && Number.isFinite(latestMediaTime)
        ? latestMediaTime
        : activeVideo().currentTime;
    return seg.start_s + local;
  }

  return {
    getClipTime: clipOffsetTime,
    currentTime: clipOffsetTime,
    on(event, fn) {
      if (event === "ended" && typeof fn === "function") {
        endedListeners.push(fn);
      }
    },
    onEnded(fn) {
      this.on("ended", fn);
    },
    play() {
      const p = activeVideo().play();
      if (p && typeof p.catch === "function") {
        p.catch(() => {});
      }
    },
    pause() {
      activeVideo().pause();
    },
    togglePlay() {
      const v = activeVideo();
      if (v.paused) {
        this.play();
      } else {
        this.pause();
      }
    },
    step(deltaSeconds) {
      const v = activeVideo();
      const seg = segments[segmentIndex];
      const dur = segmentDuration(seg);
      const next = Math.min(Math.max(0, v.currentTime + deltaSeconds), dur || 0);
      v.currentTime = next;
      latestMediaTime = next;
    },
    getActiveVideo() {
      return activeVideo();
    },
    // jump to a clip time, across segments when needed; keeps playing if it was playing
    seek(clipTime) {
      const t = Number(clipTime);
      if (!Number.isFinite(t) || !segments.length) {
        return;
      }
      let idx = segments.length - 1;
      for (let i = 0; i < segments.length; i++) {
        if (t < segments[i].end_s) {
          idx = i;
          break;
        }
      }
      const seg = segments[idx];
      const local = Math.max(0, Math.min(segmentDuration(seg), t - seg.start_s));
      const apply = (video) => {
        video.currentTime = local;
        latestMediaTime = local;
      };
      if (idx !== segmentIndex) {
        segmentIndex = idx;
        cancelRvfc();
        const video = activeVideo();
        const wasPlaying = !video.paused;
        loadSegmentInto(video, idx);
        const go = () => {
          apply(video);
          scheduleRvfc();
          if (wasPlaying) {
            const p = video.play();
            if (p && typeof p.catch === "function") {
              p.catch(() => {});
            }
          }
        };
        if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
          go();
        } else {
          video.addEventListener("loadedmetadata", go, { once: true });
        }
        return;
      }
      apply(activeVideo());
    },
  };
}

function stubPlayer() {
  const noop = () => {};
  return {
    getClipTime: () => 0,
    currentTime: () => 0,
    on: noop,
    onEnded: noop,
    play: noop,
    pause: noop,
    togglePlay: noop,
    step: noop,
    seek: noop,
    getActiveVideo() {
      return null;
    },
  };
}
