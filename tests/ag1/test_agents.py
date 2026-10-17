"""MVP agents: corridor presence, and risk with hysteresis, gap, and cap."""

from __future__ import annotations

from dh.agents.yolo_naive import YoloNaive
from dh.agents.yolo_risk import YoloRisk
from dh.models import ClipMeta, Det
from dh.risk import in_corridor

_FRAME = (1920, 1080)
# Bottom-centre sits near (960, 900), inside the default corridor on 1920x1080.
_IN_BOX = [880.0, 400.0, 1040.0, 900.0]


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


def test_import_does_not_need_network():
    assert YoloNaive.name == "yolo_naive"
    assert YoloRisk.name == "yolo_risk"


def test_yolo_naive_clicks_person_in_corridor_then_waits():
    assert in_corridor(_IN_BOX, _FRAME)
    agent = YoloNaive()
    agent.reset(_meta())
    det = {"cls": "person", "xyxy": list(_IN_BOX)}

    first = agent.step(0.0, "f0", [det], [])
    assert first.click is True
    assert first.risk == 1.0
    assert first.note == "object in path"
    assert first.calls == []

    early = agent.step(0.4, "f1", [det], [])
    assert early.click is False
    assert early.risk == 1.0
    assert early.note is None
    assert early.calls == []

    again = agent.step(0.5, "f2", [Det(t=0.5, frame=2, cls="person", conf=0.9, xyxy=list(_IN_BOX))], [])
    assert again.click is True
    assert again.note == "object in path"
    assert again.calls == []


def test_yolo_naive_ignores_traffic_light():
    agent = YoloNaive()
    agent.reset(_meta())
    light = {"cls": "traffic light", "xyxy": list(_IN_BOX)}
    result = agent.step(0.0, "f0", [light], [])
    assert result.click is False
    assert result.risk == 0.0
    assert result.note is None
    assert result.calls == []

    dog = {"cls": "dog", "xyxy": list(_IN_BOX)}
    dog_result = agent.step(0.0, "f1", [dog], [])
    assert dog_result.click is False
    assert dog_result.risk == 0.0


def test_yolo_risk_clicks_after_ema_rise_and_respects_gap_and_cap():
    agent = YoloRisk()
    agent.reset(_meta())
    click_times: list[float] = []
    risks: list[float] = []

    # 30 s at 5 fps. High phases loom; short gaps let the EMA fall so the
    # agent can re-arm. The cap must still hold the click count at 3.
    for index in range(150):
        t = index * 0.2
        high = (index % 10) < 7
        dets = [_looming_person(index, t)] if high else []
        result = agent.step(t, f"f{index}", dets, [])
        risks.append(result.risk)
        assert result.calls == []
        if result.click:
            assert result.risk >= 0.6
            assert result.note == "person"
            click_times.append(t)

    assert click_times, f"ema never crossed 0.6, curve={risks[:20]}"
    assert all(later - earlier >= 1.5 for earlier, later in zip(click_times, click_times[1:]))
    first = click_times[0]
    assert all(t >= first + 1.5 for t in click_times[1:])
    assert len(click_times) <= 3
    assert agent.n_clicks <= 3
