"""Connector, camera analysis, fixed-camera risk and the camera-aware agent."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from dh.agents.scene_risk import SceneRisk, reason
from dh.risk_fixed import FixedScene
from dh.scene import Road, calibrate, foot, image_to_ground, learn_road, rig, scenery, world_to_image

FRAME = (1920.0, 1080.0)
POSE = {"x": 0.0, "z": 0.0, "height_m": 5.0, "yaw_deg": 0.0, "pitch_deg": 22.0, "hfov_deg": 100.0, "k1": 0.0}


def box_at(R, x, z, height, width=0.6):
    """Pixel box of an upright object standing at ground (x, z), as the camera sees it."""
    b = world_to_image(R, (x, 0.0, z))
    top = world_to_image(R, (x, height, z))
    left = world_to_image(R, (x - width / 2, 0.0, z))
    right = world_to_image(R, (x + width / 2, 0.0, z))
    return [left[0] * FRAME[0], top[1] * FRAME[1], right[0] * FRAME[0], b[1] * FRAME[1]]


def test_image_ground_round_trip_matches_the_web_camera():
    R = rig(POSE, FRAME)
    for x, z in [(0, 8), (-4, 12), (6, 20), (1.5, 40)]:
        u, v = world_to_image(R, (x, 0.0, z))
        g = image_to_ground(R, u, v)
        assert g is not None and math.hypot(g[0] - x, g[1] - z) < 1e-6
    assert image_to_ground(R, 0.5, 0.0) is None, "above the horizon has no ground point"


def test_calibration_recovers_a_street_camera_from_people():
    R = rig(POSE, FRAME)
    dets = []
    for i in range(30):
        x, z = -6 + (i % 7) * 2.0, 7 + (i * 1.3) % 22
        dets.append({"t": i * 0.2, "cls": "person", "conf": 0.9, "xyxy": box_at(R, x, z, 1.7)})
    cal = calibrate(dets, FRAME, hfov=100.0)
    assert cal is not None
    assert abs(cal["pose"]["pitch_deg"] - 22.0) < 1.5
    assert abs(cal["pose"]["height_m"] - 5.0) / 5.0 < 0.12


def test_the_road_is_where_vehicles_drive():
    tracks = {1: [(t * 0.2, (-20 + t * 2.0, 15.0 + 0.1 * (t % 2)), "car") for t in range(20)],
              2: [(t * 0.2, (20 - t * 2.0, 18.0), "car") for t in range(20)],
              3: [(t * 0.2, (2.0, 9.0), "person") for t in range(20)]}
    road = learn_road(tracks)
    assert len(road.strips) == 1
    s = road.strips[0]
    assert abs(abs(s["axis"][0]) - 1.0) < 0.05, "the road runs along x"
    assert road.contains((0.0, 16.5)) and not road.contains((0.0, 6.0))
    sc = scenery(road)
    assert len(sc["roads"]) == 1 and len(sc["sidewalks"]) == 2 and sc["lane_lines"][0]["dash"]
    assert learn_road({9: [(0.0, (0, 10), "car"), (0.2, (0.1, 10), "car"), (0.4, (0.2, 10), "car")]}).strips == [], "a parked car is not a road"


def live(tid, cls, xyxy, vx=0.0):
    return SimpleNamespace(id=tid, cls=cls, xyxy=xyxy, vx=vx, vy=0.0, h_rate=0.0, t=0.0)


def scenario(person_in_road: bool, car_moving: bool):
    """A car driving along the road toward a person; returns the person's peak risk."""
    R = rig(POSE, FRAME)
    road = Road(strips=[{"c": (0.0, 15.0), "axis": (1.0, 0.0), "half_len": 40.0, "half_w": 3.5}])
    scene = FixedScene(R, FRAME, road)
    peak = 0.0
    for k in range(15):
        t = k * 0.2
        cx = -14 + (k * 1.6 if car_moving else 0.0)              # 8 m/s toward the person
        pz = 15.0 if person_in_road else 9.0
        feats = scene.features(t, [live(1, "car", box_at(R, cx, 16.0, 1.5, 4.0)), live(2, "person", box_at(R, 0.0, pz, 1.7))])
        p = next(f for f in feats if f.track_id == 2)
        peak = max(peak, p.risk)
    return peak, p


def test_fixed_risk_rates_a_person_in_the_road_with_traffic_highest():
    in_road_traffic, last = scenario(True, True)
    in_road_quiet, _ = scenario(True, False)
    pavement_traffic, _ = scenario(False, True)
    assert in_road_traffic >= 0.6, in_road_traffic
    assert in_road_quiet < 0.6 and pavement_traffic < 0.6
    assert in_road_traffic > max(in_road_quiet, pavement_traffic)
    assert last.in_corridor is True and "in the road" in last.why


def test_agent_clicks_with_a_reason_on_a_fixed_camera():
    R = rig(POSE, FRAME)
    camera = {"kind": "fixed", "pose": POSE, "frame_wh": list(FRAME), "road": [{"c": (0.0, 15.0), "axis": (1.0, 0.0), "half_len": 40.0, "half_w": 3.5}]}
    agent = SceneRisk({"camera": camera})
    agent.reset(None)
    clicks = []
    for k in range(25):
        t = k * 0.2
        dets = [{"t": t, "cls": "car", "conf": 0.9, "xyxy": box_at(R, -16 + k * 1.6, 16.0, 1.5, 4.0)},
                {"t": t, "cls": "person", "conf": 0.9, "xyxy": box_at(R, 0.0, 15.0, 1.7)}]
        res = agent.step(t, "", dets, [])
        if res.click:
            clicks.append((t, res.note))
    assert clicks, "a person in the road with a car closing must be clicked"
    assert "person" in clicks[0][1] and "in the road" in clicks[0][1]


