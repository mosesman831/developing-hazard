"""Phase 1 video stub.

A later phase proxies bytes from VSS. This handler does not call the
network and does not log the source.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from dh.api.clips import media_sources

router = APIRouter()


@router.get("/video")
def get_video(source: str | None = None) -> Response:
    if not source:
        raise HTTPException(status_code=400, detail="source is required")
    if source not in media_sources():
        raise HTTPException(status_code=404, detail="source not found")
    return Response(
        content=b"EXAMPLE",
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes"},
    )
