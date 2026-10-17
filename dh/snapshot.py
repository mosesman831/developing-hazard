"""Build the read-only bundle the demo pod serves.

The pod ConfigMap stores a gzipped tar, base64-encoded, and Kubernetes caps
that object at 1 MiB. The check measures that payload, not the raw tree.
Media is not copied.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
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

_DATA_FILES = ("clips.json", "hazards.json", "leaderboard.json", "humans.jsonl")
_SKIP_PARTS = {"__pycache__", ".git"}
_SKIP_SUFFIXES = {".mp4", ".jpg", ".jpeg", ".png", ".pyc"}
# Dev-only trees. presets.js still ships; the recorded preset JSON does not.
_SPATIAL_SKIP_DIRS = frozenset({"fixtures", "tests", "media", "presets-data"})
# Room for ConfigMap metadata under the 1 MiB apiserver limit.
PAYLOAD_MARGIN_BYTES = 64 * 1024


class SnapshotError(RuntimeError):
    """The snapshot could not be built or is over the pod budget."""


def budget_bytes() -> int:
    """Hard ConfigMap ceiling in bytes (pod_budget_kb, default 1 MiB)."""
    try:
        from dh.config import pod_budget_kb

        return int(pod_budget_kb) * 1024
    except Exception:
        return 900 * 1024


def payload_budget_bytes() -> int:
    """Largest gzipped-base64 payload that still leaves PAYLOAD_MARGIN_BYTES."""
    return budget_bytes() - PAYLOAD_MARGIN_BYTES


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


def _copy_spatial(dest: Path) -> None:
    """Copy the standalone 3D app next to ``web/`` so the pod can serve ``/spatial``.

    ``fixtures/``, ``tests/``, ``media/`` and ``presets-data/`` stay behind.
    A checkout without ``spatial/`` still builds the rest of the bundle.
    """
    src = _REPO / "spatial"
    if not src.is_dir():
        return
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(src)
        if _SPATIAL_SKIP_DIRS.intersection(relative.parts):
            continue
        if _SKIP_PARTS.intersection(path.parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        _copy_file(path, dest / "spatial" / relative)


def directory_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def configmap_payload_bytes(root: Path) -> int:
    """Bytes of the base64 gzip tar ``deploy.sh`` stores in the ConfigMap.

    The command is ``tar -C <root> -czf <archive> .``. Kubernetes keeps
    binaryData base64-encoded, which is what the 1 MiB object limit counts.
    """
    handle = tempfile.NamedTemporaryFile(
        prefix="dh-snapshot-", suffix=".tar.gz", delete=False
    )
    handle.close()
    archive = Path(handle.name)
    try:
        subprocess.run(
            ["tar", "-C", str(root), "-czf", str(archive), "."],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        gzipped = archive.read_bytes()
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise SnapshotError(f"could not pack snapshot: {detail or exc}") from exc
    finally:
        archive.unlink(missing_ok=True)
    return len(base64.b64encode(gzipped))


def build_snapshot(dest: Path | None = None) -> int:
    """Write the pod bundle and return the ConfigMap payload size in bytes.

    The returned size is the base64 length of the gzipped tar, which is what
    the apiserver stores. Raises SnapshotError when that payload exceeds
    ``budget_bytes()`` minus a 64 KB margin. The over-budget directory is
    removed so deploy cannot ship it.
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
    _copy_spatial(target)

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

    raw = directory_size(target)
    payload = configmap_payload_bytes(target)
    ceiling = budget_bytes()
    limit = payload_budget_bytes()
    if payload > limit:
        shutil.rmtree(target, ignore_errors=True)
        raise SnapshotError(
            f"snapshot configmap payload is {payload} bytes, "
            f"budget is {ceiling} bytes with a {PAYLOAD_MARGIN_BYTES} byte margin "
            f"(raw tree {raw} bytes)"
        )
    return payload


def main() -> int:
    try:
        size = build_snapshot()
    except SnapshotError as exc:
        print(f"snapshot: {exc}", file=sys.stderr)
        return 1
    raw = directory_size(_DEFAULT_DEST)
    print(
        f"snapshot: {size} bytes configmap payload ({raw} bytes raw) in {_DEFAULT_DEST}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
