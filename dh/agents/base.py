"""Shared agent records (SPEC 7.10).

The harness owns the clock and the verifier. An agent returns a step
result and, when it needs a verdict, a call request. It never sees labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from dh.models import ClipMeta


@dataclass(frozen=True)
class CallRequest:
    t: float
    track_id: int | None
    blocking: bool


@dataclass(frozen=True)
class CallResult:
    latency_s: float
    is_hazard: bool = False
    object: str = ""
    track_id: int | None = None


@dataclass(frozen=True)
class StepResult:
    click: bool
    risk: float
    note: str | None
    calls: list[CallRequest]


class Agent(Protocol):
    name: str

    def reset(self, clip_meta: ClipMeta) -> None: ...

    def step(
        self,
        t: float,
        frame_ref: str,
        dets: list,
        ready: list[CallResult],
    ) -> StepResult: ...

    def resume(self, out: CallResult) -> StepResult: ...
