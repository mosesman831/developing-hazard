"""Simulated-clock replayer (SPEC 7.9 and 12.1).

Frames are pulled one at a time. A blocking call charges its latency to
the clock and later frames inside that gap are skipped. A non-blocking
call leaves the clock where it is; the answer arrives with the first
frame at or after the send time plus latency.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from types import SimpleNamespace

from dh.agents.base import CallResult


def replay(frames: Iterable[tuple]) -> Iterator[tuple]:
    """Yield (t, frame_ref, dets) in the order given.

    This is a generator. It never builds a list and it does not read the
    next frame until the caller asks for it.
    """
    for t, frame_ref, dets in frames:
        yield (t, frame_ref, dets)


def apply_latency(mode: str, measured_s: float) -> float:
    """Return the latency to charge for one call (SPEC 9.5).

    ``zero`` is 0. ``measured`` is ``measured_s``. ``fixed:L`` is L seconds.
    """
    if mode == "zero":
        return 0.0
    if mode == "measured":
        return float(measured_s)
    if mode.startswith("fixed:"):
        return float(mode.split(":", 1)[1])
    raise ValueError(f"unrecognised latency mode: {mode}")


@dataclass
class _Pending:
    result: CallResult
    ready_at: float


def sit_clip(agent, meta, frames, verifier=None, latency_mode: str = "zero"):
    """Run one agent over one clip on a simulated clock (SPEC 12.1).

    ``frames`` is an iterable of ``(t, frame_ref, dets)``. The click time
    is the clock after any blocking latency. ``t_trigger`` stays the frame
    time, and the risk curve is stamped with that frame time as well.
    """
    agent.reset(meta)
    clock = 0.0
    clicks: list[dict] = []
    calls: list[dict] = []
    risk_curve: list[list] = []
    pending: list[_Pending] = []
    seen: list[float] = []

    for t, frame_ref, dets in replay(frames):
        if t < clock:
            continue
        clock = t
        ready = [item.result for item in pending if item.ready_at <= clock]
        pending = [item for item in pending if item.ready_at > clock]
        seen.append(t)
        res = agent.step(t, frame_ref, dets, ready)
        for req in res.calls:
            if verifier is None:
                out = CallResult(latency_s=0.0)
            else:
                out = verifier.answer(meta.clip_id, req.t, req.track_id)
            lat = apply_latency(latency_mode, out.latency_s)
            sent_at = clock
            calls.append(
                {
                    "t": req.t,
                    "track_id": req.track_id,
                    "blocking": req.blocking,
                    "latency_s": lat,
                }
            )
            if req.blocking:
                clock = clock + lat
                res = agent.resume(out)
            else:
                pending.append(_Pending(result=out, ready_at=sent_at + lat))
        risk_curve.append([t, res.risk])
        if res.click:
            clicks.append(
                {
                    "t": clock,
                    "t_trigger": t,
                    "latency_s": clock - t,
                    "reason": res.note,
                }
            )

    return SimpleNamespace(
        clicks=clicks,
        calls=calls,
        risk_curve=risk_curve,
        seen=seen,
    )
