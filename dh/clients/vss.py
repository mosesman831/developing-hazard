"""VSS retrieval client (SPEC 11.4).

Login, search, stream and detections. Uses ``requests`` only so the pod can
import this module. Re-logs in on HTTP 401. Timeouts are 30 seconds, and
120 seconds for video. Never logs the JWT or the password.
"""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path

import requests

TIMEOUT_S = 30
VIDEO_TIMEOUT_S = 120
_RETRY_STATUSES = {429, 502, 503, 504}
_MAX_RETRIES = 2

logger = logging.getLogger(__name__)
_secrets: set[str] = set()


class _RedactFilter(logging.Filter):
    """Drop JWT and password text from any log record on this logger."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for secret in _secrets:
            if secret:
                redacted = redacted.replace(secret, "[redacted]")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


logger.addFilter(_RedactFilter())


class VSSError(Exception):
    """VSS call failed. The message never includes a JWT or password."""


def _remember(secret: str) -> None:
    if secret:
        _secrets.add(secret)


def _config_files() -> list[Path]:
    config_dir = Path("/config")
    if not config_dir.is_dir():
        return []
    return sorted(
        path
        for path in config_dir.iterdir()
        if path.is_file() and path.name.endswith(".config")
    )


def _parse_config_value(path: Path, name: str) -> str:
    prefix = name + "="
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name or line.startswith(prefix):
            return value.strip().strip('"').strip("'")
    return ""


def _credential(name: str) -> str:
    """Read one team credential from the environment, else the single config file.

    On zsh, ``USERNAME`` is reserved, so the skills parse ``/config/*.config``
    instead of sourcing it (SPEC 18.5). This does the same. The value is not logged.
    """
    value = os.environ.get(name, "")
    if value:
        _remember(value if name in {"PASSWORD"} else "")
        return value
    files = _config_files()
    if len(files) != 1:
        return ""
    found = _parse_config_value(files[0], name)
    if name == "PASSWORD":
        _remember(found)
    return found


def _in_cluster() -> bool:
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


def _with_api_prefix(root: str) -> str:
    root = root.rstrip("/")
    if root.endswith("/api/v1"):
        return root
    return root + "/api/v1"


def resolve_base_url(base_url: str | None = None) -> str:
    """``$INGRESS_URL/api/v1``, or the in-cluster backend URL inside a pod."""
    if base_url:
        return base_url.rstrip("/")
    if _in_cluster():
        team = _credential("USERNAME")
        if team:
            return (
                f"http://video-backend-service.{team}"
                ".svc.cluster.local:8000/api/v1"
            )
    ingress = _credential("INGRESS_URL")
    if not ingress:
        raise VSSError("INGRESS_URL is not set")
    return _with_api_prefix(ingress)


class VSS:
    def __init__(
        self,
        base_url: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = resolve_base_url(base_url)
        self._session = session if session is not None else requests.Session()
        self._token: str | None = None
        self._username = _credential("USERNAME")
        self._password = _credential("PASSWORD")
        _remember(self._password)

    def __repr__(self) -> str:
        return f"VSS(base_url={self.base_url!r})"

    def login(self) -> str:
        """``POST /auth/login`` and cache the access token. The token is not logged."""
        username = self._username or _credential("USERNAME")
        password = self._password or _credential("PASSWORD")
        self._username = username
        self._password = password
        _remember(password)
        if not username or not password:
            raise VSSError("VSS username or password is not set")
        network_tries = 0
        while True:
            try:
                response = self._session.request(
                    "POST",
                    self._url("/auth/login"),
                    json={"username": username, "password": password},
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    timeout=TIMEOUT_S,
                )
            except requests.RequestException:
                network_tries += 1
                if network_tries > _MAX_RETRIES:
                    raise VSSError("VSS login failed")
                self._backoff()
                continue
            if response.status_code in _RETRY_STATUSES:
                response.close()
                network_tries += 1
                if network_tries > _MAX_RETRIES:
                    raise VSSError(f"VSS login returned {response.status_code}")
                self._backoff()
                continue
            if response.status_code != 200:
                response.close()
                raise VSSError(f"VSS login returned {response.status_code}")
            token = _access_token(response)
            response.close()
            self._token = token
            _remember(token)
            logger.info("VSS login succeeded")
            return token

    def search(
        self,
        query: str,
        filters: dict | None = None,
        top_k: int = 30,
    ) -> list[dict]:
        """``POST /search``. Returns the ``results`` list."""
        body = {
            "query": query,
            "top_k": top_k,
            "llm_top_n": 1,
            "min_similarity": 0.3,
            "metadata_filters": dict(filters or {}),
        }
        response = self._call("POST", "/search", timeout=TIMEOUT_S, json_body=body)
        try:
            payload = response.json()
        except ValueError:
            response.close()
            raise VSSError("VSS search returned no JSON")
        response.close()
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise VSSError("VSS search returned no results list")
        return payload["results"]

    def stream(
        self,
        source: str,
        range_header: str | None = None,
    ) -> requests.Response:
        """``GET /videos/stream`` with ``stream=True``. JWT is the ``token`` query param."""
        headers: dict[str, str] = {}
        if range_header:
            headers["Range"] = range_header
        return self._call(
            "GET",
            "/videos/stream",
            timeout=VIDEO_TIMEOUT_S,
            params={"source": source},
            headers=headers,
            stream=True,
            auth="query",
        )

    def detections(self, source: str) -> dict:
        """Raw ``GET /videos/detections`` JSON. A missing sidecar is an error, not an empty dict."""
        response = self._call(
            "GET",
            "/videos/detections",
            timeout=TIMEOUT_S,
            params={"source": source},
        )
        try:
            payload = response.json()
        except ValueError:
            response.close()
            raise VSSError("VSS detections returned no JSON")
        response.close()
        if not isinstance(payload, dict):
            raise VSSError("VSS detections returned no object")
        return payload

    def _ensure_token(self) -> str:
        if not self._token:
            self.login()
        assert self._token is not None
        return self._token

    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def _backoff(self) -> None:
        time.sleep(random.random())

    def _call(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        params: dict | None = None,
        json_body: dict | None = None,
        headers: dict | None = None,
        stream: bool = False,
        auth: str = "bearer",
    ) -> requests.Response:
        network_tries = 0
        did_relogin = False
        while True:
            token = self._ensure_token() if auth != "none" else ""
            call_headers = dict(headers or {})
            call_params = dict(params or {})
            if auth == "bearer":
                call_headers["Authorization"] = f"Bearer {token}"
                call_headers.setdefault("Accept", "application/json")
            elif auth == "query":
                call_params["token"] = token
            try:
                response = self._session.request(
                    method,
                    self._url(path),
                    headers=call_headers or None,
                    params=call_params or None,
                    json=json_body,
                    timeout=timeout,
                    stream=stream,
                )
            except requests.RequestException:
                network_tries += 1
                if network_tries > _MAX_RETRIES:
                    raise VSSError(f"VSS {method} {path} failed")
                self._backoff()
                continue
            if response.status_code == 401 and auth != "none" and not did_relogin:
                response.close()
                self._token = None
                self.login()
                did_relogin = True
                continue
            if response.status_code in _RETRY_STATUSES:
                response.close()
                network_tries += 1
                if network_tries > _MAX_RETRIES:
                    raise VSSError(
                        f"VSS {method} {path} returned {response.status_code}"
                    )
                self._backoff()
                continue
            if response.status_code >= 400:
                status = response.status_code
                response.close()
                raise VSSError(f"VSS {method} {path} returned {status}")
            return response


def _access_token(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        raise VSSError("VSS login returned no JSON")
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise VSSError("VSS login returned no access_token")
    return token
