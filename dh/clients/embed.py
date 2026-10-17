"""Cosmos Embed1 client (SPEC 11.4).

POST {COSMOS_EMBED1_URL}/v1/embeddings with the GPU bearer token,
request_type query and encoding_format float. Timeout is 30 seconds, with
two retries and jitter. A vector must have 256 dimensions. The bearer token
is never logged.

more_like_this ranks rows by cosine similarity of vectors_visual. It does not
write data/candidates.jsonl and it does not rank by detection or YOLO fields.
"""

from __future__ import annotations

import os
import random
import re
import time

import requests

TIMEOUT_S = 30
EMBED_DIM = 256
VECTOR_COLUMN = "vectors_visual"
CAMERA_ID = "pie_cam-3"


class EmbedError(RuntimeError):
    """An embeddings call failed. The message does not include the bearer token."""


_RETRIES = 2
_ATTEMPTS = _RETRIES + 1
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_PUBLIC_MODEL_ID = "nvidia/cosmos-embed1"

_BEARER_RE = re.compile(r"(?i)\bbearer\s+\S+")
_SENSITIVE_RE = re.compile(
    r"(?i)\b((?:authorization|api[_-]?key|token|password|secret)\s*[:=]\s*)\S+"
)


def _optional_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _require_env(name: str) -> str:
    value = _optional_env(name)
    if value is None:
        raise EmbedError(f"missing environment variable {name}")
    return value


def _redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove bearer tokens and other secrets from a short error snippet."""
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = _BEARER_RE.sub("Bearer [redacted]", cleaned)
    cleaned = _SENSITIVE_RE.sub(r"\1[redacted]", cleaned)
    return cleaned


def _safe_url(url: str) -> str:
    """Drop userinfo, query, and fragment so an error cannot carry a secret."""
    if "://" in url:
        scheme, rest = url.split("://", 1)
        rest = rest.rsplit("@", 1)[-1]
        rest = rest.split("?", 1)[0].split("#", 1)[0]
        return f"{scheme}://{rest}"
    return url.split("?", 1)[0].split("#", 1)[0]


def _snippet(response: object) -> str:
    text = getattr(response, "text", "")
    if not isinstance(text, str):
        text = str(text)
    return text[:500]


def _pause(attempt: int) -> None:
    """Pause before another try. attempt is the zero-based index that just failed."""
    time.sleep(random.uniform(0.05, 0.25) * (attempt + 1))


def _model_id(model: str | None) -> str:
    if model is not None and str(model).strip():
        return str(model).strip()
    return _optional_env("COSMOS_EMBED1_MODEL") or _PUBLIC_MODEL_ID


def _as_vector(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != EMBED_DIM:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _cosine(left: list[float], right: list[float]) -> float:
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for x_value, y_value in zip(left, right):
        dot += x_value * y_value
        left_norm += x_value * x_value
        right_norm += y_value * y_value
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / ((left_norm ** 0.5) * (right_norm ** 0.5))


def _parse_json(response: object, url: str, secrets: tuple[str, ...]) -> dict:
    try:
        parsed = response.json()
    except ValueError:
        detail = _redact(_snippet(response), secrets)
        raise EmbedError(
            f"POST {_safe_url(url)} returned a non-JSON body: {detail}"
        ) from None
    if not isinstance(parsed, dict):
        raise EmbedError(f"POST {_safe_url(url)} returned JSON that is not an object")
    return parsed


def _vectors_from_payload(payload: dict) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise EmbedError("embedding must have 256 dimensions")
    ordered = sorted(
        data,
        key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
    )
    vectors: list[list[float]] = []
    for item in ordered:
        raw = item.get("embedding") if isinstance(item, dict) else None
        vector = _as_vector(raw)
        if vector is None:
            raise EmbedError("embedding must have 256 dimensions")
        vectors.append(vector)
    return vectors


def _post_embeddings(
    session: object | None,
    url: str,
    headers: dict[str, str],
    body: dict,
    secrets: tuple[str, ...],
) -> dict:
    close_session = False
    if session is None:
        session = requests.Session()
        close_session = True
    safe_url = _safe_url(url)
    try:
        for attempt in range(_ATTEMPTS):
            try:
                response = session.post(url, headers=headers, json=body, timeout=TIMEOUT_S)
            except (requests.Timeout, requests.ConnectionError):
                if attempt < _ATTEMPTS - 1:
                    _pause(attempt)
                    continue
                raise EmbedError(f"POST {safe_url} failed after 2 retries") from None
            status = int(getattr(response, "status_code", 0))
            if status in _RETRY_STATUSES and attempt < _ATTEMPTS - 1:
                _pause(attempt)
                continue
            if status >= 400:
                detail = _redact(_snippet(response), secrets)
                raise EmbedError(f"POST {safe_url} returned HTTP {status}: {detail}")
            return _parse_json(response, url, secrets)
    finally:
        if close_session:
            session.close()
    raise EmbedError(f"POST {safe_url} failed after 2 retries")


try:
    import weave
except ImportError:

    class _Weave:
        @staticmethod
        def op(fn):
            return fn

    weave = _Weave()


@weave.op
def embed_query(
    content: str,
    *,
    session: object | None = None,
    model: str | None = None,
) -> list[float]:
    """POST one query embedding and return its 256 floats."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("embedding input must be text or a data URL")
    base = _require_env("COSMOS_EMBED1_URL").rstrip("/")
    token = _require_env("GPU_BEARER_TOKEN")
    url = f"{base}/v1/embeddings"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "input": content,
        "model": _model_id(model),
        "request_type": "query",
        "encoding_format": "float",
    }
    payload = _post_embeddings(session, url, headers, body, (token,))
    vectors = _vectors_from_payload(payload)
    if len(vectors) != 1:
        raise EmbedError("embedding response must contain one vector")
    return vectors[0]


@weave.op
def more_like_this(
    query: str,
    rows: list[dict],
    *,
    session: object | None = None,
    model: str | None = None,
) -> list[dict]:
    """Rank rows by cosine similarity to a query embedding.

    ``query`` is text or a base64 data URL. Only ``vectors_visual`` is read
    from each row. A row whose ``camera_id`` is set to something other than
    pie_cam-3 is left out. Rows without a 256-dimension visual vector are
    left out. Nothing is written to data/candidates.jsonl.
    """
    if not rows:
        return []
    query_vector = embed_query(query, session=session, model=model)
    ranked: list[tuple[float, int, dict]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        row_camera = row.get("camera_id")
        if isinstance(row_camera, str) and row_camera != CAMERA_ID:
            continue
        stored = _as_vector(row.get(VECTOR_COLUMN))
        if stored is None:
            continue
        ranked.append((_cosine(query_vector, stored), index, row))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    results: list[dict] = []
    for score, _index, row in ranked:
        copied = dict(row)
        copied["similarity"] = score
        results.append(copied)
    return results
