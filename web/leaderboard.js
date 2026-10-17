/**
 * Leaderboard (SPEC 16.7). Numbers come from the API. Example boards are labelled.
 */

const LATENCY = [
  { id: "measured", label: "measured" },
  { id: "fixed:0.5", label: "0.5 s" },
  { id: "fixed:1", label: "1 s" },
  { id: "fixed:2", label: "2 s" },
  { id: "fixed:4", label: "4 s" },
  { id: "zero", label: "zero" },
];

export function mountLeaderboard(el) {
  el.replaceChildren();
  const shell = document.createElement("section");
  shell.className = "leaderboard";
  const title = document.createElement("h1");
  title.textContent = "Leaderboard";
  const banner = document.createElement("p");
  banner.className = "example-banner";
  banner.hidden = true;
  const toggle = document.createElement("div");
  toggle.className = "latency-toggle";
  const note = document.createElement("p");
  note.className = "muted";
  const tableHost = document.createElement("div");
  const legend = document.createElement("p");
  legend.className = "muted";
  legend.textContent = "DVSA car pass rate (44/75), for reference only";
  const humansHost = document.createElement("div");
  const typesHost = document.createElement("div");
  shell.append(title, banner, toggle, note, legend, tableHost, humansHost, typesHost);
  el.append(shell);

  let selected = "";

  function paintToggle(active) {
    toggle.replaceChildren();
    for (const mode of LATENCY) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = mode.label;
      button.setAttribute("aria-pressed", mode.id === active ? "true" : "false");
      button.addEventListener("click", () => {
        selected = mode.id;
        void load(mode.id);
      });
      toggle.append(button);
    }
  }

  async function load(latency) {
    paintToggle(latency);
    const query = latency ? `?latency=${encodeURIComponent(latency)}` : "";
    let board = null;
    try {
      const response = await fetch(`api/leaderboard${query}`);
      if (response.ok) {
        board = await response.json();
      }
    } catch {
      board = null;
    }
    if (!board) {
      tableHost.textContent = "Leaderboard could not be loaded.";
      return;
    }
    const example = typeof board._note === "string" && board._note.length > 0;
    banner.hidden = !example;
    banner.textContent = example
      ? "Example data. Not a result."
      : "";
    if (board.latency_applied === false) {
      note.textContent = "This board is not split by latency. The same rows are shown for every toggle.";
    } else if (latency) {
      note.textContent = `Latency ${labelFor(latency)}.`;
    } else {
      note.textContent = "";
    }
    paintTable(tableHost, board);
    paintHumans(humansHost, board);
    paintTypes(typesHost, board);
  }

  void load(selected);
}

function labelFor(id) {
  const found = LATENCY.find((mode) => mode.id === id);
  return found ? found.label : id;
}

function paintTable(host, board) {
  host.replaceChildren();
  const rows = Array.isArray(board.rows) ? board.rows : [];
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No leaderboard rows.";
    host.append(empty);
    return;
  }
  const table = document.createElement("table");
  table.className = "board";
  const head = document.createElement("tr");
  for (const label of [
    "Rank",
    "Name",
    "Kind",
    "Score",
    "Pct",
    "Lift over chance",
    "Hit rate",
    "Pattern rate",
    "Median reaction",
    "Mean latency",
  ]) {
    const cell = document.createElement("th");
    cell.textContent = label;
    head.append(cell);
  }
  table.append(head);
  const reference = Number(board.dvsa_reference_pct);
  const max = board.max;
  rows.forEach((row, index) => {
    const tr = document.createElement("tr");
    const score = row.score == null ? "-" : String(row.score);
    const maxText = max == null ? "-" : String(max);
    const cells = [
      String(index + 1),
      row.name || "-",
      row.kind || "-",
      `${score} / ${maxText}`,
      null,
      formatNumber(row.lift_vs_chance),
      formatNumber(row.hit_rate),
      formatNumber(row.pattern_rate),
      formatSeconds(row.reaction_s),
      formatSeconds(row.latency_s),
    ];
    cells.forEach((value, cellIndex) => {
      const td = document.createElement("td");
      if (cellIndex === 4) {
        td.append(intervalBar(row.pct, row.ci90, reference));
      } else {
        td.textContent = value;
        if (cellIndex !== 1 && cellIndex !== 2) {
          td.className = "mono";
        }
      }
      tr.append(td);
    });
    table.append(tr);
  });
  host.append(table);
}

