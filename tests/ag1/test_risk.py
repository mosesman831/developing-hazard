"""Corridor membership, heading, and the SPEC 7.6 risk score."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dh.risk import features, heading_in, in_corridor, scene_risk

FRAME = (1920.0, 1080.0)


def _track(cls: str, xyxy: list[float], **overrides) -> SimpleNamespace:
    x1, y1, x2, y2 = xyxy
    base = dict(
        id=1,
        t=1.0,
        cls=cls,
        xyxy=xyxy,
        vx=0.0,
        vy=0.0,
        h_rate=0.0,
        cx=(x1 + x2) / 2.0,
        cy=(y1 + y2) / 2.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_bottom_centre_inside_default_corridor_top_left_is_outside():
    # Bottom-centre is (960, 900), inside the trapezoid. The box centre is
    # above top_y, so this fails if the test uses the box centre by mistake.
    assert in_corridor([910.0, 100.0, 1010.0, 900.0], FRAME) is True
    assert in_corridor([0.0, 0.0, 40.0, 80.0], FRAME) is False


def test_person_inside_with_two_second_ttc_has_bounded_risk():
    # h_rate 0.5 gives TTC = 2 s. vx is 0, so the track is not heading in.
    track = _track(
        "person",
        [910.0, 100.0, 1010.0, 900.0],
        id=3,
        t=4.0,
        h_rate=0.5,
        cx=960.0,
        cy=500.0,
    )
    feat = features(track, FRAME)
    assert feat.in_corridor is True
    assert feat.heading_in is False
    assert feat.ttc == pytest.approx(2.0)
    assert feat.t_lat is None
    assert 0.0 < feat.risk <= 1.0


def test_heading_in_left_of_centre_with_vx_above_v_min():
    # v_min = 0.01 * 1920 = 19.2 px/s. 40 px/s is above that.
    assert heading_in(200.0, 900.0, 40.0, FRAME) is True
    assert heading_in(1700.0, 900.0, -40.0, FRAME) is True
    assert heading_in(200.0, 900.0, -40.0, FRAME) is False


def test_heading_uses_corridor_centre_at_that_y():
    corridor = {
        "bottom_x0": 0.0,
        "bottom_x1": 0.2,
        "top_x0": 0.0,
        "top_x1": 0.2,
        "top_y": 0.5,
    }
    # Centre line is x = 0.1 of the width (192 px). x = 500 is to the right.
    assert heading_in(500.0, 900.0, 40.0, FRAME, corridor) is False
    assert heading_in(500.0, 900.0, -40.0, FRAME, corridor) is True


def test_scene_risk_is_the_max():
    assert scene_risk([]) == 0.0
    low = SimpleNamespace(risk=0.2)
    high = SimpleNamespace(risk=0.75)
    assert scene_risk([low, high, SimpleNamespace(risk=0.4)]) == 0.75


def test_traffic_light_class_weight_contributes_nothing():
    xyxy = [0.0, 0.0, 40.0, 80.0]
    person = features(_track("person", xyxy), FRAME)
    light = features(_track("traffic light", xyxy), FRAME)
    assert person.in_corridor is False
    assert person.heading_in is False
    assert person.ttc is None
    assert person.risk == pytest.approx(0.1)
    assert light.risk == 0.0


def test_lateral_time_uses_nearest_edge():
    # Bottom y is the frame bottom. Nearest edge is 0.25 * 1920 = 480.
    # Distance 280 px at 40 px/s is 7 s.
    track = _track(
        "person",
        [180.0, 980.0, 220.0, 1080.0],
        vx=40.0,
        cx=200.0,
        cy=1030.0,
    )
    feat = features(track, FRAME)
    assert feat.heading_in is True
    assert feat.in_corridor is False
    assert feat.t_lat == pytest.approx(7.0)
