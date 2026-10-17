"""YOLO infer HTTP client (SPEC 11.4).

YOLO_URL is the base. There is no fallback host. The whole video is one payload.
"""

from __future__ import annotations

import os
import random
import re
import time

import requests

_TIMEOUT_S = 120
_ATTEMPTS = 3
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

_BEARER_RE = re.compile(r"(?i)\bbearer\s+\S+")
_SENSITIVE_RE = re.compile(
    r"(?i)\b((?:authorization|api[_-]?key|token|password|secret)\s*[:=]\s*)\S+"
)
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")


def _redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove bearer tokens and other secrets from a short error snippet."""
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = _BEARER_RE.sub("Bearer [redacted]", cleaned)
    cleaned = _SENSITIVE_RE.sub(r"\1[redacted]", cleaned)
    cleaned = _SK_RE.sub("[redacted]", cleaned)
    return cleaned


def _safe_url(url: str) -> str:
    """Drop userinfo, query, and fragment so an error cannot carry a secret."""
    if "://" in url:
        scheme, rest = url.split("://", 1)
        rest = rest.rsplit("@", 1)[-1]
        rest = rest.split("?", 1)[0].split("#", 1)[0]
        return f"{scheme}://{rest}"
    return url.split("?", 1)[0].split("#", 1)[0]


def _snippet(response: requests.Response) -> str:
    text = getattr(response, "text", "")
    if not isinstance(text, str):
        text = str(text)
    return text[:500]


def _lookup(name: str) -> str | None:
    """Read one setting at call time. A missing value stays None."""
    raw = None
    try:
        import dh.config as config
    except ImportError:
        config = None
    if config is not None:
        raw = config.env(name)
    else:
        raw = os.environ.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _require(name: str) -> str:
    value = _lookup(name)
    if value is None:
        raise RuntimeError(f"missing environment variable {name}")
    return value


def _backoff(attempt: int) -> None:
    """Pause before another try. attempt is the zero-based index that just failed."""
    time.sleep(random.uniform(0.05, 0.25) * (attempt + 1))


def _dispatch(
    method: str,
    url: str,
    headers: dict[str, str],
    timeout: float,
    json_body: dict | None,
) -> requests.Response:
    if method == "GET":
        return requests.get(url, headers=headers, timeout=timeout)
    if method == "POST":
        return requests.post(url, headers=headers, json=json_body, timeout=timeout)
    raise RuntimeError(f"unsupported method {method}")


def _parse_json(
    response: requests.Response,
    method: str,
    url: str,
    secrets: tuple[str, ...],
) -> dict:
    try:
        parsed = response.json()
    except ValueError:
        detail = _redact(_snippet(response), secrets)
        raise RuntimeError(
            f"{method} {_safe_url(url)} returned a non-JSON body: {detail}"
        ) from None
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{method} {_safe_url(url)} returned JSON that is not an object")
    return parsed


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    json_body: dict | None = None,
    secrets: tuple[str, ...] = (),
) -> dict:
    """Send one HTTP call, with two jittered retries after the first attempt."""
    safe_url = _safe_url(url)
    for attempt in range(_ATTEMPTS):
        try:
            response = _dispatch(method, url, headers, timeout, json_body)
        except (requests.Timeout, requests.ConnectionError):
            if attempt < _ATTEMPTS - 1:
                _backoff(attempt)
                continue
            raise RuntimeError(f"{method} {safe_url} failed after {_ATTEMPTS} attempts") from None

        status = response.status_code
        if status in _RETRY_STATUSES and attempt < _ATTEMPTS - 1:
            _backoff(attempt)
            continue
        if status >= 400:
            detail = _redact(_snippet(response), secrets)
            raise RuntimeError(f"{method} {safe_url} returned HTTP {status}: {detail}")
        return _parse_json(response, method, url, secrets)

    raise RuntimeError(f"{method} {safe_url} failed after {_ATTEMPTS} attempts")


def _infer_url(raw: str) -> str:
    """POST the given URL when its path already ends with /v1/infer."""
    base = raw.strip().rstrip("/")
    rest = base.split("://", 1)[1] if "://" in base else base
    slash = rest.find("/")
    path = rest[slash:] if slash != -1 else ""
    path = path.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if path.endswith("/v1/infer"):
        return base
    return f"{base}/v1/infer"


try:
    import weave
except ImportError:
    class _Weave:
        @staticmethod
        def op(fn):
            return fn

    weave = _Weave()


@weave.op
def infer(video_b64: str, *, include_frames: bool = True) -> dict:
    """POST the whole video and return the parsed JSON object."""
    base = _require("YOLO_URL")
    token = _require("GPU_BEARER_TOKEN")
    url = _infer_url(base)
    headers = {"Authorization": f"Bearer {token}"}
    body = {"video": video_b64, "include_frames": include_frames}
    return _request_json(
        "POST",
        url,
        headers=headers,
        timeout=_TIMEOUT_S,
        json_body=body,
        secrets=(token,),
    )