function intervalBar(pct, ci90, reference) {
  const wrap = document.createElement("div");
  wrap.className = "interval";
  const track = document.createElement("div");
  track.className = "interval-track";
  if (typeof pct === "number") {
    const fill = document.createElement("div");
    fill.className = "interval-fill";
    fill.style.width = `${Math.max(0, Math.min(1, pct)) * 100}%`;
    track.append(fill);
  }
  if (Array.isArray(ci90) && ci90.length >= 2 && typeof ci90[0] === "number" && typeof ci90[1] === "number") {
    const range = document.createElement("div");
    range.className = "interval-ci";
    const start = Math.max(0, Math.min(1, ci90[0]));
    const end = Math.max(0, Math.min(1, ci90[1]));
    range.style.left = `${start * 100}%`;
    range.style.width = `${Math.max(0, end - start) * 100}%`;
    track.append(range);
  }
  if (Number.isFinite(reference)) {
    const line = document.createElement("div");
    line.className = "dvsa-line";
    line.style.left = `${Math.max(0, Math.min(1, reference)) * 100}%`;
    line.title = "DVSA car pass rate (44/75), for reference only";
    track.append(line);
  }
  const caption = document.createElement("span");
  caption.className = "mono";
  caption.textContent = typeof pct === "number" ? `${(pct * 100).toFixed(1)}%` : "-";
  wrap.append(track, caption);
  return wrap;
}

function paintHumans(host, board) {
  host.replaceChildren();
  const fullHeading = document.createElement("h2");
  fullHeading.textContent = "Full set";
  host.append(fullHeading);
  const full = Array.isArray(board.full_set_humans) ? board.full_set_humans : [];
  const fullRows = (Array.isArray(board.rows) ? board.rows : []).filter((row) => row.kind === "human");
  const shown = full.length ? full : fullRows;
  if (!shown.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No one has sat the full test set.";
    host.append(empty);
  } else {
    host.append(simpleTable(["Name", "Score", "Clips"], shown.map((row) => [
      row.name || "-",
      row.score == null ? "-" : String(row.score),
      row.n_clips == null ? "-" : String(row.n_clips),
    ])));
  }

  const heading = document.createElement("h2");
  heading.textContent = "Per clip";
  host.append(heading);
  const perClip = Array.isArray(board.per_clip) ? board.per_clip : [];
  if (!perClip.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No blind human sits recorded.";
    host.append(empty);
    return;
  }
  host.append(simpleTable(
    ["Clip", "Human", "Human score", "Best agent", "Best agent score"],
    perClip.map((row) => [
      row.clip_id || "-",
      row.name || "-",
      row.human_score == null ? "-" : String(row.human_score),
      row.best_agent || "-",
      row.best_agent_score == null ? "-" : String(row.best_agent_score),
    ]),
  ));
}

function paintTypes(host, board) {
  host.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = "Hazard types";
  host.append(heading);
  const rows = typeRows(board);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No hazard-type breakdown in this board.";
    host.append(empty);
    return;
  }
  const chart = document.createElement("div");
  chart.className = "type-chart";
  const peak = Math.max(...rows.map((row) => row.value), 1);
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "type-bar";
    const label = document.createElement("span");
    label.textContent = row.label;
    const track = document.createElement("div");
    track.className = "interval-track";
    const fill = document.createElement("div");
    fill.className = "interval-fill";
    fill.style.width = `${(row.value / peak) * 100}%`;
    track.append(fill);
    const value = document.createElement("span");
    value.className = "mono";
    value.textContent = String(row.value);
    item.append(label, track, value);
    chart.append(item);
  }
  host.append(chart);
}

function typeRows(board) {
  const source = board.by_type || board.hazard_types;
  if (!Array.isArray(source)) {
    return [];
  }
  const rows = [];
  for (const item of source) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const label = item.type || item.name || item.hazard_type;
    const value = firstNumber(item, ["points", "score", "mean", "mean_points"]);
    if (!label || value == null) {
      continue;
    }
    rows.push({ label: String(label), value });
  }
  return rows;
}

function firstNumber(item, keys) {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "number" && !Number.isNaN(value)) {
      return value;
    }
  }
  return null;
}

function simpleTable(headers, rows) {
  const table = document.createElement("table");
  table.className = "board";
  const head = document.createElement("tr");
  for (const header of headers) {
    const cell = document.createElement("th");
    cell.textContent = header;
    head.append(cell);
  }
  table.append(head);
  for (const row of rows) {
    const tr = document.createElement("tr");
    row.forEach((value, index) => {
      const td = document.createElement("td");
      td.textContent = value;
      if (index > 0) {
        td.className = "mono";
      }
      tr.append(td);
    });
    table.append(tr);
  }
  return table;
}

function formatNumber(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

function formatSeconds(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${value.toFixed(2)} s`;
}
