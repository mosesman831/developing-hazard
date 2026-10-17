"""Phase 3 proposal route and agreement_summary."""

import json
import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dh.api.labels import agreement_summary, router

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"


def _client(monkeypatch, tmp_path):
    shutil.copytree(EXAMPLES, tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def test_proposal_404_with_one_labeller_even_if_file_exists(monkeypatch, tmp_path):
    client, directory = _client(monkeypatch, tmp_path)
    hazards_path = directory / "hazards.json"
    hazards = json.loads(hazards_path.read_text(encoding="utf-8"))
    hazards[0]["labellers"] = {"riyu": hazards[0]["labellers"]["riyu"]}
    hazards[0]["agreed"] = False
    hazards_path.write_text(json.dumps(hazards, indent=2), encoding="utf-8")

    proposals_dir = directory / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    proposal_body = {"clip_id": "c07", "window_start": 16.0, "window_end": 19.0}
    (proposals_dir / "c07.json").write_text(
        json.dumps(proposal_body), encoding="utf-8"
    )

    response = client.get("/api/clips/c07/proposal")
    assert response.status_code == 404


def test_proposal_returns_file_after_both_labellers_saved(monkeypatch, tmp_path):
    client, directory = _client(monkeypatch, tmp_path)
    proposals_dir = directory / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    proposal_body = {
        "clip_id": "c07",
        "window_start": 16.1,
        "window_end": 18.9,
        "source": "ag1",
    }
    (proposals_dir / "c07.json").write_text(
        json.dumps(proposal_body), encoding="utf-8"
    )

    response = client.get("/api/clips/c07/proposal")
    assert response.status_code == 200
    assert response.json() == proposal_body


def test_agreement_summary_counts_pair_and_ignores_single_labeller():
    hazards = [
        {
            "hazard_id": "c01_h1",
            "labellers": {"riyu": [10.0, 15.0], "fmd": [10.4, 14.8]},
        },
        {
            "hazard_id": "c01_h2",
            "labellers": {"riyu": [2.0, 5.0]},
        },
        {
            "hazard_id": "c01_h3",
            "labellers": {"riyu": [1.0, 4.0], "fmd": [2.5, 4.0]},
        },
    ]
    summary = agreement_summary(hazards)
    assert summary["windows"] == 3
    assert summary["paired"] == 2
    assert summary["agreed"] == 1
    assert summary["status_text"] == "1 of 2 windows agreed within tolerance"
