"""Proxy clip bytes from VSS. The JWT stays on the server.

Only sources listed on a clip are forwarded. Range is passed through.
The source URI and the token are not logged.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from dh.api.clips import media_sources
from dh.clients.vss import VSS, VSSError

router = APIRouter()

_PASS_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
)


# Missing config or credentials. These are not upstream failures.
_NOT_CONFIGURED = frozenset(
    {
        "INGRESS_URL is not set",
        "VSS username or password is not set",
    }
)


def open_upstream(source: str, range_header: str | None):
    """Open the VSS stream. Tests replace this so they do not call the network."""
    client = VSS()
    return client.stream(source, range_header=range_header)


@router.get("/video")
def get_video(request: Request, source: str | None = None) -> StreamingResponse:
    if not source:
        raise HTTPException(status_code=400, detail="source is required")
    if source not in media_sources():
        raise HTTPException(status_code=404, detail="source not found")
    range_header = request.headers.get("range")
    try:
        upstream = open_upstream(source, range_header)
    except VSSError as exc:
        if str(exc) in _NOT_CONFIGURED:
            raise HTTPException(status_code=503, detail="video not configured") from exc
        raise HTTPException(status_code=502, detail="video upstream failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="video upstream failed") from exc

    status = getattr(upstream, "status_code", 200)
    if status >= 400:
        upstream.close()
        raise HTTPException(status_code=502, detail="video upstream failed")

    raw_headers = {key.lower(): value for key, value in upstream.headers.items()}
    headers: dict[str, str] = {}
    for key in _PASS_HEADERS:
        value = raw_headers.get(key)
        if value:
            headers[key] = value
    headers.setdefault("accept-ranges", "bytes")
    media_type = headers.pop("content-type", "video/mp4")

    def body() -> Iterator[bytes]:
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        body(),
        status_code=status,
        media_type=media_type,
        headers=headers,
    )
