"""Embed client retries and cosine ranking. No live GPU call."""

import dh.clients.embed as embed


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_embed_query_checks_256_dimensions(monkeypatch):
    monkeypatch.setenv("COSMOS_EMBED1_URL", "http://example.test")
    monkeypatch.setenv("GPU_BEARER_TOKEN", "secret-token")
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["timeout"] = kwargs.get("timeout")
        seen["headers"] = kwargs.get("headers")
        seen["json"] = kwargs.get("json")
        return _Response(200, {"data": [{"embedding": [0.1] * 256}]})

    monkeypatch.setattr(embed.requests, "post", fake_post)
    monkeypatch.setattr(embed.time, "sleep", lambda _seconds: None)
    vector = embed.embed_query("a cyclist moves into the lane")
    assert len(vector) == 256
    assert seen["url"] == "http://example.test/v1/embeddings"
    assert seen["timeout"] == 30
    assert seen["json"]["request_type"] == "query"
    assert "secret-token" not in str(seen["json"])


def test_embed_query_retries_then_stops(monkeypatch):
    monkeypatch.setenv("COSMOS_EMBED1_URL", "http://example.test")
    monkeypatch.setenv("GPU_BEARER_TOKEN", "secret-token")
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        return _Response(503, {})

    monkeypatch.setattr(embed.requests, "post", fake_post)
    monkeypatch.setattr(embed.time, "sleep", lambda _seconds: None)
    try:
        embed.embed_query("pedestrian")
    except embed.EmbedError as exc:
        assert "503" in str(exc)
    else:
        raise AssertionError("expected EmbedError")
    assert calls["n"] == 3


def test_more_like_this_ranks_cosine_and_ignores_detection_fields():
    query = [1.0, 0.0, 0.0]
    rows = [
        {
            "source": "s3://segments/far.mp4",
            "camera_id": "pie_cam-3",
            "vectors_visual": [0.0, 1.0, 0.0],
            "object_counts": {"person": 9},
            "risk": 0.99,
        },
        {
            "source": "s3://segments/near.mp4",
            "camera_id": "pie_cam-3",
            "vectors_visual": [1.0, 0.0, 0.0],
        },
        {
            "source": "s3://segments/other.mp4",
            "camera_id": "i24_cam-1",
            "vectors_visual": [1.0, 0.0, 0.0],
        },
    ]
    ranked = embed.more_like_this(query, rows)
    assert [source for _score, source in ranked] == [
        "s3://segments/near.mp4",
        "s3://segments/far.mp4",
    ]
