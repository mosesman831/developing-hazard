"""Detections loader (SPEC 7.4). CrossWise sidecars with optional YOLO fallback."""

from __future__ import annotations

import base64
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import dh.config as config

KEEP_CLASSES = frozenset(
    {
        "person",
        "bicycle",
        "car",
        "motorcycle",
        "bus",
        "truck",
        "traffic light",
        "stop sign",
        "dog",
    }
)

_LABEL_ALIASES = {
    "traffic_light": "traffic light",
    "stop_sign": "stop sign",
}

_TIME_GRID_TOL = 1e-3


def _normalise_label(raw: Any) -> str | None:
    if raw is None:
        return None
    label = str(raw).strip().lower()
    label = _LABEL_ALIASES.get(label, label)
    return label


def _frame_shape(payload: dict) -> tuple[float, float] | None:
    shape = payload.get("video_shape")
    if shape is None:
        wh = payload.get("width"), payload.get("height")
        if wh[0] is not None and wh[1] is not None:
            return float(wh[0]), float(wh[1])
        h = payload.get("h")
        w = payload.get("w")
        if h is not None and w is not None:
            return float(w), float(h)
        return None
    if isinstance(shape, dict):
        w = shape.get("width", shape.get("w"))
        h = shape.get("height", shape.get("h"))
        if w is not None and h is not None:
            return float(w), float(h)
        return None
    if isinstance(shape, (list, tuple)) and len(shape) >= 2:
        h, w = shape[0], shape[1]
        return float(w), float(h)
    return None


def _parse_xyxy(bbox: Any) -> list[float] | None:
    if bbox is None:
        return None
    if isinstance(bbox, dict):
        try:
            return [
                float(bbox["x1"]),
                float(bbox["y1"]),
                float(bbox["x2"]),
                float(bbox["y2"]),
            ]
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        except (TypeError, ValueError):
            return None
    return None


def _box_height(xyxy: list[float]) -> float:
    return abs(xyxy[3] - xyxy[1])


def _should_keep_frame(
    frame_index: int,
    time_sec: float,
    fps: float | None,
    fps_sample: int,
) -> bool:
    if fps is not None and fps > 0:
        step = fps / fps_sample
        if step <= 0:
            return True
        step_i = int(step) if step == int(step) else int(round(step))
        if step_i <= 0:
            step_i = 1
        return frame_index % step_i == 0
    grid = 1.0 / fps_sample
    return abs(time_sec - round(time_sec / grid) * grid) <= _TIME_GRID_TOL


def _filter_frames_no_fps(frames: list[dict], fps_sample: int) -> list[tuple[int, dict]]:
    grid = 1.0 / fps_sample
    seen_bins: set[int] = set()
    kept: list[tuple[int, dict]] = []
    for idx, frame in enumerate(frames):
        if not isinstance(frame, dict):
            continue
        try:
            time_sec = float(frame.get("time_sec", 0.0))
        except (TypeError, ValueError):
            continue
        on_grid = abs(time_sec - round(time_sec / grid) * grid) <= _TIME_GRID_TOL
        if not on_grid:
            continue
        bin_idx = int(math.floor(time_sec / grid + 1e-12))
        if bin_idx in seen_bins:
            continue
        seen_bins.add(bin_idx)
        kept.append((idx, frame))
    return kept


def _parse_detections_impl(
    payload: dict,
    start_s: float,
) -> tuple[list[dict], tuple[float, float] | None, int]:
    """Return rows, frame size, and count of subsampled frames."""
    frame_wh = _frame_shape(payload)
    fps_raw = payload.get("fps")
    fps: float | None
    if fps_raw is None:
        fps = None
    else:
        try:
            fps = float(fps_raw)
        except (TypeError, ValueError):
            fps = None

    fps_sample = config.fps_sample
    conf_min = config.det_conf_min
    min_h_frac = config.min_box_h

    frames_raw = payload.get("frames")
    if not isinstance(frames_raw, list):
        frames_raw = []

    frame_h = frame_wh[1] if frame_wh is not None else None

    if fps is not None and fps > 0:
        frame_iter: list[tuple[int, dict]] = []
        for idx, frame in enumerate(frames_raw):
            if not isinstance(frame, dict):
                continue
            try:
                time_sec = float(frame.get("time_sec", 0.0))
            except (TypeError, ValueError):
                continue
            if _should_keep_frame(idx, time_sec, fps, fps_sample):
                frame_iter.append((idx, frame))
    else:
        frame_iter = _filter_frames_no_fps(frames_raw, fps_sample)

    rows: list[dict] = []
    out_frame = 0
    for _src_index, frame in frame_iter:
        try:
            time_sec = float(frame.get("time_sec", 0.0))
        except (TypeError, ValueError):
            time_sec = 0.0
        clip_t = start_s + time_sec
        dets_raw = frame.get("detections")
        if not isinstance(dets_raw, list):
            out_frame += 1
            continue
        frame_rows: list[dict] = []
        for det in dets_raw:
            if not isinstance(det, dict):
                continue
            label = _normalise_label(det.get("label", det.get("cls")))
            if label is None or label not in KEEP_CLASSES:
                continue
            conf_raw = det.get("confidence", det.get("conf"))
            try:
                conf = float(conf_raw)
            except (TypeError, ValueError):
                continue
            if conf < conf_min:
                continue
            xyxy = _parse_xyxy(det.get("bbox"))
            if xyxy is None:
                continue
            if frame_h is not None and _box_height(xyxy) < min_h_frac * frame_h:
                continue
            frame_rows.append(
                {
                    "t": clip_t,
                    "frame": out_frame,
                    "cls": label,
                    "conf": conf,
                    "xyxy": xyxy,
                }
            )
        rows.extend(frame_rows)
        out_frame += 1

    return rows, frame_wh, out_frame


