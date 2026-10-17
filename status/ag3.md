# AG3 status (fmdplt33)

Only AG3 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Merged | ag3/phase-1 | #11 | 2026-10-17 11:59 |
| 2 | PR open | ag3/phase-2 | #15 | 2026-10-17 12:14 |
| 3 | Not started | ag3/phase-3 | | |
| 4 | Not started | ag3/phase-4 | | |

## Now

Doing: waiting on the merge bot for #15.
Next: wait for the merge bot. Do not start Phase 3.
Blocked: nothing on the code. `data/tracks/` is not on main, so the watch screen has no boxes for the recorded run. Laptop port-forward was not confirmed.

## Handoffs ready for others

- Dev server: `DH_MODE=dev` on `0.0.0.0:8000`. Home lists the 26 clips. Sit is `#/sit/:clipId`. Watch is `#/watch/:runId/:clipId`.
- `GET /video` proxies VSS with the JWT on the server and Range passed through. A Range request returned 206 and an MP4 `ftyp` header, on the VM and on `/app`.
- Blind sit `POST /api/human` for `fmd` on `c01` at 21.0s scored 4. Sessions are in `data/humans.jsonl`.
- Snapshot is 204835 bytes, under the 900 KB budget. Deployed app: https://workshop.thecosmoslabs.com App button. `/app/api/clips` returned 26 clips.
- `web/player.js` exports `mountPlayer` and `getActiveVideo` for the label, sit, and watch screens.
- `#/label/:clipId` still calls `mountLabel` from `label.js`.

## Needs from others

- AG1: `data/tracks/` is empty, so overlays have nothing to draw. The recorded run `r_yolo_risk_20261017T113337` is on `c07` with score 0 and no clicks. That is what the watch screen shows.
- AG2: clips and hazards are on main and are what the app lists.

## Go / no-go question 4

A segment does play from inside the pod via the in-cluster backend.

- VM DNS: `video-backend-service.team-36.svc.cluster.local` does not resolve on the VM.
- From the hello-world pod: `GET http://video-backend-service.team-36.svc.cluster.local:8000/health` returned 200. A `Range: bytes=0-1023` request to `/api/v1/videos/stream` returned 206, `content-type` `binary/octet-stream`, magic `ftyp` / `isom` (MP4).
- The same stream via the public ingress also returned 206 with the same magic.
- Port forwarding to a laptop browser was not confirmed here. The Cursor browser in this session could not open `127.0.0.1:8000` (chrome error page). On the VM, headless Chrome rendered the home screen: title, three cards, label link, clips 1, hazards 1, frozen at `-`, hash `-`. Health dots are red because Phase 1 does not probe VSS, Cosmos, or W&B.

## Log (newest first)

- 2026-10-17 12:14 BST. PR #15 open: https://github.com/mosesman831/developing-hazard/pull/15
- 2026-10-17 12:12 BST. Phase 2 checks: `pytest tests/ag3` 18 passed, full suite 133 passed before the health fallback tweak. `make snapshot` 204835 bytes. Dev smoke and `/app` smoke passed, including video 206. Blind sit on `c01` at 21.0s scored 4. Headless Chrome showed the 26-clip list, sit reached "segments ready", and the watch screen showed score 0, risk 0.00, no clicks, and a window band for the recorded run.
- 2026-10-17 11:57 BST. PR #11 open: https://github.com/mosesman831/developing-hazard/pull/11
- 2026-10-17 11:52 BST. Phase 1 checks passed. `make test`: 67 passed. `pytest tests/ag3`: 15 passed. `make serve` on port 8011 returned the home HTML. `scripts/smoke.sh` against `127.0.0.1:8000` ok for `/health`, `/api/health`, `/api/clips`, `/api/leaderboard`. `deploy/deploy.sh` exited 0 after a retry on the ingress (first curl was 503 while endpoints caught up). Past the 10:30 due time.
- 2026-10-17 11:23 BST. Phase 1 started. AG1 and AG2 Phase 1 were already merged.
