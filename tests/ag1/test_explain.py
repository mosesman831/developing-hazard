"""Miss explainer cache. The model client is mocked."""

from __future__ import annotations

import json
from pathlib import Path

from dh.explain import explain_run, risk_summary, track_summary, verdict_summary


def _hazard(hazard_id: str, points: int) -> dict:
    return {
        "hazard_id": hazard_id,
        "clip_id": "cfix",
        "window_start": 10.0,
        "window_end": 14.0,
        "description": "a person steps out",
    }


def _write_run(root: Path, points: dict[str, int]) -> None:
    hazards = [_hazard(hazard_id, score) for hazard_id, score in points.items()]
    (root / "hazards.json").write_text(json.dumps(hazards), encoding="utf-8")
    run_dir = root / "runs" / "r_fix"
    run_dir.mkdir(parents=True)
    row = {
        "clip_id": "cfix",
        "clicks": [{"t": 2.0}],
        "hazard_points": points,
        "risk_curve": [[10.0, 0.2], [12.0, 0.5], [20.0, 0.9]],
        "clip_score": sum(points.values()),
    }
    (run_dir / "clips.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    grid_dir = root / "grid" / "cosmos_verify_v2"
    grid_dir.mkdir(parents=True)
    point = {"t": 12.0, "is_hazard": False}
    (grid_dir / "cfix.jsonl").write_text(json.dumps(point) + "\n", encoding="utf-8")
    track_dir = root / "tracks"
    track_dir.mkdir()
    box = {"t": 10.0, "xyxy": [0, 0, 10, 10]}
    (track_dir / "cfix.jsonl").write_text(json.dumps(box) + "\n", encoding="utf-8")


def test_explain_run_caches_miss_with_approved_false(tmp_path: Path):
    _write_run(tmp_path, {"cfix_h1": 0, "cfix_h2": 5})
    seen: list[str] = []

    def fake_complete(prompt: str) -> str:
        seen.append(prompt)
        return "The click was before the window. Risk inside the window stayed low."

    written = explain_run("r_fix", data_dir=tmp_path, complete=fake_complete)
    assert written == ["cfix_h1"]
    assert seen
    assert "0/5" in seen[0]
    assert "a person steps out" in seen[0]
    cache = tmp_path / "cache" / "explain" / "r_fix" / "cfix_h1.json"
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["approved"] is False
    assert payload["points"] == 0
    assert payload["text"] == (
        "The click was before the window. Risk inside the window stayed low."
    )
    assert payload["prompt_version"] == "explain_miss_v1"
    assert not (tmp_path / "cache" / "explain" / "r_fix" / "cfix_h2.json").exists()


def test_risk_verdict_and_track_summaries_use_the_window():
    assert risk_summary([[10.0, 0.2], [12.0, 0.5], [20.0, 0.9]], 10.0, 14.0) == (
        "2 samples inside the window, min 0.2, max 0.5"
    )
    assert verdict_summary([{"t": 12.0, "is_hazard": True}], 10.0, 14.0) == "t=12.0 HAZARD"
    text = track_summary(
        [
            {"t": 10.0, "xyxy": [0, 0, 2, 2]},
            {"t": 10.0, "xyxy": [0, 0, 8, 8]},
            {"t": 1.0, "xyxy": [0, 0, 100, 100]},
        ],
        10.0,
    )
    assert text.startswith("t=10.0 xyxy=[0, 0, 8, 8]")
