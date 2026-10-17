"""Offline tests for dh.dets (SPEC 7.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dh.dets import frames_from_dets, load_clip, parse_detections


def _frame(time_sec: float, detections: list[dict]) -> dict:
    return {"time_sec": time_sec, "detections": detections}


def _det(label: str, conf: float, y1: float, y2: float) -> dict:
    return {
        "label": label,
        "confidence": conf,
        "bbox": [10.0, y1, 50.0, y2],
    }


def test_parse_filters_classes_confidence_and_box_height() -> None:
    payload = {
        "video_shape": [1000, 1920],
        "fps": 30,
        "frames": [
            _frame(
                0.0,
                [
                    _det("person", 0.9, 100.0, 200.0),
                    _det("cow", 0.99, 100.0, 200.0),
                    _det("person", 0.1, 100.0, 200.0),
                    _det("person", 0.9, 10.0, 30.0),
                    _det("person", 0.9, 10.0, 110.0),
                ],
            ),
        ],
    }
    rows, wh = parse_detections(payload, start_s=0.0)
    assert wh == (1920.0, 1000.0)
    assert len(rows) == 2
    confs = sorted(r["conf"] for r in rows)
    assert confs == [0.9, 0.9]
    heights = sorted(abs(r["xyxy"][3] - r["xyxy"][1]) for r in rows)
    assert heights == [100.0, 100.0]


def test_parse_adds_segment_start_to_time() -> None:
    payload = {
        "video_shape": [1000, 1920],
        "fps": 30,
        "frames": [_frame(1.0, [_det("person", 0.9, 100.0, 200.0)])],
    }
    rows, _ = parse_detections(payload, start_s=10.0)
    assert len(rows) == 1
    assert rows[0]["t"] == pytest.approx(11.0)


def test_parse_subsamples_at_30_fps() -> None:
    frames = [
        _frame(i / 30.0, [_det("person", 0.9, 100.0, 200.0)]) for i in range(30)
    ]
    payload = {"video_shape": [1000, 1920], "fps": 30, "frames": frames}
    rows, _ = parse_detections(payload, start_s=0.0)
    kept_times = sorted({r["t"] for r in rows})
    assert len(kept_times) == 5
    assert len(kept_times) < len(frames)


def test_frames_from_dets_groups_by_time() -> None:
    dets = [
        {"t": 2.0, "frame": 1, "cls": "person", "conf": 0.9, "xyxy": [0, 0, 1, 1]},
        {"t": 1.0, "frame": 0, "cls": "car", "conf": 0.8, "xyxy": [0, 0, 2, 2]},
        {"t": 2.0, "frame": 1, "cls": "dog", "conf": 0.7, "xyxy": [0, 0, 3, 3]},
    ]
    grouped = frames_from_dets(dets)
    assert grouped == [
        (1.0, "", [dets[1]]),
        (2.0, "", [dets[0], dets[2]]),
    ]


def test_load_clip_uses_cache_on_second_call(tmp_path: Path) -> None:
    calls: list[str] = []

    class FakeClient:
        def detections(self, source: str) -> dict:
            calls.append(source)
            return {
                "video_shape": [1000, 1920],
                "fps": 30,
                "frames": [_frame(0.0, [_det("person", 0.9, 100.0, 200.0)])],
            }

    clip = {
        "clip_id": "clip-a",
        "segments": [{"source": "seg-1", "start_s": 0.0, "end_s": 5.0}],
    }
    first = load_clip(clip, client=FakeClient(), data_dir=tmp_path)
    second = load_clip(clip, client=FakeClient(), data_dir=tmp_path)
    assert len(first["dets"]) == 1
    assert second["dets"] == first["dets"]
    assert calls == ["seg-1"]
    cache = tmp_path / "det" / "clip-a.jsonl"
    assert cache.is_file()


def test_load_clip_yolo_fallback_writes_person(tmp_path: Path) -> None:
    class FailingClient:
        def detections(self, source: str) -> dict:
            raise RuntimeError("sidecar missing")

    def fake_read(_source: str) -> bytes:
        return b"fake-video-bytes"

    def fake_yolo(video_b64: str, include_frames: bool = True) -> dict:
        assert include_frames is True
        assert video_b64
        return {
            "video_shape": [1000, 1920],
            "fps": 30,
            "frames": [_frame(0.0, [_det("person", 0.9, 100.0, 200.0)])],
        }

    clip = {
        "clip_id": "clip-b",
        "segments": [{"source": "seg-2", "start_s": 0.0, "end_s": 5.0}],
    }
    out = load_clip(
        clip,
        client=FailingClient(),
        yolo_infer=fake_yolo,
        read_video=fake_read,
        data_dir=tmp_path,
    )
    assert out["errors"] == []
    assert len(out["dets"]) == 1
    assert out["dets"][0]["cls"] == "person"
    assert (tmp_path / "det" / "clip-b.jsonl").is_file()


def test_load_clip_total_failure_no_cache(tmp_path: Path) -> None:
    class FailingClient:
        def detections(self, source: str) -> dict:
            raise RuntimeError("no sidecar")

    def failing_yolo(video_b64: str, include_frames: bool = True) -> dict:
        raise RuntimeError("yolo down")

    clip = {
        "clip_id": "clip-c",
        "segments": [{"source": "seg-3", "start_s": 0.0, "end_s": 5.0}],
    }
    out = load_clip(
        clip,
        client=FailingClient(),
        yolo_infer=failing_yolo,
        read_video=lambda _s: b"bytes",
        data_dir=tmp_path,
    )
    assert out["dets"] == []
    assert out["errors"]
    assert not (tmp_path / "det" / "clip-c.jsonl").exists()


def test_label_aliases_normalised() -> None:
    payload = {
        "video_shape": [1000, 1920],
        "fps": 30,
        "frames": [
            _frame(
                0.0,
                [
                    {
                        "cls": "traffic_light",
                        "conf": 0.9,
                        "bbox": {"x1": 1, "y1": 100, "x2": 2, "y2": 200},
                    },
                ],
            ),
        ],
    }
    rows, _ = parse_detections(payload, start_s=0.0)
    assert rows[0]["cls"] == "traffic light"