def test_agent_on_a_dashcam_uses_the_corridor_model():
    agent = SceneRisk({"camera": {"kind": "dashcam", "frame_wh": [1920, 1080]}})
    agent.reset(None)
    fired = False
    for k in range(20):
        t = k * 0.2
        h = 120 + k * 22                                          # a person growing fast in the corridor: closing
        res = agent.step(t, "", [{"t": t, "cls": "person", "conf": 0.9, "xyxy": [930, 1000 - h, 990, 1000]}], [])
        fired = fired or res.click
    assert fired


def test_reason_line_without_why():
    f = SimpleNamespace(cls="car", track_id=4, risk=0.7, in_corridor=True, heading_in=False, ttc=1.5, t_lat=None)
    assert reason(f, "dashcam") == "car #4 (risk 0.70): in our path; closing, time to contact 1.5 s"


def test_connector_end_to_end_with_a_stub_detector(tmp_path, monkeypatch):
    """No network, no model: the detector, the video probe and the motion check are stubbed."""
    import dh.connect as connect
    from dh.clients import yolo_local

    R = rig(POSE, FRAME)
    frames = []
    for k in range(25):
        t = round(k * 0.2, 3)
        frames.append({"time_sec": t, "detections": [
            {"label": "car", "confidence": 0.9, "bbox": box_at(R, -16 + k * 1.6, 16.0, 1.5, 4.0)},
            {"label": "person", "confidence": 0.9, "bbox": box_at(R, 0.0, 15.0, 1.7)},
            *[{"label": "person", "confidence": 0.8, "bbox": box_at(R, -6 + j * 3.0, 8 + j * 3.5, 1.7)} for j in range(4)]]})
    payload = {"fps": 5, "video_shape": [1080, 1920], "model": "stub", "frames": frames}
    video = tmp_path / "neighborhood_test_clip.mp4"
    video.write_bytes(b"\x00" * 64)
    monkeypatch.setattr(yolo_local, "available", lambda: True)
    monkeypatch.setattr(yolo_local, "detect_video", lambda *a, **k: payload)
    monkeypatch.setattr(connect, "probe", lambda p: {"fps": 30.0, "frames": 150, "w": 1920, "h": 1080, "duration_s": 5.0})
    import dh.scene as scene

    monkeypatch.setattr(scene, "camera_kind", lambda *a, **k: {"kind": "fixed", "flow": 0.0, "moving_share": 0.0, "why": "stub: still background"})
    for key in ("YOLO_URL", "GPU_BEARER_TOKEN", "COSMOS3_REASON_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(connect, "has", lambda *names: False)
    out = connect.connect(str(video), data_dir=str(tmp_path / "data"))
    data = tmp_path / "data"
    assert out["camera"] == "fixed" and out["camera_id"] == "neighborhood_cam-1"
    assert (data / "det" / f"{out['clip_id']}.jsonl").is_file()
    tracks = [json.loads(x) for x in (data / "tracks" / f"{out['clip_id']}.jsonl").read_text().splitlines()]
    assert tracks and {"track_id", "t", "cls", "xyxy", "risk"} <= set(tracks[0])
    cam = json.loads((data / "cameras" / "neighborhood_cam-1.json").read_text())
    assert cam["kind"] == "fixed" and cam["pose"]["height_m"] > 0 and cam["scenery"]["roads"]
    clip = json.loads((data / "clips.json").read_text())[0]
    assert clip["segments"][0]["source"].startswith("local:") and (data / "clips" / clip["segments"][0]["source"][6:]).is_file()
    row = json.loads((data / "runs" / out["runs"][0] / "clips.jsonl").read_text())
    assert row["clicks"], "the agent clicks on the person in the road"
    assert row["clicks"][0]["reason"].startswith("person")


def test_api_serves_connector_outputs(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    (tmp_path / "cameras").mkdir()
    (tmp_path / "cameras" / "cam-x.json").write_text(json.dumps({"camera_id": "cam-x", "kind": "fixed"}))
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "u_a.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
    (tmp_path / "clips.json").write_text(json.dumps([{"clip_id": "u_a", "camera_id": "cam-x", "original_video": "local:u_a.mp4",
                                                     "segments": [{"source": "local:u_a.mp4", "start_s": 0, "end_s": 5}], "duration_s": 5}]))
    monkeypatch.setenv("DH_DATA_DIR", str(tmp_path))
    from dh.server import create_app

    c = TestClient(create_app())
    assert c.get("/api/cameras/cam-x").json()["kind"] == "fixed"
    assert c.get("/api/cameras/nope").status_code == 404
    assert c.get("/api/clips/u_a/det").json() == []
    assert c.get("/api/clips/zz/det").status_code == 404
    r = c.get("/video", params={"source": "local:u_a.mp4"}, headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10
    assert c.get("/video", params={"source": "local:../clips.json"}).status_code == 404
