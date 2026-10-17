"""Cosmos gate and async agents. No network and no labels."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dh.agents.base import CallResult
from dh.agents.yolo_cosmos import YoloCosmosAsync, YoloCosmosGate
from dh.models import ClipMeta

_ROOT = Path(__file__).resolve().parents[2]
_BANNED = ("hazards.json", "reasoning_content", "object_counts", "caption")


def _meta() -> ClipMeta:
    return ClipMeta(clip_id="clip-a", duration_s=40.0, fps_sample=5, segments=[])


def _looming_person(index: int, t: float) -> dict:
    """Same person, bottom-centre in the corridor, box growing so range closes."""
    growth = 1.0 + 0.2 * (index % 6)
    height = 340.0 * growth
    width = 110.0 * growth
    cx = max(960.0, 1120.0 - 40.0 * (index % 6))
    y2 = 900.0
    y1 = y2 - height
    return {
        "t": t,
        "frame": index,
        "cls": "person",
        "conf": 0.95,
        "xyxy": [cx - width / 2.0, y1, cx + width / 2.0, y2],
    }


def _drive(agent, limit: int = 40):
    for index in range(limit):
        t = index * 0.2
        result = agent.step(t, f"f{index}", [_looming_person(index, t)], [])
        if result.calls or result.click:
            return index, t, result
    raise AssertionError(f"{agent.name} did not fire")


def test_import_does_not_need_network_or_cosmos():
    sys.modules.pop("dh.clients.cosmos", None)
    assert YoloCosmosGate.name == "yolo_cosmos_gate"
    assert YoloCosmosAsync.name == "yolo_cosmos_async"
    assert "dh.clients.cosmos" not in sys.modules


def test_agent_source_has_no_banned_substrings():
    text = (_ROOT / "dh" / "agents" / "yolo_cosmos.py").read_text(encoding="utf-8")
    for banned in _BANNED:
        assert banned not in text


def test_gate_blocking_call_then_hazard_clicks():
    agent = YoloCosmosGate()
    agent.reset(_meta())
    _index, _t, result = _drive(agent)
    assert result.click is False
    assert len(result.calls) == 1
    assert result.calls[0].blocking is True
    resumed = agent.resume(
        CallResult(
            latency_s=0.9,
            is_hazard=True,
            object="person stepping out",
            track_id=result.calls[0].track_id,
        )
    )
    assert resumed.click is True
    assert resumed.note == "cosmos: person stepping out"
    assert resumed.calls == []
    assert resumed.risk == pytest.approx(result.risk)


def test_gate_clear_verdict_does_not_click_and_suppresses():
    agent = YoloCosmosGate()
    agent.reset(_meta())
    index, t, result = _drive(agent)
    assert result.click is False
    tid = result.calls[0].track_id
    cleared = agent.resume(
        CallResult(latency_s=0.3, is_hazard=False, object="parked car", track_id=tid)
    )
    assert cleared.click is False
    assert cleared.calls == []
    assert agent.suppress_until[tid] == pytest.approx(t + 1.5)

    nxt = index + 1
    nxt_t = nxt * 0.2
    assert nxt_t < t + 1.5
    held = agent.step(nxt_t, f"f{nxt}", [_looming_person(nxt, nxt_t)], [])
    assert held.click is False
    assert held.calls == []

    # Re-arm. The cleared track stays quiet until 1.5 s after the ask.
    agent.armed = True
    for step in range(nxt + 1, nxt + 12):
        ts = step * 0.2
        again = agent.step(ts, f"f{step}", [_looming_person(step, ts)], [])
        if ts >= agent.suppress_until[tid]:
            break
        assert again.click is False
        assert all(call.track_id != tid for call in again.calls)


def test_async_clicks_on_rise_with_non_blocking_call():
    agent = YoloCosmosAsync()
    agent.reset(_meta())
    _index, _t, result = _drive(agent)
    assert result.click is True
    assert result.note == "first rise"
    assert len(result.calls) == 1
    assert result.calls[0].blocking is False
    assert agent.n_clicks == 1


def test_async_not_hazard_prevents_another_click_on_that_track():
    blocked = YoloCosmosAsync()
    open_agent = YoloCosmosAsync()
    meta = _meta()
    blocked.reset(meta)
    open_agent.reset(meta)

    index = None
    tid = None
    for i in range(40):
        t = i * 0.2
        dets = [_looming_person(i, t)]
        left = blocked.step(t, f"f{i}", dets, [])
        right = open_agent.step(t, f"f{i}", dets, [])
        assert left.click is right.click
        if left.click:
            index = i
            tid = left.calls[0].track_id
            assert left.calls[0].blocking is False
            assert right.calls[0].track_id == tid
            break
    assert index is not None and tid is not None

    nxt = index + 1
    t2 = nxt * 0.2
    dets = [_looming_person(nxt, t2)]
    for agent in (blocked, open_agent):
        agent.armed = True
        agent.last_click = t2 - 1.2
    ready = [CallResult(latency_s=0.1, is_hazard=False, object="parked car", track_id=tid)]
    stopped = blocked.step(t2, "fb", dets, ready)
    again = open_agent.step(t2, "fo", dets, [])
    assert stopped.click is False
    assert stopped.calls == []
    assert blocked.verdict[tid] is False
    assert again.click is True
    assert again.calls[0].blocking is False
    assert again.calls[0].track_id == tid

    blocked.armed = True
    blocked.last_click = -1.0e9
    later_t = (nxt + 1) * 0.2
    later = blocked.step(
        later_t,
        "fl",
        [_looming_person(nxt + 1, later_t)],
        [],
    )
    assert later.click is False
    assert later.calls == []


def test_async_resume_does_not_click():
    agent = YoloCosmosAsync()
    agent.reset(_meta())
    out = agent.resume(CallResult(latency_s=0.2, is_hazard=True, object="person", track_id=1))
    assert out.click is False
    assert out.calls == []
