"""Frame extractor (SPEC 7.3).

``python -m dh.frames`` reads ``clips.json`` and writes JPEG frames under
the data frames directory. Clip time 0 is the first frame.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from dh.clips import data_dir, load_clips

_CLIP_ID = re.compile(r"[A-Za-z0-9_-]+")


def frame_times(n: int, fps: int) -> list[float]:
    """Clip-time seconds for ``n`` frames, rounded to 3 decimals."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    if n < 0:
        raise ValueError("frame count must be zero or more")
    return [round(index / fps, 3) for index in range(n)]


def extract_frames(clip: dict, fps: int = 5) -> dict:
    """Sample one clip to JPEG and write ``frames.json``.

    ffmpeg scale keeps the aspect ratio and an even height (``scale=960:-2``).
    """
    clip_id = _safe_clip_id(str(clip.get("clip_id") or ""))
    local = _existing_local(clip)
    if local is None:
        raise FileNotFoundError(clip_id)
    out_dir = _frames_dir(clip_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "%06d.jpg"
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(local),
            "-vf",
            f"fps={fps},scale=960:-2",
            "-q:v",
            "3",
            str(pattern),
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("ffmpeg frame extract failed")
    names = sorted(path.name for path in out_dir.glob("*.jpg"))
    frames = [
        {"file": name, "t": stamp}
        for name, stamp in zip(names, frame_times(len(names), fps))
    ]
    payload = {"clip_id": clip_id, "fps": fps, "frames": frames}
    manifest = out_dir / "frames.json"
    temporary = manifest.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest)
    return payload


def main() -> None:
    fps = _sample_fps()
    for clip in load_clips():
        clip_id = str(clip.get("clip_id") or "")
        if _existing_local(clip) is None:
            print(clip_id)
            continue
        try:
            extract_frames(clip, fps=fps)
        except (OSError, RuntimeError, ValueError):
            print(clip_id)


def _sample_fps() -> int:
    raw = os.environ.get("DH_FPS_SAMPLE", "5")
    try:
        fps = int(raw)
    except ValueError:
        return 5
    if fps <= 0:
        return 5
    return fps


def _safe_clip_id(clip_id: str) -> str:
    if not _CLIP_ID.fullmatch(clip_id):
        raise ValueError("clip id is not a safe frames directory name")
    return clip_id


def _frames_dir(clip_id: str) -> Path:
    root = (data_dir() / "frames").resolve()
    out = (root / clip_id).resolve()
    if not out.is_relative_to(root):
        raise ValueError("refusing to write outside the frames directory")
    return out


def _existing_local(clip: dict) -> Path | None:
    raw = clip.get("local_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if path.is_file():
        return path
    fallback = data_dir() / "clips" / path.name
    if fallback.is_file():
        return fallback
    return None


if __name__ == "__main__":
    main()
