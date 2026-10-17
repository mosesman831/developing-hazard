"""The spatial page must load clip c07 from the backend.

These tests follow the requests a browser actually makes. They do not
inspect how the server mounts files or how the page builds strings,
except to evaluate the URLs ``paths('app', ...)`` publishes and to
require that those URLs stay relative.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest
from fastapi.testclient import TestClient

from dh.server import create_app

ROOT = Path(__file__).resolve().parents[2]
CLIP = "c07"
RUN_ID = "r_yolo_risk_20261017T145932"
PAGE = "http://testserver/spatial/index.html"
# Loaded for every clip in app mode. Missing files are empty 200s, not 404s.
MUST_SUCCEED = ("clip", "tracks", "run")
# Present on the page, but a missing sidecar or calibration must not 500.
MAY_MISS = ("det", "grid", "explain", "vss", "camera")

# Browser fetches that carry this clip and the selected run. Camera
# calibration is separate: the catalogue names a camera that may have
# no file, and that 404 is not a wiring failure.
_CLIP_DATA_MARKERS = ("/clips/", "/runs/", "/data/", "vss-detections")
_OPTIONAL_FETCH_MARKERS = ("/cameras/", "vss-detections")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DH_MODE", "dev")
    monkeypatch.setenv("DH_DATA_DIR", str(ROOT / "data"))
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client


def test_spatial_root_returns_index_html(client: TestClient) -> None:
    response = client.get("/spatial/")
    body = response.text[:240]
    assert response.status_code == 200, (
        f"GET /spatial/ returned {response.status_code} ({body!r}); "
        "opening /spatial/ must return the spatial page"
    )
    content_type = response.headers.get("content-type", "")
    assert "html" in content_type.lower(), (
        f"GET /spatial/ content-type is {content_type!r}, expected HTML"
    )
    assert "Spatial Hazard View" in response.text, (
        "GET /spatial/ did not return the spatial index page"
    )


def _camera_id() -> str:
    """Camera the clip catalogue names, which is the one the page requests."""
    path = ROOT / "data" / "clips.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "pie_cam-3"
    rows = payload if isinstance(payload, list) else []
    for row in rows:
        if isinstance(row, dict) and row.get("clip_id") == CLIP:
            camera = row.get("camera_id")
            if isinstance(camera, str) and camera:
                return camera
    return "pie_cam-3"


def _paths_from_node() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; cannot evaluate spatial/data.js paths()")
    script = """
