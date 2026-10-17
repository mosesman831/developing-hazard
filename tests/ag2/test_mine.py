"""Miner: caption filters, keyword rank, and clip build. No network."""

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import Mock

import dh.mine as mine
from dh.clients.vss import VSS, VSSError
from dh.mine import (
    QUERIES,
    assemble_clip,
    build,
    keyword_score,
    main,
    mine as run_mine,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_TOKEN = "fixture-token"

STRONG = (
    "The camera vehicle is driving. A pedestrian steps off the curb "
    "and starts to cross the road."
)
WEAK = "The camera vehicle is driving. The vehicle ahead brakes suddenly."
STOPPED = "The camera vehicle is stopped while a pedestrian steps off the curb."
NEGATED = "No pedestrians are visible as the camera vehicle is driving."
PARTIAL = (
    "No pedestrians are visible. The camera vehicle is driving and a cyclist "
    "moves out into the lane."
)
SCRUB = "The camera vehicle continues forward. A cyclist moves out into the lane."
BRAKE_TRAP = "The camera vehicle is driving. Brake lights flash ahead."


def _name(set_name: str, index: int) -> str:
    return f"20240101_{set_name}_video_chunk_{index:04d}.mp4"


def _uri(set_name: str, index: int) -> str:
    return f"s3://example-bucket/team/{_name(set_name, index)}"


def _segment_rows(set_name: str, index: int, captions: dict[int, tuple[str, float]]) -> list[dict]:
    stem = _name(set_name, index).removesuffix(".mp4")
    rows = []
    for number in range(6, 0, -1):
        text, start = captions.get(number, ("The road is empty.", float((number - 1) * 5)))
        rows.append(
            {
                "source": (
                    f"s3://example-bucket/segments/{stem}"
                    f"_segment_{number:03d}_of_006.mp4"
                ),
                "segment_number": number,
                "segment_start_sec": start,
                "reasoning_content": text,
                "object_counts": '{"person": 999}',
                "perception_json": '{"risk": 1}',
                "detection_count": 999,
            }
        )
    return rows


def _hit(set_name: str, index: int, caption: str, **extra) -> dict:
    hit = {
        "original_video": _uri(set_name, index),
        "filename": _name(set_name, index),
        "source": (
            f"s3://example-bucket/segments/{_name(set_name, index).removesuffix('.mp4')}"
            "_segment_004_of_006.mp4"
        ),
        "reasoning_content": caption,
        "similarity_score": 0.31,
        "object_counts": '{"person": 1}',
        "perception_json": '{"risk": 0}',
        "detection_count": 1,
        "location": "toronto",
    }
    hit.update(extra)
    return hit


def _client():
    strong = _hit("set03", 5, STRONG, segment_start_sec=15, similarity_score=0.31)
    strong["object_counts"] = '{"person": 1}'
    weak = _hit(
        "set03",
        9,
        WEAK,
        segment_start_sec=10,
        similarity_score=0.99,
        object_counts='{"person": 500}',
        perception_json='{"risk": 9}',
        detection_count=500,
    )
    negated = _hit("set05", 1, NEGATED, segment_start_sec=10, similarity_score=0.4)
    stopped = _hit(
        "set05",
        2,
        STOPPED,
        segment_start_sec=15,
        similarity_score=0.98,
        object_counts='{"person": 900}',
        detection_count=900,
    )
    early = _hit(
        "set05",
        3,
        STRONG,
        segment_start_sec=2.0,
        best_match_start_sec=20,
        similarity_score=0.97,
        object_counts='{"person": 800}',
    )
    partial = _hit(
        "set06",
        7,
        PARTIAL,
        similarity_score=0.33,
        object_counts='{"person": 40}',
    )
    partial.pop("segment_start_sec", None)
    partial["best_match_start_sec"] = 10

    by_query = {query: [] for query in QUERIES}
    by_query[QUERIES[0]] = [strong]
    by_query[QUERIES[1]] = [negated]
    by_query[QUERIES[2]] = [stopped]
    by_query[QUERIES[3]] = [early]
    by_query[QUERIES[4]] = [weak]
    by_query[QUERIES[5]] = [partial]

    segments = {
        _uri("set03", 5): _segment_rows(
            "set03",
            5,
            {
                4: (STRONG, 15),
                6: (BRAKE_TRAP, 25),
            },
        ),
        _uri("set03", 9): _segment_rows("set03", 9, {3: (WEAK, 10)}),
        _uri("set04", 2): _segment_rows(
            "set04",
            2,
            {
                2: ("No pedestrians are visible.", 5),
                3: (STOPPED, 10),
                5: (SCRUB, 20),
            },
        ),
        _uri("set01", 1): _segment_rows("set01", 1, {4: (STRONG, 15)}),
    }
    explore = {
        "chunks": [
            {"filename": _name("set03", 5), "original_video": _uri("set03", 5), "location": "toronto"},
            {"filename": _name("set03", 9), "original_video": _uri("set03", 9), "location": "toronto"},
            {"filename": _name("set04", 2), "original_video": _uri("set04", 2), "location": "toronto"},
            {"filename": _name("set01", 1), "original_video": _uri("set01", 1), "location": "toronto"},
            {"filename": "neighborhood_clip.mp4", "original_video": "s3://example-bucket/team/neighborhood_clip.mp4", "location": "toronto"},
        ],
        "total": 5,
    }
    client = Mock()
    client.search.side_effect = lambda query, filters=None, top_k=30: list(by_query[query])
    client.explore.return_value = explore
    client.segments.side_effect = lambda original_video: list(segments.get(original_video, []))
    return client


def test_mine_source_does_not_name_detection_fields():
    source = (ROOT / "dh" / "mine.py").read_text(encoding="utf-8")
    for banned in ("object_counts", "perception_json", "detection_count"):
        assert banned not in source


def test_mine_drops_negated_stopped_and_early_and_ranks_by_caption(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DH_DATA_DIR", "data")
    client = _client()
    rows = run_mine(client)
    again = run_mine(client)
    assert [row["candidate_id"] for row in rows] == [
        "pie_set03_c0005",
        "pie_set03_c0009",
        "pie_set04_c0002",
        "pie_set06_c0007",
    ]
    assert rows == again
    ids = {row["candidate_id"] for row in rows}
    assert "pie_set05_c0001" not in ids
    assert "pie_set05_c0002" not in ids
    assert "pie_set05_c0003" not in ids
    assert "pie_set01_c0001" not in ids

    strong = rows[0]
    assert strong["ego_moving"] is True
    assert strong["hit_second"] == 15
    assert strong["camera_id"] == "pie_cam-3"
    assert strong["location"] == "toronto"
    assert strong["set"] == "set03"
    assert strong["chunk_index"] == 5
    assert strong["found_by"] == "search"
    assert strong["status"] == "new"
    assert strong["search_score"] == 0.31
    assert strong["queries"] == [QUERIES[0]]
    assert "pedestrian" in strong["caption_snippet"]
    assert "brake" not in strong["caption_snippet"].lower()
    assert len(strong["caption_snippet"]) <= 400
    assert [Path(source).name.split("_segment_")[1] for source in strong["segments"]] == [
        "001_of_006.mp4",
        "002_of_006.mp4",
        "003_of_006.mp4",
        "004_of_006.mp4",
        "005_of_006.mp4",
        "006_of_006.mp4",
    ]
    assert keyword_score(STRONG) > keyword_score(WEAK)
    assert rows[1]["search_score"] == 0.99
    assert rows[1]["hit_second"] == 10

    scrub = rows[2]
    assert scrub["found_by"] == "scrub"
    assert scrub["search_score"] is None
    assert scrub["queries"] == []
    assert scrub["ego_moving"] is True
    assert scrub["hit_second"] == 20
    assert "cyclist" in scrub["caption_snippet"]

    partial = rows[3]
    assert partial["hit_second"] == 10
    assert "cyclist" in partial["caption_snippet"]
    assert "no pedestrian" not in partial["caption_snippet"].lower()

    assert [call.args[0] for call in client.search.call_args_list][: len(QUERIES)] == list(QUERIES)
    for call in client.search.call_args_list:
        assert call.kwargs["filters"] == {"camera_id": "pie_cam-3"}
        assert call.kwargs["top_k"] == 30
    client.explore.assert_called_with(location="toronto", limit=48, offset=0)
    fetched = [call.args[0] for call in client.segments.call_args_list]
    assert _uri("set01", 1) not in fetched
    assert fetched.count(_uri("set03", 5)) == 2

    path = tmp_path / "data" / "candidates.jsonl"
    body = path.read_text(encoding="utf-8")
    assert body.endswith("\n")
    assert body.count("\n") == len(rows)
    assert not (tmp_path / "data" / "hazards.json").exists()
    printed = capsys.readouterr().out.splitlines()
    assert printed[:5] == ["4", * [row["candidate_id"] for row in rows]]
    assert "s3://" not in capsys.readouterr().out
    joined = "\n".join(printed)
    assert "s3://" not in joined
    assert "Bearer" not in joined


def test_segment_fetch_is_capped(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DH_DATA_DIR", "data")
    chunks = []
    for index in range(181):
        name = _name("set02", index)
        chunks.append(
            {
                "filename": name,
                "original_video": f"s3://example-bucket/team/{name}",
                "location": "toronto",
            }
        )
    client = Mock()
    client.search.return_value = []

    def explore(*, location, limit, offset):
        return {"chunks": chunks[offset : offset + limit], "total": len(chunks)}

    client.explore.side_effect = explore
    client.segments.return_value = []
    rows = run_mine(client)
    assert rows == []
    assert client.segments.call_count == 180
    called = {call.args[0] for call in client.segments.call_args_list}
    assert chunks[0]["original_video"] in called
    assert chunks[180]["original_video"] not in called


def test_vss_explore_segments_and_metadata_values(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="dh.clients.vss")
    monkeypatch.setenv("USERNAME", "fixture-user")
    monkeypatch.setenv("PASSWORD", "fixture-password")
    script = [
        {"chunks": [{"filename": "a.mp4"}], "total": 1},
        [{"source": "s3://example-bucket/from-list.mp4", "skipped": "no"}],
        {"results": [{"source": "s3://example-bucket/from-results.mp4"}]},
        {"segments": [{"source": "s3://example-bucket/from-segments.mp4", "object_counts": "9"}]},
        {"field": "location", "values": ["toronto", 3], "count": 2},
        {"chunks": [], "total": 0},
    ]

    class _Response:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

        def close(self):
            return None

    class _Session:
        def __init__(self):
            self.calls = []

        def request(self, method, url, headers=None, params=None, json=None, timeout=None, stream=False):
            self.calls.append(
                {"method": method, "url": url, "headers": headers, "params": params}
            )
            return _Response(script.pop(0))

    session = _Session()
    client = VSS(base_url="http://vss.example/api/v1", session=session)
    client._token = FIXTURE_TOKEN
    monkeypatch.setattr(client, "_backoff", lambda: None)
    explored = client.explore(location="toronto", limit=48, offset=0)
    assert explored["total"] == 1
    assert client.segments("s3://example-bucket/parent.mp4") == [
        {"source": "s3://example-bucket/from-list.mp4", "skipped": "no"}
    ]
    assert client.segments("s3://example-bucket/parent.mp4") == [
        {"source": "s3://example-bucket/from-results.mp4"}
    ]
    listed = client.segments("s3://example-bucket/parent.mp4")
    assert listed == [{"source": "s3://example-bucket/from-segments.mp4", "object_counts": "9"}]
    assert client.metadata_values("location", limit=50) == ["toronto"]
    bare = client.explore(limit=48, offset=0)
    assert bare["chunks"] == []
    explore_call, list_call, results_call, segments_call, values_call, bare_call = session.calls
    assert explore_call["url"].endswith("/videos/explore")
    assert explore_call["params"] == {
        "scope": "all",
        "limit": 48,
        "offset": 0,
        "location": "toronto",
    }
    assert explore_call["headers"]["Authorization"] == f"Bearer {FIXTURE_TOKEN}"
    assert list_call["url"].endswith("/tools/segments")
    assert list_call["params"]["original_video"] == "s3://example-bucket/parent.mp4"
    assert results_call["url"].endswith("/tools/segments")
    assert segments_call["params"]["original_video"] == "s3://example-bucket/parent.mp4"
    assert values_call["url"].endswith("/metadata/values")
    assert values_call["params"] == {"field": "location", "limit": 50}
    assert "location" not in bare_call["params"]
    assert FIXTURE_TOKEN not in caplog.text
    assert "fixture-password" not in caplog.text


def test_main_dispatches_mine_and_build(monkeypatch):
    mined = Mock(return_value=[])
    built = Mock(return_value=[])
    monkeypatch.setattr(mine, "mine", mined)
    monkeypatch.setattr(mine, "build", built)
    main([])
    main(["build"])
    mined.assert_called_once_with()
    built.assert_called_once_with()


def _candidate(index: int, **extra) -> dict:
    name = _name("set02", index)
    row = {
        "candidate_id": f"pie_set02_c{index:04d}",
        "camera_id": "pie_cam-3",
        "location": "toronto",
        "original_video": f"s3://example-bucket/team/{name}",
        "set": "set02",
        "chunk_index": index,
        "segments": [
            f"s3://example-bucket/segments/{name.removesuffix('.mp4')}_segment_{number:03d}_of_006.mp4"
            for number in range(1, 7)
        ],
        "found_by": "search",
        "queries": [QUERIES[0]],
        "hit_second": 10,
        "search_score": 0.3,
        "caption_snippet": "The camera vehicle is driving.",
        "ego_moving": True,
        "status": "new",
    }
    row.update(extra)
    return row


class _Stream:
    def iter_content(self, chunk_size=1024 * 1024):
        yield b"segment-bytes"

    def close(self):
        return None


def test_build_splits_dev_and_test_and_joins_clips(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DH_DATA_DIR", "data")
    monkeypatch.delenv("DH_FPS_SAMPLE", raising=False)
    rows = [_candidate(index) for index in range(1, 7)]
    rows.append(_candidate(7, status="labelled", segments=["s3://example-bucket/segments/only-one.mp4"]))
    rows.append(_candidate(8, status="rejected"))
    rows.append(_candidate(9, ego_moving=False))
    rows.append(_candidate(10, hit_second=2))
    directory = tmp_path / "data"
    directory.mkdir()
    body = "".join(json.dumps(row) + "\n" for row in rows)
    (directory / "candidates.jsonl").write_text(body, encoding="utf-8")

    def stream(source, range_header=None):
        if "video_chunk_0003" in source:
            raise VSSError("VSS GET /videos/stream returned 404")
        return _Stream()

    def segments(original_video):
        stem = original_video.rsplit("/", 1)[-1].removesuffix(".mp4")
        return [
            {"source": f"s3://example-bucket/segments/{stem}_segment_{number:03d}_of_006.mp4"}
            for number in range(6, 0, -1)
        ]

    def fake_ffmpeg(command, **kwargs):
        output = Path(command[-1])
        output.write_bytes(b"joined")
        assert command[command.index("-f") + 1] == "concat"
        assert command[command.index("-c") + 1] == "copy"
        return subprocess.CompletedProcess(command, 0)

    client = Mock()
    client.stream.side_effect = stream
    client.segments.side_effect = segments
    monkeypatch.setattr(mine.subprocess, "run", fake_ffmpeg)
    clips = build(client)
    assert [clip["clip_id"] for clip in clips] == [f"c{index:02d}" for index in range(1, 8)]
    assert [clip["split"] for clip in clips] == ["dev"] * 6 + ["test"]
    assert clips[0]["candidate_id"] == "pie_set02_c0001"
    assert clips[6]["candidate_id"] == "pie_set02_c0007"
    assert "pie_set02_c0008" not in {clip["candidate_id"] for clip in clips}
    for clip in clips:
        assert clip["camera_id"] == "pie_cam-3"
        assert clip["fps_native"] == 30
        assert clip["fps_sample"] == 5
        assert clip["seen_by"] == ["riyu"]
        assert len(clip["segments"]) == 6
        assert clip["duration_s"] == 30
        assert clip["segments"][0]["start_s"] == 0
        assert clip["segments"][0]["end_s"] == 5
    assert "local_path" not in clips[2]
    assert clips[2]["notes"]
    assert "s3://" not in clips[2]["notes"]
    assert "Bearer" not in clips[2]["notes"]
    assert clips[0]["local_path"] == "data/clips/c01.mp4"
    assert clips[0]["notes"] == ""
    assert (tmp_path / "data" / "clips" / "c01.mp4").is_file()
    assert not (tmp_path / "data" / "clips" / "c03.mp4").exists()
    assert clips[6]["segments"][0]["source"].endswith("segment_001_of_006.mp4")
    assert client.segments.call_count == 1
    text = (tmp_path / "data" / "clips.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text)[0]["clip_id"] == "c01"
    assert not (tmp_path / "data" / "hazards.json").exists()


def test_assemble_prepends_the_previous_chunk_when_onset_is_early():
    sources = [f"s3://example-bucket/seg/b_segment_{number:03d}_of_006.mp4" for number in range(1, 7)]
    previous = [f"s3://example-bucket/seg/a_segment_{number:03d}_of_006.mp4" for number in range(1, 7)]
    row = {
        "candidate_id": "pie_set03_c0005",
        "original_video": "s3://example-bucket/team/chunk.mp4",
        "hit_second": 2,
    }
    clip = assemble_clip(
        row,
        "c01",
        fps=5,
        split="dev",
        sources=sources,
        previous_sources=previous,
    )
    assert clip["duration_s"] == 60
    assert len(clip["segments"]) == 12
    assert clip["segments"][0]["source"] == previous[0]
    assert clip["segments"][0]["start_s"] == 0
    assert clip["segments"][6]["source"] == sources[0]
    assert clip["segments"][6]["start_s"] == 30
    assert clip["seen_by"] == ["riyu"]
    assert "onset_s" not in clip
    assert "local_path" not in clip
    try:
        assemble_clip(
            row,
            "c01",
            fps=5,
            split="dev",
            sources=sources,
            previous_sources=None,
        )
    except ValueError as exc:
        assert "previous" in str(exc)
    else:
        raise AssertionError("expected ValueError")
