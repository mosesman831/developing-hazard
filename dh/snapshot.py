"""Build the read-only bundle the demo pod serves.

Code plus JSON must stay under the pod budget (SPEC 6.4). Media is not copied.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_DEST = _REPO / "data" / "snapshot"

_PY_FILES = (
    "dh/__init__.py",
    "dh/server.py",
    "dh/score.py",
    "dh/clips.py",
    "dh/config.py",
    "dh/api/__init__.py",
    "dh/api/health.py",
    "dh/api/clips.py",
    "dh/api/video.py",
    "dh/api/runs.py",
    "dh/api/human.py",
    "dh/api/leaderboard.py",
    "dh/api/_stubs.py",
    "dh/clients/__init__.py",
    "dh/clients/vss.py",
)

_DATA_FILES = (
    "clips.json",
    "hazards.json",
    "leaderboard.json",
    "humans.jsonl",
    "testset_v2.json",
)
_SKIP_PARTS = {"__pycache__", ".git"}
_SKIP_SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png", ".pyc"}


class SnapshotError(RuntimeError):
    """The snapshot could not be built or is over the pod budget."""


def budget_bytes() -> int:
    try:
        from dh.config import pod_budget_kb

        return int(pod_budget_kb) * 1024
    except Exception:
        return 900 * 1024


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _copy_tree(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        if _SKIP_PARTS.intersection(path.parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        relative = path.relative_to(src)
        _copy_file(path, dest / relative)


def _copy_approved_explanations(src: Path, dest: Path) -> None:
    """Copy only explanations a human has marked approved."""
    if not src.is_dir():
        return
    for path in src.rglob("*.json"):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("approved") is not True:
            continue
        _copy_file(path, dest / path.relative_to(src))


def directory_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def build_snapshot(dest: Path | None = None) -> int:
    """Write the pod bundle and return its size in bytes.

    Raises SnapshotError when the bundle is over the budget. The over-budget
    directory is removed so deploy cannot ship it.
    """
    target = dest if dest is not None else _DEFAULT_DEST
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for relative in _PY_FILES:
        source = _REPO / relative
        if not source.is_file():
            raise SnapshotError(f"missing {relative}")
        _copy_file(source, target / relative)

    web = _REPO / "web"
    _copy_tree(web, target / "web")

    data_src = _REPO / "data"
    for name in _DATA_FILES:
        path = data_src / name
        if path.is_file():
            _copy_file(path, target / "data" / name)
    for folder in ("runs", "tracks"):
        _copy_tree(data_src / folder, target / "data" / folder)

    requirements = _REPO / "requirements-pod.txt"
    if requirements.is_file():
        _copy_file(requirements, target / "requirements-pod.txt")

    _copy_approved_explanations(
        data_src / "cache" / "explain",
        target / "data" / "cache" / "explain",
    )

    size = directory_size(target)
    limit = budget_bytes()
    if size > limit:
        shutil.rmtree(target, ignore_errors=True)
        raise SnapshotError(
            f"snapshot is {size} bytes, budget is {limit} bytes"
        )
    return size


def main() -> int:
    try:
        size = build_snapshot()
    except SnapshotError as exc:
        print(f"snapshot: {exc}", file=sys.stderr)
        return 1
    print(f"snapshot: {size} bytes in {_DEFAULT_DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
