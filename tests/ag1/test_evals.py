"""Eval runner, bootstrap, and dev-only tuning."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dh.evals import (
    bootstrap_interval,
    build_leaderboard,
    label_sensitivity,
    latency_modes,
    paired_interval,
    start_run,
    tune_dev,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "split_test"


def test_start_run_writes_example_clip(tmp_path: Path):
    run_id = start_run(
        "yolo_risk",
        {"split": "dev"},
        testset_id="testset_v0",
        latency_mode="zero",
        data_dir=tmp_path,
    )
    run_dir = tmp_path / "runs" / run_id
    assert run_dir.is_dir()
    run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_doc["agent"] == "yolo_risk"
    assert isinstance(run_doc["weave_url"], str)
    lines = (run_dir / "clips.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    clip_row = json.loads(lines[0])
    assert clip_row["clip_id"] == "c07"
    assert isinstance(clip_row["clip_score"], int)
    assert isinstance(clip_row["pattern"]["flag"], bool)


def test_bootstrap_of_one_clip_is_degenerate():
    # One clip, score 4 of max 5, resampled: every draw is 0.8.
    assert bootstrap_interval([4], [5]) == (0.8, 0.8)
    assert bootstrap_interval([4, 4, 4], [5, 5, 5]) == (0.8, 0.8)
    assert bootstrap_interval([], []) == (0.0, 0.0)


def test_paired_interval_of_identical_series_is_zero():
    scores = [4.0, 1.0, 0.0]
    maxima = [5.0, 5.0, 5.0]
    low, high = paired_interval(scores, scores, maxima)
    assert low == 0.0
    assert high == 0.0


def test_label_sensitivity_uses_riyu_and_skips_missing_fmd():
    hazard = {
        "hazard_id": "h1",
        "clip_id": "c1",
        "window_start": 20.0,
        "window_end": 25.0,
        "labellers": {"riyu": [0.0, 5.0]},
    }
    result = label_sensitivity([[0.0]], [[hazard]], [30.0])
    assert set(result) == {"riyu"}
    assert result["riyu"]["score"] == 5
    assert result["riyu"]["max"] == 5
    assert result["riyu"]["pct"] == 1.0


def test_tune_dev_does_not_score_the_test_clip(tmp_path: Path, monkeypatch):
    clips = [
        {"clip_id": "dev_clip", "split": "dev", "duration_s": 30.0},
        {"clip_id": "test_clip", "split": "test", "duration_s": 30.0},
    ]
    (tmp_path / "clips.json").write_text(json.dumps(clips), encoding="utf-8")
    seen: list[str] = []

    def fake_start_run(*args, **kwargs):
        data_dir = Path(kwargs["data_dir"])
        loaded = json.loads((data_dir / "clips.json").read_text(encoding="utf-8"))
        assert kwargs["split"] == "dev"
        assert all(clip.get("split") == "dev" for clip in loaded)
        seen.extend(clip["clip_id"] for clip in loaded)
        return "r_fake"

    monkeypatch.setattr("dh.evals.start_run", fake_start_run)
    result = tune_dev(tmp_path)
    assert result["tuned_on_test"] is False
    assert result["split"] == "dev"
    assert result["best"] == {"theta_up": 0.6, "ema_weight": 0.4}
    assert "dev only" in result["note"]
    assert seen
    assert set(seen) == {"dev_clip"}
    assert "test_clip" not in seen


def test_tune_dev_refuses_test_split(tmp_path: Path, monkeypatch):
    (tmp_path / "clips.json").write_text(
        json.dumps([{"clip_id": "test_clip", "split": "test"}]),
        encoding="utf-8",
    )

    def fake_start_run(*args, **kwargs):
        raise AssertionError("start_run must not open a test split")

    monkeypatch.setattr("dh.evals.start_run", fake_start_run)
    with pytest.raises(ValueError, match="test"):
        tune_dev(tmp_path, split="test")


def test_latency_modes_are_the_sweep_list():
    assert latency_modes() == ["zero", "fixed:0.5", "fixed:1", "fixed:2", "fixed:4"]


def test_split_test_cli_and_testset_v2_leaderboard(tmp_path: Path):
    """python -m dh.evals --split test, then build_leaderboard('testset_v2').

    The fixture lives under tests/ag1. The run and the leaderboard are
    written only under tmp_path.
    """
    data = tmp_path / "data"
    shutil.copytree(_FIXTURE, data)
    blob = (data / "clips.json").read_bytes() + b"\n" + (data / "hazards.json").read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    testset = json.loads((data / "testset_v2.json").read_text(encoding="utf-8"))
    assert testset["sha256"] == digest
    assert testset["clips"] == ["fixclip"]

    env = os.environ.copy()
    for name in ("WANDB_API_KEY", "WANDB_TEAM", "WANDB_PROJECT"):
        env.pop(name, None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["DH_DATA_DIR"] = str(data)
    repo = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-m", "dh.evals", "--agent", "yolo_risk", "--split", "test"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    run_id = completed.stdout.strip().splitlines()[-1]
    run_doc = json.loads((data / "runs" / run_id / "run.json").read_text(encoding="utf-8"))
    assert run_doc["testset_id"] == "testset_v2"
    assert run_doc["testset_sha256"] == digest
    lines = (data / "runs" / run_id / "clips.jsonl").read_text(encoding="utf-8").splitlines()
    clip_ids = [json.loads(line)["clip_id"] for line in lines if line.strip()]
    assert clip_ids == ["fixclip"]

    board = build_leaderboard("testset_v2", data_dir=data)
    assert board["testset_id"] == "testset_v2"
    names = [row["name"] for row in board["rows"]]
    assert names == ["yolo_risk"]
    assert (data / "leaderboard.json").is_file()
    assert not (repo / "data" / "testset_v2.json").exists()
