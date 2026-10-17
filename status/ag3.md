# AG3 status (fmdplt33)

Only AG3 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Merged | ag3/phase-1 | #11 | 2026-10-17 11:59 |
| 2 | Merged | ag3/phase-2 | #15 | 2026-10-17 12:15 |
| 3 | Merged | ag3/phase-3 | #17 | 2026-10-17 12:27 |
| 4 | In progress | ag3/phase-4-c | | 2026-10-17 15:30 |

## Now

Doing: Phase 4-c redeploy and smoke on `ag3/phase-4-c`.
Next: AG3-P4-4 stays open. `scripts/smoke.sh` exits 1 because `POST /api/explain/<first run>/c03_h1` is 404.
Blocked: AG3-P4-1 and AG3-P4-4 are not ticked. Deploy succeeded. Smoke did not.

## Phase 4-c

Branch `ag3/phase-4-c` from `main` at `34fa7b8`. The snapshot on main was not replaced and was not committed. `deploy/deploy.sh` still runs `python -m dh.snapshot` before it packs the ConfigMap. That rewrite was 1,039,803 bytes and matched the committed tree (no file added, removed, or changed).

### 1. Leaderboard file

`data/snapshot/data/leaderboard.json` has 4 rows, all `kind: agent`, and no human row: `yolo_risk`, `yolo_cosmos_async`, `yolo_cosmos_gate`, `yolo_naive`.

### 2. Deploy

`bash deploy/deploy.sh` on the CoreWeave lab VM. Rollout finished. Health:

```
{"ok":true}
```

App: http://video-lab-team-36.cosmos.vastdata.com/app

### 3. Smoke

`DH_BASE=http://video-lab-team-36.cosmos.vastdata.com/app bash scripts/smoke.sh` exited 1. Full output:

```
ok http://video-lab-team-36.cosmos.vastdata.com/app/health
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/health
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/clips
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/runs
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/leaderboard
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/clips/c01
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/clips/c01?blind=1
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/clips/c01/tracks
ok http://video-lab-team-36.cosmos.vastdata.com/app/video 206
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/runs/r_yolo_cosmos_async_20261017T122908
ok http://video-lab-team-36.cosmos.vastdata.com/app/api/runs/r_yolo_cosmos_async_20261017T122908/stream?clip=c01
error: explain returned 404
```

The 404 body is `{"detail":"explanation not approved"}`. The first run is `r_yolo_cosmos_async_20261017T122908`. The only approved explanation in the snapshot is `r_yolo_risk_20261017T122620/c01_h1.json`.

### 4. NVIDIA

Live replay of clip `c03` with `yolo_cosmos_async`. Detections from `data/det/c03.jsonl` (150 frames). The agent made 3 non-blocking verify calls and 3 clicks (0.8s, 13.8s, 18.0s). The first call was sent to Cosmos (`nvidia/cosmos3-nano-reasoner`) with 5 JPEG frames from c03 segment 1. The endpoint returned `choices`. Latency **1.550 s**. Parsed act `no`, object `pedestrian in black dress`, `is_hazard` false. The later two calls used the stored grid so the replay could finish.

Weave trace for that live `verify_frames` call: https://wandb.ai/vastdata/team-36/r/call/01a14a41-994a-7969-b56e-dbd1591cf213

### 5. VAST

`dh.clients.vastdb.connect()` reached the data VIP. Schemas in the team bucket: `vss-schema` only. `developing_hazard` is absent, so there is no `clips` table and no `runs` table to count.

The reads the deployed app actually uses:

| Read | Result |
|---|---|
| `GET /app/api/clips` | 34 clip rows |
| `GET /app/api/runs` | 18 run rows |
| `GET /app/api/leaderboard` | 4 agent rows, no human row |
| c03 segment 1 via the VSS stream (`dh.clients.vss`) | HTTP 200, 7,234,034 bytes |
| `GET /app/video` range in smoke | 206 |

### 6. W&B

c03 is in run `r_yolo_cosmos_async_20261017T122908`. Its `weave_url` is https://wandb.ai/vastdata/team-36/r/call/01a1499f-8129-7d6b-95d6-7b63cee224df

The Weave API returned that call. Op name ends in `Evaluation.evaluate`. A logged-out browser open of the same URL redirected to the team-36 Weave workspace and showed "404 Page not found" (login or privacy). The API still has the trace.

### 7. Deployed page

Headless Chrome on the VM, 1920x1080, ignoring the lab TLS error, at `https://video-lab-team-36.cosmos.vastdata.com/app/` (the slash matters: `/app` without it requests `/app.js` and gets 404). The Cursor browser could not open the host.

