"""Run and hazard_score row builders. No network."""

import json
from pathlib import Path

from dh.clients.vastdb import (
    HAZARD_SCORE_FIELDS,
    HAZARD_SCORES_TABLE,
    RUN_FIELDS,
    RUNS_TABLE,
    TABLE_NAME,
    VastDBError,
    refuse,
)
from dh.store import hazard_score_rows, load_run_docs, run_rows

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RUN = ROOT / "data" / "runs" / "r_yolo_risk_20261017T122620"


def test_run_rows_reads_totals_from_run_json():
    run = json.loads((SAMPLE_RUN / "run.json").read_text(encoding="utf-8"))
    rows = run_rows([run])
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "r_yolo_risk_20261017T122620"
    assert row["testset_id"] == "dev"
    assert row["testset_sha256"] == "unfrozen"
    totals = run["totals"]
    assert row["score"] == totals["score"]
    assert row["max"] == totals["max"]
    assert row["pct"] == totals["pct"]
    assert row["lift_vs_chance"] == totals["lift_vs_chance"]
    assert '"theta_up":0.7' in row["agent_config"]


def test_run_rows_missing_totals_leaves_score_none():
    rows = run_rows([{"run_id": "r_empty", "agent": "yolo_risk"}])
    assert rows[0]["score"] is None
    assert rows[0]["max"] is None


def test_hazard_score_rows_use_segment_source_and_clicks():
    run = json.loads((SAMPLE_RUN / "run.json").read_text(encoding="utf-8"))
    clip_rows = []
    for line in (SAMPLE_RUN / "clips.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            clip_rows.append(json.loads(line))
    hazards = json.loads((ROOT / "data" / "hazards.json").read_text(encoding="utf-8"))
    clips = json.loads((ROOT / "data" / "clips.json").read_text(encoding="utf-8"))
    rows = hazard_score_rows(run, clip_rows, hazards, clips)
    c03 = [r for r in rows if r["clip_id"] == "c03" and r["hazard_id"] == "c03_h1"]
    assert len(c03) == 1
    assert c03[0]["points"] == 3
    assert c03[0]["first_click_t"] == 6.4
    assert c03[0]["segment_source"].startswith("s3://")


def test_load_run_docs_filters_testset():
    docs = load_run_docs(ROOT / "data", testset_id="dev")
    assert docs
    assert all(doc.get("testset_id") == "dev" for doc in docs)


def test_refuse_allows_runs_and_hazard_scores(monkeypatch):
    monkeypatch.setenv("VASTDB_BUCKET", "team-bucket")
    monkeypatch.setenv("S3_CHUNKS_BUCKET", "team-chunks")
    monkeypatch.setenv("S3_SEGMENTS_BUCKET", "team-segments")
    refuse("developing_hazard", TABLE_NAME, "team-bucket")
    refuse("developing_hazard", RUNS_TABLE, "team-bucket")
    refuse("developing_hazard", HAZARD_SCORES_TABLE, "team-bucket")
    try:
        refuse("developing_hazard", "human_sessions", "team-bucket")
    except VastDBError as exc:
        assert "allowlist" in str(exc)
    else:
        raise AssertionError("expected a refusal")


def test_vastdb_field_lists_include_segment_source():
    assert "agent_config" in RUN_FIELDS
    assert "segment_source" in HAZARD_SCORE_FIELDS
    assert "first_click_t" in HAZARD_SCORE_FIELDS
