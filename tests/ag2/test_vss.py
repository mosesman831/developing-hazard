"""VSS client: login, search, stream, detections, 401 re-login, timeouts."""

import ast
import logging
import sys
from pathlib import Path

import requests

import dh.clients.vss as vss
from dh.clients.vss import TIMEOUT_S, VIDEO_TIMEOUT_S, VSS, VSSError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PASSWORD = "fixture-password"
FIXTURE_TOKEN = "fixture-token"
FIXTURE_TOKEN_RELOGIN = "fixture-token-relogin"


def test_vss_imports_are_stdlib_or_requests():
    tree = ast.parse((ROOT / "dh" / "clients" / "vss.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= sys.stdlib_module_names | {"requests"}


class _Response:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload
        self.closed = False

    def json(self):
        return self._payload

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None, stream=False):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
                "stream": stream,
            }
        )
        if not self.script:
            raise AssertionError(f"unexpected {method} {url}")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(script, monkeypatch):
    monkeypatch.setenv("USERNAME", "fixture-user")
    monkeypatch.setenv("PASSWORD", FIXTURE_PASSWORD)
    monkeypatch.delenv("INGRESS_URL", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    session = _Session(script)
    client = VSS(base_url="http://vss.example/api/v1", session=session)
    monkeypatch.setattr(client, "_backoff", lambda: None)
    return client, session


def test_login_search_detections_and_stream(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="dh.clients.vss")
    client, session = _client(
        [
            _Response(200, {"access_token": FIXTURE_TOKEN, "token_type": "bearer"}),
            _Response(200, {"results": [{"source": "s3://example/segment.mp4"}]}),
            _Response(200, {"frames": [], "fps": 30}),
            _Response(200, b""),
        ],
        monkeypatch,
    )
    hits = client.search(
        "pedestrian starts to cross",
        filters={"camera_id": "pie_cam-3"},
        top_k=30,
    )
    assert hits == [{"source": "s3://example/segment.mp4"}]
    detections = client.detections("s3://example/segment.mp4")
    assert detections["fps"] == 30
    streamed = client.stream("s3://example/segment.mp4", range_header="bytes=0-")
    assert streamed.status_code == 200
    login, search, detections_call, stream = session.calls
    assert login["url"].endswith("/auth/login")
    assert login["json"] == {"username": "fixture-user", "password": FIXTURE_PASSWORD}
    assert login["timeout"] == TIMEOUT_S
    assert search["timeout"] == TIMEOUT_S
    assert search["json"]["top_k"] == 30
    assert search["json"]["llm_top_n"] == 1
    assert search["json"]["min_similarity"] == 0.3
    assert search["json"]["metadata_filters"] == {"camera_id": "pie_cam-3"}
    assert search["headers"]["Authorization"] == f"Bearer {FIXTURE_TOKEN}"
    assert detections_call["timeout"] == TIMEOUT_S
    assert detections_call["params"]["source"] == "s3://example/segment.mp4"
    assert stream["timeout"] == VIDEO_TIMEOUT_S
    assert stream["stream"] is True
    assert stream["params"]["token"] == FIXTURE_TOKEN
    assert stream["headers"]["Range"] == "bytes=0-"
    assert "Authorization" not in (stream["headers"] or {})
    assert FIXTURE_PASSWORD not in caplog.text
    assert FIXTURE_TOKEN not in caplog.text


def test_relogin_on_401(monkeypatch):
    client, session = _client(
        [
            _Response(200, {"access_token": FIXTURE_TOKEN}),
            _Response(401, {}),
            _Response(200, {"access_token": FIXTURE_TOKEN_RELOGIN}),
            _Response(200, {"results": [{"source": "s3://example/after.mp4"}]}),
        ],
        monkeypatch,
    )
    hits = client.search("cyclist moves out")
    assert hits[0]["source"] == "s3://example/after.mp4"
    assert session.calls[1]["headers"]["Authorization"] == f"Bearer {FIXTURE_TOKEN}"
    assert session.calls[3]["headers"]["Authorization"] == f"Bearer {FIXTURE_TOKEN_RELOGIN}"
    assert session.calls[2]["url"].endswith("/auth/login")


def test_search_stops_after_two_retries(monkeypatch):
    client, session = _client(
        [
            _Response(200, {"access_token": FIXTURE_TOKEN}),
            requests.Timeout("timed out"),
            requests.Timeout("timed out"),
            requests.Timeout("timed out"),
        ],
        monkeypatch,
    )
    try:
        client.search("parked car door opening")
    except VSSError as exc:
        assert FIXTURE_PASSWORD not in str(exc)
    else:
        raise AssertionError("expected VSSError")
    assert len(session.calls) == 4


def test_password_comes_from_config_file_not_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("PASSWORD", raising=False)
    config = tmp_path / "team.config"
    config.write_text('export PASSWORD="fixture-password"\n', encoding="utf-8")
    monkeypatch.setattr(vss, "_config_files", lambda: [config])
    assert vss._credential("PASSWORD") == FIXTURE_PASSWORD
    assert FIXTURE_PASSWORD in vss._secrets


def test_search_retries_timeout_then_succeeds(monkeypatch):
    client, session = _client(
        [
            _Response(200, {"access_token": FIXTURE_TOKEN}),
            requests.Timeout("timed out"),
            _Response(200, {"results": []}),
        ],
        monkeypatch,
    )
    assert client.search("bus pulling away") == []
    assert len(session.calls) == 3


def test_login_error_does_not_include_password(monkeypatch):
    client, _session = _client([_Response(401, {"detail": FIXTURE_PASSWORD})], monkeypatch)
    try:
        client.login()
    except VSSError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected VSSError")
    assert FIXTURE_PASSWORD not in message
    assert "401" in message


def test_detections_404_is_an_error(monkeypatch):
    client, _session = _client(
        [
            _Response(200, {"access_token": FIXTURE_TOKEN}),
            _Response(404, {}),
        ],
        monkeypatch,
    )
    try:
        client.detections("s3://example/missing.mp4")
    except VSSError as exc:
        assert "404" in str(exc)
    else:
        raise AssertionError("expected VSSError")


def test_base_url_from_ingress_or_cluster(monkeypatch):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.setenv("INGRESS_URL", "http://ingress.example")
    assert vss.resolve_base_url() == "http://ingress.example/api/v1"
    monkeypatch.setenv("INGRESS_URL", "http://ingress.example/api/v1/")
    assert vss.resolve_base_url() == "http://ingress.example/api/v1"
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setenv("USERNAME", "team-fixture")
    assert vss.resolve_base_url() == (
        "http://video-backend-service.team-fixture.svc.cluster.local:8000/api/v1"
    )
    assert vss.resolve_base_url("http://override.example/api/v1") == (
        "http://override.example/api/v1"
    )


def test_redact_filter_hides_password(caplog):
    vss._remember(FIXTURE_PASSWORD)
    caplog.set_level(logging.INFO, logger="dh.clients.vss")
    vss.logger.info("saw %s", FIXTURE_PASSWORD)
    assert FIXTURE_PASSWORD not in caplog.text
    assert "[redacted]" in caplog.text
