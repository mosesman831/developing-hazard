const appEl = document.getElementById("app");

/** @type {{ vss_ok?: boolean | null, cosmos_ok?: boolean | null, wandb_ok?: boolean | null }} */
let healthState = { vss_ok: null, cosmos_ok: null, wandb_ok: null };

export const api = {
  async getClip(id, opts) {
    const q = opts?.blind ? "?blind=1" : "";
    const res = await fetch(`api/clips/${encodeURIComponent(id)}${q}`);
    if (!res.ok) {
      throw new Error(`clip ${id}: ${res.status}`);
    }
    return res.json();
  },
  async postHuman(body) {
    const res = await fetch("api/human", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(`human: ${res.status}`);
    }
    return res.json();
  },
  videoUrl(source) {
    return `video?source=${encodeURIComponent(source)}`;
  },
};

function parseRoute() {
  const raw = (location.hash || "").replace(/^#/, "").replace(/^\//, "");
  if (!raw) {
    return { name: "home" };
  }
  const parts = raw.split("/").filter(Boolean);
  const [head, ...rest] = parts;
  switch (head) {
    case "label":
      return { name: "label", clipId: rest[0] || "" };
    case "sit":
      return { name: "sit", clipId: rest[0] || "" };
    case "watch":
      return { name: "watch", runId: rest[0] || "", clipId: rest[1] || "" };
    case "leaderboard":
      return { name: "leaderboard" };
    default:
      return { name: "unknown" };
  }
}

function healthDotClass(ok) {
  if (ok === true) {
    return "health-dot ok";
  }
  if (ok === false) {
    return "health-dot bad";
  }
  return "health-dot";
}

function renderHealthStrip(container) {
  const strip = document.createElement("div");
  strip.className = "health-strip";
  strip.innerHTML = `
    <span class="health-item"><span class="${healthDotClass(healthState.vss_ok)}" data-key="vss"></span> VSS</span>
    <span class="health-item"><span class="${healthDotClass(healthState.cosmos_ok)}" data-key="cosmos"></span> Cosmos</span>
    <span class="health-item"><span class="${healthDotClass(healthState.wandb_ok)}" data-key="wandb"></span> W&amp;B</span>
  `;
  container.prepend(strip);
  return strip;
}

function updateHealthStrip(strip) {
  const map = {
    vss: healthState.vss_ok,
    cosmos: healthState.cosmos_ok,
    wandb: healthState.wandb_ok,
  };
  for (const [key, ok] of Object.entries(map)) {
    const dot = strip.querySelector(`[data-key="${key}"]`);
    if (dot) {
      dot.className = healthDotClass(ok);
    }
  }
}

async function fetchHealth() {
  try {
    const res = await fetch("api/health");
    if (!res.ok) {
      return;
    }
    const data = await res.json();
    healthState = {
      vss_ok: data.vss_ok ?? null,
      cosmos_ok: data.cosmos_ok ?? null,
      wandb_ok: data.wandb_ok ?? null,
    };
  } catch {
    /* keep nulls */
  }
}

function shortHash(value) {
  if (value == null || value === "") {
    return "-";
  }
  const s = String(value);
  if (s.length <= 12) {
    return s;
  }
  return `${s.slice(0, 8)}…${s.slice(-4)}`;
}

function sumHazards(clips) {
  if (!Array.isArray(clips)) {
    return null;
  }
  let total = 0;
  let hasField = false;
  for (const c of clips) {
    if (typeof c.n_hazards === "number") {
      total += c.n_hazards;
      hasField = true;
    }
  }
  return hasField ? total : null;
}

function pickFrozenMeta(clipsPayload, leaderboardPayload) {
  const sources = [leaderboardPayload, clipsPayload].filter(Boolean);
  let frozenAt = null;
  let hash = null;
  for (const src of sources) {
    if (frozenAt == null && src.frozen_at != null) {
      frozenAt = src.frozen_at;
    }
    if (hash == null) {
      hash =
        src.testset_sha256 ??
        src.sha256 ??
        src.hash ??
        null;
    }
  }
  return { frozenAt, hash };
}

function renderHome(root) {
  root.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "app-shell";

  const healthStrip = renderHealthStrip(shell);

  const header = document.createElement("header");
  header.className = "home-header";
  header.innerHTML = `
    <h1>Developing Hazard</h1>
    <p class="subtitle">An AI sits the hazard perception test.</p>
  `;
  shell.append(header);

  const grid = document.createElement("div");
  grid.className = "card-grid";
  grid.innerHTML = `
    <a class="card" href="#/sit/c07"><span class="card-title">Sit a clip yourself</span></a>
    <a class="card" href="#/watch/r_EXAMPLE_yolo_risk/c07"><span class="card-title">Watch the AI</span></a>
    <a class="card" href="#/leaderboard"><span class="card-title">Leaderboard</span></a>
  `;
  shell.append(grid);

  const devLink = document.createElement("p");
  devLink.className = "dev-link";
  devLink.innerHTML = '<a href="#/label/c07">Label a clip</a> (dev)';
  shell.append(devLink);

  const panel = document.createElement("section");
  panel.className = "panel";
  panel.innerHTML = `
    <h2>Test set</h2>
    <div class="stats-grid">
      <div><div class="stat-label">Clips</div><div class="stat-value mono" data-stat="clips">-</div></div>
      <div><div class="stat-label">Hazards</div><div class="stat-value mono" data-stat="hazards">-</div></div>
      <div><div class="stat-label">Frozen at</div><div class="stat-value mono" data-stat="frozen">-</div></div>
      <div><div class="stat-label">Hash</div><div class="stat-value mono" data-stat="hash">-</div></div>
    </div>
  `;
  shell.append(panel);

  root.append(shell);

  void fetchHealth().then(() => updateHealthStrip(healthStrip));

  void (async () => {
    let clips = null;
    let leaderboard = null;
    try {
      const res = await fetch("api/clips");
      if (res.ok) {
        clips = await res.json();
      }
    } catch {
      /* ignore */
    }
    try {
      const res = await fetch("api/leaderboard");
      if (res.ok) {
        leaderboard = await res.json();
      }
    } catch {
      /* ignore */
    }

    const clipList = Array.isArray(clips) ? clips : clips?.clips;
    const clipCount = Array.isArray(clipList) ? clipList.length : null;
    const hazardCount = sumHazards(clipList);
    const { frozenAt, hash } = pickFrozenMeta(clips, leaderboard);

    const setStat = (key, value) => {
      const el = panel.querySelector(`[data-stat="${key}"]`);
      if (el) {
        el.textContent = value;
      }
    };

    setStat("clips", clipCount != null ? String(clipCount) : "-");
    setStat("hazards", hazardCount != null ? String(hazardCount) : "-");
    setStat("frozen", frozenAt != null ? String(frozenAt) : "-");
    setStat("hash", hash != null ? shortHash(hash) : "-");
  })();
}

function renderOneLine(root, text) {
  root.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "app-shell route-screen";
  renderHealthStrip(shell);
  const p = document.createElement("p");
  p.textContent = text;
  shell.append(p);
  root.append(shell);
  void fetchHealth().then(() => {
    const strip = shell.querySelector(".health-strip");
    if (strip) {
      updateHealthStrip(strip);
    }
  });
}

async function renderLabel(root, clipId) {
  root.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "app-shell";
  renderHealthStrip(shell);
  const mountPoint = document.createElement("div");
  mountPoint.className = "route-screen";
  shell.append(mountPoint);
  root.append(shell);

  void fetchHealth().then(() => {
    const strip = shell.querySelector(".health-strip");
    if (strip) {
      updateHealthStrip(strip);
    }
  });

  try {
    const mod = await import("./label.js");
    if (typeof mod.mountLabel === "function") {
      mod.mountLabel(mountPoint, clipId, api);
      return;
    }
  } catch {
    /* fall through */
  }
  const msg = document.createElement("p");
  msg.textContent = "label screen not merged yet";
  mountPoint.append(msg);
}

function renderRoute() {
  const route = parseRoute();
  switch (route.name) {
    case "home":
      renderHome(appEl);
      break;
    case "label":
      void renderLabel(appEl, route.clipId);
      break;
    case "sit":
      renderOneLine(appEl, "Sit screen arrives in Phase 2.");
      break;
    case "watch":
      renderOneLine(appEl, "Watch screen arrives in Phase 2.");
      break;
    case "leaderboard":
      renderOneLine(appEl, "Leaderboard arrives in Phase 3.");
      break;
    default:
      renderOneLine(appEl, "Unknown route.");
  }
}

window.addEventListener("hashchange", renderRoute);
renderRoute();
