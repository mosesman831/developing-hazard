"""Leaderboard file written from runs and blind human sessions."""

from __future__ import annotations

import json
from pathlib import Path

from dh.evals import build_leaderboard


def _write_run(
    root: Path,
    run_id: str,
    agent: str,
    started_at: str,
    score: int,
    lift: float,
    testset_id: str = "testset_v0",
) -> None:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    maximum = 5
    doc = {
        "run_id": run_id,
        "agent": agent,
        "testset_id": testset_id,
        "started_at": started_at,
        "weave_url": "",
        "totals": {
            "score": score,
            "max": maximum,
            "pct": score / maximum,
            "hit_rate": 1.0,
            "pattern_rate": 0.0,
            "lift_vs_chance": lift,
            "median_reaction_s": 0.7,
            "mean_latency_s": 0.0,
        },
    }
    (run_dir / "run.json").write_text(json.dumps(doc), encoding="utf-8")
    clip = {"clip_id": "c1", "clip_score": score, "hazard_points": {"h1": score}}
    (run_dir / "clips.jsonl").write_text(json.dumps(clip) + "\n", encoding="utf-8")


def test_build_leaderboard_writes_ci90_and_lift(tmp_path: Path):
    _write_run(
        tmp_path,
        "r_old",
        "yolo_risk",
        "2026-10-17T09:00:00+01:00",
        score=1,
        lift=0.0,
    )
    _write_run(
        tmp_path,
        "r_new",
        "yolo_risk",
        "2026-10-17T12:00:00+01:00",
        score=4,
        lift=0.25,
    )
    board = build_leaderboard("testset_v0", data_dir=tmp_path)
    written = json.loads((tmp_path / "leaderboard.json").read_text(encoding="utf-8"))
    assert written == board
    assert board["testset_id"] == "testset_v0"
    assert board["max"] == 5
    assert board["dvsa_reference_pct"] == 0.587
    assert len(board["rows"]) == 1
    row = board["rows"][0]
    assert row["name"] == "yolo_risk"
    assert row["kind"] == "agent"
    assert row["score"] == 4
    assert row["ci90"] == [0.8, 0.8]
    assert row["lift_vs_chance"] == 0.25
    assert "ci90" in row and "lift_vs_chance" in row


def test_missing_humans_jsonl_does_not_raise(tmp_path: Path):
    _write_run(
        tmp_path,
        "r1",
        "yolo_risk",
        "2026-10-17T12:00:00+01:00",
        score=4,
        lift=0.1,
    )
    assert not (tmp_path / "humans.jsonl").exists()
    board = build_leaderboard("testset_v0", data_dir=tmp_path)
    assert board["rows"]
    assert all(row["kind"] != "human" for row in board["rows"])


def test_no_runs_writes_an_empty_board(tmp_path: Path):
    board = build_leaderboard("testset_v0", data_dir=tmp_path)
    assert board["rows"] == []
    assert board["max"] == 0
    assert board["dvsa_reference_pct"] == 0.587
    assert (tmp_path / "leaderboard.json").is_file()


def test_blind_human_is_scored_and_a_seen_session_is_left_out(tmp_path: Path):
    (tmp_path / "clips.json").write_text(
        json.dumps([{"clip_id": "c1", "duration_s": 30.0, "split": "dev"}]),
        encoding="utf-8",
    )
    (tmp_path / "hazards.json").write_text(
        json.dumps(
            [
                {
                    "hazard_id": "h1",
                    "clip_id": "c1",
                    "window_start": 0.0,
                    "window_end": 5.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    blind = {
        "session_id": "h_blind",
        "name": "Ada",
        "role": "team",
        "blind": True,
        "clip_id": "c1",
        "clicks": [0.0],
        "created_at": "2026-10-17T10:00:00+01:00",
    }
    seen = {
        "session_id": "h_seen",
        "name": "Bea",
        "role": "team",
        "blind": False,
        "clip_id": "c1",
        "clicks": [0.0],
        "created_at": "2026-10-17T10:05:00+01:00",
    }
    (tmp_path / "humans.jsonl").write_text(
        json.dumps(blind) + "\n" + json.dumps(seen) + "\n",
        encoding="utf-8",
    )
    board = build_leaderboard("testset_v0", data_dir=tmp_path)
    humans = [row for row in board["rows"] if row["kind"] == "human"]
    assert [row["name"] for row in humans] == ["Ada"]
    assert humans[0]["score"] == 5
    assert humans[0]["pct"] == 1.0
    assert humans[0]["ci90"] == [1.0, 1.0]
    assert humans[0]["lift_vs_chance"] == 0.0
