"""Replay must not look ahead, and latency must move the simulated clock."""

from __future__ import annotations

import pytest

from dh.agents.base import CallRequest, CallResult, StepResult
from dh.models import ClipMeta
from dh.replay import apply_latency, replay, sit_clip


def _meta() -> ClipMeta:
    return ClipMeta(clip_id="clip-a", duration_s=5.0, fps_sample=5, segments=[])


class _Verifier:
    def __init__(self, latency_s: float, marker: str = "") -> None:
        self.latency_s = latency_s
        self.marker = marker

    def answer(self, clip_id: str, t: float, track_id: int | None) -> CallResult:
        return CallResult(
            latency_s=self.latency_s,
            is_hazard=True,
            object=self.marker,
            track_id=track_id,
        )


class AskEveryFrameAgent:
    """Blocking call on every frame it is actually shown. Defined here, not in dh.agents."""

    name = "ask_every_frame"

    def __init__(self) -> None:
        self.seen: list[float] = []

    def reset(self, meta) -> None:
        self.seen = []

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        self.seen.append(t)
        return StepResult(
            click=False,
            risk=0.0,
            note=None,
            calls=[CallRequest(t=t, track_id=None, blocking=True)],
        )

    def resume(self, out: CallResult) -> StepResult:
        return StepResult(click=False, risk=0.0, note=None, calls=[])


class _ClickAfterBlock:
    def __init__(self) -> None:
        self.asked = False

    def reset(self, meta) -> None:
        self.asked = False

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        if not self.asked:
            self.asked = True
            return StepResult(
                click=False,
                risk=0.2,
                note=None,
                calls=[CallRequest(t=t, track_id=3, blocking=True)],
            )
        return StepResult(click=False, risk=0.2, note=None, calls=[])

    def resume(self, out: CallResult) -> StepResult:
        return StepResult(click=True, risk=0.9, note="after block", calls=[])


class _AsyncProbe:
    def __init__(self) -> None:
        self.log: list[tuple[float, list[CallResult]]] = []
        self.sent = False

    def reset(self, meta) -> None:
        self.log = []
        self.sent = False

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        self.log.append((t, list(ready)))
        calls: list[CallRequest] = []
        if not self.sent:
            self.sent = True
            calls = [CallRequest(t=t, track_id=9, blocking=False)]
        return StepResult(click=False, risk=0.0, note=None, calls=calls)

    def resume(self, out: CallResult) -> StepResult:
        raise AssertionError("a non-blocking call must not resume")


def test_replay_is_generator():
    produced: list[int] = []

    def source():
        for index, frame in enumerate(((0.0, "f0", []), (0.2, "f1", []))):
            produced.append(index)
            yield frame

    stream = replay(source())
    assert hasattr(stream, "__next__")
    assert not isinstance(stream, list)
    assert produced == []
    assert next(stream) == (0.0, "f0", [])
    assert produced == [0]
    assert next(stream) == (0.2, "f1", [])
    assert produced == [0, 1]


def test_apply_latency_modes():
    assert apply_latency("zero", 2.5) == 0.0
    assert apply_latency("measured", 0.9) == 0.9
    assert apply_latency("fixed:1.0", 0.2) == 1.0
    assert apply_latency("fixed:4", 9.0) == 4.0


def test_blocking_call_skips_frames():
    frames = [(i / 5, f"f{i}", []) for i in range(11)]
    agent = AskEveryFrameAgent()
    sat = sit_clip(agent, _meta(), frames, _Verifier(1.0), latency_mode="measured")
    assert len(agent.seen) >= 2
    assert all(b - a >= 1.0 for a, b in zip(agent.seen, agent.seen[1:]))
    assert sat.seen == agent.seen


def test_blocking_click_is_stamped_after_latency():
    frames = [(0.0, "f0", []), (0.5, "f1", []), (1.0, "f2", []), (1.5, "f3", [])]
    sat = sit_clip(
        _ClickAfterBlock(),
        _meta(),
        frames,
        _Verifier(1.0),
        latency_mode="fixed:1.0",
    )
    assert len(sat.clicks) == 1
    click = sat.clicks[0]
    assert click["t_trigger"] == pytest.approx(0.0)
    assert click["t"] == pytest.approx(1.0)
    assert click["latency_s"] == pytest.approx(1.0)
    assert click["reason"] == "after block"
    assert click["t"] == pytest.approx(click["t_trigger"] + 1.0)
    assert sat.risk_curve[0][0] == pytest.approx(0.0)
    assert 0.5 not in sat.seen


def test_non_blocking_result_arrives_on_a_later_frame():
    frames = [(0.0, "f0", []), (0.25, "f1", []), (0.5, "f2", []), (0.75, "f3", [])]
    agent = _AsyncProbe()
    sat = sit_clip(
        agent,
        _meta(),
        frames,
        _Verifier(0.5, marker="later"),
        latency_mode="measured",
    )
    by_t = {t: ready for t, ready in agent.log}
    assert by_t[0.0] == []
    assert by_t[0.25] == []
    assert len(by_t[0.5]) == 1
    assert by_t[0.5][0].object == "later"
    assert sat.seen == [0.0, 0.25, 0.5, 0.75]
    assert sat.calls[0]["blocking"] is False
    assert sat.calls[0]["latency_s"] == pytest.approx(0.5)
