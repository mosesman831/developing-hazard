// Hazard-clip presets. The recording plays in the video pane. Tracks, boxes and the
// 3D street come from presets-data/<id>.json, built from the stored detector boxes
// so the models sit on the same objects as the footage.
export const PRESETS = [
  { id: 'cross', label: 'Crossing', file: 'set02_video_chunk_0004', video: 'media/20261001_062008_set02_video_chunk_0004.mp4', blurb: 'A person walks off the right pavement and across the lane.', hazard: { start: 11, end: 16.4, click: 12.2, type: 'pedestrian_crossing' } },
  { id: 'cycle', label: 'Cyclist', file: 'set05_video_chunk_0012', video: 'media/20261001_070258_set05_video_chunk_0012.mp4', blurb: 'A cyclist moves out of the right side into the lane. A person crosses further ahead.', hazard: { start: 9, end: 15, click: 10.4, type: 'cyclist_into_lane' } },
  { id: 'bus', label: 'Bus', file: 'set02_video_chunk_0028', video: 'media/20261001_063016_set02_video_chunk_0028.mp4', blurb: 'A bus is stopped ahead, then pulls away.', hazard: { start: 6, end: 13, click: 8.2, type: 'bus_ahead' } },
  { id: 'door', label: 'Open door', file: 'set01_video_chunk_0028', video: 'media/20261001_061720_set01_video_chunk_0028.mp4', blurb: 'A parked van has someone at the open side, and a car is stopped ahead.', hazard: { start: 6, end: 12.5, click: 7.6, type: 'door_opening' } },
  { id: 'brake', label: 'Braking', file: 'set01_video_chunk_0027', video: 'media/20261001_061655_set01_video_chunk_0027.mp4', blurb: 'The car ahead brakes and the gap closes. A cyclist is in front of it.', hazard: { start: 10, end: 16, click: 11.4, type: 'lead_vehicle_braking' } },
  { id: 'junction', label: 'Junction', file: 'set03_video_chunk_0005', video: 'media/20261001_063353_set03_video_chunk_0005.mp4', blurb: 'A person and a cyclist cross the junction in front of the stopped cars.', hazard: { start: 8, end: 13.5, click: 9.2, type: 'junction_crossing' } },
  { id: 'oncoming', label: 'Oncoming cyclist', file: 'set02_video_chunk_0002', video: 'media/20261001_061917_set02_video_chunk_0002.mp4', blurb: 'A cyclist rides toward the camera into the lane. A van is stopped at the curb.', hazard: { start: 8, end: 16, click: 10.1, type: 'oncoming_cyclist' } },
  { id: 'lights', label: 'Brake lights', file: 'set06_video_chunk_0014', video: 'media/20261001_071626_set06_video_chunk_0014.mp4', blurb: 'The vehicle ahead is stopped in the lane with its brake lights on.', hazard: { start: 4, end: 12, click: 6.4, type: 'vehicle_stopped_ahead' } },
];

const byId = new Map(PRESETS.map((p) => [p.id, p]));
export const presetById = (id) => byId.get(id) || PRESETS[0];

const quad = (x0, z0, x1, z1) => [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
const cache = new Map();

export function loadPreset(id) {
  const preset = presetById(id);
  if (!cache.has(preset.id)) {
    cache.set(preset.id, fetch(`presets-data/${preset.id}.json`).then((r) => {
      if (!r.ok) throw new Error(`missing tracks for ${preset.id}`);
      return r.json();
    }).then((data) => parts(preset, data)));
  }
  return cache.get(preset.id);
}

function parts(preset, data) {
  const h = preset.hazard;
  const pose = data.pose;
  return {
    camera: {
      camera_id: 'pie_cam-3',
      kind: 'fixed',
      follow: 'video',
      pose,
      scenery: {
        roads: [quad(-5.5, 0.4, 5.5, 46)],
        sidewalks: [quad(-11, 0.4, -5.5, 46), quad(5.5, 0.4, 11, 46)],
        lane_lines: [{ pts: [[0, 1.5], [0, 44]], dash: true, width: 0.12 }],
      },
    },
    clip: [{
      clip_id: preset.id,
      camera_id: 'pie_cam-3',
      duration_s: data.duration_s || 30,
      segments: [0, 1, 2, 3, 4, 5].map((i) => ({ source: preset.video, start_s: i * 5, end_s: i * 5 + 5 })),
    }],
    tracks: data.tracks,
    det: data.dets,
    hazards: [{ hazard_id: preset.id + '_h', clip_id: preset.id, type: h.type, window_start: h.start, window_end: h.end, agreed: true, description: preset.blurb }],
    run: [{ run_id: 'preview', clip_id: preset.id, clicks: [{ t: h.click, t_trigger: h.start, latency_s: +(h.click - h.start).toFixed(2), reason: 'preview' }], risk_curve: [] }],
  };
}

export function paintPreview(g, w, h) {
  g.fillStyle = '#12161c';
  g.fillRect(0, 0, w, h);
}
