"""Leaderboard JSON from the data directory, or the example file."""

from __future__ import annotations

import json

from fastapi import APIRouter

from dh.api._stubs import example_leaderboard
from dh.clips import data_dir

router = APIRouter()


@router.get("/api/leaderboard")
def get_leaderboard() -> dict:
    path = data_dir() / "leaderboard.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    try:
        return example_leaderboard()
    except OSError:
        # The demo pod does not ship contracts/examples. Do not invent scores.
        return {
            "testset_id": None,
            "max": None,
            "dvsa_reference_pct": 0.587,
            "rows": [],
        }