Leaderboard: four agent rows (`yolo_risk` 15/90, `yolo_cosmos_async` 9/90, `yolo_cosmos_gate` 0/90, `yolo_naive` 0/90). No human row on the board. Per-clip table still shows fmd on c01. DVSA reference line is on the page.

c03 replay: `#/watch/r_yolo_cosmos_async_20261017T122908/c03`. Title "Watch c03", label "Recorded run, replayed.", async tab, video frame with boxes, clicks at 0.80s, 13.80s and 18.00s, "Open in Weave" on the cosmos lines.

Miss panel: `c03_h1: 0 points.` then `Not approved for display.`

## Phase 4

Interim snapshot from this branch, after #20 merged: `python -m dh.snapshot` wrote **930,673 bytes** (budget 1,048,576). Not a final snapshot. `data/humans.jsonl` no longer has the smoke test row. The remaining sit is fmd on c01, clip_score 4. `GET /api/leaderboard` drops a row named smoke, including the smoke human still stored in `data/leaderboard.json` until AG1 rebuilds that file.

Projector check at 1920x1080, headless Chrome against `http://127.0.0.1:8765` (the Cursor browser could not open the VM address). Home, leaderboard, and watch rendered. No page JavaScript errors. Score class is 64px IBM Plex Mono. Leaderboard shows interval bars, the dashed line at 58.7% titled "DVSA car pass rate (44/75), for reference only", and a separate per-clip human table (fmd, c01, 4). Watch `r_yolo_risk_20261017T122620` / c01 shows the miss panel for `c01_h1` (0 points) and "Not approved for display." `#/label/c01` still loads the label module.

`POST /api/explain/{run_id}/{hazard_id}` returns 404 unless `data/cache/explain/<run_id>/<hazard_id>.json` has `"approved": true`. The snapshot copies only those approved files. `GET /api/runs/{run_id}/stream` emits `risk`, `click`, `cosmos_call`, and `score` from the recorded clip, and does not invent fields. Ingress annotations: `proxy-buffering: "off"` and `proxy-read-timeout: "3600"`.

`python -m pytest -q tests` after rebase onto main: 176 passed. Snapshot rebuilt: 930,673 bytes.

Deploy command for the lab VM, after this branch is on main: `bash deploy/deploy.sh`. Then `DH_BASE=http://video-lab-team-36.cosmos.vastdata.com/app bash scripts/smoke.sh`.

## Handoffs ready for others

- Dev server: `DH_MODE=dev` on `0.0.0.0:8000`. Sit is `#/sit/:clipId` (name, role judge/guest/team, seen-before). After the clip, the score sits next to each recorded agent's clicks.
- Leaderboard is `#/leaderboard`: interval bars, lift, the dashed 58.7% line labelled "DVSA car pass rate (44/75), for reference only", latency toggle, per-clip humans, full-set line when someone has sat every test clip.
- Watch is `#/watch/:runId/:clipId` with agent tabs (naive, risk, gate, async, vlm), event feed, vertical risk meter, and "Recorded run, replayed."
- `POST /api/runs` in dev calls `dh.evals.start_run`. Demo mode still returns 404. `dh.evals` is not on main yet, so a missing import returns the example run id and `stub: true`.
- Snapshot is 234197 bytes, under the 900 KB budget. Judges open https://workshop.thecosmoslabs.com and click App.
- `POST /api/human` for a recorded clip includes that clip's agent scores. On `c07` the recorded `yolo_risk` score is 0.

## Needs from others

- AG1: `data/leaderboard.json` for a real board. Runs for naive, gate, async, and vlm, plus any `weave_url`, so those tabs and the Weave links light up. `data/tracks/` for boxes.
- AG2: nothing new. Clips and hazards on main are what the app lists.

## Go / no-go question 4

A segment does play from inside the pod via the in-cluster backend.

- VM DNS: `video-backend-service.team-36.svc.cluster.local` does not resolve on the VM.
- From the hello-world pod: `GET http://video-backend-service.team-36.svc.cluster.local:8000/health` returned 200. A `Range: bytes=0-1023` request to `/api/v1/videos/stream` returned 206, `content-type` `binary/octet-stream`, magic `ftyp` / `isom` (MP4).
- The same stream via the public ingress also returned 206 with the same magic.
- Port forwarding to a laptop browser was not confirmed here. The Cursor browser in this session could not open `127.0.0.1:8000` (chrome error page). On the VM, headless Chrome rendered the leaderboard, the watch screen for `c07`, and the sit form for `c01` once all 6 segments were ready.

## Log (newest first)

