"""Label routes round-trip against a temp copy of contracts/examples/."""

import hashlib
import json
import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dh.api.labels import router
from dh.clips import load_clips, load_hazards

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"


def _client(monkeypatch, tmp_path):
    shutil.copytree(EXAMPLES, tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def _examples_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(EXAMPLES.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(EXAMPLES).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_put_and_post_round_trip_on_example_copy(monkeypatch, tmp_path):
    before = _examples_digest()
    client, directory = _client(monkeypatch, tmp_path)
    original = json.loads((EXAMPLES / "hazards.json").read_text(encoding="utf-8"))[0]
    riyu = original["labellers"]["riyu"]
    put = client.put(
        f"/api/hazards/{original['hazard_id']}",
        json={
            "labeller": "riyu",
            "ws": riyu[0],
            "we": riyu[1],
            "type": original["type"],
            "description": original["description"] + " saved",
        },
    )
    assert put.status_code == 200
    saved = put.json()
    assert saved["labellers"]["riyu"] == riyu
    assert saved["description"].endswith(" saved")
    assert saved["agreed"] is True
    assert saved["window_start"] == original["window_start"]
    assert saved["window_end"] == original["window_end"]
    on_disk = json.loads((directory / "hazards.json").read_text(encoding="utf-8"))
    assert on_disk[0]["description"] == saved["description"]
    assert on_disk[0]["labellers"]["fmd"] == original["labellers"]["fmd"]

    post = client.post(
        "/api/hazards",
        json={
            "clip_id": original["clip_id"],
            "labeller": "riyu",
            "ws": riyu[0],
            "we": riyu[1],
            "type": original["type"],
            "description": "added from the example window",
        },
    )
    assert post.status_code == 201
    created = post.json()
    assert created["hazard_id"] == "c07_h2"
    assert created["agreed"] is False
    assert created["auto_window"] is None
    stored = json.loads((directory / "hazards.json").read_text(encoding="utf-8"))
    assert stored[-1]["hazard_id"] == created["hazard_id"]
    assert stored[-1]["description"] == created["description"]
    assert _examples_digest() == before


def test_routes_use_only_this_router(monkeypatch, tmp_path):
    client, directory = _client(monkeypatch, tmp_path)
    missing = client.put(
        "/api/hazards/missing",
        json={
            "labeller": "riyu",
            "ws": 1,
            "we": 2,
            "type": "other",
            "description": "absent",
        },
    )
    assert missing.status_code == 404
    proposal = client.get("/api/clips/c07/proposal")
    assert proposal.status_code == 404
    status = client.post("/api/clips/c07/status", json={"status": "rejected"})
    assert status.status_code == 200
    clips = load_clips()
    assert clips[0]["clip_id"] == "c07"
    assert clips[0]["notes"].endswith("[status:rejected]")
    hazards = load_hazards()
    assert hazards[0]["hazard_id"] == "c07_h1"
    assert (directory / "hazards.json").is_file()
