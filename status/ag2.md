# AG2 status (Riyu-D1)

Only AG2 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Merged | ag2/phase-1 | #4 | 2026-10-17 10:54 |
| 2 | Merged; 2-b in progress, freeze waiting | ag2/phase-2-b | #8 | 2026-10-17 12:40 |
| 3 | Not started | ag2/phase-3 | | |
| 4 | Not started | ag2/phase-4 | | |

## Now

Doing: Phase 2-b on `ag2/phase-2-b`. Five confirmed chunks were re-ingested, one at a time, with the custom hazard prompt. Camera, capture type, and location were left as indexed.
Next: freeze `testset_v1` only after the message "labels agreed".
Blocked: no second labeller, so nothing is `agreed` and `testset_v1` is not written. `data/hazards.json` was not edited.

## Go / no-go (questions 1 and 4)

Re-checked against VSS on 17 Oct, about 12:05 BST. Counts are from this run.

- Dashboard `metadata.camera_id`: `pie_cam-3` has 1080 segment rows. Overview: 3537 segment rows, 612 unique videos, 0 re-ingest rows.
- Explore `location=toronto`: `total` 180. Counted from the pages: 30 chunks in each of `set01` through `set06`.
- Ten SPEC 7.1 queries, `camera_id` `pie_cam-3`, `top_k` 30. Result counts, then distinct parent chunks: slows down 30/23, pedestrian starts to cross 30/24, walks out between parked cars 30/27, pulls out 30/17, brakes suddenly 6/5, cyclist moves out 20/16, turns while pedestrians cross 30/26, cuts in 0/0, door opening 2/2, bus pulling away 30/16.
- Question 1: yes. The 11 contact sheets already watched still show a developing hazard with the camera car moving or moving off. That is at least 8. Near-miss mode is not flagged. The eight new set01 rows are caption scrubs, not a second watch.
- Question 4: no, for the public app. `http://video-lab-team-36.cosmos.vastdata.com/app/health` returned 200 and `{"ok":true,"service":"developing-hazard"}`. `GET /app/video` returned 404. `dh/api/video.py` on this `main` still returns the bytes `EXAMPLE` and does not proxy VSS. A segment was not played through the pod proxy in this probe.

## Handoffs ready for others

- `data/candidates.jsonl`: 26 rows, sets `set02` to `set06`, `ego_moving` true, `hit_second` at least 5. Ranked from captions, not from detection counts.
- `data/clips.json`: 26 clips, `c01` to `c06` dev, `c07` to `c26` test. `seen_by` is `["riyu"]` because the miner watched them. Local joins are `data/clips/*.mp4` (gitignored). Each joined file is 30 seconds.
- `data/frames/<clip_id>/` at 5 fps, 150 JPEGs and `frames.json` per clip (gitignored).
- `data/hazards.json`: 11 hazards, labeller `riyu` only, `agreed` false. Written by `POST /api/hazards`, not by hand.
- `dh.api.labels.router` hides another labeller's window and `auto_window` until the caller has a saved window. Disk keeps the full record. Freeze keeps `split: "test"` clips only.
- `web/label.js`: `mountLabel`. Blind sit, then handles, type, description, labeller select, and the four buttons. The other window, the dashed proposal, and a risk curve are drawn only after this labeller has saved.

## Needs from others

- fmd: blind sit, then labeller B windows on these clips.
- Moses: arbitrate where the two windows disagree.
- AG3: `web/player.js` and the dev server, so the label screen can play the real segments. The IDE browser on this session could not open `127.0.0.1`. Headless Chrome on the VM did load the screen against example data and a stub player.

## Log (newest first)

- 2026-10-17 12:40 BST. Re-ingested five parent chunks, `chunk_count` 1, custom prompt, metadata unchanged. Each still has segments 1 to 6. Dashboard `duplicate_segment_rows` is 0 and `segment_rows` is still 3537. The progress URL returned 404 before a `completed` status; caption text had changed by then. `c01`'s chunk (`20261001_061917_set02_video_chunk_0002.mp4`) was submitted twice because the first progress record disappeared while its captions were still the old text. The other four were submitted once. `testset_v1` was not frozen.
- 2026-10-17 12:20 BST. Phase 2-b probes and eight more set01 clips (`c27` to `c34`, test). `pytest tests/ag2`: 33 passed, 1 warning. Re-ingest not started. `testset_v1` not frozen. Hazards file not edited.
- 2026-10-17 11:39 BST. Phase 2 data and label screen. `pytest tests/ag2`: 33 passed, 1 warning (Starlette `httpx` inside FastAPI's TestClient). Headless Chrome: after the stub blind sit, the label view shows drag handles, the type and labeller selects, and the four buttons. Save sends `PUT api/hazards/c07_h1`. The other labeller outline, the dashed window, and the risk curve stay hidden until that labeller has saved. `testset_v1` was not frozen: every hazard has only riyu's window, so `agreed` is false. Dev clips `c02`, `c04`, and `c06` were watched and left without a window because a developing hazard was not clear. Nothing was pushed to `main`.
