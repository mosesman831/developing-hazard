"""Verdict rule, grid lookup, and offline fill."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from dh.grid import (
    GridVerifier,
    fill_clip,
    is_hazard,
    load_grid,
    main,
    parse_answer,
    save_grid,
)

_HAZARD = {
    "act": "yes",
    "motion": "moving_into_our_path",
    "where": "other_lane",
    "our_car": "moving",
    "object": "dark car",
}


def test_is_hazard_follows_the_rule():
    assert is_hazard(dict(_HAZARD)) is True
    stationary = {
        "act": "yes",
        "motion": "stationary",
        "where": "other_lane",
        "our_car": "moving",
    }
    assert is_hazard(stationary) is False
    in_lane = {
        "act": "yes",
        "motion": "stationary",
        "where": "in_our_lane",
        "our_car": "moving",
    }
    assert is_hazard(in_lane) is True
    stopped = {
        "act": "yes",
        "motion": "moving_into_our_path",
        "where": "in_our_lane",
        "our_car": "stopped",
    }
    assert is_hazard(stopped) is False
    assert is_hazard({"act": "yes", "motion": "moving_into_our_path"}) is False
    assert is_hazard({"act": "no", **{k: _HAZARD[k] for k in ("motion", "where", "our_car")}}) is False


def test_parse_answer_reads_json_or_returns_unclear():
    raw = 'note {"where":"in_our_lane","motion":"moving_away","our_car":"slowing","act":"yes","object":"a cyclist"}'
    parsed = parse_answer(raw)
    assert parsed["object"] == "a cyclist"
    assert parsed["act"] == "yes"
    assert is_hazard(parsed) is True
    unclear = {
        "act": "unclear",
        "motion": "unclear",
        "where": "unclear",
        "our_car": "unclear",
        "object": "",
    }
    assert parse_answer("not json at all") == unclear
    assert is_hazard(parse_answer("not json at all")) is False


def test_grid_verifier_later_point_wins_and_mismatch_does_not_click():
    points = [
        {
            "t": 1.0,
            "track_id": 7,
            "latency_s": 0.4,
            "is_hazard": True,
            "answer": {"object": "early car", "act": "yes"},
        },
        {
            "t": 2.0,
            "track_id": 7,
            "latency_s": 0.8,
            "is_hazard": False,
            "answer": {"object": "later person"},
        },
    ]
    verifier = GridVerifier(points)
    early = verifier.answer("c1", 1.4, 7)
    assert early.is_hazard is True
    assert early.object == "early car"
    assert early.latency_s == pytest.approx(0.4)
    assert early.track_id == 7

    later = verifier.answer("c1", 2.0, 7)
    assert later.is_hazard is False
    assert later.object == "later person"
    assert later.latency_s == pytest.approx(0.8)

    mismatch = verifier.answer("c1", 2.0, 3)
    assert mismatch.is_hazard is False
    assert mismatch.track_id == 3

    missing = verifier.answer("c1", 0.2, 7)
    assert missing.is_hazard is False
    assert missing.latency_s == 0.0
    assert missing.object == ""


def test_grid_verifier_open_track_uses_the_answer_rule():
    points = [
        {
            "t": 1.0,
            "latency_s": None,
            "answer": {
                "act": "yes",
                "motion": "stationary",
                "where": "in_our_lane",
                "our_car": "moving",
                "object": "person ahead",
            },
        }
    ]
    out = GridVerifier(points).answer("c1", 1.0, 4)
    assert out.is_hazard is True
    assert out.object == "person ahead"
    assert out.latency_s == 0.0


def test_save_and_load_jsonl(tmp_path):
    path = tmp_path / "grid" / "c1.jsonl"
    rows = [
        {"t": 0.5, "track_id": 1, "is_hazard": True, "answer": {"object": "bus"}},
        {"t": 1.5, "track_id": None, "is_hazard": False, "error": None},
    ]
    save_grid(path, rows)
    assert load_grid(path) == rows
    text = path.read_text(encoding="utf-8")
    assert text.count("\n") == 2
    assert load_grid(tmp_path / "missing.jsonl") == []


def test_fill_clip_fake_client_selects_frames_and_limits_flight():
    frames = [
        {"t": round(-1.8 + i * 0.2, 3), "jpeg_b64": f"frame:{round(-1.8 + i * 0.2, 3)}"}
        for i in range(10)
    ]
    seen: list[list[str]] = []

    def client(frames_b64, prompt, model):
        assert prompt == "PROMPT"
        assert model == "cosmos-test"
        seen.append(list(frames_b64))
        return {
            "raw": '{"act":"yes","motion":"stationary","where":"in_our_lane","our_car":"moving","object":"a person"}',
            "latency_s": 0.25,
        }

    rows = fill_clip(
        {"clip_id": "c1", "duration_s": 0.1, "split": "dev"},
        [],
        frames,
        client=client,
        prompt="PROMPT",
        model="cosmos-test",
        in_flight=2,
    )
    assert len(rows) == 1
    assert rows[0]["t"] == 0.0
    assert rows[0]["track_id"] is None
    assert rows[0]["prompt_version"] == "cosmos_verify_v2"
    assert rows[0]["is_hazard"] is True
    assert rows[0]["error"] is None
    assert rows[0]["latency_s"] == pytest.approx(0.25)
    assert rows[0]["answer"]["object"] == "a person"
    assert seen == [[f"frame:{round(-1.4 + i * 0.2, 3)}" for i in range(8)]]


def test_fill_clip_keeps_two_calls_in_flight_and_skips_dev_points_on_test():
    state = {"current": 0, "max": 0}
    lock = threading.Lock()

    def client(frames_b64, prompt, model):
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return {
            "raw": '{"act":"no","motion":"stationary","where":"other_lane","our_car":"moving","object":"tree"}',
            "latency_s": 0.01,
        }

    dev_rows = fill_clip(
        {"clip_id": "c-dev", "duration_s": 6.5, "split": "dev"},
        [],
        [],
        client=client,
        prompt="PROMPT",
        model="m",
        in_flight=2,
    )
    assert [row["t"] for row in dev_rows] == [0.0, 3.0, 6.0]
    assert state["max"] == 2
    assert all(row["is_hazard"] is False for row in dev_rows)

    test_rows = fill_clip(
        {"clip_id": "c-test", "duration_s": 10.0, "split": "test"},
        [],
        [],
        client=client,
        prompt="PROMPT",
        model="m",
    )
    assert test_rows == []


def test_fill_clip_uses_top_track_and_the_time_window():
    det = {"t": 0.4, "cls": "person", "conf": 0.9, "xyxy": [880.0, 400.0, 1040.0, 900.0]}
    frames = [
        {"t": -1.7, "jpeg_b64": "too-old"},
        {"t": 0.0, "jpeg_b64": "frame:0"},
        {"t": 0.4, "jpeg_b64": "frame:0.4"},
        {"t": 0.9, "jpeg_b64": "future"},
    ]
    seen: list[list[str]] = []

    def client(frames_b64, prompt, model):
        seen.append(list(frames_b64))
        return {
            "raw": '{"act":"yes","motion":"moving_into_our_path","where":"other_lane","our_car":"slowing","object":"person"}',
            "latency_s": 0.05,
        }

    rows = fill_clip(
        {"duration_s": 1.0, "split": "test"},
        [det],
        frames,
        client=client,
        prompt="PROMPT",
        model="m",
    )
    assert [row["t"] for row in rows] == [0.5]
    assert rows[0]["track_id"] == 1
    assert rows[0]["is_hazard"] is True
    assert seen == [["frame:0", "frame:0.4"]]


def test_fill_clip_error_string_has_no_secret():
    def client(frames_b64, prompt, model):
        raise RuntimeError("Bearer secret-token failed")

    rows = fill_clip(
        {"duration_s": 0.1, "split": "dev"},
        [],
        [],
        client=client,
        prompt="PROMPT",
        model="m",
    )
    assert len(rows) == 1
    assert rows[0]["error"] == "RuntimeError"
    assert "secret" not in rows[0]["error"].lower()
    assert rows[0]["is_hazard"] is False


def test_main_messages(capsys):
    main([])
    assert capsys.readouterr().out.strip() == "grid: offline stub, cosmos fill is phase 3"
    main(["--fill"])
    assert capsys.readouterr().out.strip() == "grid fill is run by the phase runner"


def test_module_entrypoint_does_not_fill():
    root = Path(__file__).resolve().parents[2]
    plain = subprocess.run(
        [sys.executable, "-m", "dh.grid"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert plain.returncode == 0
    assert plain.stdout.strip() == "grid: offline stub, cosmos fill is phase 3"
    filled = subprocess.run(
        [sys.executable, "-m", "dh.grid", "--fill"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert filled.returncode == 0
    assert filled.stdout.strip() == "grid fill is run by the phase runner"
