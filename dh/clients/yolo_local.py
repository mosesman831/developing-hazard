"""Local YOLO fallback (no network, no keys).

Runs Ultralytics YOLO on the CPU over a local video and returns the same
payload shape as the GPU service in ``dh.clients.yolo.infer`` (CrossWise
style), so ``dh.dets`` parses either without knowing which one ran:

    {"fps": 30.0, "video_shape": [h, w], "model": "yolo11n.pt",
     "frames": [{"time_sec": 0.0, "detections": [
         {"label": "car", "confidence": 0.91, "bbox": [x1, y1, x2, y2]}]}]}

Only frames on the ``fps_sample`` grid are decoded into the model, and only
the classes ``dh.dets`` keeps are asked for. Boxes are in source pixels.
"""

from __future__ import annotations

import os
from pathlib import Path

# COCO ids of the classes dh.dets.KEEP_CLASSES keeps
_COCO_KEEP = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 9: "traffic light", 11: "stop sign", 16: "dog"}
_MODEL_CACHE: dict[str, object] = {}


def available() -> bool:
    """True when ultralytics and OpenCV import."""
    try:
        import cv2  # noqa: F401
        import ultralytics  # noqa: F401
    except ImportError:
        return False
    return True


def _model(name: str):
    if name not in _MODEL_CACHE:
        from ultralytics import YOLO

        _MODEL_CACHE[name] = YOLO(name)
    return _MODEL_CACHE[name]


MOTION_MIN_CONF = 0.08       # a low-confidence box is kept only if it moves and persists
MOTION_COVER = 0.2           # share of the box that must be moving pixels
MOTION_WARMUP_S = 0.6        # the background model needs this long before its mask means anything


def detect_video(
    path: str | Path,
    *,
    fps_sample: int = 5,
    model: str | None = None,
    imgsz: int | None = None,
    conf: float = 0.2,
    motion: bool = False,
    progress=None,
) -> dict:
    """Detect objects on the fps_sample grid of a local video.

    ``motion=True`` (a fixed camera only: its background stands still) adds a background model.
    A box the detector is unsure of (``MOTION_MIN_CONF`` up to ``conf``), say a car at night behind its
    own headlights, is kept when at least ``MOTION_COVER`` of it is moving pixels and a box of the
    same kind is there in two neighbouring samples too. It keeps its real confidence and is
    marked ``"motion": <cover>``, so nothing downstream mistakes it for a confident detection.
    """
    import cv2
    import numpy as np

    name = model or os.environ.get("DH_LOCAL_YOLO", "yolo11n.pt")
    # a fixed camera sees small, far objects, so it gets the larger input; a dashcam's are big and near
    size = int(imgsz or os.environ.get("DH_LOCAL_IMGSZ") or (1280 if motion else 960))
    try:
        import torch

        torch.set_num_threads(max(1, os.cpu_count() or 1))
    except ImportError:
        pass
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video {Path(path).name}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(fps / fps_sample)))
    yolo = _model(name)
    scale = 640.0 / max(1, width)
    mog = cv2.createBackgroundSubtractorMOG2(history=int(fps * 8), varThreshold=25, detectShadows=False) if motion else None
    kernel = np.ones((3, 3), np.uint8)
    frames: list[dict] = []
    low = MOTION_MIN_CONF if mog is not None else conf
    batch: list[tuple] = []                                    # (time, image, motion mask) waiting for the model

    def flush() -> None:
        if not batch:
            return
        results = yolo.predict([b[1] for b in batch], imgsz=size, conf=low, classes=list(_COCO_KEEP), verbose=False)
        for (t, _, mask), result in zip(batch, results):
            dets = []
            for xyxy, score, cls in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist()):
                label = _COCO_KEEP.get(int(cls))
                if not label:
                    continue
                det = {"label": label, "confidence": round(float(score), 4), "bbox": [round(v, 1) for v in xyxy]}
                if score < conf:
                    if mask is None:
                        continue
                    x1, y1, x2, y2 = (int(v * scale) for v in xyxy)
                    patch = mask[max(0, y1):max(y1 + 1, y2), max(0, x1):max(x1 + 1, x2)]
                    cover = float(patch.mean()) if patch.size else 0.0
                    if cover < MOTION_COVER:
                        continue
                    det["motion"] = round(cover, 2)
                dets.append(det)
            frames.append({"time_sec": t, "detections": _dedupe_motion(dets)})
        batch.clear()

    index = 0
    try:
        while True:
            if mog is None and index % step:
                if not cap.grab():
                    break
                index += 1
                continue
            ok, image = cap.read()
            if not ok:
                break
            fg = None
            if mog is not None:                                   # the background model sees every frame
                small = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(image, (640, max(1, int(height * scale)))), cv2.COLOR_BGR2GRAY), (5, 5), 0)
                fg = mog.apply(small)
            if index % step == 0:
                mask = None
                if fg is not None and index / fps >= MOTION_WARMUP_S:
                    mask = cv2.dilate(cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel), kernel, iterations=2) > 0
                batch.append((round(index / fps, 3), image, mask))
                if len(batch) >= 4:                               # batched inference: fewer framework round trips on the CPU
                    flush()
                if progress:
                    progress(index, total)
            index += 1
        flush()
    finally:
        cap.release()
    if mog is not None:
        _confirm_motion(frames)
    return {
        "fps": fps_sample,
        "source_fps": fps,
        "video_shape": [height, width],
        "duration_s": round(index / fps, 3),
        "model": f"{name} (local CPU, imgsz {size}{', motion-assisted' if motion else ''})",
        "frames": frames,
    }


