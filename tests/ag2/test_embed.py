"""Cosmos Embed client tests. A fake session stands in for the GPU."""

from __future__ import annotations

import ast
import socket
import sys
from pathlib import Path

import pytest
import requests

import dh.clients.embed as embed

ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "dh" / "clients" / "embed.py"
CANDIDATES = ROOT / "data" / "candidates.jsonl"
TOKEN = "test-bearer-token"
URL = "http://embed.test"


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("unexpected network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)

    def refuse_http(*_args, **_kwargs):
        raise AssertionError("unexpected HTTP call")

    monkeypatch.setattr(embed.requests, "post", refuse_http)
    monkeypatch.setattr(embed.requests.Session, "post", refuse_http)


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COSMOS_EMBED1_URL", URL)
    monkeypatch.setenv("GPU_BEARER_TOKEN", TOKEN)
    monkeypatch.setenv("COSMOS_EMBED1_MODEL", "nvidia/cosmos-embed1")


def _vector(*pairs: tuple[int, float]) -> list[float]:
    values = [0.0] * embed.EMBED_DIM
    for index, value in pairs:
        values[index] = value
    return values


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("no scripted response")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok(vector: list[float]) -> FakeResponse:
    return FakeResponse(200, {"data": [{"embedding": vector, "index": 0}]})


def test_source_has_no_em_dash_and_does_not_import_vastdb():
    text = CLIENT_PATH.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text
    tree = ast.parse(text)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                raise AssertionError("embed client must not open files")
            if isinstance(func, ast.Attribute) and func.attr in {
                "write_text",
                "write_bytes",
                "open",
            }:
                raise AssertionError("embed client must not write files")
    assert "vastdb" not in roots
    assert "pyarrow" not in roots
    assert roots <= sys.stdlib_module_names | {"requests", "weave"}


def test_import_with_empty_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GPU_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("COSMOS_EMBED1_URL", raising=False)
    monkeypatch.delenv("COSMOS_EMBED1_MODEL", raising=False)
    import importlib

    importlib.reload(embed)
    assert embed.EMBED_DIM == 256
    assert embed.TIMEOUT_S == 30


def test_embed_query_posts_query_float_and_bearer(monkeypatch: pytest.MonkeyPatch):
    _block_network(monkeypatch)
    _env(monkeypatch)
    vector = _vector((0, 1.0))
    session = FakeSession([_ok(vector)])
    result = embed.embed_query("a person walking", session=session)
    assert result == vector
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == f"{URL}/v1/embeddings"
    assert call["timeout"] == 30
    assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
    body = call["json"]
    assert body["input"] == "a person walking"
    assert body["request_type"] == "query"
    assert body["encoding_format"] == "float"
    assert body["model"] == "nvidia/cosmos-embed1"
    assert TOKEN not in str(body)


def test_wrong_dimension_raises(monkeypatch: pytest.MonkeyPatch):
    _block_network(monkeypatch)
    _env(monkeypatch)
    session = FakeSession([FakeResponse(200, {"data": [{"embedding": [0.1, 0.2]}]})])
    with pytest.raises(RuntimeError, match="256"):
        embed.embed_query("hello", session=session)
    assert len(session.calls) == 1


def test_retries_twice_with_jitter(monkeypatch: pytest.MonkeyPatch):
    _block_network(monkeypatch)
    _env(monkeypatch)
    vector = _vector((1, 1.0))
    session = FakeSession(
        [
            FakeResponse(503, text="busy"),
            requests.ConnectionError("down"),
            _ok(vector),
        ]
    )
    slept: list[float] = []
    monkeypatch.setattr(embed.random, "uniform", lambda _low, _high: 0.05)
    monkeypatch.setattr(embed.time, "sleep", slept.append)
    result = embed.embed_query("again", session=session)
    assert result == vector
    assert len(session.calls) == 3
    assert slept == [0.05, 0.10]
    assert all(call["timeout"] == 30 for call in session.calls)


def test_error_redacts_bearer_token(monkeypatch: pytest.MonkeyPatch):
    _block_network(monkeypatch)
    _env(monkeypatch)
    session = FakeSession(
        [
            FakeResponse(500, text=f"Bearer {TOKEN} failed"),
            FakeResponse(500, text=f"token={TOKEN}"),
            FakeResponse(400, text=f"rejected {TOKEN}"),
        ]
    )
    monkeypatch.setattr(embed.time, "sleep", lambda _delay: None)
    with pytest.raises(RuntimeError) as exc:
        embed.embed_query("hello", session=session)
    assert TOKEN not in str(exc.value)
    assert len(session.calls) == 3


def test_missing_url_does_not_call_session(monkeypatch: pytest.MonkeyPatch):
    _block_network(monkeypatch)
    monkeypatch.delenv("COSMOS_EMBED1_URL", raising=False)
    monkeypatch.setenv("GPU_BEARER_TOKEN", TOKEN)
    session = FakeSession([])
    with pytest.raises(RuntimeError, match="COSMOS_EMBED1_URL") as exc:
        embed.embed_query("hello", session=session)
    assert TOKEN not in str(exc.value)
    assert session.calls == []


def test_more_like_this_ranks_visual_vectors_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _block_network(monkeypatch)
    _env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path / "data"))
    before = CANDIDATES.read_bytes() if CANDIDATES.is_file() else None
    query = _vector((0, 1.0))
    session = FakeSession([_ok(query)])
    similar = {
        "source": "s3://example/segments/similar.mp4",
        "vectors_visual": _vector((0, 1.0)),
        "yolo_score": 0.01,
        "object_counts": {"person": 0},
        "detections": [],
        "risk": 0.0,
    }
    other_camera = {
        "source": "s3://example/segments/other.mp4",
        "camera_id": "other-cam",
        "vectors_visual": _vector((0, 1.0)),
        "yolo_score": 1.0,
    }
    dissimilar = {
        "source": "s3://example/segments/dissimilar.mp4",
        "vectors_visual": _vector((1, 1.0)),
        "yolo_score": 0.99,
        "object_counts": {"person": 9},
        "detections": [{"cls": "person"}],
        "risk": 1.0,
    }
    detector_only = {
        "source": "s3://example/segments/detector.mp4",
        "yolo_score": 1.0,
        "object_counts": {"person": 12},
        "detections": [{"cls": "car"}],
        "risk": 1.0,
    }
    ranked = embed.more_like_this(
        "data:video/mp4;base64,AAAA",
        [other_camera, dissimilar, detector_only, similar],
        session=session,
    )
    assert [row["source"] for row in ranked] == [
        "s3://example/segments/similar.mp4",
        "s3://example/segments/dissimilar.mp4",
    ]
    assert ranked[0]["similarity"] == 1.0
    assert ranked[1]["similarity"] == 0.0
    assert "similarity" not in similar
    assert session.calls[0]["json"]["input"] == "data:video/mp4;base64,AAAA"
    assert session.calls[0]["json"]["request_type"] == "query"
    assert session.calls[0]["json"]["encoding_format"] == "float"
    assert not (tmp_path / "data" / "candidates.jsonl").exists()
    assert list(tmp_path.rglob("*")) == []
    after = CANDIDATES.read_bytes() if CANDIDATES.is_file() else None
    assert before == after


def test_more_like_this_empty_rows_do_not_call_the_session(monkeypatch: pytest.MonkeyPatch):
    _block_network(monkeypatch)
    session = FakeSession([])
    assert embed.more_like_this("unused", [], session=session) == []
    assert session.calls == []
