"""Camera-aware risk agent: one agent for dashcam and fixed-camera footage.

The camera kind comes from the clip's camera setup (``dh.scene``), never from
labels. A dashcam uses the ego-corridor features of ``dh.risk``; a fixed camera
uses ``dh.risk_fixed`` (people in or stepping into the road near moving traffic).
Smoothing, hysteresis, the click cap and the minimum gap are the same as
``yolo_risk`` and come from ``dh.config``.

With ``verify=True`` it behaves like ``yolo_cosmos_gate``: at ``theta_trig`` it asks
the verifier (a vision-language model) about the riskiest track and clicks only
on a hazard verdict. Without a verifier it clicks on the risk rise alone.
Each click carries a reason built from the fields that fired.
"""

from __future__ import annotations

from dh import config
from dh.agents.base import CallRequest, CallResult, StepResult
from dh.risk import features as dash_features
from dh.track import IoUTracker

_LAST = -1.0e9
_SUPPRESS_S = 1.5


class SceneRisk:
    name = "scene_risk"

    def __init__(self, overrides: dict | None = None) -> None:
        chosen = overrides or {}
        self.camera = chosen.get("camera") or {"kind": "dashcam"}
        self.verify = bool(chosen.get("verify", False))
        self.theta_up = float(chosen.get("theta_up", config.theta_up))
        self.theta_trig = float(chosen.get("theta_trig", config.theta_trig))
        self.theta_down = float(config.theta_down)
        self.ema_weight = float(chosen.get("ema_weight", config.ema_weight))
        self.max_clicks = int(config.max_clicks)
        self.min_click_gap_s = float(config.min_click_gap_s)
        self.max_calls = int(config.max_verify_calls)
        self.reset(None)

    def reset(self, meta) -> None:
        self.frame_wh = tuple(self.camera.get("frame_wh") or getattr(meta, "frame_wh", None) or (1920, 1080))
        self.tracker = IoUTracker()
        self.scene = None
        if self.camera.get("kind") == "fixed" and self.camera.get("pose"):
            from dh.risk_fixed import FixedScene
            from dh.scene import Road, rig

            road = Road(strips=[dict(s) for s in self.camera.get("road", [])])
            self.scene = FixedScene(rig(self.camera["pose"], self.frame_wh), self.frame_wh, road)
        self.ema = 0.0
        self.armed = True
        self.n_clicks = 0
        self.n_calls = 0
        self.last_click = _LAST
        self.pending = None
        self.suppress: dict = {}
        self.top = None

    def _features(self, t, dets):
        tracks = self.tracker.update(t, dets)
        if self.scene is not None:
            return self.scene.features(t, tracks)
        return [dash_features(tr, self.frame_wh) for tr in tracks]

    def step(self, t, frame_ref, dets, ready) -> StepResult:
        feats = self._features(t, dets)
        raw = max((float(f.risk) for f in feats), default=0.0)
        self.ema = (1.0 - self.ema_weight) * self.ema + self.ema_weight * raw
        self.top = max(feats, key=lambda f: float(f.risk)) if feats else None
        click, note, calls = False, None, []
        can_click = self.n_clicks < self.max_clicks and (t - self.last_click) >= self.min_click_gap_s
        if self.armed and self.top is not None and can_click:
            if self.verify and self.n_calls < self.max_calls and self.ema >= self.theta_trig and t >= self.suppress.get(self.top.track_id, 0.0):
                self.armed = False
                self.n_calls += 1
                self.pending = (t, self.top.track_id, reason(self.top, self.camera.get("kind")))
                calls.append(CallRequest(t=t, track_id=self.top.track_id, blocking=True))
            elif not self.verify and self.ema >= self.theta_up:
                click, note = True, reason(self.top, self.camera.get("kind"))
                self.armed = False
        if self.ema <= self.theta_down:
            self.armed = True
        if click:
            self.n_clicks += 1
            self.last_click = t
        return StepResult(click=click, risk=self.ema, note=note, calls=calls)

    def resume(self, out: CallResult) -> StepResult:
        if self.pending is None:
            return StepResult(click=False, risk=self.ema, note=None, calls=[])
        t, track_id, why = self.pending
        self.pending = None
        if out.is_hazard:
            self.n_clicks += 1
            self.last_click = t
            return StepResult(click=True, risk=self.ema, note=f"{why}; verified: {out.object}".strip("; "), calls=[])
        self.suppress[track_id] = t + _SUPPRESS_S
        return StepResult(click=False, risk=self.ema, note=None, calls=[])


def reason(f, kind) -> str:
    """One line from the fields that fired, e.g. 'person #3: in the road; car #5 moving 6.2 m/s, 3.1 m away'."""
    head = f"{f.cls} #{f.track_id} (risk {float(f.risk):.2f})"
    why = getattr(f, "why", "")
    if why:
        return f"{head}: {why}"
    bits = []
    if getattr(f, "in_corridor", False):
        bits.append("in our path")
    if getattr(f, "heading_in", False):
        bits.append("moving toward our path" + (f", {f.t_lat:.1f} s away" if f.t_lat is not None else ""))
    if getattr(f, "ttc", None) is not None:
        bits.append(f"closing, time to contact {f.ttc:.1f} s")
    return head + (": " + "; ".join(bits) if bits else "")
