"""Straw-man presence agent (SPEC 12.4).

Clicks when any road user is inside the ego corridor, then waits 0.5 s.
Dog and traffic light are ignored. This policy is fixed, not tuned.
"""

from __future__ import annotations

from dh.agents.base import StepResult
from dh.risk import in_corridor

ROAD_USERS = frozenset(
    {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
)
_CLICK_GAP_S = 0.5
_LAST_RESET = -1.0e9


class YoloNaive:
    """Click on a road user in the corridor, with a half-second gap."""

    name = "yolo_naive"

    def __init__(self) -> None:
        self.last = _LAST_RESET
        self.frame_wh = (1920, 1080)

    def reset(self, meta) -> None:
        self.last = _LAST_RESET
        self.frame_wh = tuple(getattr(meta, "frame_wh", (1920, 1080)))

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        inside = any(_kept(det, self.frame_wh) for det in dets)
        click = inside and (t - self.last) >= _CLICK_GAP_S
        if click:
            self.last = t
        return StepResult(
            click=click,
            risk=1.0 if inside else 0.0,
            note="object in path" if click else None,
            calls=[],
        )


def _cls_xyxy(det):
    if isinstance(det, dict):
        return det["cls"], det["xyxy"]
    return det.cls, det.xyxy


def _kept(det, frame_wh) -> bool:
    cls, xyxy = _cls_xyxy(det)
    if cls not in ROAD_USERS:
        return False
    return bool(in_corridor(xyxy, frame_wh))
