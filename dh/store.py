"""Build VastDB hazard rows from local hazard records (SPEC 7.13 and 10.10).

JSON files under data/ stay the source of truth. This module does not replace
the loaders in dh.clips. Each segment source becomes its own row so it can
join the index on source. Several sources on one hazard become several rows.
"""

from __future__ import annotations

from dh.clients.vastdb import ROW_COLUMNS

__all__ = ["ROW_COLUMNS", "hazard_rows", "write_hazards"]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _videos_by_clip(clips: object) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    if isinstance(clips, dict):
        for key, value in clips.items():
            if isinstance(value, str):
                mapping[str(key)] = _optional_text(value)
            elif isinstance(value, dict):
                clip_id = value.get("clip_id") or key
                mapping[str(clip_id)] = _optional_text(value.get("original_video"))
        return mapping
    if isinstance(clips, list):
        for clip in clips:
            if not isinstance(clip, dict) or not clip.get("clip_id"):
                continue
            mapping[str(clip["clip_id"])] = _optional_text(clip.get("original_video"))
    return mapping


def _labeller_pair(hazard: dict) -> tuple[str | None, str | None]:
    """Labeller A is riyu when she labelled the hazard. Otherwise, record order."""
    if "labeller_a" in hazard or "labeller_b" in hazard:
        return (
            _optional_text(hazard.get("labeller_a")),
            _optional_text(hazard.get("labeller_b")),
        )
    raw = hazard.get("labellers")
    names: list[str] = []
    if isinstance(raw, dict):
        names = [str(name) for name in raw if str(name).strip()]
    if "riyu" in names:
        others = [name for name in names if name != "riyu"]
        return "riyu", others[0] if others else None
    first = names[0] if names else None
    second = names[1] if len(names) > 1 else None
    return first, second


def _source_text(item: object) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    return _optional_text(item)


def _sources(hazard: dict) -> list[str | None]:
    """One entry per distinct segment source, in the order given."""
    many = hazard.get("segment_sources")
    if isinstance(many, list) and many:
        sources: list[str | None] = []
        for item in many:
            text = _source_text(item)
            if text is None or text in sources:
                continue
            sources.append(text)
        return sources or [None]
    one = hazard.get("segment_source")
    if isinstance(one, str) and one.strip():
        return [one.strip()]
    return [None]


def _window(hazard: dict, name: str) -> float:
    try:
        value = hazard[name]
        number = float(value)
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"hazard record is missing a numeric {name}") from None
    if isinstance(value, bool):
        raise ValueError(f"hazard record is missing a numeric {name}")
    return number


def hazard_rows(
    hazards: list[dict],
    clips: list[dict] | dict | None = None,
    testset_id: str | None = None,
) -> list[dict]:
    """Turn hazard records into VastDB row dicts.

    ``testset_id`` overrides any test set id on the records. ``clips`` supplies
    ``original_video`` by clip id when the hazard record does not carry it.
    This function does not read or write files.
    """
    videos = _videos_by_clip(clips)
    rows: list[dict] = []
    for hazard in hazards:
        if not isinstance(hazard, dict):
            raise ValueError("each hazard must be an object")
        hazard_id = hazard.get("hazard_id")
        if not isinstance(hazard_id, str) or not hazard_id:
            raise ValueError("hazard record is missing hazard_id")
        agreed = hazard.get("agreed")
        if not isinstance(agreed, bool):
            raise ValueError("agreed must be a boolean")
        clip_id = hazard.get("clip_id")
        if not isinstance(clip_id, str) or not clip_id:
            raise ValueError("hazard record is missing clip_id")
        type_name = hazard.get("type")
        if not isinstance(type_name, str) or not type_name:
            raise ValueError("hazard record is missing type")
        own_video = _optional_text(hazard.get("original_video"))
        video = own_video if own_video is not None else videos.get(clip_id)
        labeller_a, labeller_b = _labeller_pair(hazard)
        if testset_id is not None:
            chosen_set = testset_id
        else:
            chosen_set = _optional_text(hazard.get("testset_id"))
        for source in _sources(hazard):
            rows.append(
                {
                    "hazard_id": hazard_id,
                    "clip_id": clip_id,
                    "type": type_name,
                    "window_start": _window(hazard, "window_start"),
                    "window_end": _window(hazard, "window_end"),
                    "segment_source": source,
                    "original_video": video,
                    "labeller_a": labeller_a,
                    "labeller_b": labeller_b,
                    "agreed": agreed,
                    "testset_id": chosen_set,
                }
            )
    return rows


def write_hazards(
    testset_id: str | None = None,
    hazards: list[dict] | None = None,
    clips: list[dict] | dict | None = None,
) -> int:
    """Insert rows built from local hazard records.

    When ``hazards`` or ``clips`` is omitted, the existing dh.clips loaders
    supply them. Those loaders are not replaced. Tests should call hazard_rows.
    """
    if hazards is None or clips is None:
        from dh.clips import load_clips, load_hazards

        if hazards is None:
            hazards = load_hazards()
        if clips is None:
            clips = load_clips()
    from dh.clients.vastdb import write_hazards as insert_rows

    return insert_rows(hazard_rows(hazards, clips, testset_id))
