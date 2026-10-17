"""Phase 1 data models.

Times stay in seconds of clip time. The scorer converts them to integer
milliseconds. ClipMeta is the view an agent may see: clip id, duration,
sample rate, and segments only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Number = int | float

_IGNORE = ConfigDict(extra="ignore")


class Segment(BaseModel):
    """One source span on a clip timeline."""

    model_config = _IGNORE

    source: str
    start_s: Number
    end_s: Number


class Candidate(BaseModel):
    """A mined video chunk before it is cut into a clip."""

    model_config = _IGNORE

    candidate_id: str
    camera_id: str
    original_video: str
    segments: list[str]
    found_by: Literal["search", "scrub", "embed"]
    status: Literal["new", "rejected", "sat_blind", "labelled", "frozen"]
    location: str | None = None
    set: str | None = None
    chunk_index: int | None = None
    queries: list[Any] | None = None
    hit_second: Number | None = None
    search_score: Number | None = None
    caption_snippet: str | None = None
    ego_moving: bool | None = None


class Clip(BaseModel):
    """A frozen clip. Unknown fields are rejected (additionalProperties false)."""

    model_config = ConfigDict(extra="forbid")

    clip_id: str
    candidate_id: str
    camera_id: str
    original_video: str
    segments: list[Segment]
    duration_s: Number
    fps_native: Number
    fps_sample: Number
    split: Literal["dev", "test"]
    seen_by: list[str]
    local_path: str | None = None
    notes: str | None = None


class ClipMeta(BaseModel):
    """Fields an agent may see. Never hazard ids or windows."""

    model_config = _IGNORE

    clip_id: str
    duration_s: Number
    fps_sample: Number
    segments: list[Segment]


class Det(BaseModel):
    """One detector box at a clip time."""

    model_config = _IGNORE

    t: Number
    frame: int
    cls: str
    conf: Number
    xyxy: Annotated[list[Number], Field(min_length=4, max_length=4)]


class Track(BaseModel):
    """Per-frame track state. ttc and t_lat may be null."""

    model_config = _IGNORE

    track_id: int
    t: Number
    cls: str
    xyxy: Annotated[list[Number], Field(min_length=4, max_length=4)]
    risk: Number
    vx: Number | None = None
    vy: Number | None = None
    h_rate: Number | None = None
    in_corridor: bool | None = None
    heading_in: bool | None = None
    ttc: Number | None = None
    t_lat: Number | None = None


class Hazard(BaseModel):
    """An agreed hazard window on a clip."""

    model_config = _IGNORE

    hazard_id: str
    clip_id: str
    type: Literal[
        "pedestrian_crossing",
        "vehicle_pulling_out",
        "vehicle_cut_in",
        "lead_vehicle_braking",
        "cyclist",
        "vehicle_turning_across",
        "other",
    ]
    window_start: Number
    window_end: Number
    labellers: dict[str, Annotated[list[Number], Field(min_length=2, max_length=2)]]
    agreed: bool
    arbitrated_by: str | None = None
    auto_window: list[Number] | None = None
    track_id: int | None = None
    segment_sources: list[str] | None = None
    description: str | None = None


class TestSet(BaseModel):
    """A frozen set of clip and hazard ids."""

    model_config = _IGNORE

    testset_id: str
    frozen_at: str
    clips: list[str]
    hazards: list[str]
    scorer_version: str
    pattern_version: str
    sha256: str


class Pattern(BaseModel):
    """Whether PATTERN_V1 fired, and which rules."""

    model_config = _IGNORE

    flag: bool
    reasons: list[str]


class Click(BaseModel):
    """One click recorded on a clip timeline."""

    model_config = _IGNORE

    t: Number
    t_trigger: Number | None = None
    latency_s: Number | None = None
    reason: str | None = None


class Call(BaseModel):
    """One verifier call made while a clip was running."""

    model_config = _IGNORE

    kind: Literal["cosmos", "vlm", "llm"]
    t_sent: Number
    latency_s: Number
    blocking: bool
    grid_t: Number | None = None
    verdict: Literal["HAZARD", "NO_HAZARD", "ERROR"] | None = None


class Run(BaseModel):
    """One evaluation run over a frozen test set."""

    model_config = _IGNORE

    run_id: str
    agent: str
    testset_id: str
    testset_sha256: str
    scorer_version: str
    pattern_version: str
    latency_mode: str
    totals: dict[str, Any]
    agent_config: dict[str, Any] | None = None
    git_sha: str | None = None
    mode: str | None = None
    started_at: str | None = None
    weave_url: str | None = None


class ClipResult(BaseModel):
    """Score for one clip inside a run."""

    model_config = _IGNORE

    run_id: str
    clip_id: str
    clicks: list[Click]
    pattern: Pattern
    hazard_points: dict[str, Annotated[int, Field(ge=0, le=5)]]
    clip_score: int
    calls: list[Call] | None = None
    risk_curve: list[list[Number]] | None = None
    explanation: str | None = None


class HumanSession(BaseModel):
    """A person's clicks on one clip. No email address is stored."""

    model_config = _IGNORE

    session_id: str
    name: str
    role: Literal["team", "judge", "guest"]
    blind: bool
    clip_id: str
    clicks: list[float]
    created_at: str
    ua: str | None = None


def clip_meta_from_clip(clip: Clip) -> ClipMeta:
    """Copy only clip_id, duration_s, fps_sample, and segments."""
    segments = [
        {"source": segment.source, "start_s": segment.start_s, "end_s": segment.end_s}
        for segment in clip.segments
    ]
    return ClipMeta(
        clip_id=clip.clip_id,
        duration_s=clip.duration_s,
        fps_sample=clip.fps_sample,
        segments=segments,
    )
