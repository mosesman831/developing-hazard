"""Corridor risk agent with hysteresis (SPEC 12.2).

Clicks when the smoothed scene risk rises through theta_up, then waits
until it falls to theta_down. At most max_clicks per clip, with a minimum
gap. Thresholds come from dh.config and are not tuned here.
"""

from __future__ import annotations

from dh import config
from dh.agents.base import StepResult
from dh.risk import features, scene_risk
from dh.track import IoUTracker

_LAST_RESET = -1.0e9


class YoloRisk:
    """Click on a rising scene-risk EMA, with a cap and a minimum gap."""

    name = "yolo_risk"

    def __init__(self, overrides: dict | None = None) -> None:
        chosen = overrides or {}
        self.theta_up = float(chosen.get("theta_up", config.theta_up))
        self.theta_down = float(config.theta_down)
        self.ema_weight = float(chosen.get("ema_weight", config.ema_weight))
        self.max_clicks = int(config.max_clicks)
        self.min_click_gap_s = float(config.min_click_gap_s)
        self.frame_wh = (1920, 1080)
        self.tracker = IoUTracker()
        self.armed = True
        self.ema = 0.0
        self.n_clicks = 0
        self.last_click = _LAST_RESET

    def reset(self, meta) -> None:
        self.tracker = IoUTracker()
        self.frame_wh = tuple(getattr(meta, "frame_wh", (1920, 1080)))
        self.armed = True
        self.ema = 0.0
        self.n_clicks = 0
        self.last_click = _LAST_RESET

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        tracks = self.tracker.update(t, dets)
        feats = [features(track, self.frame_wh) for track in tracks]
        raw = float(scene_risk(feats))
        weight = self.ema_weight
        self.ema = (1.0 - weight) * self.ema + weight * raw
        click = False
        note = None
        if (
            self.armed
            and self.ema >= self.theta_up
            and (t - self.last_click) >= self.min_click_gap_s
            and self.n_clicks < self.max_clicks
        ):
            click = True
            self.armed = False
            self.last_click = t
            self.n_clicks += 1
            note = _top_class(feats)
        if self.ema <= self.theta_down:
            self.armed = True
        return StepResult(click=click, risk=self.ema, note=note, calls=[])


def _top_class(feats) -> str:
    if not feats:
        return "risk"
    top = max(feats, key=lambda feat: float(getattr(feat, "risk", 0.0)))
    cls = getattr(top, "cls", None)
    if cls:
        return str(cls)
    return "risk"
