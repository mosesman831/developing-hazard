"""Response redaction for label routes (visible_hazard)."""

import json
import shutil
from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dh.api.labels import router, visible_hazard

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"


def _client(monkeypatch, tmp_path):
    shutil.copytree(EXAMPLES, tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def test_put_first_save_allows_other_labeller_in_response(monkeypatch, tmp_path):
    client, directory = _client(monkeypatch, tmp_path)
    hazards_path = directory / "hazards.json"
    hazards = json.loads(hazards_path.read_text(encoding="utf-8"))
    fmd_only = {
        "hazard_id": "c07_h9",
        "clip_id": "c07",
        "type": "cyclist",
        "window_start": 5.0,
        "window_end": 8.0,
        "labellers": {"fmd": [5.0, 8.0]},
        "agreed": False,
        "arbitrated_by": None,
        "auto_window": [5.2, 7.8],
        "track_id": None,
        "segment_sources": [],
        "description": "fmd-only hazard for redaction test",
    }
    hazards.append(fmd_only)
    hazards_path.write_text(json.dumps(hazards, indent=2), encoding="utf-8")

    put = client.put(
        "/api/hazards/c07_h9",
        json={
            "labeller": "riyu",
            "ws": 5.1,
            "we": 7.9,
            "type": "cyclist",
            "description": "riyu first save",
        },
    )
    assert put.status_code == 200
    body = put.json()
    assert "riyu" in body["labellers"]
    assert "fmd" in body["labellers"]
    assert body["auto_window"] == [5.2, 7.8]

    on_disk = json.loads(hazards_path.read_text(encoding="utf-8"))
    by_id = {h["hazard_id"]: h for h in on_disk}
    assert "riyu" in by_id["c07_h9"]["labellers"]
    assert "fmd" in by_id["c07_h9"]["labellers"]
    assert by_id["c07_h9"]["auto_window"] == [5.2, 7.8]


def test_post_create_hides_auto_window_in_response(monkeypatch, tmp_path):
    client, directory = _client(monkeypatch, tmp_path)
    post = client.post(
        "/api/hazards",
        json={
            "clip_id": "c07",
            "labeller": "riyu",
            "ws": 2.0,
            "we": 5.0,
            "type": "other",
            "description": "fresh hazard",
        },
    )
    assert post.status_code == 201
    created = post.json()
    assert created["auto_window"] is None
    stored = json.loads((directory / "hazards.json").read_text(encoding="utf-8"))
    match = [h for h in stored if h["hazard_id"] == created["hazard_id"]][0]
    assert match["auto_window"] is None


def test_visible_hazard_strips_until_caller_has_saved():
    original = json.loads((EXAMPLES / "hazards.json").read_text(encoding="utf-8"))[0]
    hazard = deepcopy(original)
    hazard["auto_window"] = [15.8, 19.6]

    hidden = visible_hazard(hazard, "moses")
    assert hidden["auto_window"] is None
    assert hidden["labellers"] == {}

    shown = visible_hazard(hazard, "riyu")
    assert shown["auto_window"] == [15.8, 19.6]
    assert "fmd" in shown["labellers"]
    assert shown["labellers"]["riyu"] == original["labellers"]["riyu"]
