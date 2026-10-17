"""Route shapes against contracts/examples/ when the data directory is empty."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dh.server import create_app

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"


def load_example(name: str, required: tuple[str, ...] = ()):
    """Load one contracts/examples file and check required keys."""
    path = EXAMPLES / name
    text = path.read_text(encoding="utf-8")
    if name.endswith(".jsonl"):
        payload = [json.loads(line) for line in text.splitlines() if line.strip()]
        if required:
            assert payload, name
            _require_keys(payload[0], required, name)
        return payload
    payload = json.loads(text)
    if required:
        target = payload[0] if isinstance(payload, list) else payload
        _require_keys(target, required, name)
    return payload


def _require_keys(obj: dict, required: tuple[str, ...], name: str) -> None:
    missing = [key for key in required if key not in obj]
    assert not missing, f"{name} missing {missing}"


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("DH_MODE", "dev")
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    application = create_app()
    with TestClient(application) as client:
        yield client


@pytest.fixture
def demo(monkeypatch, tmp_path):
    monkeypatch.setenv("DH_MODE", "demo")
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    application = create_app()
    with TestClient(application) as client:
        yield client


def test_health(api):
    response = api.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_api_health(api):
    example = load_example("testset_v0.json", ("testset_id",))
    response = api.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    _require_keys(
        body,
        ("ok", "vss_ok", "cosmos_ok", "wandb_ok", "testset_id", "mode"),
        "/api/health",
    )
    assert body["ok"] is True
    assert body["vss_ok"] is False
    assert body["cosmos_ok"] is False
    assert body["wandb_ok"] is False
    assert body["testset_id"] == example["testset_id"]
    assert body["testset_id"] == "testset_v0"
    assert body["mode"] == "dev"


def test_list_clips(api):
    example = load_example(
        "clips.json",
        ("clip_id", "split", "duration_s", "segments", "original_video"),
    )
    response = api.get("/api/clips")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    item = next(row for row in body if row["clip_id"] == example[0]["clip_id"])
    _require_keys(
        item,
        ("clip_id", "split", "duration_s", "n_hazards", "label_status"),
        "/api/clips",
    )
    assert item["clip_id"] == "c07"
    assert item["split"] == "dev"
    assert item["duration_s"] == 30.0
    assert item["n_hazards"] >= 1
    assert item["label_status"] == "labelled"
    assert "hazards" not in item
    assert "window_start" not in item


def test_clip_detail_and_blind(api):
    response = api.get("/api/clips/c07")
    assert response.status_code == 200
    body = response.json()
    _require_keys(body, ("clip_id", "segments", "hazards"), "/api/clips/c07")
    assert body["clip_id"] == "c07"
    assert any(hazard["hazard_id"] == "c07_h1" for hazard in body["hazards"])

    hidden = api.get("/api/clips/c07", params={"blind": "1"})
    assert hidden.status_code == 200
    payload = hidden.json()
    assert "hazards" not in payload or payload.get("hazards") == []
    assert "hazards" not in payload
    assert "window_start" not in hidden.text

    missing = api.get("/api/clips/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "clip not found"


def test_tracks(api):
    load_example("tracks_c07.jsonl", ("track_id", "t"))
    response = api.get("/api/clips/c07/tracks")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body
    assert "track_id" in body[0]
    assert "t" in body[0]
    assert api.get("/api/clips/missing/tracks").status_code == 404


def test_runs(api):
    example = load_example("run.json", ("run_id", "totals"))
    assert "score" in example["totals"]
    response = api.get("/api/runs")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    found = next(row for row in body if row["run_id"] == "r_EXAMPLE_yolo_risk")
    assert found["run_id"] == example["run_id"]
    assert "score" in found["totals"]

    detail = api.get("/api/runs/r_EXAMPLE_yolo_risk")
    assert detail.status_code == 200
    payload = detail.json()
    assert isinstance(payload["clips"], list)
    assert payload["clips"]
    assert "clip_score" in payload["clips"][0]

    missing = api.get("/api/runs/nope")
    assert missing.status_code == 404


def test_leaderboard(api):
    example = load_example(
        "leaderboard.json",
        ("testset_id", "rows", "dvsa_reference_pct"),
    )
    response = api.get("/api/leaderboard")
    assert response.status_code == 200
    body = response.json()
    assert body["testset_id"] == "testset_v0"
    assert isinstance(body["rows"], list)
    assert "dvsa_reference_pct" in body
    assert body == example


def test_human_score_and_log(api, tmp_path):
    response = api.post(
        "/api/human",
        json={
            "name": "Judge 1",
            "role": "judge",
            "blind": True,
            "clip_id": "c07",
            "clicks": [16.9],
        },
    )
    assert response.status_code == 200
    body = response.json()
    _require_keys(body, ("clip_score", "pattern", "hazards"), "/api/human")
    assert isinstance(body["clip_score"], int)
    assert "flag" in body["pattern"]
    assert isinstance(body["hazards"], list)

    path = tmp_path / "humans.jsonl"
    assert path.is_file()
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["clip_id"] == "c07"


def test_human_bad_role(api, tmp_path):
    response = api.post(
        "/api/human",
        json={
            "name": "Judge 1",
            "role": "spectator",
            "blind": True,
            "clip_id": "c07",
            "clicks": [16.9],
        },
    )
    assert response.status_code == 422
    assert not (tmp_path / "humans.jsonl").exists()


def test_post_run(api):
    response = api.post(
        "/api/runs",
        json={
            "agent": "yolo_risk",
            "config": {},
            "testset_id": "testset_v0",
            "latency_mode": "zero",
        },
    )
    assert response.status_code == 200
    assert isinstance(response.json()["run_id"], str)


class _FakeUpstream:
    def __init__(self, range_header):
        self.range_header = range_header
        self.status_code = 206 if range_header else 200
        self.headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
            "Content-Length": "4",
        }
        if range_header:
            self.headers["Content-Range"] = "bytes 0-3/4"
        self._closed = False

    def iter_content(self, chunk_size=1024):
        yield b"ftyp"

    def close(self):
        self._closed = True


def test_video(api, monkeypatch):
    clips = load_example("clips.json", ("segments", "original_video"))
    source = clips[0]["segments"][0]["source"]
    seen = {}

    def fake_open(src, range_header):
        seen["source"] = src
        seen["range"] = range_header
        return _FakeUpstream(range_header)

    monkeypatch.setattr("dh.api.video.open_upstream", fake_open)

    missing = api.get("/video")
    assert missing.status_code == 400

    response = api.get("/video", params={"source": source}, headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.headers["content-type"].startswith("video/")
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 0-3/4"
    assert response.content == b"ftyp"
    assert seen["source"] == source
    assert seen["range"] == "bytes=0-3"

    original = api.get("/video", params={"source": clips[0]["original_video"]})
    assert original.status_code == 200

    unknown = api.get("/video", params={"source": "s3://not-in-list"})
    assert unknown.status_code == 404
    assert seen["source"] != "s3://not-in-list"


def test_explain_and_stream(api):
    explained = api.post("/api/explain/r_EXAMPLE_yolo_risk/c07_h1")
    assert explained.status_code == 200
    assert explained.json()["explanation"] is None

    stream = api.get("/api/runs/r_EXAMPLE_yolo_risk/stream", params={"clip": "c07"})
    assert stream.status_code == 200
    assert "event: score" in stream.text
    assert "clip_score" in stream.text


def test_real_clip_without_tracks_is_empty(monkeypatch, tmp_path):
    clips = [
        {
            "clip_id": "c01",
            "duration_s": 30.0,
            "split": "dev",
            "segments": [{"source": "s3://real/seg.mp4", "start_s": 0.0, "end_s": 5.0}],
        }
    ]
    (tmp_path / "clips.json").write_text(json.dumps(clips), encoding="utf-8")
    (tmp_path / "hazards.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("DH_MODE", "dev")
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        response = client.get("/api/clips/c01/tracks")
    assert response.status_code == 200
    assert response.json() == []


def test_snapshot_under_budget(tmp_path):
    from dh.snapshot import SnapshotError, build_snapshot, budget_bytes

    size = build_snapshot(tmp_path / "snapshot")
    assert size > 0
    assert size <= budget_bytes()
    assert (tmp_path / "snapshot" / "dh" / "server.py").is_file()
    assert (tmp_path / "snapshot" / "web" / "index.html").is_file()
    assert not list((tmp_path / "snapshot").rglob("*.mp4"))


def test_snapshot_rejects_over_budget(monkeypatch, tmp_path):
    from dh import snapshot as snapshot_mod

    monkeypatch.setattr(snapshot_mod, "budget_bytes", lambda: 1)
    with pytest.raises(snapshot_mod.SnapshotError):
        snapshot_mod.build_snapshot(tmp_path / "too-big")
    assert not (tmp_path / "too-big").exists()


def test_demo_mode(demo):
    hazard = load_example(
        "hazards.json",
        ("clip_id", "window_start", "window_end", "type", "description"),
    )[0]
    denied = demo.post(
        "/api/runs",
        json={
            "agent": "yolo_risk",
            "config": {},
            "testset_id": "testset_v0",
            "latency_mode": "zero",
        },
    )
    assert denied.status_code == 404

    labels = demo.post(
        "/api/hazards",
        json={
            "clip_id": hazard["clip_id"],
            "labeller": "riyu",
            "ws": hazard["window_start"],
            "we": hazard["window_end"],
            "type": hazard["type"],
            "description": hazard["description"],
        },
    )
    assert labels.status_code in (404, 405)
    assert labels.status_code != 201


def test_index_html_when_present(api):
    index = ROOT / "web" / "index.html"
    if not index.is_file():
        return
    response = api.get("/")
    assert response.status_code == 200
    assert "Developing Hazard" in response.text


def test_example_score_uses_contract_numbers():
    from dh.api._stubs import example_score

    result = load_example(
        "run_clips.jsonl",
        ("clip_score", "pattern", "hazard_points", "clicks"),
    )[0]
    hazards = load_example(
        "hazards.json",
        ("hazard_id", "window_start", "window_end"),
    )
    scored = example_score()
    _require_keys(scored, ("clip_score", "pattern", "hazards", "agents"), "example_score")
    assert scored["clip_score"] == result["clip_score"]
    assert scored["pattern"]["flag"] is result["pattern"]["flag"]
    assert scored["hazards"][0]["hazard_id"] == "c07_h1"
    assert scored["hazards"][0]["points"] == result["hazard_points"]["c07_h1"]
    assert scored["hazards"][0]["window"] == [
        hazards[0]["window_start"],
        hazards[0]["window_end"],
    ]
    assert scored["hazards"][0]["first_click"] == result["clicks"][0]["t"]
    assert scored["agents"] == {}
