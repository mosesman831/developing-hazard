"""Offline tests for the AG1 HTTP clients.

The bearer token exists only in memory. These tests do not write it to disk.
"""

from __future__ import annotations

import importlib

import pytest
import requests

_ENV_NAMES = (
    "GPU_BEARER_TOKEN",
    "COSMOS3_REASON_URL",
    "YOLO_URL",
    "WANDB_API_KEY",
    "WANDB_TEAM",
    "WANDB_PROJECT",
)


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text

    def json(self):
        return self._payload


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_import_with_empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    import dh.clients.cosmos as cosmos
    import dh.clients.wandb_llm as wandb_llm
    import dh.clients.yolo as yolo

    importlib.reload(cosmos)
    importlib.reload(yolo)
    importlib.reload(wandb_llm)


def test_cosmos_chat_posts_bearer_and_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import dh.clients.cosmos as cosmos

    token = "secret-token"
    monkeypatch.setenv("COSMOS3_REASON_URL", "http://example.test")
    monkeypatch.setenv("GPU_BEARER_TOKEN", token)
    seen: dict = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["timeout"] = kwargs.get("timeout")
        seen["headers"] = kwargs.get("headers")
        seen["json"] = kwargs.get("json")
        return _Response(200, {"id": "ok"})

    monkeypatch.setattr(cosmos.requests, "post", fake_post)

    result = cosmos.chat([{"role": "user", "content": "hello"}], model="cosmos-test")

    assert result == {"id": "ok"}
    assert seen["url"] == "http://example.test/v1/chat/completions"
    assert seen["timeout"] == 30
    assert seen["headers"]["Authorization"] == f"Bearer {token}"
    assert token not in str(seen["json"])
    assert list(tmp_path.rglob("*")) == []


def test_cosmos_retries_500_then_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    import dh.clients.cosmos as cosmos

    monkeypatch.setenv("COSMOS3_REASON_URL", "http://example.test")
    monkeypatch.setenv("GPU_BEARER_TOKEN", "secret-token")
    calls = {"n": 0}
    slept: list[float] = []

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Response(500, text="busy")
        return _Response(200, {"id": "second"})

    monkeypatch.setattr(cosmos.requests, "post", fake_post)
    monkeypatch.setattr(cosmos.random, "uniform", lambda _low, _high: 0.1)
    monkeypatch.setattr(cosmos.time, "sleep", lambda delay: slept.append(delay))

    result = cosmos.chat([{"role": "user", "content": "x"}], model="m")

    assert result == {"id": "second"}
    assert calls["n"] == 2
    assert slept == [0.1]


def test_missing_cosmos_url(monkeypatch: pytest.MonkeyPatch) -> None:
    import dh.clients.cosmos as cosmos

    monkeypatch.delenv("COSMOS3_REASON_URL", raising=False)
    monkeypatch.setenv("GPU_BEARER_TOKEN", "secret-token")

    with pytest.raises(RuntimeError, match="COSMOS3_REASON_URL"):
        cosmos.list_models()


def test_yolo_infer_posts_include_frames_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import dh.clients.yolo as yolo

    monkeypatch.setenv("YOLO_URL", "http://example.test")
    monkeypatch.setenv("GPU_BEARER_TOKEN", "secret-token")
    seen: dict = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["timeout"] = kwargs.get("timeout")
        seen["json"] = kwargs.get("json")
        seen["headers"] = kwargs.get("headers")
        return _Response(200, {"detections": []})

    monkeypatch.setattr(yolo.requests, "post", fake_post)

    result = yolo.infer("abcd")

    assert result == {"detections": []}
    assert seen["url"] == "http://example.test/v1/infer"
    assert seen["timeout"] == 120
    assert seen["json"]["include_frames"] is True
    assert seen["json"]["video"] == "abcd"
    assert seen["headers"]["Authorization"] == "Bearer secret-token"


def test_wandb_complete_posts_to_inference_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import dh.clients.wandb_llm as wandb_llm

    monkeypatch.setenv("WANDB_API_KEY", "test-wandb-key")
    monkeypatch.delenv("WANDB_TEAM", raising=False)
    monkeypatch.delenv("WANDB_PROJECT", raising=False)
    seen: dict = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["timeout"] = kwargs.get("timeout")
        seen["headers"] = kwargs.get("headers")
        seen["json"] = kwargs.get("json")
        return _Response(200, {"choices": []})

    monkeypatch.setattr(wandb_llm.requests, "post", fake_post)

    result = wandb_llm.complete("Say hi", model="demo")

    assert result == {"choices": []}
    assert seen["url"] == "https://api.inference.wandb.ai/v1/chat/completions"
    assert seen["timeout"] == 30
    assert seen["headers"]["Authorization"] == "Bearer test-wandb-key"
    assert "OpenAI-Project" not in seen["headers"]
    assert seen["json"]["messages"] == [{"role": "user", "content": "Say hi"}]


def test_public_calls_work_without_weave(monkeypatch: pytest.MonkeyPatch) -> None:
    """The no-op decorator leaves the public functions callable."""
    import dh.clients.cosmos as cosmos
    import dh.clients.wandb_llm as wandb_llm
    import dh.clients.yolo as yolo

    monkeypatch.setenv("COSMOS3_REASON_URL", "http://example.test")
    monkeypatch.setenv("YOLO_URL", "http://example.test/v1/infer")
    monkeypatch.setenv("GPU_BEARER_TOKEN", "secret-token")
    monkeypatch.setenv("WANDB_API_KEY", "test-wandb-key")

    def fake_post(url, **kwargs):
        return _Response(200, {"via": "post", "url": url})

    def fake_get(url, **kwargs):
        return _Response(200, {"via": "get", "url": url})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)

    assert cosmos.list_models()["via"] == "get"
    frames = ["data:image/jpeg;base64,AAAA"]
    verified = cosmos.verify_frames(frames, "hazard?", model="m")
    assert verified["via"] == "post"
    inferred = yolo.infer("zzzz", include_frames=True)
    assert inferred["url"] == "http://example.test/v1/infer"
    completed = wandb_llm.complete("ping", model="demo")
    assert completed["url"] == "https://api.inference.wandb.ai/v1/chat/completions"
