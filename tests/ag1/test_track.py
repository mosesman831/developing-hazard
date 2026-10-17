"""IoU tracker, top-k selection, and track jsonl export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dh.track import IoUTracker, run_clip, select_top, thin_tracks, write_tracks


class _Box:
    def __init__(self, cls: str, xyxy: list[float]) -> None:
        self.cls = cls
        self.xyxy = xyxy


def test_two_stationary_same_class_boxes_keep_one_id_each():
    tracker = IoUTracker()
    left = _Box("person", [100.0, 100.0, 160.0, 220.0])
    right = _Box("person", [400.0, 100.0, 460.0, 220.0])
    for step in range(3):
        live = tracker.update(0.2 * step, [left, right])
        by_id = {tr.id: tr for tr in live}
        assert set(by_id) == {1, 2}
        assert by_id[1].cx == 130.0
        assert by_id[2].cx == 430.0
        assert by_id[1].vx == 0.0
        assert by_id[2].vx == 0.0
        assert by_id[1].h == 120.0


def test_far_away_box_gets_a_second_id():
    tracker = IoUTracker()
    near = {"cls": "person", "xyxy": [100.0, 100.0, 160.0, 220.0]}
    for step in range(2):
        live = tracker.update(float(step), [near])
        assert [tr.id for tr in live] == [1]
    far = {"cls": "person", "xyxy": [900.0, 100.0, 960.0, 220.0]}
    live = tracker.update(2.0, [near, far])
    by_id = {tr.id: tr.cx for tr in live}
    assert set(by_id) == {1, 2}
    assert by_id[1] == 130.0
    assert by_id[2] == 930.0


def test_track_missing_four_updates_is_dropped():
    box = {"cls": "car", "xyxy": [10.0, 10.0, 80.0, 60.0]}
    kept = IoUTracker()
    assert kept.update(0.0, [box])[0].id == 1
    for step in range(1, 4):
        assert kept.update(0.2 * step, []) == []
    # Three misses is still within max_misses, so the id survives.
    assert [tr.id for tr in kept.update(0.8, [box])] == [1]

    dropped = IoUTracker()
    assert dropped.update(0.0, [box])[0].id == 1
    for step in range(1, 5):
        assert dropped.update(0.2 * step, []) == []
    again = dropped.update(1.0, [box])
    assert [tr.id for tr in again] == [2]


def test_different_class_does_not_steal_the_track():
    tracker = IoUTracker()
    person = {"cls": "person", "xyxy": [100.0, 100.0, 180.0, 260.0]}
    car = {"cls": "car", "xyxy": [100.0, 100.0, 180.0, 260.0]}
    assert tracker.update(0.0, [person])[0].id == 1
    stolen = tracker.update(0.2, [car])
    assert [(tr.id, tr.cls) for tr in stolen] == [(2, "car")]
    back = tracker.update(0.4, [person])
    assert [(tr.id, tr.cls) for tr in back] == [(1, "person")]


def test_centre_x_velocity_is_about_fifty_px_per_s():
    # Centre x moves 10 px every 0.2 s, so the slope is 50 px/s.
    tracker = IoUTracker()
    live = []
    for step in range(4):
        cx = 100.0 + 10.0 * step
        det = {"cls": "bicycle", "xyxy": [cx - 15.0, 200.0, cx + 15.0, 320.0]}
        live = tracker.update(0.2 * step, [det])
        assert len(live) == 1
        assert live[0].id == 1
    assert live[0].vx == pytest.approx(50.0, abs=1e-6)
    assert live[0].vy == pytest.approx(0.0, abs=1e-6)
    assert live[0].h_rate == pytest.approx(0.0, abs=1e-6)


def test_write_tracks_round_trips_and_keeps_at_most_three_per_t(tmp_path):
    rows = []
    for index, risk in enumerate((0.1, 0.9, 0.4, 0.2, 0.8)):
        rows.append(
            {
                "track_id": index + 1,
                "t": 1.23456,
                "cls": "person",
                "xyxy": [10.1234, 20.0, 30.0, 40.5],
                "vx": 1.2349,
                "vy": 0.0,
                "h_rate": 0.0,
                "in_corridor": True,
                "heading_in": False,
                "ttc": None,
                "t_lat": None,
                "risk": risk,
            }
        )
    rows.append(
        {
            "track_id": 7,
            "t": 2.0,
            "cls": "car",
            "xyxy": [1.0, 2.0, 3.0, 4.0],
            "risk": 0.25,
            "vx": -3.14159,
        }
    )
    chosen = select_top(rows)
    path = write_tracks("c07", chosen, data_dir=str(tmp_path))
    text = path.read_text(encoding="utf-8")
    assert path == tmp_path / "tracks" / "c07.jsonl"
    loaded = [json.loads(line) for line in text.splitlines()]
    by_t: dict[float, list] = {}
    for row in loaded:
        by_t.setdefault(row["t"], []).append(row)
    assert all(len(group) <= 3 for group in by_t.values())
    # Top risks 0.9, 0.8, 0.4 are ids 2, 5, 3, then ordered by track_id.
    assert [row["track_id"] for row in loaded] == [2, 3, 5, 7]
    assert loaded[0]["t"] == round(1.23456, 3)
    assert loaded[0]["vx"] == round(1.2349, 3)
    assert loaded[0]["xyxy"][0] == round(10.1234, 3)
    assert loaded[0]["ttc"] is None
    assert loaded[3]["vx"] == round(-3.14159, 3)
    again = write_tracks("c07", loaded, data_dir=str(tmp_path))
    assert again.read_text(encoding="utf-8") == text


def test_thin_tracks_keeps_overlay_schema_every_nth_frame(tmp_path):
    rows = []
    for step in range(6):
        t = step * 0.2
        for risk, x in ((0.2, 10.4), (0.9, 20.6)):
            rows.append(
                {
                    "track_id": 1 if risk < 0.5 else 2,
                    "t": t,
                    "cls": "car",
                    "xyxy": [x, 30.2, 40.8, 50.1],
                    "vx": 1.2349,
                    "risk": risk,
                }
            )
    thinned = thin_tracks(
        rows, every_n=3, top_k=1, coord_digits=0, keys=("t", "xyxy")
    )
    assert [row["t"] for row in thinned] == [0, 0.6]
    assert thinned[0]["xyxy"] == [21, 30, 41, 50]
    assert set(thinned[0]) == {"t", "xyxy"}
    path = write_tracks(
        "c30",
        rows,
        data_dir=str(tmp_path),
        thin={"every_n": 3, "top_k": 1, "coord_digits": 0, "keys": ("t", "xyxy")},
    )
    assert path.read_text(encoding="utf-8").splitlines()[0] == (
        '{"t":0,"xyxy":[21,30,41,50]}'
    )


def test_demo_and_late_clips_use_the_overlay_schema():
    root = Path(__file__).resolve().parents[2] / "data" / "tracks"
    template = json.loads(
        (root / "c02.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert set(template) == {"t", "xyxy"}
    for clip_id in ("c01", "c27", "c28", "c29", "c30", "c31", "c32", "c33", "c34"):
        lines = (root / f"{clip_id}.jsonl").read_text(encoding="utf-8").splitlines()
        assert lines
        row = json.loads(lines[0])
        assert set(row) == {"t", "xyxy"}
        assert len(row["xyxy"]) == 4
    # c01 is the demo clip, so it keeps a sample twice as often as the others.
    assert len((root / "c01.jsonl").read_text(encoding="utf-8").splitlines()) > len(
        (root / "c30.jsonl").read_text(encoding="utf-8").splitlines()
    )


def test_run_clip_keeps_three_rows_ordered_by_time_and_id():
    dets = []
    for index in range(5):
        x = 50.0 + index * 300.0
        dets.append(
            {
                "t": 1.0,
                "cls": "person",
                "xyxy": [x, 800.0, x + 40.0, 1040.0],
            }
        )
    rows = run_clip(dets, (1920.0, 1080.0))
    assert len(rows) == 3
    assert rows == sorted(rows, key=lambda row: (row["t"], row["track_id"]))
    assert all(row["risk"] <= 1.0 for row in rows)
