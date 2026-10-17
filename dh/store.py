"""Local JSON is the source of truth. VastDB rows are a copy (SPEC 7.13).

``hazard_rows`` does not open the network. ``write_hazards`` is the only
function that calls VastDB, and only for schema ``developing_hazard``.
"""

from __future__ import annotations

from typing import Any

from dh.clients.vastdb import insert_hazard_rows


def hazard_rows(
    hazards: list[dict[str, Any]],
    clips: list[dict[str, Any]] | None = None,
    testset_id: str = "",
) -> list[dict[str, Any]]:
    """One VastDB row per segment source. Labeller A is riyu when present."""
    originals = {
        clip.get("clip_id"): clip.get("original_video") or ""
        for clip in (clips or [])
        if isinstance(clip, dict)
    }
    rows: list[dict[str, Any]] = []
    for hazard in hazards:
        labellers = hazard.get("labellers") if isinstance(hazard.get("labellers"), dict) else {}
        names = [name for name in labellers if isinstance(name, str)]
        labeller_a = "riyu" if "riyu" in names else (names[0] if names else "")
        others = [name for name in names if name != labeller_a]
        labeller_b = others[0] if others else ""
        sources = [
            source
            for source in (hazard.get("segment_sources") or [])
            if isinstance(source, str) and source
        ]
        if not sources:
            sources = [""]
        for source in sources:
            rows.append(
                {
                    "hazard_id": hazard.get("hazard_id") or "",
                    "clip_id": hazard.get("clip_id") or "",
                    "type": hazard.get("type") or "",
                    "window_start": float(hazard.get("window_start") or 0.0),
                    "window_end": float(hazard.get("window_end") or 0.0),
                    "segment_source": source,
                    "original_video": originals.get(hazard.get("clip_id"), "") or "",
                    "labeller_a": labeller_a,
                    "labeller_b": labeller_b,
                    "agreed": hazard.get("agreed") is True,
                    "testset_id": testset_id,
                }
            )
    return rows


def write_hazards(testset_id: str = "") -> int:
    """Insert the local hazard file into VastDB. JSON stays the source of truth."""
    from dh.clips import load_clips, load_hazards

    return insert_hazard_rows(hazard_rows(load_hazards(), load_clips(), testset_id))
