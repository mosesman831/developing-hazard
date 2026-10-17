"""Loaders read contracts/examples/. Clip definition is the 30 second chunk."""

import ast
import sys
from pathlib import Path

import dh.clips as clips

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"


def test_clips_module_is_stdlib_only():
    tree = ast.parse((ROOT / "dh" / "clips.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= sys.stdlib_module_names


def test_loaders_read_contract_examples(monkeypatch):
    monkeypatch.setenv("DH_DATA_DIR", str(EXAMPLES))
    loaded = clips.load_clips()
    hazards = clips.load_hazards()
    testset = clips.load_testset()
    assert loaded[0]["clip_id"] == "c07"
    assert len(loaded[0]["segments"]) == 6
    assert hazards[0]["hazard_id"] == "c07_h1"
    assert testset["testset_id"] == "testset_v0"
    meta = clips.clip_meta(loaded[0])
    assert set(meta) == {"clip_id", "duration_s", "fps_sample", "segments"}
    assert "hazards" not in meta
    assert "window_start" not in meta
    assert "window_end" not in meta


def test_clip_meta_drops_hazard_fields():
    meta = clips.clip_meta(
        {
            "clip_id": "c07",
            "duration_s": 30.0,
            "fps_sample": 5,
            "segments": [],
            "hazards": [{"hazard_id": "c07_h1"}],
            "window_start": 1.0,
            "window_end": 2.0,
            "description": "hidden",
        }
    )
    assert set(meta) == {"clip_id", "duration_s", "fps_sample", "segments"}


def test_latest_testset_is_highest_version(monkeypatch, tmp_path):
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    clips.write_json("testset_v0.json", {"testset_id": "testset_v0"})
    clips.write_json("testset_v2.json", {"testset_id": "testset_v2"})
    clips.write_json("testset_v1.json", {"testset_id": "testset_v1"})
    assert clips.load_testset()["testset_id"] == "testset_v2"
    assert clips.load_testset("testset_v1")["testset_id"] == "testset_v1"


def test_chunk_offsets_and_early_onset_prepends_previous_chunk():
    sources = [f"chunk-b-{index}" for index in range(1, 7)]
    previous = [f"chunk-a-{index}" for index in range(1, 7)]
    defined = clips.define_chunk_clip(sources, onset_s=5)
    assert defined["prepended"] is False
    assert defined["duration_s"] == 30
    assert defined["onset_s"] == 5
    assert [segment["start_s"] for segment in defined["segments"]] == [
        0, 5, 10, 15, 20, 25
    ]
    assert [segment["end_s"] for segment in defined["segments"]] == [
        5, 10, 15, 20, 25, 30
    ]
    early = clips.define_chunk_clip(sources, onset_s=4, previous_sources=previous)
    assert early["prepended"] is True
    assert early["duration_s"] == 60
    assert early["onset_s"] == 34
    starts = [segment["start_s"] for segment in early["segments"]]
    assert starts == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
    assert early["segments"][0]["source"] == "chunk-a-1"
    assert early["segments"][6]["source"] == "chunk-b-1"


def test_early_onset_without_previous_chunk_is_rejected():
    sources = [f"only-{index}" for index in range(6)]
    try:
        clips.define_chunk_clip(sources, onset_s=0)
    except ValueError as exc:
        assert "previous chunk" in str(exc)
    else:
        raise AssertionError("expected ValueError")