_KIND = {"person": "p", "bicycle": "b", "motorcycle": "b", "car": "v", "truck": "v", "bus": "v"}


def _dedupe_motion(dets: list[dict]) -> list[dict]:
    """Glare splits one vehicle into several weak boxes: keep the strongest of each overlapping group of motion
    boxes, and drop a motion box that a confident box of the same kind already covers."""
    def overlap(a, b):
        ix, iy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
        if ix <= 0 or iy <= 0:
            return 0.0
        inter = ix * iy
        return inter / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))   # share of the smaller box

    kept: list[dict] = [d for d in dets if "motion" not in d]
    for d in sorted((d for d in dets if "motion" in d), key=lambda d: -d["confidence"]):
        kind = _KIND.get(d["label"], d["label"])
        if any(_KIND.get(o["label"], o["label"]) == kind and overlap(d["bbox"], o["bbox"]) >= 0.5 for o in kept):
            continue
        kept.append(d)
    return kept


def _near(a, b) -> bool:
    ix, iy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if ix > 0 and iy > 0:
        return True
    ca, cb = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return abs(ca[0] - cb[0]) < (a[2] - a[0] + b[2] - b[0]) / 2 and abs(ca[1] - cb[1]) < (a[3] - a[1] + b[3] - b[1]) / 2


def _confirm_motion(frames: list[dict], reach: int = 2, need: int = 2, min_shift: float = 0.25) -> None:
    """Keep a motion-only box when boxes of its kind sit near it in `need` of the `reach` samples either side
    AND the box itself travels (its centre moves at least `min_shift` box widths across them). A still
    object that something moved behind, such as a tree trunk a car drove past, is not a moving object."""
    keep = []
    for i, fr in enumerate(frames):
        kept = []
        for d in fr["detections"]:
            if "motion" not in d:
                kept.append(d)
                continue
            kind = _KIND.get(d["label"], d["label"])
            hits, shift = 0, 0.0
            cx, w = (d["bbox"][0] + d["bbox"][2]) / 2, max(1.0, d["bbox"][2] - d["bbox"][0])
            for j in range(max(0, i - reach), min(len(frames), i + reach + 1)):
                if j == i:
                    continue
                near = [o for o in frames[j]["detections"] if _KIND.get(o["label"], o["label"]) == kind and _near(d["bbox"], o["bbox"])]
                if near:
                    hits += 1
                    shift = max(shift, max(abs((o["bbox"][0] + o["bbox"][2]) / 2 - cx) for o in near) / w)
            if hits >= need and shift >= min_shift:
                kept.append(d)
        keep.append(kept)
    for fr, kept in zip(frames, keep):
        fr["detections"] = kept
