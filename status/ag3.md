# AG3 status (fmdplt33)

Only AG3 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | In progress | ag3/phase-1 | | 2026-10-17 11:52 |
| 2 | Not started | ag3/phase-2 | | |
| 3 | Not started | ag3/phase-3 | | |
| 4 | Not started | ag3/phase-4 | | |

## Now

Doing: Phase 1 PR (past the 10:30 gate; started after the other Phase 1 merges).
Next: wait for the merge bot. Do not start Phase 2.
Blocked: nothing on the code. Laptop port-forward of the VM dev server was not confirmed from this session.

## Handoffs ready for others

- Dev server: `DH_MODE=dev` on `0.0.0.0:8000` (`make serve` with the project venv on `PATH`). Home screen is `#/`. This VM had no system `make` or pip; both were installed locally (`make` via apt, Python deps in `.venv`).
- `web/player.js` exports `mountPlayer(host, options)` for `web/label.js`. Options: `segments`, `resolveVideoUrl`, `controls`, `autoplay`, `playOnce`. Returned object: `getClipTime`, `currentTime`, `on("ended")`, `onEnded`, `play`, `pause`, `togglePlay`, `step`.
- `#/label/:clipId` calls `mountLabel` from `label.js`. Headless Chrome on the VM showed the blind-sit copy for `c07`.
- Deployed hello-world: open https://workshop.thecosmoslabs.com and click the App button. Cluster check `http://video-lab-team-36.cosmos.vastdata.com/app/health` returned `{"ok":true,"service":"developing-hazard"}`.
- Phase 1 `GET /video` is a stub. It returns the bytes `EXAMPLE` for sources listed in the example clips, and does not proxy VSS yet. Real playback is Phase 2.

## Needs from others

- AG1: `dh.evals.start_run` is not in the tree. `POST /api/runs` returns the example run id with `"stub": true`.
- AG2: real `data/clips.json` is not in the tree yet. Clip routes fall back to `contracts/examples/`.

## Go / no-go question 4

A segment does play from inside the pod via the in-cluster backend.

- VM DNS: `video-backend-service.team-36.svc.cluster.local` does not resolve on the VM.
- From the hello-world pod: `GET http://video-backend-service.team-36.svc.cluster.local:8000/health` returned 200. A `Range: bytes=0-1023` request to `/api/v1/videos/stream` returned 206, `content-type` `binary/octet-stream`, magic `ftyp` / `isom` (MP4).
- The same stream via the public ingress also returned 206 with the same magic.
- Port forwarding to a laptop browser was not confirmed here. The Cursor browser in this session could not open `127.0.0.1:8000` (chrome error page). On the VM, headless Chrome rendered the home screen: title, three cards, label link, clips 1, hazards 1, frozen at `-`, hash `-`. Health dots are red because Phase 1 does not probe VSS, Cosmos, or W&B.

## Log (newest first)

- 2026-10-17 11:52 BST. Phase 1 checks passed. `make test`: 67 passed. `pytest tests/ag3`: 15 passed. `make serve` on port 8011 returned the home HTML. `scripts/smoke.sh` against `127.0.0.1:8000` ok for `/health`, `/api/health`, `/api/clips`, `/api/leaderboard`. `deploy/deploy.sh` exited 0 after a retry on the ingress (first curl was 503 while endpoints caught up). Past the 10:30 due time.
- 2026-10-17 11:23 BST. Phase 1 started. AG1 and AG2 Phase 1 were already merged.
