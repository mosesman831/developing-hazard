"""Row builder tests. These call hazard_rows only and do not open VastDB."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import dh.clients.vastdb as vastdb
import dh.store as store

ROOT = Path(__file__).resolve().parents[2]
STORE_PATH = ROOT / "dh" / "store.py"


def _hazard(**extra) -> dict:
    hazard = {
        "hazard_id": "c07_h1",
        "clip_id": "c07",
        "type": "pedestrian_crossing",
        "window_start": 16.2,
        "window_end": 19.0,
        "labellers": {
            "riyu": [16.0, 19.1],
            "fmd": [16.4, 18.9],
        },
        "agreed": True,
        "segment_sources": [
            "s3://example/segments/a.mp4",
            "s3://example/segments/a.mp4",
            "s3://example/segments/b.mp4",
        ],
        "yolo_score": 0.99,
        "object_counts": {"person": 4},
        "detections": [{"cls": "person"}],
    }
    hazard.update(extra)
    return hazard


def test_source_has_no_em_dash():
    text = STORE_PATH.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text


def test_store_does_not_import_database_packages():
    tree = ast.parse(STORE_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= sys.stdlib_module_names | {"dh"}


def test_one_row_per_distinct_segment_source():
    clips = [
        {
            "clip_id": "c07",
            "original_video": "s3://example/chunks/parent.mp4",
        }
    ]
    rows = store.hazard_rows([_hazard()], testset_id="testset_v1", clips=clips)
    assert [row["segment_source"] for row in rows] == [
        "s3://example/segments/a.mp4",
        "s3://example/segments/b.mp4",
    ]
    assert rows[0]["hazard_id"] == "c07_h1"
    assert isinstance(rows[0]["hazard_id"], str)
    assert rows[0]["clip_id"] == "c07"
    assert rows[0]["type"] == "pedestrian_crossing"
    assert rows[0]["window_start"] == 16.2
    assert rows[0]["window_end"] == 19.0
    assert rows[0]["original_video"] == "s3://example/chunks/parent.mp4"
    assert rows[0]["labeller_a"] == "riyu"
    assert rows[0]["labeller_b"] == "fmd"
    assert rows[0]["agreed"] is True
    assert rows[1]["testset_id"] == "testset_v1"
    assert list(rows[0]) == list(store.ROW_COLUMNS)
    for row in rows:
        assert "yolo_score" not in row
        assert "object_counts" not in row
        assert "detections" not in row
        vastdb.project_row(row)


def test_riyu_stays_labeller_a_when_listed_second():
    hazard = _hazard(
        labellers={"fmd": [16.4, 18.9], "riyu": [16.0, 19.1]},
        segment_sources=["s3://example/segments/a.mp4"],
    )
    rows = store.hazard_rows([hazard])
    assert rows[0]["labeller_a"] == "riyu"
    assert rows[0]["labeller_b"] == "fmd"


def test_optional_testset_id_and_single_labeller():
    hazard = _hazard(
        labellers={"riyu": [16.0, 19.1]},
        segment_sources=["s3://example/segments/only.mp4"],
        agreed=False,
    )
    rows = store.hazard_rows([hazard])
    assert len(rows) == 1
    assert rows[0]["testset_id"] is None
    assert rows[0]["labeller_a"] == "riyu"
    assert rows[0]["labeller_b"] is None
    assert rows[0]["agreed"] is False


def test_hazard_video_overrides_clip_and_singular_source():
    hazard = _hazard(
        original_video="s3://example/chunks/from-hazard.mp4",
        segment_source="s3://example/segments/singular.mp4",
        testset_id="from-record",
    )
    del hazard["segment_sources"]
    clips = [{"clip_id": "c07", "original_video": "s3://example/chunks/from-clip.mp4"}]
    rows = store.hazard_rows([hazard], clips=clips)
    assert len(rows) == 1
    assert rows[0]["segment_source"] == "s3://example/segments/singular.mp4"
    assert rows[0]["original_video"] == "s3://example/chunks/from-hazard.mp4"
    assert rows[0]["testset_id"] == "from-record"


def test_explicit_testset_id_overrides_the_record():
    hazard = _hazard(testset_id="from-record", segment_sources=["s3://example/segments/a.mp4"])
    rows = store.hazard_rows([hazard], testset_id="testset_v2")
    assert rows[0]["testset_id"] == "testset_v2"


def test_missing_source_still_emits_one_row():
    hazard = _hazard()
    del hazard["segment_sources"]
    rows = store.hazard_rows([hazard], clips={"c07": "s3://example/chunks/mapped.mp4"})
    assert len(rows) == 1
    assert rows[0]["segment_source"] is None
    assert rows[0]["original_video"] == "s3://example/chunks/mapped.mp4"


def test_row_builder_does_not_call_loaders_or_import_sdk(monkeypatch):
    import dh.clips as clips

    def boom(*_args, **_kwargs):
        raise AssertionError("loader called")

    monkeypatch.setattr(clips, "load_hazards", boom)
    monkeypatch.setattr(clips, "load_clips", boom)
    sys.modules.pop("vastdb", None)
    sys.modules.pop("pyarrow", None)
    rows = store.hazard_rows([_hazard(segment_sources=["s3://example/segments/a.mp4"])])
    assert rows[0]["segment_source"] == "s3://example/segments/a.mp4"
    assert "vastdb" not in sys.modules
    assert "pyarrow" not in sys.modules
