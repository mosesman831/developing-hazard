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
With no parameters the dev page opens the house-camera fixture. Add `&video=<url>` to play one local file without the picker. Add `&debug=1` to see source file + line for hovered boxes, markers and events. Play a local mp4 with the file picker, or "Load segments" (`video?source=`, override with `&vbase=`). With no video, the slider drives time.

## Inputs (all optional except the clip; missing ones are named in the Inputs strip)
`clips.json`, `tracks/<id>.jsonl`, `det/<id>.jsonl` (only source of box confidence), `hazards.json`, `runs/<run>/clips.jsonl`, `grid/cosmos_verify_v2/<id>.jsonl` (not in `contracts/`, parsed defensively), `cache/explain/<id>.json` (optional). Confidence = best-IoU (>= 0.5) detection at the same `t`; otherwise "?" (amber). `xyxy` is auto-detected as pixels or 0-1.

## What it shows
Ring = perception confidence (green solid / amber dashed). Fill = hazard assessment (grey / amber / red from pipeline `risk`, human window, Cosmos A.1 rule). Grey hatch = not visible to camera; nothing there is ever red. Bearing = linear in x over `ASSUMED_HFOV_DEG` (157); range = 3 ordinal bands from box-bottom y vs an assumed horizon (0.55). Arrows are observed motion over the past 1 s, not forecasts. All thresholds live in `THRESHOLDS` in `core.js`.

## Wall-mounted cameras (the default)
The camera is assumed to be **fixed on a wall, a house or a pole, looking at a public road**. The dashcam model (ego car, 157° wedge, projected path) is used only for a camera known to move with a car: PIE's `pie_cam-3`, or a calibration or clip that says `"kind": "dashcam"`.

**Where the camera pose comes from**, best first. The inputs strip names which one was used:
1. A calibration file, `data/cameras/<camera_id>.json` (below).
2. Auto-calibration from the people in the footage (`autoCalibrate`).
3. An assumed house camera (`WALL_DEFAULT`: 4 m up, 20° down, 100° lens), labelled "assumed, rough".

**Lens distortion:** the pose takes an optional `k1` (a one-parameter radial division model; negative values model barrel distortion). Wide security lenses need it. The house fixture uses -0.22, and the camera view bends straight edges the same way the video does.

**What a wall camera can measure:** there is no ego car, so the log replaces the pipeline's ego-path events (`in_corridor`, `heading_in`) with `proximityEvents`. Each one is a MEASURED event when a person or cyclist comes within 2 m of a vehicle moving faster than 1 m/s. It uses the calibrated ground positions, typical vehicle sizes and the vehicle's observed heading, and records the closest gap.

**For AG1 and Moses:** the pipeline's risk features (corridor, TTC) and the Cosmos A.1 prompt ("would a careful driver of *this car*…") both assume an ego car. For wall cameras they need a different hazard definition, such as "person close to a moving vehicle". Until then, the fill colour still shows the pipeline's risk as given.

**Real data:** the 26 clips on main (`data/clips.json`, all `pie_cam-3`) are PIE drives filmed from a moving car, so they correctly open in dashcam mode. Wall-camera footage, such as `neighborhood_cam-1` in the challenge corpus, needs clips mined by AG2.

With a calibration, the panel places objects on a flat ground plane in approximate metres and renders the street around them.

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
- Models are authored in metres and scaled by one factor (height, from `METRIC` in `models3d.js`), so wheels and heads stay round. The sizes are typical, not measured. A track with no observed motion faces the nearest lane, or the camera if there is no lane. The opening view frames the actors from the street side of the camera. `C` still jumps to the video viewpoint.
- The 3D view adds a **Camera** view that renders from the calibrated viewpoint, masks the area outside the video frame, and draws 3D boxes: the base and its X show the hazard colour, and the top and uprights show the confidence colour. Ground the camera cannot see is hatched. Plan mode becomes Top + Ortho.
- Fixtures: `SYNTHETIC_c97.*` (`gen-house.mjs`) is a house camera 3.6 m up with a 112° barrel lens, looking across a front yard at a 2-lane road; it is the dev page's default. `SYNTHETIC_c98.*` (`gen-street.mjs`) is a pole camera 18 m up over an avenue. Both build their boxes by projecting 3D objects through the same camera, so the image-to-ground round trip can be checked.

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

**Type** (`style.css`, self-hosted in `spatial/fonts/`):
- IBM Plex Sans for the interface.
- IBM Plex Mono for every number and timestamp, with tabular figures and a slashed zero (SPEC 16.1).

