# AG2 status (Riyu-D1)

Only AG2 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Merged | ag2/phase-1 | #4 | 2026-10-17 10:54 |
| 2 | Merged | ag2/phase-2-b | #19 | 2026-10-17 12:40 |
| 3 | In progress, freeze blocked | ag2/phase-3 | | 2026-10-17 13:25 |
| 4 | Code ready, VastDB write on lab VM | ag2/phase-4 | | 2026-10-17 15:30 |

## Now

Doing: Phase 4 on `ag2/phase-4`. Row builders and `refuse()` allowlist are in place; live VastDB insert is not run from this session.
Next: parent agent opens the PR. On the lab VM, run the VastDB write command below once credentials are loaded.
Blocked: window proposal vs agreed-window MAE (no agreed windows; fmd pass parked). AG2-P4-2 stays open until the lab VM write succeeds.

## Phase 4 sanity (SPEC 14.5, dev only)

Numbers below are copied from `status/ag1.md` on this branch and from `data/runs/*/run.json`. Label: **dev**. `testset_id` is `dev` and `testset_sha256` is `unfrozen` in these run files.

| Check | Result (dev) | Source |
|---|---|---|
| `yolo_risk` (tuned) | score 6, max 15, pct 0.4, `lift_vs_chance` 0.3202000000000003, `pattern_rate` 0.0 | `status/ag1.md`; `data/runs/r_yolo_risk_20261017T122620/run.json` totals |
| `yolo_naive` | score 0, max 15, pct 0.0, `pattern_rate` 0.8333333333333334 | `status/ag1.md`; `data/runs/r_yolo_naive_20261017T122551/run.json` totals |
| `yolo_cosmos_gate` | score 0, max 15, pct 0.0; AG1 notes mean latency 0.94 s on dev | `status/ag1.md` |
| `yolo_cosmos_async` | score 0, max 15, pct 0.0, `lift_vs_chance` -0.13 | `status/ag1.md` |
| Gaming (`random@6` vs tuned risk) | `random@6` pct 0.284; tuned `yolo_risk` pct 0.40 on dev; random does not come close | `status/ag1.md` gaming table |
| Verifier false alarms on dev grid | 4 of 270 points (1.5%); grid 1518 points, 23 HAZARD (1.5%), median latency 0.953 s | `status/ag1.md` Phase 3 grid |
| Blind humans | `fmd` 4/5 (pct 0.8); `smoke` 0/5 | `status/ag1.md`; `data/leaderboard.json` rows |
| Window proposal vs agreed MAE | **BLOCKED** | No paired agreed windows: 0 of 0 paired within tolerance (`status/ag2.md` agreement line). fmd labeller B pass not done. |

## VastDB runs and hazard_scores (AG2-P4-2)

**Needs the lab VM.** Code-only here: `run_rows`, `hazard_score_rows`, and `write_runs_and_scores` in `dh/store.py`. Dev runs under `data/runs/` use `testset_id` `dev` and `testset_sha256` `unfrozen` (or empty if absent in a file).

On the lab VM, after merging this branch and with `S3_ENDPOINT`, `ACCESS_KEY`, `SECRET_KEY`, and `VASTDB_BUCKET` set:

```bash
cd /home/mosesman831/dh-ag2 && PYTHONPATH=. /home/mosesman831/developing-hazard/.venv/bin/python -m dh.store
```

That calls `write_runs_and_scores(testset_id="dev")` and inserts into `developing_hazard.runs` and `developing_hazard.hazard_scores` only.

## Secret scan (AG2-P4-3)

From `/home/mosesman831/dh-ag2`: `bash scripts/secret_scan.sh`  
Summary: `files_scanned=300`, `hits=0` (script stdout on 2026-10-17).

## Blocked on the fmd pass

These Phase 3 items are not done, because fmd has not labelled and Moses has not arbitrated:

- Labeller B windows. All 21 hazards have only riyu's window, so `agreed` is false. Nothing was marked agreed by hand.
- Blind sits from Moses, and blind sits from fmd beyond the two sessions already in `data/humans.jsonl`, both on `c01`.
- Arbitration (`arbitrated_by`).
- `testset_v1` and `testset_v2`. Neither file was written. Freeze stays blocked until paired windows exist.
- Live "more like this" search. Mining and labelling were not short, so `dh/clients/embed.py` is only the client. It was not run against the index.

## Agreement (13.5)

0 of 0 paired windows agreed within tolerance. 21 hazards have a window from riyu only, so none can agree yet.

## Go / no-go (questions 1 and 4)

Re-checked against VSS on 17 Oct, about 12:05 BST. Counts are from this run.

