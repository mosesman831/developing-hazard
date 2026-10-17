"""Verdict grid (SPEC 12.3).

``grid_times`` and ``lookup`` choose and read grid points. ``fill_clip`` asks
the verdict model. The module entry point does not call the network.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dh.agents.base import CallResult
from dh.risk import features, scene_risk
from dh.track import IoUTracker

_UNCLEAR_ANSWER = {
    "act": "unclear",
    "motion": "unclear",
    "where": "unclear",
    "our_car": "unclear",
    "object": "",
}

_SECRET_MARKERS = (
    "bearer",
    "token",
    "password",
    "secret",
    "api_key",
    "api-key",
    "authorization",
)


def grid_times(
    samples: list[tuple[float, float]],
    duration_s: float,
    step_s: float = 0.5,
    risk_min: float = 0.3,
    dev_every_s: float = 3.0,
    include_dev_points: bool = True,
) -> list[float]:
    """Risk-threshold grid points plus optional dev check points every 3 s."""
    times: set[float] = set()
    for t, raw_scene_risk in samples:
        if raw_scene_risk >= risk_min:
            snapped = round(t / step_s) * step_s
            times.add(snapped)
    if include_dev_points:
        t = 0.0
        while t < duration_s:
            times.add(t)
            t += dev_every_s
    return sorted(times)


def lookup(points: list[dict], t: float) -> dict | None:
    """Latest point with point['t'] <= t. None if none."""
    best: dict | None = None
    for point in points:
        pt = float(point["t"])
        if pt <= t and (best is None or pt > float(best["t"])):
            best = point
    return best


def is_hazard(answer: dict) -> bool:
    """Appendix A.1. HAZARD iff act==yes AND (motion==moving_into_our_path OR where==in_our_lane) AND our_car != stopped. Missing keys are not a hazard."""
    if not isinstance(answer, dict):
        return False
    try:
        act = answer["act"]
        motion = answer["motion"]
        where = answer["where"]
        our_car = answer["our_car"]
    except KeyError:
        return False
    return (
        act == "yes"
        and (motion == "moving_into_our_path" or where == "in_our_lane")
        and our_car != "stopped"
    )


def parse_answer(raw: str) -> dict:
    """Parse the JSON object from a model reply. If parsing fails, return {"act":"unclear","motion":"unclear","where":"unclear","our_car":"unclear","object":""}."""
    if not isinstance(raw, str):
        return dict(_UNCLEAR_ANSWER)
    text = raw.strip().lstrip("\ufeff")
    parsed = _json_object(text)
    if parsed is None:
        return dict(_UNCLEAR_ANSWER)
    return parsed


class GridVerifier:
    """Harness-side lookup. answer(clip_id, t, track_id) -> CallResult.

    Latest grid point with point['t'] <= t.
    If that point's track_id is set and differs from the requested track_id,
    is_hazard is False (unclear, never clicks).
    latency_s is the stored measured latency, or 0.
    object is the answer object string.
    """

    def __init__(self, points: list[dict] | None = None, path=None) -> None:
        if path is not None:
            points = load_grid(path)
        self.points = list(points or [])

    def answer(self, clip_id, t: float, track_id) -> CallResult:
        candidates = []
        for point in self.points:
            point_clip = point.get("clip_id")
            if point_clip is not None and point_clip != clip_id:
                continue
            candidates.append(point)
        point = lookup(candidates, float(t))
        if point is None:
            return CallResult(latency_s=0.0, is_hazard=False, object="", track_id=track_id)

        answer = point.get("answer")
        if isinstance(answer, str):
            answer = parse_answer(answer)
        if not isinstance(answer, dict):
            answer = {}
        obj = answer.get("object", "")
        if not isinstance(obj, str):
            obj = "" if obj is None else str(obj)

        latency = point.get("latency_s")
        latency_s = 0.0 if latency is None else float(latency)
        hazard = bool(point["is_hazard"]) if "is_hazard" in point else is_hazard(answer)
        point_track = point.get("track_id")
        if point_track is not None and point_track != track_id:
            hazard = False
        return CallResult(
            latency_s=latency_s,
            is_hazard=hazard,
            object=obj,
            track_id=track_id,
        )


def load_grid(path) -> list[dict]:
    """Read a JSONL verdict grid. A missing file is an empty grid."""
    file = Path(path)
    if not file.is_file():
        return []
    rows: list[dict] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def save_grid(path, rows) -> None:
    """Write rows as JSON lines, one object per line."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    text = ("\n".join(lines) + "\n") if lines else ""
    file.write_text(text, encoding="utf-8")


