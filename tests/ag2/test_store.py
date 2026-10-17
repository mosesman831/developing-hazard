"""VastDB row builder and the write guard. No network."""

from dh.clients.vastdb import TABLE_NAME, VastDBError, refuse
from dh.store import hazard_rows


def test_hazard_rows_split_sources_and_name_riyu_first():
    hazards = [
        {
            "hazard_id": "c07_h1",
            "clip_id": "c07",
            "type": "pedestrian_crossing",
            "window_start": 16.2,
            "window_end": 19.0,
            "labellers": {"fmd": [16.4, 18.9], "riyu": [16.0, 19.1]},
            "agreed": True,
            "segment_sources": ["s3://segments/a.mp4", "s3://segments/b.mp4"],
        }
    ]
    clips = [{"clip_id": "c07", "original_video": "s3://chunks/parent.mp4"}]
    rows = hazard_rows(hazards, clips, testset_id="")
    assert len(rows) == 2
    assert rows[0]["labeller_a"] == "riyu"
    assert rows[0]["labeller_b"] == "fmd"
    assert rows[0]["segment_source"] == "s3://segments/a.mp4"
    assert rows[1]["segment_source"] == "s3://segments/b.mp4"
    assert rows[0]["original_video"] == "s3://chunks/parent.mp4"
    assert rows[0]["agreed"] is True
    assert rows[0]["testset_id"] == ""


def test_refuse_index_tables_and_media_buckets(monkeypatch):
    monkeypatch.setenv("VASTDB_BUCKET", "team-bucket")
    monkeypatch.setenv("S3_CHUNKS_BUCKET", "team-chunks")
    monkeypatch.setenv("S3_SEGMENTS_BUCKET", "team-segments")
    try:
        refuse("developing_hazard", "vss-collection", "team-bucket")
    except VastDBError as exc:
        assert "index" in str(exc)
    else:
        raise AssertionError("expected a refusal")
    try:
        refuse("developing_hazard", TABLE_NAME, "team-chunks")
    except VastDBError as exc:
        assert "media" in str(exc)
    else:
        raise AssertionError("expected a refusal")
    refuse("developing_hazard", TABLE_NAME, "team-bucket")