def parse_detections(
    payload: dict,
    start_s: float,
) -> tuple[list[dict], tuple[float, float] | None]:
    """Parse CrossWise-style detection JSON into clip-time rows."""
    rows, frame_wh, _kept = _parse_detections_impl(payload, start_s)
    return rows, frame_wh


def frames_from_dets(dets: list[dict]) -> list[tuple[float, str, list[dict]]]:
    """Group detections by clip time, sorted."""
    by_t: dict[float, list[dict]] = {}
    for row in dets:
        t = float(row["t"])
        by_t.setdefault(t, []).append(row)
    return [(t, "", by_t[t]) for t in sorted(by_t)]


def _cache_path(clip_id: str, data_dir: Path) -> Path:
    return data_dir / "det" / f"{clip_id}.jsonl"


def _read_cache(path: Path) -> tuple[list[dict], tuple[float, float] | None]:
    dets: list[dict] = []
    frame_wh: tuple[float, float] | None = None
    if not path.is_file():
        return dets, frame_wh
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict) and obj.get("_meta") == "frame_wh":
            wh = obj.get("wh")
            if isinstance(wh, (list, tuple)) and len(wh) >= 2:
                frame_wh = (float(wh[0]), float(wh[1]))
            continue
        if isinstance(obj, dict):
            dets.append(obj)
    return dets, frame_wh


def _write_cache(
    path: Path,
    dets: list[dict],
    frame_wh: tuple[float, float] | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if frame_wh is not None:
        lines.append(
            json.dumps({"_meta": "frame_wh", "wh": [frame_wh[0], frame_wh[1]]})
        )
    for row in dets:
        lines.append(json.dumps(row, separators=(",", ":")))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_clip(
    clip: dict,
    client=None,
    yolo_infer=None,
    read_video=None,
    data_dir: str | Path | None = None,
) -> dict:
    """Load detections for a clip, with disk cache and optional YOLO fallback."""
    clip_id = str(clip["clip_id"])
    base = Path(data_dir if data_dir is not None else config.DATA_DIR)
    cache = _cache_path(clip_id, base)

    if cache.is_file():
        dets, frame_wh = _read_cache(cache)
        return {
            "clip_id": clip_id,
            "frame_wh": frame_wh,
            "dets": dets,
            "errors": [],
        }

    segments = clip.get("segments") or []
    if not isinstance(segments, list):
        segments = []

    all_dets: list[dict] = []
    frame_wh: tuple[float, float] | None = None
    errors: list[str] = []
    sources_seen: set[str] = set()
    any_success = False
    frame_offset = 0

    infer_fn: Callable[..., dict] | None = yolo_infer

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        source = seg.get("source")
        if not source or not isinstance(source, str):
            continue
        if source in sources_seen:
            continue
        sources_seen.add(source)
        try:
            start_s = float(seg.get("start_s", 0.0))
        except (TypeError, ValueError):
            start_s = 0.0

        payload: dict | None = None
        err_msg: str | None = None

        if client is not None:
            try:
                payload = client.detections(source)
            except Exception as exc:
                err_msg = f"{source}: {exc}"

        if payload is None:
            if infer_fn is None:
                try:
                    from dh.clients.yolo import infer as _default_infer

                    infer_fn = _default_infer
                except ImportError:
                    infer_fn = None

            video_bytes: bytes | None = None
            if read_video is not None:
                try:
                    video_bytes = read_video(source)
                except Exception:
                    video_bytes = None

            if infer_fn is not None and video_bytes:
                try:
                    video_b64 = base64.b64encode(video_bytes).decode("ascii")
                    payload = infer_fn(video_b64, include_frames=True)
                    err_msg = None
                except Exception as exc:
                    if err_msg:
                        err_msg = f"{err_msg}; yolo: {exc}"
                    else:
                        err_msg = f"{source}: yolo: {exc}"
            elif err_msg is None:
                err_msg = f"{source}: no detections source"

        if payload is None:
            if err_msg:
                errors.append(err_msg)
            continue

        any_success = True
        rows, seg_wh, kept_frames = _parse_detections_impl(payload, start_s)
        if frame_wh is None and seg_wh is not None:
            frame_wh = seg_wh
        for row in rows:
            row = dict(row)
            row["frame"] = int(row["frame"]) + frame_offset
            all_dets.append(row)
        frame_offset += kept_frames

    if any_success:
        _write_cache(cache, all_dets, frame_wh)

    return {
        "clip_id": clip_id,
        "frame_wh": frame_wh,
        "dets": all_dets,
        "errors": errors,
    }


def _usage() -> str:
    return "usage: python -m dh.dets <clip.json>  # load detections for one clip"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(_usage())
        return 0
    print(_usage(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
