"""Frame timestamps and the ffmpeg extractor. No real video."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import dh.frames as frames
from dh.frames import extract_frames, frame_times, main


def test_frame_times_at_five_fps():
    assert frame_times(3, 5) == [0.0, 0.2, 0.4]


def test_extract_frames_mocks_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DH_DATA_DIR", "data")
    local = tmp_path / "data" / "clips" / "c01.mp4"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"not a real video")

    def fake_run(command, check=False, capture_output=False):
        out = Path(command[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        for index in (3, 1, 2):
            (out.parent / f"{index:06d}.jpg").write_bytes(b"\xff\xd8")
        return subprocess.CompletedProcess(command, 0)

    with patch("dh.frames.subprocess.run", side_effect=fake_run) as run:
        payload = extract_frames(
            {"clip_id": "c01", "local_path": "data/clips/c01.mp4"},
            fps=5,
        )
    command = run.call_args.args[0]
    assert command[0] == "ffmpeg"
    assert "-y" in command
    assert command[command.index("-vf") + 1] == "fps=5,scale=960:-2"
    assert command[command.index("-q:v") + 1] == "3"
    assert command[-1].endswith("%06d.jpg")
    assert payload == {
        "clip_id": "c01",
        "fps": 5,
        "frames": [
            {"file": "000001.jpg", "t": 0.0},
            {"file": "000002.jpg", "t": 0.2},
            {"file": "000003.jpg", "t": 0.4},
        ],
    }
    manifest = tmp_path / "data" / "frames" / "c01" / "frames.json"
    assert json.loads(manifest.read_text(encoding="utf-8")) == payload
    assert manifest.read_text(encoding="utf-8").endswith("\n")
    assert not list(tmp_path.glob("*.jpg"))


def test_extract_refuses_a_clip_id_that_escapes_frames(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DH_DATA_DIR", "data")
    try:
        extract_frames({"clip_id": "..", "local_path": "data/clips/c01.mp4"}, fps=5)
    except ValueError as exc:
        assert "clip" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert not (tmp_path / "000001.jpg").exists()


def test_main_skips_missing_files_and_uses_sample_fps(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DH_DATA_DIR", "data")
    monkeypatch.setenv("DH_FPS_SAMPLE", "4")
    clip_dir = tmp_path / "data" / "clips"
    clip_dir.mkdir(parents=True)
    (clip_dir / "c01.mp4").write_bytes(b"x")
    (tmp_path / "data" / "clips.json").write_text(
        json.dumps(
            [
                {"clip_id": "c01", "local_path": "data/clips/c01.mp4"},
                {"clip_id": "c02", "local_path": "data/clips/c02.mp4"},
            ]
        ),
        encoding="utf-8",
    )
    seen = {}

    def fake_extract(clip, fps=5):
        seen["fps"] = fps
        seen["clip_id"] = clip["clip_id"]
        return {"clip_id": clip["clip_id"], "fps": fps, "frames": []}

    monkeypatch.setattr(frames, "extract_frames", fake_extract)
    main()
    assert seen == {"fps": 4, "clip_id": "c01"}
    assert capsys.readouterr().out.splitlines() == ["c02"]