def fill_clip(
    clip,
    dets,
    frames,
    *,
    client=None,
    prompt,
    model,
    in_flight=2,
    prompt_version="cosmos_verify_v2",
) -> list[dict]:
    """Do not call this from tests with a real client.

    frames: list of {t, path or jpeg_b64}. dets: detection dicts.
    Build scene-risk samples with IoUTracker + risk.features + scene_risk (raw, no EMA).
    Times from grid_times(..., include_dev_points=clip split==dev).
    For each time, top-risk track at the nearest sample at or before t.
    Send frames in [t-2, t], up to 8, oldest first, as data URLs or raw strings
    already prepared by the caller in frame['jpeg_b64'].
    At most `in_flight` concurrent client calls.
    client(frames_b64, prompt, model) -> {"raw": str, "latency_s": float}.
    Store t, track_id, prompt_version, answer, is_hazard, raw, latency_s, error
    (None or a short string with no secrets).
    """
    if client is None:
        from dh.clients.cosmos import verify_frames

        def client(frames_b64, prompt, model):
            started = time.perf_counter()
            try:
                payload = verify_frames(frames_b64, prompt, model=model)
            except Exception as exc:
                return {
                    "raw": "",
                    "latency_s": time.perf_counter() - started,
                    "error": type(exc).__name__,
                }
            return {
                "raw": _choice_text(payload),
                "latency_s": time.perf_counter() - started,
            }

    duration_s = float(_field(clip, "duration_s", 0.0) or 0.0)
    include_dev_points = _field(clip, "split", None) == "dev"
    frame_wh = _frame_wh(clip)
    samples = _risk_samples(dets, frame_wh)
    times = grid_times(
        [(sample[0], sample[1]) for sample in samples],
        duration_s,
        include_dev_points=include_dev_points,
    )
    jobs = [
        {
            "t": t,
            "track_id": _top_track_id(samples, t),
            "frames": _frames_for(frames, t),
            "prompt_version": prompt_version,
        }
        for t in times
    ]
    if not jobs:
        return []

    def run(index: int, job: dict) -> tuple[int, dict]:
        try:
            payload = client(job["frames"], prompt, model)
        except Exception as exc:
            payload = {"raw": "", "latency_s": 0.0, "error": type(exc).__name__}
        return index, _row_from_payload(job, payload)

    results: list[dict | None] = [None] * len(jobs)
    workers = max(1, int(in_flight))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, index, job) for index, job in enumerate(jobs)]
        for future in as_completed(futures):
            index, row = future.result()
            results[index] = row
    return [row for row in results if row is not None]


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--fill" in args:
        print("grid fill is run by the phase runner")
        return
    print("grid: offline stub, cosmos fill is phase 3")


def _json_object(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                if isinstance(parsed, dict):
                    return parsed
                return None
    return None


def _field(obj, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _frame_wh(clip) -> tuple[float, float]:
    raw = _field(clip, "frame_wh", None)
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return (float(raw[0]), float(raw[1]))
    return (1920.0, 1080.0)


def _det_time(det) -> float:
    if isinstance(det, dict):
        return float(det["t"])
    return float(det.t)


def _risk_samples(dets, frame_wh) -> list[tuple[float, float, list]]:
    """Raw scene risk at each detection time. No EMA."""
    grouped: dict[float, list] = {}
    for det in dets:
        grouped.setdefault(_det_time(det), []).append(det)
    tracker = IoUTracker()
    samples: list[tuple[float, float, list]] = []
    for t in sorted(grouped):
        tracks = tracker.update(t, grouped[t])
        feats = [features(track, frame_wh) for track in tracks]
        samples.append((t, float(scene_risk(feats)), feats))
    return samples


def _top_track_id(samples: list[tuple[float, float, list]], t: float):
    best: tuple[float, float, list] | None = None
    for sample in samples:
        if sample[0] <= t and (best is None or sample[0] > best[0]):
            best = sample
    if best is None or not best[2]:
        return None
    top = max(best[2], key=lambda feat: float(feat.risk))
    return top.track_id


def _frames_for(frames, t: float, context_s: float = 2.0, limit: int = 8) -> list[str]:
    chosen: list[tuple[float, str]] = []
    for frame in frames:
        stamp = float(frame["t"])
        if stamp < t - context_s or stamp > t:
            continue
        token = _frame_token(frame)
        if token is None:
            continue
        chosen.append((stamp, token))
    chosen.sort(key=lambda item: item[0])
    if len(chosen) > limit:
        chosen = chosen[-limit:]
    return [token for _, token in chosen]


def _frame_token(frame: dict) -> str | None:
    raw = frame.get("jpeg_b64")
    if isinstance(raw, str) and raw:
        return raw
    path = frame.get("path")
    if not isinstance(path, str) or not path:
        return None
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _row_from_payload(job: dict, payload) -> dict:
    raw = ""
    latency_s = 0.0
    error = None
    if not isinstance(payload, dict):
        error = "bad client result"
    else:
        raw_value = payload.get("raw", "")
        raw = raw_value if isinstance(raw_value, str) else ""
        if payload.get("latency_s") is not None:
            latency_s = float(payload["latency_s"])
        err = payload.get("error")
        if err:
            error = _safe_text(str(err))
    answer = parse_answer(raw)
    return {
        "t": job["t"],
        "track_id": job["track_id"],
        "prompt_version": job["prompt_version"],
        "answer": answer,
        "is_hazard": is_hazard(answer),
        "raw": raw,
        "latency_s": latency_s,
        "error": error,
    }


def _safe_text(text: str) -> str:
    compact = " ".join(text.split())
    lowered = compact.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return "client error"
    if len(compact) > 160:
        return compact[:160]
    return compact or "client error"


def _choice_text(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


if __name__ == "__main__":
    main()
