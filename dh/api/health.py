"""Process health for the dev server and the demo pod."""

from __future__ import annotations

import json

from fastapi import APIRouter

from dh.api._stubs import current_mode, example_testset
from dh.clips import load_testset

router = APIRouter()


def _testset_id() -> str:
    example = example_testset()
    fallback = example.get("testset_id")
    try:
        payload = load_testset()
    except (OSError, ValueError, json.JSONDecodeError):
        return fallback
    if isinstance(payload, dict) and isinstance(payload.get("testset_id"), str):
        return payload["testset_id"]
    return fallback


@router.get("/api/health")
def api_health() -> dict:
    """Report process state. Phase 1 does not probe VSS, Cosmos, or Weave."""
    return {
        "ok": True,
        "vss_ok": False,
        "cosmos_ok": False,
        "wandb_ok": False,
        "testset_id": _testset_id(),
        "mode": current_mode(),
    }
