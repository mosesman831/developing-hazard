"""Minimal eval runner (Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dh.evals import build_leaderboard, start_run


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
    lines = (run_dir / "clips.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    clip_row = json.loads(lines[0])
    assert clip_row["clip_id"] == "c07"
    assert isinstance(clip_row["clip_score"], int)
    assert isinstance(clip_row["pattern"]["flag"], bool)


def test_build_leaderboard_not_implemented():
    with pytest.raises(NotImplementedError, match="leaderboard is phase 3"):
        build_leaderboard("testset_v0")