SPEC 16.1 asks for self-hosted fonts. `spatial/fonts/` holds the IBM Plex Sans and Mono files the view uses, so the page does not call Google Fonts.

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
- **Object models** (`models3d.js`): person, car, truck/lorry, bus, motorcycle, bicycle, dog, traffic light and stop sign, each with a rider or a readable silhouette. Any other class gets a generic block. Aliases map `lorry`, `pedestrian`, `motorbike`, `van`, `cyclist`, `train`, `coach` and `cat` onto these. Body paint stays neutral. A ground ring is confidence (dashed amber, solid green) and a ground disc is the hazard fill. A 3D box is drawn only around the selected track. In the dashcam view the same meshes are uniform glyphs and face along their bearing.
- **2D Plan**: the original bird's-eye SVG.

Panels rebuild only when what they show changes, sample lookups use binary search, and 3D model geometry is built once per class, so playback does not churn the DOM.

**Dev page** (`index.html`): a Camera pane with a play/pause transport (it also plays the timeline with no video loaded), a scrubber marked with human-label windows and agent clicks, Open mp4 / Stream segments, and a Scene risk chart (max track risk over time with labels and clicks; click to seek).

Keys: `V` switches plan and 3D, `C` camera view (fixed cameras), `O` ortho, `F` frame (or double-click the view), `[` / `]` previous/next event, `Esc` clear. `P` and `Space` are left to the host, because SPEC 16.1 uses them for play/pause and the hazard click; the dev page uses `P` (and `Space`) for play. Clicking an event seeks to `t - 1.0` and selects its track.

> **Size.** The 60 KB `spatial/` budget (SPEC 6.4 / 16) was waived so the models and the Watch integration could ship together. The snapshot copies the scripts, `style.css` and `spatial/fonts/` into the pod, which still has to stay under the 900 KB limit in `dh/snapshot.py`. Dev-only files (`index.html`, `video.js`, `tests/`, `fixtures/`, this README) do not ship.

## Hand-off (for Moses)
1. **AG3 wiring** (`web/watch.js`) already mounts the view under the player. The dev server serves this folder at `/spatial` (`dh/server.py`), and the snapshot copies the scripts and fonts. `player.seek(clipTime)` is what event clicks call. Pass `aurora: false` if the host page already paints its own backdrop behind the glass.
   Call `sp.setTime(clipTime)` from `requestVideoFrameCallback`/`timeupdate`; `sp.setFrame({w,h})` when the video reports its size. `videoEl` is optional (the canvas overlay attaches to its parent; without it only the panel renders). `getJSON(relUrl)` must return parsed JSON or `null` on 404.
2. **Routes the app mode expects**: `api/clips/{id}` (clip, optionally `{clip, hazards}`), `/tracks`, `/det`, `/grid`, `/explain`, `api/runs/{run_id}`. Only the first two plus runs exist in `contracts/api_routes.md`; `/det`, `/grid`, `/explain` are proposals, and missing ones just show as "missing".
3. **Ownership line for CONTEXT.md**: `spatial/** | <owner> | spatial hazard view add-on; edits only under spatial/`.
4. **Snapshot** (`dh/snapshot.py`): copy `data/det/` (small, committed), `data/grid/` and `data/runs/` for the pod. Without `det/`, demo mode shows confidence "?" everywhere.
5. **Size**: the 60 KB folder budget was waived. The pod snapshot still has to stay under 900 KB; see the note above.

## Limitations
- Fixed mode assumes flat ground and one radial distortion term. Auto-calibration does not fit `k1`; it uses the file's value or 0. Uncalibrated wide lenses, such as the night street camera tried on 2026-10-17, are least accurate near the image edges.
- Proximity gaps use typical vehicle sizes and the flat-ground contact point of each box, so a gap under about half a metre means "touching distance, roughly", not a measured clearance.
- Single camera, no depth, no calibration, no ego speed: positions are ordinal and the corridor assumes straight driving.
- Tracks hold only the top 3 per frame at 5 fps, so a track can vanish when others outrank it. A dropout hides the track after 0.3 s (not interpolated).
- Cosmos rows tint a track red only when the row carries a `track_id`; otherwise it is an event only.
- Streak length is measured within these top-3 samples, so it can undercount.
- Not yet tested on real PIE footage or the segment player against a live `video?source=` (no data or server existed when built).
