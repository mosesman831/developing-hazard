"""Go/no-go probes for SPEC 20.1 questions 2 and 3.

Prints presence and measured numbers only. Never prints tokens, passwords,
or response bodies. Not collected by pytest (the name does not start with test_).
"""

from __future__ import annotations

import base64
import statistics
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import dh.config as config

_NEEDED = (
    "INGRESS_URL",
    "USERNAME",
    "PASSWORD",
    "COSMOS3_REASON_URL",
    "YOLO_URL",
    "GPU_BEARER_TOKEN",
    "WANDB_API_KEY",
    "WANDB_TEAM",
    "WANDB_PROJECT",
)


def _team_config_file() -> bool:
    """True only when a team config file is present. The OS USERNAME is not that user."""
    explicit = __import__("os").environ.get("DH_CONFIG")
    if explicit and Path(explicit).is_file():
        return True
    config_dir = Path("/config")
    if not config_dir.is_dir():
        return False
    return len(list(config_dir.glob("*.config"))) == 1


def _present(name: str) -> bool:
    if name in {"USERNAME", "PASSWORD"} and not _team_config_file():
        return False
    value = config.env(name)
    return bool(value and str(value).strip())


def _tiny_png_data_url() -> str:
    """1x1 PNG, stdlib only, so a verify call has a real frame to send."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"\x00\xff\x00\x00"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _model_id(payload: dict) -> str | None:
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and isinstance(first.get("id"), str):
            return first["id"]
    if isinstance(payload.get("id"), str):
        return payload["id"]
    return None


def _probe_cosmos() -> None:
    print("Q3 cosmos:")
    if not (_present("COSMOS3_REASON_URL") and _present("GPU_BEARER_TOKEN")):
        print("  blocked: COSMOS3_REASON_URL or GPU_BEARER_TOKEN unset")
        print("  median_s: not measured")
        print("  model_id: not measured")
        print("  video_frames_accepted: not measured")
        return

    from dh.clients import cosmos

    try:
        listed = cosmos.list_models()
    except Exception as exc:
        print(f"  list_models_error: {type(exc).__name__}")
        print("  median_s: not measured")
        print("  model_id: not measured")
        print("  video_frames_accepted: not measured")
        return

    model = _model_id(listed)
    print(f"  model_id: {model if model else 'missing from /v1/models'}")
    if not model:
        print("  median_s: not measured")
        print("  video_frames_accepted: not measured")
        return

    prompt = "Reply with JSON only: {\"where\":\"unclear\",\"motion\":\"unclear\",\"our_car\":\"unclear\",\"act\":\"unclear\",\"object\":\"probe\"}"
    frame = _tiny_png_data_url()
    latencies: list[float] = []
    accepted = 0
    rejected = 0
    errors = 0
    for _ in range(10):
        started = time.perf_counter()
        try:
            cosmos.verify_frames([frame], prompt, model=model, max_tokens=80)
            latencies.append(time.perf_counter() - started)
            accepted += 1
        except RuntimeError as exc:
            elapsed = time.perf_counter() - started
            text = str(exc)
            if "HTTP 400" in text:
                rejected += 1
                latencies.append(elapsed)
            else:
                errors += 1
                print(f"  call_error: {type(exc).__name__}")
                break
        except Exception as exc:
            errors += 1
            print(f"  call_error: {type(exc).__name__}")
            break

    if latencies:
        print(f"  calls_ok: {accepted}")
        print(f"  calls_http_400: {rejected}")
        print(f"  calls_other_error: {errors}")
        print(f"  median_s: {statistics.median(latencies):.3f}")
        print(f"  min_s: {min(latencies):.3f}")
        print(f"  max_s: {max(latencies):.3f}")
        print(f"  video_frames_accepted: {'yes' if accepted else 'no'}")
    else:
        print("  median_s: not measured")
        print("  video_frames_accepted: not measured")


def _probe_detections() -> None:
    print("Q2 detections:")
    try:
        from dh.clients.vss import VSS  # type: ignore
    except ImportError:
        vss_import = "missing"
    else:
        vss_import = "present"
    print(f"  dh.clients.vss: {vss_import}")
    have = _present("INGRESS_URL") and _present("USERNAME") and _present("PASSWORD")
    if vss_import != "present" or not have:
        print("  blocked: AG2 client not merged or INGRESS_URL/USERNAME/PASSWORD unset")
        print("  fps: not measured")
        print("  pedestrians_boxed: not measured")
        return
    print("  fps: not measured")
    print("  pedestrians_boxed: not measured")
    print("  note: client is importable but this probe does not guess segment ids")


def _probe_wandb() -> None:
    print("wandb:")
    if not _present("WANDB_API_KEY"):
        print("  inference_call: not run (WANDB_API_KEY unset)")
    else:
        from dh.clients import wandb_llm

        try:
            listed = wandb_llm.list_models()
        except Exception as exc:
            print(f"  list_models_error: {type(exc).__name__}")
            listed = {}
        model = _model_id(listed) if isinstance(listed, dict) else None
        print(f"  model_id: {model if model else 'not measured'}")
        if model:
            started = time.perf_counter()
            try:
                wandb_llm.complete("Reply with exactly one word: WAIT", model=model, max_tokens=8)
                print(f"  inference_call: ok latency_s={time.perf_counter() - started:.3f}")
            except Exception as exc:
                print(f"  inference_call: error {type(exc).__name__}")
        else:
            print("  inference_call: not run (no model id)")

    team_ok = _present("WANDB_TEAM") and _present("WANDB_PROJECT") and _present("WANDB_API_KEY")
    if not team_ok:
        print("  weave_init: not called (WANDB_TEAM, WANDB_PROJECT, or WANDB_API_KEY unset)")
        return
    try:
        import weave
    except ImportError:
        print("  weave_init: not called (weave is not installed)")
        return
    team = config.env("WANDB_TEAM")
    project = config.env("WANDB_PROJECT")
    try:
        weave.init(f"{team}/{project}")
        print("  weave_init: ok")
    except Exception as exc:
        print(f"  weave_init: error {type(exc).__name__}")


def main() -> None:
    print("settings:")
    for name in _NEEDED:
        print(f"  {name}: {'set' if _present(name) else 'unset'}")
    _probe_detections()
    _probe_cosmos()
    _probe_wandb()


if __name__ == "__main__":
    main()
