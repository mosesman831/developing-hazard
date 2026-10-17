"""Clip miner (SPEC 7.1).

Search ``pie_cam-3`` and scrub PIE sets 2 to 6. Rank by caption keywords.
Captions only: perception counts and detection fields are never read.
Runnable as ``python -m dh.mine`` and ``python -m dh.mine build``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from dh.clients.vss import VSS, VSSError
from dh.clips import data_dir, define_chunk_clip, write_json

CAMERA_ID = "pie_cam-3"
LOCATION = "toronto"
ONSET_MIN_S = 5
EXPLORE_LIMIT = 48
MAX_SEGMENT_FETCHES = 180
SNIPPET_CHARS = 400
DEV_COUNT = 6
FPS_NATIVE = 30

QUERIES = (
    "the camera vehicle slows down as a pedestrian steps off the curb ahead",
    "pedestrian starts to cross the road in front of the moving car",
    "pedestrian walks out between parked cars",
    "car pulls out of a side street in front of the camera vehicle",
    "vehicle ahead brakes suddenly, brake lights on, gap closing",
    "cyclist moves out into the lane ahead",
    "the camera vehicle turns while pedestrians are crossing",
    "vehicle cuts in front of the camera vehicle",
    "parked car door opening into the road",
    "bus pulling away from a stop ahead",
)

_SCRUB_SETS = frozenset({"set02", "set03", "set04", "set05", "set06"})
_CHUNK_NAME = re.compile(r"(set\d+)_video_chunk_(\d+)", re.IGNORECASE)
_SEGMENT_NUM = re.compile(r"segment_(\d+)_of_\d+", re.IGNORECASE)
_PAGE_KEYS = ("chunks", "videos", "results", "items")
_CAPTION_KEYS = ("reasoning_content", "caption", "reasoning")
_NEGATIONS = (
    "no pedestrian",
    "no pedestrians",
    "not visible",
    "no cyclist",
    "no vehicle ahead",
)
_CAMERA = r"camera\s+(?:vehicle|car)"
_STOPPED = re.compile(
    rf"(?:{_CAMERA}).{{0,50}}\b(?:stopped|stationary|waiting)\b"
    rf"|\b(?:stopped|stationary|waiting)\b.{{0,50}}(?:{_CAMERA})",
    re.IGNORECASE,
)
_MOVES_OFF = re.compile(
    r"\bmoves\s+off\b|\bbegins\s+to\s+(?:move|turn|drive)\b"
    r"|\bstarts\s+to\s+(?:move|turn|drive)\b",
    re.IGNORECASE,
)
_DRIVING = re.compile(
    r"\b(?:drives|driving|proceeds|travelling|traveling)\b|continues\s+forward",
    re.IGNORECASE,
)
_MOVING_CAMERA = re.compile(
    rf"(?:{_CAMERA}).{{0,40}}\bmoving\b|\bmoving\b.{{0,40}}(?:{_CAMERA})",
    re.IGNORECASE,
)
_SECRET = re.compile(r"bearer\s+\S+|token=|password", re.IGNORECASE)


def usable_caption(text: str) -> str:
    """Drop sentences that deny a road user or say the scene is not visible."""
    if not text or not text.strip():
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(phrase in lowered for phrase in _NEGATIONS):
            continue
        cleaned = sentence.strip()
        if cleaned:
            kept.append(cleaned)
    return " ".join(kept)


def caption_ego_moving(text: str) -> bool:
    """True when the caption says the camera vehicle is moving.

    Stopped, stationary, or waiting marks it false, unless the same caption
    also says the camera vehicle moves off.
    """
    if not text:
        return False
    stopped = _STOPPED.search(text) is not None
    moves_off = _MOVES_OFF.search(text) is not None
    if stopped and not moves_off:
        return False
    if _DRIVING.search(text) or _MOVING_CAMERA.search(text) or moves_off:
        return True
    return False


def keyword_score(text: str) -> int:
    """Hazard language in the caption. Detection fields are not an input."""
    if not text:
        return 0
    score = 0
    if re.search(r"\bpedestrians?\b", text, re.IGNORECASE):
        score += 1
    if re.search(r"\bcross(?:es|ing|ed)?\b", text, re.IGNORECASE):
        score += 1
    if re.search(r"\b(?:curb|kerb)s?\b", text, re.IGNORECASE):
        score += 1
    if re.search(r"\bsteps?\b", text, re.IGNORECASE):
        score += 1
    if re.search(r"\bpull(?:s|ing)?\s+out\b", text, re.IGNORECASE):
        score += 1
    if re.search(r"\bcut(?:s|ting)?\s+in\b", text, re.IGNORECASE):
        score += 1
    if re.search(r"\bbrakes?\b", text, re.IGNORECASE):
        score += 1
    if re.search(
        r"\b(?:cyclist|bicycle)\b.{0,48}\blane\b"
        r"|\blane\b.{0,48}\b(?:cyclist|bicycle)\b",
        text,
        re.IGNORECASE,
    ):
        score += 1
    if re.search(r"\bdoor\s+open(?:s|ing|ed)?\b", text, re.IGNORECASE):
        score += 1
    if re.search(
        r"\bbus\b.{0,48}\bpulling\s+away\b|\bpulling\s+away\b.{0,48}\bbus\b",
        text,
        re.IGNORECASE,
    ):
        score += 1
    if re.search(
        r"\bturns?\b.{0,48}\bpedestrians?\b|\bpedestrians?\b.{0,48}\bturns?\b",
        text,
        re.IGNORECASE,
    ):
        score += 1
    return score


def mine(client: Any = None) -> list[dict]:
    """Search and scrub, then overwrite ``candidates.jsonl``."""
    vss = client if client is not None else VSS()
    parents: dict[str, dict] = {}
    for query in QUERIES:
        for hit in vss.search(query, filters={"camera_id": CAMERA_ID}, top_k=30):
            if isinstance(hit, dict):
                _absorb_search_hit(parents, hit, query)
    _scrub_explore(vss, parents)
    candidates = _rank_candidates(parents)
    _write_candidates(candidates)
    _print_ids([row["candidate_id"] for row in candidates])
    return candidates


def build(client: Any = None) -> list[dict]:
    """Join selected candidates into ``clips.json`` and local mp4 files."""
    vss = client if client is not None else VSS()
    rows = _read_candidates()
    known = _known_six_sources(rows)
    selected = [
        row
        for row in rows
        if row.get("status") in {"new", "labelled"}
        and row.get("ego_moving") is True
        and _onset(row) is not None
        and _onset(row) >= ONSET_MIN_S
    ]
    selected.sort(key=lambda row: str(row.get("candidate_id") or ""))
    fps = _fps_sample()
    clips: list[dict] = []
    for index, row in enumerate(selected, start=1):
        clip_id = f"c{index:02d}"
        split = "dev" if index <= DEV_COUNT else "test"
        sources = _ensure_sources(vss, row)
        if len(sources) == 6:
            set_name = row.get("set")
            chunk_index = row.get("chunk_index")
            if isinstance(set_name, str) and isinstance(chunk_index, int):
                known[(set_name, chunk_index)] = sources
        onset = _onset(row)
        previous = None
        if (
            onset is not None
            and onset < ONSET_MIN_S
            and isinstance(row.get("chunk_index"), int)
            and isinstance(row.get("set"), str)
        ):
            previous = known.get((row["set"], row["chunk_index"] - 1))
        try:
            clip = assemble_clip(
                row,
                clip_id,
                fps=fps,
                split=split,
                sources=sources,
                previous_sources=previous,
            )
        except ValueError as exc:
            clip = _empty_clip(row, clip_id, fps=fps, split=split, notes=_safe_note(exc))
        if not clip.get("notes") and clip.get("segments"):
            output = data_dir() / "clips" / f"{clip_id}.mp4"
            try:
                _concat_segments(vss, clip["segments"], output)
            except (OSError, RuntimeError, VSSError) as exc:
                if output.exists():
                    output.unlink()
                clip["notes"] = _safe_note(exc)
            else:
                clip["local_path"] = _recorded_local_path(clip_id)
        clips.append(clip)
    write_json("clips.json", clips)
    _print_ids([clip["clip_id"] for clip in clips])
    return clips


def assemble_clip(
    row: dict,
    clip_id: str,
    *,
    fps: int,
    split: str,
    sources: list[str],
    previous_sources: list[str] | None = None,
) -> dict:
    """Clip dict for one candidate. Downloads happen in ``build``, not here.

    Onset under 5 seconds prepends the previous chunk when its six sources
    are known. ``define_chunk_clip`` shifts that chunk by 30 seconds.
    """
    onset = _onset(row)
    if onset is None:
        raise ValueError("candidate has no hit second")
    if len(sources) != 6:
        raise ValueError("a chunk has six segments")
    defined = define_chunk_clip(
        sources,
        onset,
        previous_sources if onset < ONSET_MIN_S else None,
    )
    return {
        "clip_id": clip_id,
        "candidate_id": row.get("candidate_id") or "",
        "camera_id": CAMERA_ID,
        "original_video": row.get("original_video") or "",
        "segments": defined["segments"],
        "duration_s": defined["duration_s"],
        "fps_native": FPS_NATIVE,
        "fps_sample": fps,
        "split": split,
        "seen_by": ["riyu"],
        "notes": "",
    }


def main(argv: list[str] | None = None) -> None:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        mine()
        return
    if args == ["build"]:
        build()
        return
    raise SystemExit("usage: python -m dh.mine [build]")


def _absorb_search_hit(parents: dict[str, dict], hit: dict, query: str) -> None:
    original = hit.get("original_video")
    if not isinstance(original, str) or not original:
        return
    parent = _parent(parents, original, hit)
    if query not in parent["queries"]:
        parent["queries"].append(query)
    parent["from_search"] = True
    similarity = _number(hit.get("similarity_score"))
    if similarity is not None:
        current = parent["search_score"]
        if current is None or similarity > current:
            parent["search_score"] = similarity
    parent["captions"].append(_caption_record(hit, query=query, from_search=True))


def _scrub_explore(vss: Any, parents: dict[str, dict]) -> None:
    offset = 0
    seen: set[str] = set()
    while offset < EXPLORE_LIMIT * 40:
        page = vss.explore(location=LOCATION, limit=EXPLORE_LIMIT, offset=offset)
        if not isinstance(page, dict):
            break
        items = _page_items(page)
        if not items:
            break
        fresh = 0
        for item in items:
            original = item.get("original_video")
            if not isinstance(original, str) or not original or original in seen:
                continue
            seen.add(original)
            fresh += 1
            filename = _filename_of(item)
            if not _is_pie_filename(filename):
                continue
            parent = _parent(parents, original, item)
            parent["from_explore"] = True
            if parent["set_name"] is None:
                parsed = _parse_chunk(filename)
                if parsed:
                    parent["set_name"], parent["chunk_index"] = parsed
                    parent["filename"] = filename
            elif not parent["filename"]:
                parent["filename"] = filename
            location = item.get("location")
            if isinstance(location, str) and location:
                parent["location"] = location
        total = page.get("total")
        covered = isinstance(total, int) and offset + len(items) >= total
        if len(items) < EXPLORE_LIMIT or fresh == 0 or covered:
            break
        offset += EXPLORE_LIMIT
    targets = [
        parent
        for parent in parents.values()
        if parent.get("from_explore")
        and parent.get("set_name") in _SCRUB_SETS
        and parent.get("original_video")
    ]
    targets.sort(
        key=lambda parent: (
            str(parent.get("set_name") or ""),
            parent.get("chunk_index") if isinstance(parent.get("chunk_index"), int) else 10**9,
            str(parent.get("original_video") or ""),
        )
    )
    for parent in targets[:MAX_SEGMENT_FETCHES]:
        try:
            rows = vss.segments(parent["original_video"])
        except VSSError:
            continue
        if not isinstance(rows, list):
            continue
        parent["segment_rows"] = [row for row in rows if isinstance(row, dict)]
        for row in parent["segment_rows"]:
            parent["captions"].append(
                _caption_record(row, query=None, from_search=False)
            )


def _rank_candidates(parents: dict[str, dict]) -> list[dict]:
    ranked: list[tuple[int, str, dict]] = []
    for parent in parents.values():
        candidate = _candidate_from_parent(parent)
        if candidate is None:
            continue
        ranked.append((candidate.pop("_score"), candidate["candidate_id"], candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked]


def _candidate_from_parent(parent: dict) -> dict | None:
    parsed = _parse_chunk(parent.get("filename") or parent.get("original_video") or "")
    if parsed is None:
        return None
    set_name, chunk_index = parsed
    options = []
    for record in parent["captions"]:
        usable = usable_caption(record["text"])
        if not usable or not caption_ego_moving(usable):
            continue
        score = keyword_score(usable)
        if score <= 0 or record["start"] is None:
            continue
        options.append((score, record["source"], usable, record["start"]))
    if not options:
        return None
    options.sort(key=lambda item: (-item[0], item[1]))
    score, _source, usable, start = options[0]
    if start < ONSET_MIN_S:
        return None
    sources = _parent_sources(parent)
    return {
        "_score": score,
        "candidate_id": f"pie_{set_name}_c{chunk_index:04d}",
        "camera_id": CAMERA_ID,
        "location": parent.get("location") or LOCATION,
        "original_video": parent["original_video"],
        "set": set_name,
        "chunk_index": chunk_index,
        "segments": sources,
        "found_by": "search" if parent["from_search"] else "scrub",
        "queries": [query for query in QUERIES if query in parent["queries"]],
        "hit_second": _json_number(start),
        "search_score": parent["search_score"] if parent["from_search"] else None,
        "caption_snippet": usable[:SNIPPET_CHARS],
        "ego_moving": True,
        "status": "new",
    }


def _parent(parents: dict[str, dict], original: str, item: dict) -> dict:
    found = parents.get(original)
    if found is not None:
        return found
    filename = _filename_of(item)
    parsed = _parse_chunk(filename)
    location = item.get("location")
    parent = {
        "original_video": original,
        "filename": filename,
        "location": location if isinstance(location, str) and location else LOCATION,
        "set_name": parsed[0] if parsed else None,
        "chunk_index": parsed[1] if parsed else None,
        "queries": [],
        "from_search": False,
        "search_score": None,
        "captions": [],
        "segment_rows": None,
        "from_explore": False,
    }
    parents[original] = parent
    return parent


def _caption_record(row: dict, *, query: str | None, from_search: bool) -> dict:
    source = row.get("source")
    return {
        "text": _caption_text(row),
        "start": _start_sec(row),
        "source": source if isinstance(source, str) else "",
        "query": query,
        "from_search": from_search,
    }


def _caption_text(row: dict) -> str:
    for key in _CAPTION_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _start_sec(row: dict) -> float | None:
    start = _number(row.get("segment_start_sec"))
    if start is not None:
        return start
    return _number(row.get("best_match_start_sec"))


def _parent_sources(parent: dict) -> list[str]:
    rows = parent.get("segment_rows")
    if isinstance(rows, list) and rows:
        sources = _sources_of(rows)
        if sources:
            return ordered_sources(sources)
    sources = [
        record["source"]
        for record in parent["captions"]
        if record["from_search"] and record["source"]
    ]
    return ordered_sources(sources)


def _sources_of(rows: list[dict]) -> list[str]:
    sources = []
    for row in rows:
        source = row.get("source")
        if isinstance(source, str) and source:
            sources.append(source)
    return sources


def ordered_sources(sources: list[str]) -> list[str]:
    """Segment URIs in segment-number order. Duplicates are dropped."""
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source and source not in seen:
            seen.add(source)
            unique.append(source)

    def sort_key(source: str) -> tuple[int, str]:
        number = _segment_number(source)
        return (number if number is not None else 10**9, source)

    return sorted(unique, key=sort_key)


def _ensure_sources(vss: Any, row: dict) -> list[str]:
    sources = ordered_sources(
        [item for item in row.get("segments") or [] if isinstance(item, str)]
    )
    if _has_six(sources):
        return _six(sources)
    original = row.get("original_video")
    if not isinstance(original, str) or not original:
        return sources
    try:
        fetched = vss.segments(original)
    except VSSError:
        return sources
    if not isinstance(fetched, list):
        return sources
    fetched_sources = ordered_sources(_sources_of([item for item in fetched if isinstance(item, dict)]))
    if fetched_sources:
        return _six(fetched_sources) if _has_six(fetched_sources) else fetched_sources
    return sources


def _has_six(sources: list[str]) -> bool:
    numbers = {_segment_number(source) for source in sources}
    return {1, 2, 3, 4, 5, 6} <= numbers


def _six(sources: list[str]) -> list[str]:
    by_number: dict[int, str] = {}
    for source in sources:
        number = _segment_number(source)
        if number is not None and 1 <= number <= 6 and number not in by_number:
            by_number[number] = source
    if len(by_number) == 6:
        return [by_number[number] for number in range(1, 7)]
    return sources


def _known_six_sources(rows: list[dict]) -> dict[tuple[str, int], list[str]]:
    known: dict[tuple[str, int], list[str]] = {}
    for row in rows:
        set_name = row.get("set")
        chunk_index = row.get("chunk_index")
        if not isinstance(set_name, str) or not isinstance(chunk_index, int):
            continue
        sources = ordered_sources(
            [item for item in row.get("segments") or [] if isinstance(item, str)]
        )
        if _has_six(sources):
            known[(set_name, chunk_index)] = _six(sources)
    return known


def _concat_segments(vss: Any, segments: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        lines: list[str] = []
        for index, segment in enumerate(segments):
            source = segment.get("source")
            if not isinstance(source, str) or not source:
                raise RuntimeError("segment download failed")
            name = f"seg_{index:03d}.mp4"
            path = folder / name
            _download(vss, source, path)
            lines.append("file '" + path.as_posix().replace("'", "'\\''") + "'")
        list_path = folder / "list.txt"
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output),
            ],
            cwd=folder,
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0 or not output.is_file():
        raise RuntimeError(f"ffmpeg concat failed with status {completed.returncode}")


def _download(vss: Any, source: str, target: Path) -> None:
    response = vss.stream(source)
    try:
        with target.open("wb") as handle:
            iterator = getattr(response, "iter_content", None)
            if callable(iterator):
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            else:
                body = getattr(response, "content", b"")
                if body:
                    handle.write(body)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _empty_clip(row: dict, clip_id: str, *, fps: int, split: str, notes: str) -> dict:
    return {
        "clip_id": clip_id,
        "candidate_id": row.get("candidate_id") or "",
        "camera_id": CAMERA_ID,
        "original_video": row.get("original_video") or "",
        "segments": [],
        "duration_s": 0,
        "fps_native": FPS_NATIVE,
        "fps_sample": fps,
        "split": split,
        "seen_by": ["riyu"],
        "notes": notes,
    }


def _recorded_local_path(clip_id: str) -> str:
    path = data_dir() / "clips" / f"{clip_id}.mp4"
    try:
        relative = path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return f"data/clips/{clip_id}.mp4"
    return relative.as_posix()


def _write_candidates(rows: list[dict]) -> None:
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "candidates.jsonl"
    temporary = directory / "candidates.jsonl.tmp"
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)


def _read_candidates() -> list[dict]:
    path = data_dir() / "candidates.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _print_ids(identifiers: list[str]) -> None:
    print(len(identifiers))
    for identifier in identifiers:
        print(identifier)


def _page_items(page: dict) -> list[dict]:
    for key in _PAGE_KEYS:
        found = page.get(key)
        if isinstance(found, list):
            return [item for item in found if isinstance(item, dict)]
    return []


def _filename_of(item: dict) -> str:
    name = item.get("filename")
    if isinstance(name, str) and name:
        return name
    for key in ("original_video", "source"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value.rsplit("/", 1)[-1]
    return ""


def _is_pie_filename(name: str) -> bool:
    lowered = name.lower()
    return "set0" in lowered and "_video_chunk_" in lowered


def _parse_chunk(name: str) -> tuple[str, int] | None:
    found = _CHUNK_NAME.search(name)
    if not found:
        return None
    return found.group(1).lower(), int(found.group(2))


def _segment_number(source: str) -> int | None:
    found = _SEGMENT_NUM.search(source)
    if not found:
        return None
    return int(found.group(1))


def _onset(row: dict) -> float | None:
    return _number(row.get("hit_second"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _json_number(value: float) -> int | float:
    if value == int(value):
        return int(value)
    return round(value, 3)


def _fps_sample() -> int:
    raw = os.environ.get("DH_FPS_SAMPLE", "5")
    try:
        fps = int(raw)
    except ValueError:
        return 5
    if fps <= 0:
        return 5
    return fps


def _safe_note(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    if not text or _SECRET.search(text):
        return "clip build failed"
    if len(text) > 240:
        return text[:240]
    return text


if __name__ == "__main__":
    main()
