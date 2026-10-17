# AG2 status (Riyu-D1)

Only AG2 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Merged | ag2/phase-1 | #4 | 2026-10-17 10:54 |
| 2 | PR open, freeze blocked | ag2/phase-2 | #8 | 2026-10-17 11:39 |
| 3 | Not started | ag2/phase-3 | | |
| 4 | Not started | ag2/phase-4 | | |

## Now

Doing: Phase 2 clips and labeller A windows are on `ag2/phase-2`.
Next: fmd labels, then Moses arbitrates. Freeze `testset_v1` only after that.
Blocked: no second labeller and no arbitration, so nothing is `agreed` and `testset_v1` is not written.

## Go / no-go (question 1)

Answered from the index on 17 Oct, not from the Phase 1 note.

- `pie_cam-3` is a camera value. Dashboard metadata counted 1080 segment rows for it.
- Explore for location `toronto` returned 180 parent chunks: 30 in each of `set01` through `set06`.
- The ten queries in SPEC 7.1 were run with `camera_id` `pie_cam-3`. "vehicle cuts in front of the camera vehicle" returned no hits. "vehicle ahead brakes suddenly, brake lights on, gap closing" returned 6.
- Question 1: yes. Eleven chunks that were watched as contact sheets have a developing hazard with the camera car moving or moving off. That is at least 8. Near-miss mode is not flagged.
- Question 4 was not run. It needs AG3's pod proxy. `web/player.js` is not on `main`.

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

- 2026-10-17 11:39 BST. Phase 2 data and label screen. `pytest tests/ag2`: 33 passed, 1 warning (Starlette `httpx` inside FastAPI's TestClient). Headless Chrome: after the stub blind sit, the label view shows drag handles, the type and labeller selects, and the four buttons. Save sends `PUT api/hazards/c07_h1`. The other labeller outline, the dashed window, and the risk curve stay hidden until that labeller has saved. `testset_v1` was not frozen: every hazard has only riyu's window, so `agreed` is false. Dev clips `c02`, `c04`, and `c06` were watched and left without a window because a developing hazard was not clear. Nothing was pushed to `main`.
