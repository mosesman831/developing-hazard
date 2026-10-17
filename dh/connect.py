"""Connector: any local video in, the whole pipeline out.

    python -m dh.connect <video.mp4> [--clip-id ID] [--camera-id ID] [--camera auto|dashcam|fixed]
                                     [--hfov DEG] [--data-dir DIR] [--no-copy]

Every stage uses the team infrastructure when its keys are in the environment
or ``.env`` (read through ``dh.config``), and a local fallback otherwise:

  detect   GPU YOLO service (YOLO_URL + GPU_BEARER_TOKEN), else local Ultralytics YOLO on the
           CPU (dh.clients.yolo_local); both return the payload dh.dets parses. (A clip already
           in VSS keeps using dh.dets.load_clip and its detection sidecars.)
  camera   dashcam or fixed, from background motion (dh.scene.camera_kind); a fixed
           camera is calibrated from object heights and its road is learned from traffic
  track    dh.track.IoUTracker; risk from dh.risk (dashcam) or dh.risk_fixed (fixed);
           top 3 per frame, written like `make track`
  agent    scene_risk (camera-aware) on the simulated clock (dh.replay.sit_clip), and
           yolo_risk too on a dashcam; with COSMOS3_REASON_URL + GPU_BEARER_TOKEN each
           rise is verified by Cosmos Reason before a click (scene_risk, gate mode)
  explain  W&B LLM when WANDB_API_KEY is set (dh.explain); otherwise a reason line built
           from the fields that fired, labelled as such

Outputs, under DH_DATA_DIR (default data/), in the formats the app already serves:
  clips.json (one record, split "dev"), clips/<clip_id>.mp4, det/<clip_id>.jsonl,
  tracks/<clip_id>.jsonl, cameras/<camera_id>.json, runs/<run_id>/{run.json,clips.jsonl}
There are no human labels for a new video, so clip scores are 0 and say so.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dh.config as config
from dh.dets import _parse_detections_impl, _write_cache, frames_from_dets
from dh.track import IoUTracker, select_top, write_tracks

_BST = timezone(timedelta(hours=1))
_SAFE = re.compile(r"[^A-Za-z0-9_-]+")
# every object in view, not the pod's top 3: a local run has no snapshot budget, and the 3D view should show every car
TRACKS_PER_FRAME = 10


def log(msg: str) -> None:
    print(f"[connect] {msg}", flush=True)


def grid_frames(dets: list[dict], duration_s: float) -> list[tuple[float, str, list[dict]]]:
    """Every sample time on the fps grid, empty ones included, so risk decays and tracks age out when nothing is seen."""
    by_t = {round(t, 3): frame for t, _, frame in frames_from_dets(dets)}
    step = 1.0 / config.fps_sample
    times = sorted(set(by_t) | {round(k * step, 3) for k in range(int(duration_s / step + 1e-6) + 1)})
    return [(t, "", by_t.get(t, [])) for t in times]


def has(*names: str) -> bool:
    return all(config.env(n) for n in names)


# ---- clip record ---------------------------------------------------------------------------
def clip_id_for(path: Path) -> str:
    """Readable and stable: 20261001_101025_sf4_chunk_0008_segment_005_of_006 -> sf4_chunk_0008_s5_<hash>."""
    h = hashlib.sha1(path.name.encode()).hexdigest()[:4]
    stem = re.sub(r"^\d{8}_\d{6}_", "", path.stem)
    stem = re.sub(r"_segment_0*(\d+)_of_\d+$", r"_s\1", stem)
    stem = re.sub(r"_20\d{6}", "", stem)
    return f"{_SAFE.sub('_', stem)[:32].strip('_')}_{h}"


def camera_id_for(path: Path) -> str:
    name = path.stem.lower()
    m = re.search(r"(?:^|_)sf(?:_streets)?_?(\d)(?:_|$)", name)
    if m:
        return f"sf_streets_cam-{m.group(1)}"
    for key, cid in (("neighborhood", "neighborhood_cam-1"), ("neighbourhood", "neighborhood_cam-1"), ("set0", "pie_cam-3"), ("pie", "pie_cam-3"),
                     ("i24", "i24_cam-1"), ("sf_streets", "sf_streets_cam-1"), ("warehouse", "sdg_warehouse_cam-2"), ("smartspace", "smartspace_cam-1")):
        if key in name:
            return cid
    return "local_cam-" + hashlib.sha1(name.encode()).hexdigest()[:6]


def probe(path: Path) -> dict:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {path.name}: not a video OpenCV can read")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {"fps": fps, "frames": n, "w": w, "h": h, "duration_s": round(n / fps, 3) if n else 0.0}


def register_clip(root: Path, path: Path, clip_id: str, camera_id: str, info: dict, copy: bool) -> dict:
    media = root / "clips" / f"{clip_id}{path.suffix.lower()}"
    if copy:
        media.parent.mkdir(parents=True, exist_ok=True)
        if not media.exists() or media.stat().st_size != path.stat().st_size:
            shutil.copy2(path, media)
    dur = info["duration_s"]
    clip = {
        "clip_id": clip_id, "candidate_id": f"local_{clip_id}", "camera_id": camera_id, "original_video": f"local:{path.name}",
        "segments": [{"source": f"local:{media.name if copy else path.name}", "start_s": 0.0, "end_s": dur}],
        "duration_s": dur, "fps_native": info["fps"], "fps_sample": config.fps_sample, "split": "dev", "seen_by": [],
        "local_path": str(media if copy else path), "notes": "added by dh.connect from a local file; no human labels",
    }
    from dh.models import Clip

    Clip.model_validate(clip)
    catalogue = root / "clips.json"
    clips = json.loads(catalogue.read_text(encoding="utf-8")) if catalogue.is_file() else []
    clips = [c for c in clips if c.get("clip_id") != clip_id] + [clip]
    catalogue.write_text(json.dumps(clips, indent=2) + "\n", encoding="utf-8")
    return clip


# ---- detection: team services first, local fallback ----------------------------------------
def _motion_rows(payload: dict, frame_wh) -> list[dict]:
    """Boxes the local detector kept only because they move and persist (below dh.dets' confidence floor)."""
    rows = []
    for k, fr in enumerate(payload.get("frames") or []):
        for d in fr.get("detections") or []:
            if "motion" not in d or float(d["confidence"]) >= config.det_conf_min:
                continue
            x1, y1, x2, y2 = (float(v) for v in d["bbox"])
            if y2 - y1 < config.min_box_h * frame_wh[1]:
                continue
            rows.append({"t": round(float(fr["time_sec"]), 3), "frame": k, "cls": d["label"], "conf": float(d["confidence"]), "xyxy": [x1, y1, x2, y2], "src": "motion", "motion": d["motion"]})
    return rows


def detect(path: Path, clip: dict, root: Path, motion: bool = False) -> tuple[list[dict], tuple[float, float], str]:
    payload, provider = None, None
    if has("YOLO_URL", "GPU_BEARER_TOKEN"):
        try:
            from dh.clients.yolo import infer

            log("detect: GPU YOLO service (YOLO_URL)")
            payload = infer(base64.b64encode(path.read_bytes()).decode("ascii"), include_frames=True)
            provider = "team GPU YOLO service"
        except Exception as exc:                              # noqa: BLE001 - fall through to the local model
            log(f"detect: GPU YOLO failed ({str(exc)[:120]}); using the local model")
    if payload is None:
        from dh.clients import yolo_local

        if not yolo_local.available():
            raise SystemExit("no detector: set YOLO_URL and GPU_BEARER_TOKEN, or pip install ultralytics opencv-python")
        log("detect: local YOLO on the CPU (no YOLO_URL/GPU_BEARER_TOKEN in the environment)" + ("; motion-assisted, the camera is fixed" if motion else ""))
        t0 = time.time()
        payload = yolo_local.detect_video(path, fps_sample=config.fps_sample, motion=motion)
        provider = f"local {payload.get('model')}, {time.time() - t0:.0f} s"
    rows, frame_wh, _ = _parse_detections_impl(payload, 0.0)
    if frame_wh is None:
        info = probe(path)
        frame_wh = (float(info["w"]), float(info["h"]))
    extra = _motion_rows(payload, frame_wh)
    if extra:
        log(f"detect: {len(extra)} low-confidence boxes kept because they move and persist (marked src=motion)")
    frame_of = {round(float(r["t"]), 3): r["frame"] for r in rows}
    for r in extra:
        r["frame"] = frame_of.get(r["t"], r["frame"])
    rows = sorted(rows + extra, key=lambda r: (float(r["t"]), r["cls"]))
    for r in rows:
        r["t"] = round(float(r["t"]), 3)
    _write_cache(root / "det" / f"{clip['clip_id']}.jsonl", rows, frame_wh)
    return rows, frame_wh, provider


# ---- camera setup ------------------------------------------------------------------------------
def which_camera(path: Path, frame_wh, camera_id: str, forced: str) -> dict:
    """Dashcam or fixed, before detection, so a fixed camera can use motion-assisted detection."""
    from dh.scene import camera_kind

    if forced in ("dashcam", "fixed"):
        kind = {"kind": forced, "why": "set on the command line", "flow": None}
    else:
        kind = camera_kind(path, [], frame_wh, fps_sample=config.fps_sample, hint=f"{camera_id} {path.stem}")
    log(f"camera: {kind['kind']} ({kind['why']})")
    return kind


def calibration_boxes(dets: list[dict]) -> list[dict]:
    """Each object once: a parked car seen in 25 frames is one box, not 25. A moving object gives one box per metre-ish of travel."""
    out, tracker, last = [], IoUTracker(), {}
    by_t = {round(float(d["t"]), 3): [] for d in dets}
    for d in dets:
        by_t[round(float(d["t"]), 3)].append(d)
    for t in sorted(by_t):
        frame = by_t[t]
        for tr in tracker.update(t, frame):
            prev = last.get(tr.id)
            h = tr.xyxy[3] - tr.xyxy[1]
            if prev is None or abs(tr.xyxy[3] - prev[3]) > 0.25 * h or abs((tr.xyxy[0] + tr.xyxy[2]) / 2 - (prev[0] + prev[2]) / 2) > 0.8 * (tr.xyxy[2] - tr.xyxy[0]):
                match = max(frame, key=lambda d: _iou(d["xyxy"], tr.xyxy))
                if match.get("src") != "motion":
                    out.append(match)
                last[tr.id] = tr.xyxy
    return out


def _iou(a, b) -> float:
    ix, iy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    i = ix * iy
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def camera_setup(path: Path, dets, frame_wh, camera_id: str, kind: dict, hfov: float, root: Path) -> dict:
    from dh.scene import calibrate

    doc = {"camera_id": camera_id, "kind": kind["kind"], "frame_wh": list(frame_wh), "detected": kind, "written_by": "dh.connect"}
    if kind["kind"] == "dashcam":
        return doc
    cal_path = root / "cameras" / f"{camera_id}.json"
    old = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.is_file() else None
    if old and old.get("pose") and old.get("written_by") != "dh.connect":     # a hand-made calibration wins
        log(f"camera: using the calibration file {cal_path.name}")
        doc.update({k: old[k] for k in ("pose", "scenery", "road") if k in old})
        return doc
    boxes = calibration_boxes(dets)
    cal = calibrate(boxes, frame_wh, hfov=hfov, min_n=6)
    if cal:
        log(f"camera: auto-calibrated from {cal['n']} distinct object views: {cal['pose']['height_m']} m up, {cal['pose']['pitch_deg']} deg down, lens {hfov} deg assumed (median size error {cal['err']})")
        doc.update({"pose": cal["pose"], "auto": {k: cal[k] for k in ("n", "err", "method")}})
    else:
        doc.update({"pose": {"x": 0.0, "z": 0.0, "height_m": 4.0, "yaw_deg": 0.0, "pitch_deg": 20.0, "hfov_deg": hfov, "k1": 0.0}, "assumed": True})
        log(f"camera: {len(boxes)} distinct object views, too few clear, confident and uncut ones at different depths to calibrate; assuming a house camera 4 m up, 20 deg down. Add data/cameras/{camera_id}.json for real positions")
    return doc


def learn_scenery(doc: dict, dets, frame_wh) -> None:
    """Track once to see where vehicles drive; that is the road and its pavements."""
    from dh.scene import foot, learn_road, rig, scenery

    R = rig(doc["pose"], frame_wh)
    W, H = frame_wh
    tracker, ground = IoUTracker(), {}
    for t, _, frame in frames_from_dets(dets):
        for tr in tracker.update(t, frame):
            g = foot(R, (tr.xyxy[0] / W, tr.xyxy[1] / H, tr.xyxy[2] / W, tr.xyxy[3] / H))
            if g is not None:
                ground.setdefault(tr.id, []).append((t, g, tr.cls))
    # moving vehicles found only by motion are often split into short tracks at night: pool their footprints too
    pooled = []
    for d in dets:
        if d.get("src") == "motion" and d["cls"] in ("car", "truck", "bus", "motorcycle"):
            x1, y1, x2, y2 = d["xyxy"]
            g = foot(R, (x1 / W, y1 / H, x2 / W, y2 / H))
            if g is not None:
                pooled.append((float(d["t"]), g, d["cls"]))
    if len(pooled) >= 3:
        ground[-1] = sorted(pooled)
    road = learn_road(ground)
    doc["road"] = road.strips
    doc["scenery"] = scenery(road)
    log(f"scenery: {len(road.strips)} road strip(s) learned from moving vehicles" if road.strips else "scenery: no vehicle moved far enough to learn the road")


# ---- tracks + risk, written like `make track` -----------------------------------------------
def write_track_file(clip_id: str, dets, frame_wh, camera: dict, root: Path, duration_s: float) -> tuple[list[dict], tuple | None, dict]:
    """-> (rows written, (peak risk, t, reason) of the riskiest object, {class: objects seen, "moving <class>": ...})."""
    from dh.agents.scene_risk import SceneRisk

    from dh.agents.scene_risk import reason

    agent = SceneRisk({"camera": camera})
    rows, best, seen = [], None, {}
    for t, _, frame in grid_frames(dets, duration_s):
        for f in agent._features(t, frame):
            rows.append({k: getattr(f, k) for k in ("track_id", "t", "cls", "xyxy", "vx", "vy", "h_rate", "in_corridor", "heading_in", "ttc", "t_lat", "risk")})
            if best is None or f.risk > best[0]:
                best = (f.risk, f.t, reason(f, camera.get("kind")))
            moving = getattr(f, "speed_ms", 0.0) >= 1.0
            seen.setdefault(f.cls, set()).add(f.track_id)
            if moving:
                seen.setdefault(f"moving {f.cls}", set()).add(f.track_id)
    top = select_top(rows, k=TRACKS_PER_FRAME)
    write_tracks(clip_id, top, data_dir=str(root))
    return top, best, {k: len(v) for k, v in seen.items()}


# ---- verification with Cosmos Reason (only with keys) ---------------------------------------
class CosmosVerifier:
    """Answers CallRequests by sending the last 2 s of frames to Cosmos Reason."""

    FIXED_PROMPT = (
        "These frames come from a fixed street camera, oldest first. Is a person, cyclist or dog at real risk of being hit "
        "by a moving vehicle in the next few seconds, so that a driver may need to slow or steer? Reply with JSON only: "
        '{"hazard": "yes" | "no", "object": "<who, in a few words>"}'
    )

    def __init__(self, path: Path, kind: str) -> None:
        self.path, self.kind = path, kind
        self.model = config.env("DH_VLM_MODEL") or "nvidia/Cosmos-Reason1-7B"
        prompt_file = Path(__file__).resolve().parents[1] / "prompts" / "cosmos_verify_v2.txt"
        self.dash_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.is_file() else self.FIXED_PROMPT

    def _frames(self, t: float) -> list[str]:
        import cv2

        cap, out = cv2.VideoCapture(str(self.path)), []
        for k in range(8):
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t - 2.0 + k * 2.0 / 7) * 1000)
            ok, img = cap.read()
            if ok:
                img = cv2.resize(img, (960, int(img.shape[0] * 960 / img.shape[1])))
                out.append("data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()).decode())
        cap.release()
        return out

    def answer(self, clip_id, t, track_id):
        from dh.agents.base import CallResult
        from dh.clients.cosmos import verify_frames
        from dh.grid import is_hazard, parse_answer

        t0 = time.time()
        try:
            prompt = self.FIXED_PROMPT if self.kind == "fixed" else self.dash_prompt
            payload = verify_frames(self._frames(t), prompt, model=self.model)
            text = payload["choices"][0]["message"]["content"]
            ans = parse_answer(text)
            hazard = ans.get("hazard") == "yes" if self.kind == "fixed" else is_hazard(ans)
            return CallResult(latency_s=time.time() - t0, is_hazard=hazard, object=str(ans.get("object", ""))[:60], track_id=track_id)
        except Exception as exc:                              # noqa: BLE001 - an unanswered call never clicks
            log(f"cosmos: call at {t:.2f} s failed ({str(exc)[:100]})")
            return CallResult(latency_s=time.time() - t0, is_hazard=False, object="", track_id=track_id)


# ---- agents -> runs ---------------------------------------------------------------------------
def quiet_note(peak_ema: float, theta: float, peak, seen: dict) -> str:
    """Why the agent stayed quiet, from what it actually saw."""
    people = sum(n for k, n in seen.items() if k in ("person", "bicycle", "dog"))
    moving = sum(n for k, n in seen.items() if k.startswith("moving "))
    scene = f"{moving} moving-vehicle track{'s' if moving != 1 else ''}, {people} person or cyclist track{'s' if people != 1 else ''}"
    top = f"; strongest single risk {peak[0]:.2f} at {peak[1]:.1f} s, {peak[2]}" if peak else ""
    return f"No click: smoothed risk peaked at {peak_ema:.2f}, below the {theta:.2f} click threshold ({scene}{top}). Template from the fields that fired, not a model."


def run_agent(name: str, agent, clip: dict, dets, root: Path, verifier=None, latency_mode: str = "zero", quiet: tuple | None = None) -> str:
    from dh.evals import _normalise_call, _normalise_click
    from dh.models import Clip, ClipResult, Run, clip_meta_from_clip
    from dh.replay import sit_clip
    from dh.score import PATTERN_VERSION, SCORER_VERSION, score_clip

    meta = clip_meta_from_clip(Clip.model_validate(clip))
    res = sit_clip(agent, meta, grid_frames(dets, float(clip["duration_s"])), verifier=verifier, latency_mode=latency_mode)
    clicks = [_normalise_click(c) for c in res.clicks]
    calls = [_normalise_call(c) for c in res.calls]
    scored = score_clip([c["t"] for c in clicks], [], float(clip["duration_s"]))
    started = datetime.now(_BST).replace(microsecond=0)
    run_id = f"r_{name}_{clip['clip_id']}_{started.strftime('%Y%m%dT%H%M%S')}"
    explanation = None
    if clicks:
        explanation = "Reason from the fields that fired (template, not a model): " + " | ".join(f"{c['t']:.2f} s {c.get('reason') or ''}".strip() for c in clicks)
    elif quiet is not None:
        peak_ema = max((float(b) for _, b in res.risk_curve), default=0.0)
        explanation = quiet_note(peak_ema, float(getattr(agent, "theta_trig" if verifier else "theta_up", config.theta_up)), *quiet)
    row = {"run_id": run_id, "clip_id": clip["clip_id"], "clicks": clicks, "calls": calls, "pattern": scored["pattern"],
           "hazard_points": scored["hazard_points"], "clip_score": scored["clip_score"],
           "risk_curve": [[round(float(a), 3), round(float(b), 4)] for a, b in res.risk_curve], "explanation": explanation}
    ClipResult.model_validate(row)
    doc = {"run_id": run_id, "agent": name, "agent_config": {"camera_kind": getattr(agent, "camera", {}).get("kind") if hasattr(agent, "camera") else "dashcam",
           "verify": bool(verifier)}, "testset_id": "local", "testset_sha256": "unfrozen", "scorer_version": SCORER_VERSION,
           "pattern_version": PATTERN_VERSION, "latency_mode": latency_mode, "mode": "connect", "started_at": started.isoformat(), "weave_url": "",
           "totals": {"clips": 1, "clicks": len(clicks), "note": "no human labels for this clip, so no points"}}
    Run.model_validate(doc)
    out = root / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (out / "clips.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return run_id


# ---- whole pipeline ----------------------------------------------------------------------------
def connect(video: str, *, clip_id: str | None = None, camera_id: str | None = None, camera: str = "auto",
            hfov: float = 100.0, data_dir: str | None = None, copy: bool = True) -> dict:
    path = Path(video).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"no such video: {video}")
    root = Path(data_dir or config.DATA_DIR)
    info = probe(path)
    cid = clip_id or clip_id_for(path)
    cam_id = camera_id or camera_id_for(path)
    log(f"clip {cid}: {info['w']}x{info['h']}, {info['fps']:.2f} fps, {info['duration_s']} s, camera id {cam_id}")
    clip = register_clip(root, path, cid, cam_id, info, copy)

    kind = which_camera(path, (float(info["w"]), float(info["h"])), cam_id, camera)
    dets, frame_wh, provider = detect(path, clip, root, motion=kind["kind"] == "fixed")
    log(f"detect: {len(dets)} boxes on {len(frames_from_dets(dets))} frames from {provider}")

    cam = camera_setup(path, dets, frame_wh, cam_id, kind, hfov, root)
    if cam["kind"] == "fixed":
        learn_scenery(cam, dets, frame_wh)
    # written for both kinds, so the 3D view follows the backend's decision for any camera id
    (root / "cameras").mkdir(parents=True, exist_ok=True)
    (root / "cameras" / f"{cam_id}.json").write_text(json.dumps(cam, indent=2) + "\n", encoding="utf-8")

    rows, peak_obj, seen = write_track_file(cid, dets, frame_wh, cam, root, float(clip["duration_s"]))
    peak = max(rows, key=lambda r: r["risk"]) if rows else None
    log(f"track: {len({r['track_id'] for r in rows})} tracks kept (up to {TRACKS_PER_FRAME} per frame); peak risk {peak['risk']:.2f} ({peak['cls']} #{peak['track_id']} at {peak['t']:.1f} s)" if peak else "track: nothing tracked")

    from dh.agents.scene_risk import SceneRisk

    verifier = CosmosVerifier(path, cam["kind"]) if has("COSMOS3_REASON_URL", "GPU_BEARER_TOKEN") else None
    quiet = (peak_obj, seen)
    runs = [run_agent("scene_risk", SceneRisk({"camera": cam, "verify": verifier is not None}), clip, dets, root, verifier, quiet=quiet)]
    if cam["kind"] == "dashcam":
        from dh.agents.yolo_risk import YoloRisk

        runs.append(run_agent("yolo_risk", YoloRisk(), clip, dets, root))
    log("verify: Cosmos Reason checks each rise" if verifier else "verify: no COSMOS3_REASON_URL/GPU_BEARER_TOKEN, so the agent clicks on risk alone")
    summary = {"clip_id": cid, "camera_id": cam_id, "camera": cam["kind"], "camera_why": cam["detected"]["why"], "detector": provider,
               "boxes": len(dets), "tracks": len({r['track_id'] for r in rows}), "runs": runs, "watch": [f"#/watch/{r}/{cid}" for r in runs]}
    for r in runs:
        row = json.loads((root / "runs" / r / "clips.jsonl").read_text(encoding="utf-8"))
        summary.setdefault("clicks", {})[r] = [{"t": c["t"], "reason": c.get("reason")} for c in row["clicks"]]
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the whole hazard pipeline on one local video.")
    p.add_argument("video")
    p.add_argument("--clip-id")
    p.add_argument("--camera-id")
    p.add_argument("--camera", choices=("auto", "dashcam", "fixed"), default="auto")
    p.add_argument("--hfov", type=float, default=100.0, help="lens width for an uncalibrated fixed camera (degrees)")
    p.add_argument("--data-dir")
    p.add_argument("--no-copy", action="store_true", help="do not copy the video under data/clips/")
    a = p.parse_args(argv)
    summary = connect(a.video, clip_id=a.clip_id, camera_id=a.camera_id, camera=a.camera, hfov=a.hfov, data_dir=a.data_dir, copy=not a.no_copy)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