- Dashboard `metadata.camera_id`: `pie_cam-3` has 1080 segment rows. Overview: 3537 segment rows, 612 unique videos, 0 re-ingest rows.
- Explore `location=toronto`: `total` 180. Counted from the pages: 30 chunks in each of `set01` through `set06`.
- Ten SPEC 7.1 queries, `camera_id` `pie_cam-3`, `top_k` 30. Result counts, then distinct parent chunks: slows down 30/23, pedestrian starts to cross 30/24, walks out between parked cars 30/27, pulls out 30/17, brakes suddenly 6/5, cyclist moves out 20/16, turns while pedestrians cross 30/26, cuts in 0/0, door opening 2/2, bus pulling away 30/16.
- Question 1: yes. The 11 contact sheets already watched still show a developing hazard with the camera car moving or moving off. That is at least 8. Near-miss mode is not flagged. The eight new set01 rows are caption scrubs, not a second watch.
- Question 4: yes, re-checked after the video proxy merge. `GET /app/health` returned 200 and `{"ok":true}`. `GET /app/api/clips` listed 26 clips. A `Range: bytes=0-15` request for the first segment of `c01` through `/app/video` returned 206, content type `binary/octet-stream`, and the bytes `ftyp` / `isom`.

## Handoffs ready for others

- `data/candidates.jsonl`: 26 rows, sets `set02` to `set06`, `ego_moving` true, `hit_second` at least 5. Ranked from captions, not from detection counts.
- `data/clips.json`: 26 clips, `c01` to `c06` dev, `c07` to `c26` test. `seen_by` is `["riyu"]` because the miner watched them. Local joins are `data/clips/*.mp4` (gitignored). Each joined file is 30 seconds.
- `data/frames/<clip_id>/` at 5 fps, 150 JPEGs and `frames.json` per clip (gitignored).
- `data/hazards.json`: 21 hazards, labeller `riyu` only, `agreed` false. The extra 10 were written by `POST /api/hazards` in Phase 3, not by hand.
- `dh.api.labels.router` hides another labeller's window and `auto_window` until the caller has a saved window. Disk keeps the full record. Freeze keeps `split: "test"` clips only.
- `web/label.js`: `mountLabel`. Blind sit, then handles, type, description, labeller select, and the four buttons. The other window, the dashed proposal, and a risk curve are drawn only after this labeller has saved.
- `SUBMISSION.md`: paste-ready project blurb for the challenge form.

## Needs from others

- fmd: blind sit, then labeller B windows on these clips.
- Moses: arbitrate where the two windows disagree.
- AG3: `web/player.js` and the dev server, so the label screen can play the real segments. The IDE browser on this session could not open `127.0.0.1`. Headless Chrome on the VM did load the screen against example data and a stub player.

## Log (newest first)

- 2026-10-17 15:30 BST. Phase 4: VastDB row builders, widened `refuse()` allowlist, `scripts/secret_scan.sh` clean (`files_scanned=300`, `hits=0`), `SUBMISSION.md`, sanity table in this file. `pytest tests`: 182 passed. AG2-P4-2 live write not run (needs lab VM).
- 2026-10-17 13:35 BST. Phase 3 PR is #22. Agent cells ticked for the proposal route, the agreement line, and the VastDB writer. Freeze, labeller B, and arbitration stay open.
- 2026-10-17 12:40 BST. Re-ingested five parent chunks, `chunk_count` 1, custom prompt, metadata unchanged. Each still has segments 1 to 6. Dashboard `duplicate_segment_rows` is 0 and `segment_rows` is still 3537. The progress URL returned 404 before a `completed` status; caption text had changed by then. `c01`'s chunk (`20261001_061917_set02_video_chunk_0002.mp4`) was submitted twice because the first progress record disappeared while its captions were still the old text. The other four were submitted once. `testset_v1` was not frozen.
- 2026-10-17 12:20 BST. Phase 2-b probes and eight more set01 clips (`c27` to `c34`, test). `pytest tests/ag2`: 33 passed, 1 warning. Re-ingest not started. `testset_v1` not frozen. Hazards file not edited.
- 2026-10-17 11:39 BST. Phase 2 data and label screen. `pytest tests/ag2`: 33 passed, 1 warning (Starlette `httpx` inside FastAPI's TestClient). Headless Chrome: after the stub blind sit, the label view shows drag handles, the type and labeller selects, and the four buttons. Save sends `PUT api/hazards/c07_h1`. The other labeller outline, the dashed window, and the risk curve stay hidden until that labeller has saved. `testset_v1` was not frozen: every hazard has only riyu's window, so `agreed` is false. Dev clips `c02`, `c04`, and `c06` were watched and left without a window because a developing hazard was not clear. Nothing was pushed to `main`.