import { paths } from './spatial/data.js';
const P = paths('app', %s, %s);
const cameraId = %s;
const out = {};
for (const [key, value] of Object.entries(P)) {
  out[key] = typeof value === 'function' ? value(cameraId) : value;
}
process.stdout.write(JSON.stringify(out));
""" % (json.dumps(CLIP), json.dumps(RUN_ID), json.dumps(_camera_id()))
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        "node could not evaluate spatial/data.js paths():\n" + proc.stderr
    )
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"paths() did not print JSON ({exc}); stdout={proc.stdout!r}"
        ) from exc
    assert isinstance(parsed, dict), f"paths() returned {type(parsed).__name__}"
    return parsed


def _resolved_request(raw: str) -> str:
    absolute = urljoin(PAGE, raw)
    parts = urlsplit(absolute)
    request = parts.path or "/"
    if parts.query:
        request += "?" + parts.query
    return request


def test_app_mode_paths_hit_the_backend(client: TestClient) -> None:
    paths = _paths_from_node()
    missing = [key for key in (*MUST_SUCCEED, *MAY_MISS) if key not in paths]
    assert not missing, f"paths('app', {CLIP!r}, run) is missing {missing}: {paths!r}"

    problems: list[str] = []
    resolved: dict[str, str] = {}
    for key, raw in paths.items():
        if not isinstance(raw, str) or not raw:
            problems.append(f"paths()[{key!r}] must be a relative URL string, got {raw!r}")
            continue
        if raw.startswith("/"):
            problems.append(
                f"paths()[{key!r}] is {raw!r}; the page is served under a prefix, "
                "so this URL must stay relative and must not start with '/'"
            )
        resolved[key] = _resolved_request(raw)

    for key in MUST_SUCCEED:
        request = resolved.get(key)
        if request is None:
            continue
        response = client.get(request)
        if response.status_code != 200:
            problems.append(
                f"{key}: paths() returned {paths[key]!r}, which resolves against "
                f"{PAGE} to {request} and returned {response.status_code}. "
                "From /spatial/index.html that request must reach the backend "
                "and return JSON."
            )
            continue
        payload = response.json()
        if not payload:
            problems.append(f"{key}: {request} returned empty JSON {payload!r}")
            continue
        if key == "clip" and (not isinstance(payload, dict) or payload.get("clip_id") != CLIP):
            problems.append(f"clip JSON at {request} is not clip {CLIP}")
        elif key == "tracks" and not isinstance(payload, list):
            problems.append(f"tracks JSON at {request} is not a list")
        elif key == "run" and (not isinstance(payload, dict) or payload.get("run_id") != RUN_ID):
            problems.append(f"run JSON at {request} is not run {RUN_ID}")

    for key in MAY_MISS:
        request = resolved.get(key)
        if request is None:
            continue
        response = client.get(request)
        if response.status_code >= 500:
            problems.append(
                f"{key}: {paths[key]!r} resolved to {request} and returned "
                f"{response.status_code}"
            )

    assert not problems, (
        "app-mode URLs from /spatial/index.html must stay relative and hit the backend:\n- "
        + "\n- ".join(problems)
    )


def _browser_executable() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


def _wait_until_ready(port: int, proc: subprocess.Popen, log_path: Path) -> None:
    deadline = time.time() + 20
    last_error = "no response"
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise AssertionError(f"uvicorn exited {proc.returncode}: {tail}")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - readiness probe
            last_error = str(exc)
            time.sleep(0.1)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    raise AssertionError(f"uvicorn did not become ready ({last_error}): {tail}")


def _is_clip_data(path: str) -> bool:
    return any(marker in path for marker in _CLIP_DATA_MARKERS)


def _is_optional_fetch(path: str) -> bool:
    return any(marker in path for marker in _OPTIONAL_FETCH_MARKERS)


def test_clip_query_without_src_loads_from_api(tmp_path: Path) -> None:
    pytest.importorskip(
        "playwright.sync_api",
        reason="playwright is not importable; cannot check the default source in a browser",
    )
    chrome = _browser_executable()
    if chrome is None:
        pytest.skip(
            "Chrome/Chromium is not available "
            "(looked for google-chrome, google-chrome-stable, chromium, chromium-browser)"
        )

    from playwright.sync_api import sync_playwright

    port = _free_port()
    log_path = tmp_path / "uvicorn.log"
    env = os.environ.copy()
    env["DH_MODE"] = "dev"
    env["DH_DATA_DIR"] = str(ROOT / "data")
    page_url = f"http://127.0.0.1:{port}/spatial/?clip={CLIP}&run={RUN_ID}"
    document_status: int | None = None
    document_type = ""
    seen: list[tuple[str, int, str]] = []
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "dh.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        _wait_until_ready(port, proc, log_path)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=chrome,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                page = browser.new_page()
                page.on(
                    "response",
                    lambda response: seen.append(
                        (response.url, response.status, response.request.resource_type)
                    ),
                )
                document = page.goto(page_url, wait_until="domcontentloaded", timeout=20000)
                if document is not None:
                    document_status = document.status
                    document_type = document.headers.get("content-type", "")
                if document_status == 200:
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        # Fonts can stay open. Clip fetches have already settled
                        # or will show up as missing URLs below.
                        pass
            finally:
                browser.close()
    finally:
        _stop_process(proc)
        log_file.close()

    problems: list[str] = []
    if document_status != 200:
        problems.append(
            f"GET /spatial/?clip={CLIP}&run={RUN_ID} (no src) returned {document_status}; "
            "expected 200 HTML"
        )
    elif "html" not in document_type.lower():
        problems.append(
            f"GET /spatial/ content-type is {document_type!r}, expected HTML"
        )

    fetches = [
        (url, status_code)
        for url, status_code, kind in seen
        if kind in ("fetch", "xhr")
    ]
    by_path: dict[str, list[int]] = {}
    for url, status_code in fetches:
        path = urlsplit(url).path
        by_path.setdefault(path, []).append(status_code)
        if _is_optional_fetch(path) and not _is_clip_data(path):
            if not path.startswith("/api/") or "/spatial/api/" in path or "/data/" in path:
                problems.append(
                    f"optional request {path} returned {status_code} outside /api/ "
                    "(must not use /spatial/api/ or /data/)"
                )
            elif status_code >= 500:
                problems.append(f"{path} returned {status_code}")
            continue
        if not _is_clip_data(path):
            continue
        if (
            not path.startswith("/api/")
            or "/spatial/api/" in path
            or "/data/" in path
        ):
            problems.append(
                f"clip-data request {path} returned {status_code}; "
                "it must go under /api/ (not /spatial/api/ or /data/) and return 200"
            )
        elif status_code != 200:
            problems.append(
                f"clip-data request {path} is under /api/ but returned {status_code}, expected 200"
            )

    required = (
        f"/api/clips/{CLIP}",
        f"/api/clips/{CLIP}/tracks",
        f"/api/clips/{CLIP}/det",
        f"/api/clips/{CLIP}/grid",
        f"/api/clips/{CLIP}/explain",
        f"/api/runs/{RUN_ID}",
    )
    for path in required:
        codes = by_path.get(path) or []
        if not codes:
            problems.append(f"page never requested {path}")
        elif any(code != 200 for code in codes):
            problems.append(f"{path} returned {codes}, expected 200")

    observed = ", ".join(f"{path} -> {codes}" for path, codes in sorted(by_path.items())) or "(none)"
    assert not problems, (
        "with ?clip set and no src param, clip data must load from /api/ and return 200:\n- "
        + "\n- ".join(problems)
        + f"\nobserved fetch/xhr: {observed}"
    )