- 2026-10-17 15:30 BST. Phase 4-c on `ag3/phase-4-c`. Deployed main's snapshot. Smoke failed on explain 404, so AG3-P4-1 and AG3-P4-4 stay unticked. Live Cosmos call on c03 returned in 1.550 s. VastDB has no `developing_hazard` schema. Weave call `01a1499f-8129-7d6b-95d6-7b63cee224df` exists. Deployed leaderboard, c03 replay, and miss panel render at `/app/`.
- 2026-10-17 14:05 BST. PR #27 open: https://github.com/mosesman831/developing-hazard/pull/27
- 2026-10-17 14:04 BST. Redeployed after #20 merged. `pytest tests`: 176 passed. `make snapshot`: 927524 bytes, over 900 KB. Judge sit on the deployed app, clip `c07`, at http://video-lab-team-36.cosmos.vastdata.com/app/#/sit/c07. Name `fmd`, role judge, seen-before checked (blind false). Six segments ready. After the clip the screen showed score 0, no pattern flag, `c07_h1` window 20.5-24, points 0, first click none. Side by side: You 0, `yolo_risk` 0. No other agent run includes `c07`. Pod log `h_7225d45b`, clicks `[]`, `clip_score` 0, created 2026-10-17T13:03:55Z. Leaderboard `#/leaderboard` on the same deploy: `yolo_risk` 6/15 40.0% lift 0.32; `yolo_cosmos_async` 0/15 lift -0.13 mean latency 0.95 s; `yolo_cosmos_gate` 0/15 mean latency 0.94 s; `yolo_naive` 0/15 pattern rate 0.83; `fmd` 4/15 80.0%; `smoke` 0/15. Per clip: `c01` smoke 0, best agent `yolo_cosmos_async` 0; `c01` fmd 4, best agent `yolo_cosmos_async` 0. No hazard-type breakdown. Judges open https://workshop.thecosmoslabs.com and click App.
- 2026-10-17 12:27 BST. Phase 3 merged: https://github.com/mosesman831/developing-hazard/pull/17
- 2026-10-17 12:25 BST. PR #17 open: https://github.com/mosesman831/developing-hazard/pull/17. GitHub created the PR at 12:25:52 BST. The status line was previously stamped 12:30, which was after the commit that added it (12:26:04 BST).
- 2026-10-17 12:25 BST. Redeployed after the Phase 2 merge. `deploy/deploy.sh` rolled out and `/app/health` returned `{"ok":true}`. Deployed smoke passed, including video 206 and demo `POST /api/runs` 404. The pod board has no `data/leaderboard.json`, so it shows no agent rows and does not show the example scores. Per-clip sits for smoke and fmd are there. Headless Chrome on `/app` showed the sit form with 6 segments ready. This line was previously stamped 12:28 in the commit at 12:25:43 BST.
- 2026-10-17 12:25 BST. Phase 3 checks: `make test` 137 passed, `pytest tests/ag3` 22 passed. `make snapshot` 234197 bytes. Dev `scripts/smoke.sh` passed, including video 206. Headless Chrome: leaderboard shows the example banner, the reference line, and the per-clip sits; watch shows score 0, risk 0.00, the five agent tabs, and no Weave URL; sit shows name, role, seen-before, and "6 segments ready."
- 2026-10-17 12:15 BST. Phase 2 merged: https://github.com/mosesman831/developing-hazard/pull/15
- 2026-10-17 12:14 BST. PR #15 open: https://github.com/mosesman831/developing-hazard/pull/15
- 2026-10-17 12:12 BST. Phase 2 checks: `pytest tests/ag3` 18 passed, full suite 133 passed before the health fallback tweak. `make snapshot` 204835 bytes. Dev smoke and `/app` smoke passed, including video 206. Blind sit on `c01` at 21.0s scored 4. Headless Chrome showed the 26-clip list, sit reached "segments ready", and the watch screen showed score 0, risk 0.00, no clicks, and a window band for the recorded run.
- 2026-10-17 11:57 BST. PR #11 open: https://github.com/mosesman831/developing-hazard/pull/11
- 2026-10-17 11:52 BST. Phase 1 checks passed. `make test`: 67 passed. `pytest tests/ag3`: 15 passed. `make serve` on port 8011 returned the home HTML. `scripts/smoke.sh` against `127.0.0.1:8000` ok for `/health`, `/api/health`, `/api/clips`, `/api/leaderboard`. `deploy/deploy.sh` exited 0 after a retry on the ingress (first curl was 503 while endpoints caught up). Past the 10:30 due time.
- 2026-10-17 11:23 BST. Phase 1 started. AG1 and AG2 Phase 1 were already merged.
