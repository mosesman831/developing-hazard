"""Miss explanations (SPEC 7.12).

Builds a short context for each hazard an agent scored 0 or 1, asks the
W&B LLM with prompts/explain_miss_v1.txt, and caches the reply.
approved is always false. Only Moses sets it true.
"""

from __future__ import annotations

import json
from pathlib import Path

import dh.config as dh_config

_PROMPT_NAME = "explain_miss_v1.txt"
_PROMPT_VERSION = "explain_miss_v1"
_MISS_POINTS = frozenset({0, 1})
_NEAR_S = 3.0
_TOP_BOXES = 3
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _fill(template: str, fields: dict[str, str]) -> str:
    text = template
    for key, value in fields.items():
        text = text.replace("{" + key + "}", value)
    return text


def _window_distance(t: float, ws: float, we: float) -> float:
    if t < ws:
        return ws - t
    if t > we:
        return t - we
    return 0.0


def _click_text(clicks: list) -> str:
    if not clicks:
        return "none"
    times = []
    for click in clicks:
        if isinstance(click, dict):
            times.append(str(click.get("t")))
        else:
            times.append(str(click))
    return ", ".join(times)


def risk_summary(curve: list, ws: float, we: float) -> str:
    """Min and max of risk samples whose time is inside the window."""
    inside: list[float] = []
    for sample in curve or []:
        if not isinstance(sample, (list, tuple)) or len(sample) < 2:
            continue
        t = float(sample[0])
        if ws <= t <= we:
            inside.append(float(sample[1]))
    if not inside:
        return "no samples inside the window"
    return (
        f"{len(inside)} samples inside the window, "
        f"min {min(inside)}, max {max(inside)}"
    )


def verdict_summary(points: list[dict], ws: float, we: float) -> str:
    """Grid points within 3 s of the window, using the stored is_hazard flag."""
    chosen = []
    for point in points:
        if "t" not in point:
            continue
        t = float(point["t"])
        if _window_distance(t, ws, we) > _NEAR_S:
            continue
        label = "HAZARD" if point.get("is_hazard") is True else "NO_HAZARD"
        chosen.append(f"t={t} {label}")
    if not chosen:
        return "no grid points within 3 s of the window"
    return "; ".join(chosen)


def _box_area(row: dict) -> float:
    raw = row.get("xyxy") or []
    if len(raw) < 4:
        return 0.0
    width = float(raw[2]) - float(raw[0])
    height = float(raw[3]) - float(raw[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    return width * height


def track_summary(rows: list[dict], ws: float) -> str:
    """Up to three boxes at the sample time closest to the window start.

    Stored tracks keep t and xyxy. There is no track id to rank by risk.
    """
    timed = [row for row in rows if "t" in row and row.get("xyxy")]
    if not timed:
        return "none"
    # Closest sample to the window start. Ties take the earlier time.
    nearest = min(
        (float(row["t"]) for row in timed),
        key=lambda t: (abs(t - ws), t),
    )
    boxes = [row for row in timed if float(row["t"]) == nearest]
    boxes.sort(key=_box_area, reverse=True)
    parts = []
    for row in boxes[:_TOP_BOXES]:
        parts.append(f"t={nearest} xyxy={row.get('xyxy')}")
    return "; ".join(parts) if parts else "none"


def _reply_text(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("W&B reply has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("W&B reply choice is not an object")
    message = first.get("message") or {}
    if not isinstance(message, dict):
        raise RuntimeError("W&B reply has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("W&B reply has no text")
    return content.strip()


def _model_id(payload: dict) -> str | None:
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                return item["id"]
    if isinstance(payload.get("id"), str) and payload["id"]:
        return payload["id"]
    return None


def _default_complete(prompt: str) -> str:
    from dh.clients.wandb_llm import complete, list_models

    model = _model_id(list_models())
    if not model:
        raise RuntimeError("W&B model list has no id")
    # 160 tokens came back with empty content: the first listed model
    # spends the budget on a reasoning field. 800 left a short answer.
    _default_complete.last_model = model
    payload = complete(prompt, model=model, max_tokens=800)
    if not isinstance(payload, dict):
        raise RuntimeError("W&B reply is not an object")
    return _reply_text(payload)


def explain_run(
    run_id: str,
    data_dir: str | Path | None = None,
    complete=None,
) -> list[str]:
    """Cache an explanation for each hazard this run scored 0 or 1.

    complete(prompt) -> str. The default calls the W&B client. The cache
    file is data/cache/explain/<run_id>/<hazard_id>.json and approved is
    false. Returns the hazard ids written. A model failure writes nothing
    for that hazard.
    """
    root = Path(data_dir) if data_dir is not None else Path(dh_config.DATA_DIR)
    run_dir = root / "runs" / run_id
    clip_rows = _read_jsonl(run_dir / "clips.jsonl")
    hazards = _read_json(root / "hazards.json")
    if not isinstance(hazards, list):
        raise ValueError("hazards.json is not a list")
    by_id = {
        item.get("hazard_id"): item
        for item in hazards
        if isinstance(item, dict) and item.get("hazard_id")
    }
    template = (_REPO_ROOT / "prompts" / _PROMPT_NAME).read_text(encoding="utf-8")
    caller = complete if complete is not None else _default_complete

    written: list[str] = []
    for row in clip_rows:
        clip_id = row.get("clip_id")
        points_map = row.get("hazard_points") or {}
        if not isinstance(points_map, dict):
            continue
        curve = row.get("risk_curve") or []
        clicks = row.get("clicks") or []
        for hazard_id, points in points_map.items():
            try:
                scored = int(points)
            except (TypeError, ValueError):
                continue
            if scored not in _MISS_POINTS:
                continue
            hazard = by_id.get(hazard_id)
            if not isinstance(hazard, dict):
                continue
            ws = float(hazard["window_start"])
            we = float(hazard["window_end"])
            description = str(hazard.get("description") or "")
            grid = _read_jsonl(root / "grid" / "cosmos_verify_v2" / f"{clip_id}.jsonl")
            tracks = _read_jsonl(root / "tracks" / f"{clip_id}.jsonl")
            prompt = _fill(
                template,
                {
                    "points": str(scored),
                    "description": description,
                    "ws": str(ws),
                    "we": str(we),
                    "clicks": _click_text(clicks),
                    "risk_summary": risk_summary(curve, ws, we),
                    "verdicts": verdict_summary(grid, ws, we),
                    "tracks": track_summary(tracks, ws),
                },
            )
            text = caller(prompt)
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError(f"no explanation text for {hazard_id}")
            cache_dir = root / "cache" / "explain" / run_id
            cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": run_id,
                "hazard_id": hazard_id,
                "clip_id": clip_id,
                "points": scored,
                "text": text.strip(),
                "approved": False,
                "prompt_version": _PROMPT_VERSION,
            }
            model = getattr(caller, "last_model", None)
            if isinstance(model, str) and model:
                payload["model"] = model
            (cache_dir / f"{hazard_id}.json").write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
            written.append(str(hazard_id))
    return written
