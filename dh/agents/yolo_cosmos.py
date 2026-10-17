"""Cosmos agents (SPEC 7.10.3, 7.10.4, and 12.3).

Both agents smooth scene risk the same way. The gate waits for a verdict
before it clicks. The async agent clicks on the rise and may click again
when a hazard verdict arrives. Neither agent reads labels.
"""

from __future__ import annotations

from dh import config
from dh.agents.base import CallRequest, CallResult, StepResult
from dh.risk import features, scene_risk
from dh.track import IoUTracker

_LAST_CLICK = -1.0e9
_SUPPRESS_S = 1.5


class _TrackedRisk:
    """Tracker, raw scene risk, and the EMA shared by both Cosmos agents."""

    def __init__(self, overrides: dict | None = None) -> None:
        chosen = overrides or {}
        self.ema_weight = float(chosen.get("ema_weight", config.ema_weight))
        self.theta_down = float(config.theta_down)
        self.theta_trig = float(chosen.get("theta_trig", config.theta_trig))
        self.frame_wh = (1920, 1080)
        self.tracker = IoUTracker()
        self.ema = 0.0
        self.armed = True
        self.feats: list = []
        self.top = None

    def reset(self, meta) -> None:
        self.tracker = IoUTracker()
        self.ema = 0.0
        self.armed = True
        self.feats = []
        self.top = None
        wh = getattr(meta, "frame_wh", None)
        self.frame_wh = tuple(wh) if wh else (1920, 1080)

    def update(self, t, dets) -> None:
        tracks = self.tracker.update(t, dets)
        self.feats = [features(track, self.frame_wh) for track in tracks]
        raw = float(scene_risk(self.feats))
        weight = self.ema_weight
        self.ema = (1.0 - weight) * self.ema + weight * raw
        if self.feats:
            self.top = max(self.feats, key=lambda feat: float(feat.risk))
        else:
            self.top = None

    def top_id(self):
        if self.top is None:
            return None
        return self.top.track_id

    def track_risk(self, track_id) -> float:
        for feat in self.feats:
            if feat.track_id == track_id:
                return float(feat.risk)
        return 0.0


class YoloCosmosGate(_TrackedRisk):
    """Ask for a blocking verdict at theta_trig, then click only on a hazard."""

    name = "yolo_cosmos_gate"

    def __init__(self, overrides: dict | None = None) -> None:
        super().__init__(overrides)
        self.max_calls = int(config.max_verify_calls)
        self.n_calls = 0
        self.suppress_until: dict = {}
        self.pending: tuple[float, int] | None = None

    def reset(self, meta) -> None:
        super().reset(meta)
        self.n_calls = 0
        self.suppress_until = {}
        self.pending = None

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        self.update(t, dets)
        top_id = self.top_id()
        if (
            self.armed
            and self.ema >= self.theta_trig
            and self.n_calls < self.max_calls
            and top_id is not None
            and t >= self.suppress_until.get(top_id, 0.0)
        ):
            self.armed = False
            self.n_calls += 1
            self.pending = (t, top_id)
            return StepResult(
                click=False,
                risk=self.ema,
                note=None,
                calls=[CallRequest(t=t, track_id=top_id, blocking=True)],
            )
        if self.ema <= self.theta_down:
            self.armed = True
        return StepResult(click=False, risk=self.ema, note=None, calls=[])

    def resume(self, out: CallResult) -> StepResult:
        if self.pending is None:
            return StepResult(click=False, risk=self.ema, note=None, calls=[])
        pending_t, track_id = self.pending
        if out.is_hazard:
            return StepResult(
                click=True,
                risk=self.ema,
                note=f"cosmos: {out.object}",
                calls=[],
            )
        self.suppress_until[track_id] = pending_t + _SUPPRESS_S
        return StepResult(click=False, risk=self.ema, note=None, calls=[])


class YoloCosmosAsync(_TrackedRisk):
    """Click on the first rise, then confirm or drop the track when the verdict arrives."""

    name = "yolo_cosmos_async"

    def __init__(self, overrides: dict | None = None) -> None:
        super().__init__(overrides)
        self.max_clicks = int(config.max_clicks_async)
        self.min_click_gap_s = float(config.min_click_gap_async_s)
        self.n_clicks = 0
        self.last_click = _LAST_CLICK
        self.verdict: dict = {}

    def reset(self, meta) -> None:
        super().reset(meta)
        self.n_clicks = 0
        self.last_click = _LAST_CLICK
        self.verdict = {}

    def can_click(self, t: float) -> bool:
        return self.n_clicks < self.max_clicks and (t - self.last_click) >= self.min_click_gap_s

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        self.update(t, dets)
        calls: list[CallRequest] = []
        click = False
        note = None
        for out in ready:
            self.verdict[out.track_id] = out.is_hazard
            if (
                out.is_hazard
                and self.track_risk(out.track_id) >= self.theta_trig
                and self.can_click(t)
            ):
                click = True
                note = f"confirmed: {out.object}"
        top_id = self.top_id()
        if (
            not click
            and self.armed
            and self.ema >= self.theta_trig
            and top_id is not None
            and self.verdict.get(top_id) is not False
            and self.can_click(t)
        ):
            click = True
            note = "first rise"
            self.armed = False
            calls.append(CallRequest(t=t, track_id=top_id, blocking=False))
        if self.ema <= self.theta_down:
            self.armed = True
        if click:
            self.n_clicks += 1
            self.last_click = t
        return StepResult(click=click, risk=self.ema, note=note, calls=calls)

    def resume(self, out: CallResult) -> StepResult:
        return StepResult(click=False, risk=self.ema, note=None, calls=[])
