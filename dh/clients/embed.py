"""Cosmos Embed1 client (SPEC 11.4).

``more_like_this`` ranks stored visual vectors. It does not write
``data/candidates.jsonl`` and it does not read detection fields.
The bearer token is never logged.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

import requests

_TIMEOUT_S = 30
_ATTEMPTS = 3
_DIMS = 256


class EmbedError(RuntimeError):
    """An embeddings call failed. The message does not include the bearer token."""


def _lookup(name: str) -> str | None:
    try:
        from dh.config import env
    except ImportError:
        env = None
    raw = env(name) if env is not None else os.environ.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _require(name: str) -> str:
    value = _lookup(name)
    if value is None:
        raise EmbedError(f"missing environment variable {name}")
    return value


def _vector(payload: dict) -> list[float]:
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise EmbedError("embeddings response has no vector")
    vector = data[0].get("embedding")
    if not isinstance(vector, list) or len(vector) != _DIMS:
        raise EmbedError(f"embeddings vector must have {_DIMS} dimensions")
    if not all(isinstance(item, (int, float)) for item in vector):
        raise EmbedError("embeddings vector must be numeric")
    return [float(item) for item in vector]


def embed_query(value: str, *, session: requests.Session | None = None) -> list[float]:
    """POST ``/v1/embeddings`` with ``request_type`` ``query``. Two retries."""
    url = _require("COSMOS_EMBED1_URL").rstrip("/") + "/v1/embeddings"
    token = _require("GPU_BEARER_TOKEN")
    body = {
        "input": value,
        "request_type": "query",
        "encoding_format": "float",
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    caller = session.post if session is not None else requests.post
    last_status = None
    for attempt in range(_ATTEMPTS):
        try:
            response = caller(url, json=body, headers=headers, timeout=_TIMEOUT_S)
        except requests.RequestException:
            last_status = None
        else:
            last_status = response.status_code
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise EmbedError("embeddings response was not JSON") from exc
                if not isinstance(payload, dict):
                    raise EmbedError("embeddings response was not an object")
                return _vector(payload)
            if response.status_code not in {429, 500, 502, 503, 504}:
                raise EmbedError(f"embeddings returned {response.status_code}")
        if attempt + 1 < _ATTEMPTS:
            time.sleep(random.random() * 0.05)
    if last_status is None:
        raise EmbedError("embeddings request failed")
    raise EmbedError(f"embeddings returned {last_status}")


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / ((left_norm ** 0.5) * (right_norm ** 0.5))


def more_like_this(
    query_vector: list[float],
    rows: list[dict[str, Any]],
    *,
    camera_id: str = "pie_cam-3",
) -> list[tuple[float, str]]:
    """Rank rows by cosine of ``vectors_visual``. Detection fields are ignored.

    This function does not write candidates and does not call the network.
    """
    ranked: list[tuple[float, str]] = []
    for row in rows:
        row_camera = row.get("camera_id")
        if isinstance(row_camera, str) and row_camera != camera_id:
            continue
        vector = row.get("vectors_visual")
        source = row.get("source")
        if not isinstance(vector, list) or not isinstance(source, str):
            continue
        ranked.append((_cosine(query_vector, [float(item) for item in vector]), source))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked
