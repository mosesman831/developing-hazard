# Spatial Hazard View

Approximate bird's-eye panel + evidence-backed event list + box overlay, synced to the dashcam video. Reads the pipeline's outputs; never re-scores, never calls Cosmos/YOLO/W&B.

## Run

```
node spatial/fixtures/gen.mjs                  # regenerate SYNTHETIC fixtures (UI work only)
node --test spatial/tests/core.test.mjs        # unit tests, no packages
# serve the clone root with any static server, then open:
spatial/index.html?clip=c07&src=examples       # contracts/examples (placeholder data)
spatial/index.html?clip=c99&src=fixtures       # synthetic, red banner
spatial/index.html?clip=c07&src=dev&run=<id>   # real data/ files
```
Add `&video=<url>` to play one local file without the picker. Add `&debug=1` to see source file + line for hovered boxes, markers and events. Play a local mp4 with the file picker, or "Load segments" (`video?source=`, override with `&vbase=`). With no video, the slider drives time.

## Inputs (all optional except the clip; missing ones are named in the Inputs strip)
`clips.json`, `tracks/<id>.jsonl`, `det/<id>.jsonl` (only source of box confidence), `hazards.json`, `runs/<run>/clips.jsonl`, `grid/cosmos_verify_v2/<id>.jsonl` (not in `contracts/`, parsed defensively), `cache/explain/<id>.json` (optional). Confidence = best-IoU (>= 0.5) detection at the same `t`; otherwise "?" (amber). `xyxy` is auto-detected as pixels or 0-1.

## What it shows
Ring = perception confidence (green solid / amber dashed). Fill = hazard assessment (grey / amber / red from pipeline `risk`, human window, Cosmos A.1 rule). Grey hatch = not visible to camera; nothing there is ever red. Bearing = linear in x over `ASSUMED_HFOV_DEG` (157); range = 3 ordinal bands from box-bottom y vs an assumed horizon (0.55). Arrows are observed motion over the past 1 s, not forecasts. All thresholds live in `THRESHOLDS` in `core.js`.

## Stationary cameras (fixed mode)
If the footage comes from a fixed camera rather than a dashcam, give the camera a calibration file. The panel then places objects on a flat ground plane in approximate metres, and renders the street around them.

`data/cameras/<camera_id>.json` (app route proposal: `api/cameras/{camera_id}`), or inline as `clip.camera`:
```json
{ "camera_id": "cam1", "kind": "fixed",
  "pose": { "x": -10.5, "z": -14, "height_m": 18, "yaw_deg": 11, "pitch_deg": 33, "hfov_deg": 72 },
  "scenery": { "roads": [[[x,z],...]], "sidewalks": [...], "medians": [...],
               "lane_lines": [{ "pts": [[x,z],[x,z]], "dash": true, "width": 0.15 }],
               "crossings": [{ "a": [x,z], "b": [x,z], "width": 4 }],
               "buildings": [{ "footprint": [[x,z],...], "height_m": 18 }],
               "poles": [{ "at": [x,z], "height_m": 7.5, "arm_deg": 90 }], "trees": [{ "at": [x,z], "height_m": 6.5 }] } }
```
- `camera.js` turns a box's bottom-centre into a ground point through a pinhole camera (no lens distortion yet). A box whose bottom is above the horizon, or more than 150 m away, has no ground point and is left out of the 3D view.
- Heading and speed come only from the track's own ground positions over the last second. A parked object keeps its last observed heading.
- Models are stretched to typical real class sizes (`METRIC` in `models3d.js`). These sizes are not measured.
- The 3D view adds a **Camera** view that renders from the calibrated viewpoint, masks the area outside the video frame, and draws 3D boxes: the base and its X show the hazard colour, and the top and uprights show the confidence colour. Ground the camera cannot see is hatched. Plan mode becomes Top + Ortho.
- Without a calibration file, the panel assumes the PIE forward dashcam and says so in the inputs strip.
- `fixtures/SYNTHETIC_c98.*` (from `gen-street.mjs`) is a synthetic avenue. Its boxes are produced by projecting 3D objects through the same camera, so the round trip can be checked.

## Sponsor stack (VAST Builders Challenge)
From [vast-data/vast-builders-challenge](https://github.com/vast-data/vast-builders-challenge), read 2026-10-17. The panel only reads outputs; it never calls a model or the pipeline itself.
- **VAST VSS / DataEngine:** the Detector function runs YOLO11 on every segment and stores a bounding-box sidecar per segment, served by `GET /api/v1/videos/detections?source=<segment>`. When `data/det/<clip>.jsonl` is missing, the panel reads `data/vss/<clip>.detections.json` (`[{ "start_s", "sidecar" }]` per segment; app route proposal `api/clips/{id}/vss-detections`) through `parseVssDetections`. The sidecar schema is not documented, so the parser accepts the common shapes, skips the rest and counts what it skipped. **Untested against a real sidecar.** To fetch them, on the team VM ask Cursor: *"use retrieval/videos to save the detections sidecar for every segment of <original_video> as [{start_s, sidecar}] JSON"*.
- **Camera IDs:** `CAMERAS` in `camera.js` lists the challenge corpus. `pie_cam-3` is the dashcam. `i24_cam-1`, `neighborhood_cam-1`, `sf_streets_cam-1..4`, `sdg_warehouse_cam-2` and `smartspace_cam-1` are fixed.
- **Auto-calibration:** a known fixed camera without a calibration file is calibrated from the person boxes in its tracks or detections (`autoCalibrate`). It searches for the camera height and pitch that make every person about 1.7 m tall. Lens width is assumed (90° unless the file gives `hfov_deg`), and the camera is placed at the origin facing +z. On the synthetic street it recovers 31.1° pitch (true 33°) and 14.3 m height (true 18 m, 21% low). The inputs strip marks this as auto-calibrated and approximate. It needs at least 20 clear people at a range of depths, and does not model lens distortion.
- **NVIDIA Cosmos Reason:** grid verdicts are already read from `data/grid/` (MODEL events). Segment descriptions in VastDB are not shown yet.
- **W&B:** generated explanations are read from `data/cache/explain/` (GENERATED events). Nothing in the panel calls W&B.
- **Tracks** still come from AG1's tracker (`dh/track.py`). VSS gives detections, not tracks, so a VSS-only clip shows calibration and confidence but no tracked objects until AG1 runs.

## Workspace and design
The interface mixes three materials, and each one has a single job:
- **Glass** for anything that sits over other content: the panes, the legend, the units tag, the crumbs and the status bar. They are translucent and blurred over an ambient aurora, so the scene stays present behind the chrome.
- **Neumorphic** surfaces for controls. A tool group is a pressed groove, and the active tool rises out of it. Layer toggles in the outliner are soft switches. The video sits in a recessed screen, and the play key is a raised button that presses in while playing.
- **Material** behaviour: elevation tiers, hover and press state layers, ripples, visible focus rings, and one easing curve.

The accent is periwinkle (`#8ab4ff`) and only marks selection and active state. Green, amber and red stay reserved for the data channels.

**Type** (`style.css`, Google Fonts with `display=swap`):
- Instrument Sans for the interface. Its width axis condenses dense toolbars and labels.
- IBM Plex Mono for every number and timestamp, with tabular figures and a slashed zero (SPEC 16.1).
- Instrument Serif italic for the wordmark only.

SPEC 16.1 asks for self-hosted fonts and leaves open whether the pod can reach Google Fonts. Offline, the stack falls back to IBM Plex Sans (if AG3 self-hosts it in `web/fonts/`), then to system fonts, so nothing breaks.

**Layout:**
- A header with the wordmark, a clip/run breadcrumb and one status chip per input. Missing inputs are spelled out in a note under it.
- The outliner: scene items with switches, and tracks with outline/fill swatches and live confidence.
- The viewport: Plan / 3D, camera presets, projection and layer tools. Labels collapse to icons when the pane is narrow (container queries). The legend collapses itself in a short viewport until you open it.
- Properties: state pills, stat tiles, the reason behind each colour, and a risk sparkline with a time cursor.
- The event log, with provenance filters that shrink to dot and count when narrow.
- A status bar.
- Ripples and transitions switch off under `prefers-reduced-motion`.

**3D rendering:**
- Back-face culling, a key light with sky and ground ambient, and a sheen on glass.
- Distance fog in street scenes and soft three-layer contact shadows.
- Models built from stacked volumes so the painter's sort never fights, with shaped glass cabins, wheels with hubcaps and lights.
- Neutral paint, so a body colour never looks like a hazard colour.
- Glass label pills with a status dot and a leader line, stacked so they never overlap. The view cube and axis triad sit on glass discs.
- **3D Viewport** (`view3d.js`, canvas 2D, no library): drag to orbit, right/shift-drag to pan, wheel to zoom. Preset views Persp / Top / Front / Side, the view cube (click a face), Ortho, Frame, and Grid / FOV / Path / Labels toggles. Axis triad: X right, Y up, Z forward.
- 3D positions use the same bearing and ordinal range bands as the plan view. The grid is in band units, not metres, and the viewport says so.
- **Object models** (`models3d.js`): low-poly generic shapes for person, car, truck/lorry, bus, motorcycle, bicycle, dog, traffic light and stop sign. Any other class gets a generic block. Aliases map `lorry`, `pedestrian`, `motorbike`, `van`, `cyclist`, `train`, `coach` and `cat` onto these. The body colour is the hazard fill, and the footprint outline on the ground is the confidence ring (dashed amber, solid green, white when selected). Models are **not to scale and their heading is not measured**: they face away from the ego car along their bearing.
- **2D Plan**: the original bird's-eye SVG.

Panels rebuild only when what they show changes, sample lookups use binary search, and 3D model geometry is built once per class, so playback does not churn the DOM.

**Dev page** (`index.html`): a Camera pane with a play/pause transport (it also plays the timeline with no video loaded), a scrubber marked with human-label windows and agent clicks, Open mp4 / Stream segments, and a Scene risk chart (max track risk over time with labels and clicks; click to seek).

Keys: `V` switches plan and 3D, `C` camera view (fixed cameras), `O` ortho, `F` frame (or double-click the view), `[` / `]` previous/next event, `Esc` clear. `P` and `Space` are left to the host, because SPEC 16.1 uses them for play/pause and the hazard click; the dev page uses `P` (and `Space`) for play. Clicking an event seeks to `t - 1.0` and selects its track.

> **AG3: size budget exceeded.** The shipped files (`core.js`, `data.js`, `spatial.js`, `view3d.js`, `models3d.js`, `camera.js`, `style.css`) total 120,196 bytes (40 KB gzipped), about 60 KB over the 60 KB `spatial/` budget (SPEC 6.4 / 16). The lead accepted 4 KB over for the 2D plan plus the 3D viewport. Everything since (workspace polish, fixed-camera mode, auto-calibration and VSS sidecars, and the neu / glass / material redesign) still needs the lead's OK, and the pod's 900 KB budget in `dh/snapshot.py` must absorb it. If the pod runs short, drop the 2D plan first (about 5 KB), since 3D Top + Ortho replaces it.

## Hand-off (for Moses)
1. **AG3 wiring** (`web/watch.js`): `import { mountSpatial } from "../spatial/spatial.js"` (or copy the folder to `web/spatial/`), then
   `const sp = mountSpatial(el, { clipId, runId, initialMode: "3d", api: { getJSON }, mode: "app", videoEl, frame: {w: 1920, h: 1080}, onSeek: t => player.seek(t), onSelect: () => {} })`. Pass `aurora: false` if the host page already paints its own backdrop behind the glass.
   Call `sp.setTime(clipTime)` from `requestVideoFrameCallback`/`timeupdate`; `sp.setFrame({w,h})` when the video reports its size. `videoEl` is optional (the canvas overlay attaches to its parent; without it only the panel renders). `getJSON(relUrl)` must return parsed JSON or `null` on 404.
2. **Routes the app mode expects**: `api/clips/{id}` (clip, optionally `{clip, hazards}`), `/tracks`, `/det`, `/grid`, `/explain`, `api/runs/{run_id}`. Only the first two plus runs exist in `contracts/api_routes.md`; `/det`, `/grid`, `/explain` are proposals, and missing ones just show as "missing".
3. **Ownership line for CONTEXT.md**: `spatial/** | <owner> | spatial hazard view add-on; edits only under spatial/`.
4. **Snapshot** (`dh/snapshot.py`): copy `data/det/` (small, committed), `data/grid/` and `data/runs/` for the pod. Without `det/`, demo mode shows confidence "?" everywhere.
5. **Size**: shipped files total 120,196 bytes, about 60 KB over the 60 KB budget; see the AG3 note above. Dev-only files (`index.html`, `video.js`, `tests/`, `fixtures/`, this README) do not ship.

## Limitations
- Fixed mode assumes flat ground and a distortion-free lens. Wide security cameras (such as the night street camera tested on 2026-10-17) have strong barrel distortion, so ground positions near the image edges will be off until a radial-distortion term is added to the calibration.
- Single camera, no depth, no calibration, no ego speed: positions are ordinal and the corridor assumes straight driving.
- Tracks hold only the top 3 per frame at 5 fps, so a track can vanish when others outrank it. A dropout hides the track after 0.3 s (not interpolated).
- Cosmos rows tint a track red only when the row carries a `track_id`; otherwise it is an event only.
- Streak length is measured within these top-3 samples, so it can undercount.
- Not yet tested on real PIE footage or the segment player against a live `video?source=` (no data or server existed when built).
