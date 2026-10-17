# CHECKLIST

Single source of truth for who does what and by when. Saturday 17 October 2026, all times BST.

How to tick: agent task rows have four status columns. Edit only your own rows and never untick anyone else's cell.

| Column | Who fills it | What it means |
|---|---|---|
| Agent | The agent that owns the row | `[x]` when the task is done, ticked on your phase branch |
| PR | The agent that owns the row | PR number, e.g. `#5`, added in a follow-up commit once the PR is open |
| Gate | Merge bot | `[x]` when the PR passes the merge bot's checks |
| Merged | Merge bot | `[x]` when the PR is merged to `main` |

`M-` rows are ticked by the merge bot (Merged column, PR column holds the merge bot's own checklist PR). Humans tick the timeline and `S-` rows in the Done column.

## Timeline

| Time | Milestone | Owner | Done |
|---|---|---|---|
| 08:30 | Arrive, photo ID, breakfast | All humans | [ ] |
| 09:00 | Keynotes | All humans | [ ] |
| 09:30 | Build starts, Phase 1 prompts pasted | All humans | [ ] |
| 10:00 | Near-miss mode decision if fewer than 8 usable hazards | mosesman831 | [ ] |
| 10:30 | Phase 1 PRs merged | Merge bot | [ ] |
| 11:00-11:15 | Blind human sits on dev clips | All humans | [ ] |
| 12:30 | Gaming check done, PATTERN_V1 frozen, testset_v1 frozen, Phase 2 PRs merged | AG1, AG2, Merge bot | [ ] |
| 12:30-13:00 | MVP deployed | AG3 | [ ] |
| 14:00 | testset_v2 frozen (no label changes after) | AG2 | [ ] |
| 14:05 | testset_v2 merged with sha256 | Merge bot | [ ] |
| 15:15 | Final runs and leaderboard handed to AG3 for snapshot | AG1 | [ ] |
| 15:30 | Code freeze, Phase 4 PRs merged, secret scan clean | All, Merge bot | [ ] |
| 15:30-16:00 | Demo video recorded, opens logged out | All humans | [ ] |
| 16:00-16:20 | Repo access for reviewers, SUBMISSION.md pasted | mosesman831 | [ ] |
| 16:30 | Submitted at tokensand.com/vastlondon, demos | All humans | [ ] |

## Phase 1 (due 10:30)

| ID | Task | Owner | Due | Agent | PR | Gate | Merged |
|---|---|---|---|---|---|---|---|
| AG1-P1-1 | `dh/config.py`: every default in SPEC 19 plus the env vars in 18.5 that you use. Stdlib only. Read env... | AG1 (mosesman831) | 10:30 | [x] | #6 | [x] | [x] |
| AG1-P1-2 | `dh/models.py`: pydantic models for Candidate, Clip, ClipMeta, Det, Track, Hazard, TestSet, Run, ClipResult,... | AG1 (mosesman831) | 10:30 | [x] | #6 | [x] | [x] |
| AG1-P1-3 | `dh/score.py` skeleton with the exact signature from `contracts/python_interfaces.md`, constants set, stdlib... | AG1 (mosesman831) | 10:30 | [x] | #6 | [x] | [x] |
| AG1-P1-4 | Clients `dh/clients/cosmos.py`, `yolo.py`, `wandb_llm.py` (SPEC 11.4): timeouts, 2 retries with jitter,... | AG1 (mosesman831) | 10:30 | [x] | #6 | [x] | [x] |
| AG1-P1-5 | Go/no-go probes (SPEC 20 row 09:30, 20.1 questions 2 and 3): stored detections on 2 PIE segments (fps, are... | AG1 (mosesman831) | 10:30 | [ ] | #6 | [ ] | [ ] |
| AG1-P1-6 | `prompts/cosmos_verify_v2.txt`, `llm_decide_v1.txt`, `explain_miss_v1.txt`, `vlm_verify_v1.txt` copied from... | AG1 (mosesman831) | 10:30 | [x] | #6 | [x] | [x] |
| AG1-P1-7 | `mk/ag1.mk`: targets `detect`, `grid`, `propose`, `run`, `eval` (stubs that print "not yet" are fine). | AG1 (mosesman831) | 10:30 | [x] | #6 | [x] | [x] |
| AG1-P1-PR | Phase 1 acceptance checks pass, status/ag1.md updated, PR open | AG1 (mosesman831) | 10:30 | [ ] | #6 | [ ] | [ ] |
| AG2-P1-1 | `dh/clients/vss.py` (SPEC 11.4): login, `search`, `stream`, `detections`, re-login on 401, timeouts 30 s /... | AG2 (Riyu-D1) | 10:30 | [ ] | #4 | [x] | [x] |
| AG2-P1-2 | `dh/clips.py`: loaders from `contracts/python_interfaces.md`, stdlib only, plus the 30 s chunk clip... | AG2 (Riyu-D1) | 10:30 | [ ] | #4 | [x] | [x] |
| AG2-P1-3 | Go/no-go probes (SPEC 20 row 09:30, 20.1 questions 1 and 4 with AG3): run the 10 queries from 7.1; open the... | AG2 (Riyu-D1) | 10:30 | [ ] | #4 | [x] | [x] |
| AG2-P1-4 | `dh/api/labels.py` skeleton: `router = APIRouter()` with the routes in `contracts/api_routes.md` owned by... | AG2 (Riyu-D1) | 10:30 | [ ] | #4 | [x] | [x] |
| AG2-P1-5 | `web/label.js` v0: `export function mountLabel(el, clipId, api)` rendering the blind sit then timeline... | AG2 (Riyu-D1) | 10:30 | [ ] | #4 | [x] | [x] |
| AG2-P1-6 | `mk/ag2.mk`: `mine`, `build`, `freeze`. | AG2 (Riyu-D1) | 10:30 | [ ] | #4 | [x] | [x] |
| AG2-P1-PR | Phase 1 acceptance checks pass, status/ag2.md updated, PR open | AG2 (Riyu-D1) | 10:30 | [ ] | #4 | [x] | [x] |
| AG3-P1-1 | Hello-world deploy to `/app` with `/deploy-app-no-registry` (SPEC 6.4, 20 row 09:30, risk 14). Install... | AG3 (fmdplt33) | 10:30 | [x] | #11 | [x] | [x] |
| AG3-P1-2 | `dh/server.py`: FastAPI, `DH_MODE` dev or demo, listens on `0.0.0.0:$PORT` (pod) or `DH_PORT` (VM),... | AG3 (fmdplt33) | 10:30 | [x] | #11 | [x] | [x] |
| AG3-P1-3 | `dh/api/_stubs.py`: serves `contracts/examples/` when real modules or data are missing (scorer stub returns... | AG3 (fmdplt33) | 10:30 | [x] | #11 | [x] | [x] |
| AG3-P1-4 | `web/index.html`, `app.js` (hash routes, relative URLs), `style.css` (16.1 colours, IBM Plex, no spinners),... | AG3 (fmdplt33) | 10:30 | [x] | #11 | [x] | [x] |
| AG3-P1-5 | Go/no-go question 4 (20.1): does a segment play through the pod's proxy? Try the in-cluster URL... | AG3 (fmdplt33) | 10:30 | [x] | #11 | [x] | [x] |
| AG3-P1-6 | `requirements-pod.txt` (fastapi, uvicorn, requests only), `deploy/k8s.yaml`, `deploy/deploy.sh` (ConfigMap,... | AG3 (fmdplt33) | 10:30 | [x] | #11 | [x] | [x] |
| AG3-P1-PR | Phase 1 acceptance checks pass, status/ag3.md updated, PR open | AG3 (fmdplt33) | 10:30 | [x] | #11 | [ ] | [ ] |
| M-P1 | All three Phase 1 PRs reviewed, tested and merged | Merge bot | 10:30 | - |  | - | [x] |

## Phase 2 (due 12:30)

| ID | Task | Owner | Due | Agent | PR | Gate | Merged |
|---|---|---|---|---|---|---|---|
| AG1-P2-1 | `dh/score.py` complete: SPEC 9.1-9.5, integer ms, `PATTERN_V1` (9.3). `tests/ag1/test_score.py` and... | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-2 | `dh/replay.py` (7.9) as a generator, simulated clock, blocking vs non-blocking calls.... | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-3 | `dh/dets.py` (7.4) reading via `dh.clients.vss.detections` (AG2), caching to `data/det/<clip_id>.jsonl`, YOLO... | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-4 | `dh/track.py` (7.5, App C), `dh/risk.py` (7.6), writing `data/tracks/<clip_id>.jsonl` (top 3 tracks per frame... | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-5 | `dh/agents/base.py`, `yolo_naive.py`, `yolo_risk.py` (7.10.1, 7.10.2, 12.1, 12.2, 12.4).... | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-6 | `dh/baselines.py`: `random@k` and `random@matched` (7.10.7, App E). `tests/ag1/test_baselines.py`. | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-7 | `dh/evals.py` minimal: `start_run` writes `data/runs/<run_id>/run.json` and `clips.jsonl` per... | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-8 | 11:00-11:15: your human does blind sits through AG3's sit screen or the label screen. | AG1 (mosesman831) | 12:30 | [ ] | #9 | [ ] | [ ] |
| AG1-P2-9 | Gaming check before 12:30 (SPEC 14.5, risk 11): random clickers on the dev clips with the real scorer. Random... | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-10 | Start the verdict grid (`dh/grid.py`, 12.3) in the background if time allows. | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG1-P2-PR | Phase 2 acceptance checks pass, status/ag1.md updated, PR open | AG1 (mosesman831) | 12:30 | [x] | #9 | [x] | [x] |
| AG2-P2-1 | `dh/mine.py` (7.1): search plus scrubbing sets 2-6; 20+ candidate chunks (moving ego, onset >= 5 s) into... | AG2 (Riyu-D1) | 12:30 | [x] | #8 | [x] | [x] |
| AG2-P2-2 | `make build`: `data/clips.json` with dev/test split (aim 6 dev, 14+ test), joined local clips (`data/clips/`,... | AG2 (Riyu-D1) | 12:30 | [x] | #8 | [x] | [x] |
| AG2-P2-3 | `dh/frames.py` (7.3) at 5 fps into `data/frames/` (gitignored), for AG1's Cosmos inputs. | AG2 (Riyu-D1) | 12:30 | [x] | #8 | [x] | [x] |
| AG2-P2-4 | Label routes for real: PUT/POST hazards, clip status, testset freeze. Only the API writes... | AG2 (Riyu-D1) | 12:30 | [x] | #8 | [x] | [x] |
| AG2-P2-5 | `web/label.js` full: blind sit first, then window drag handles, type, description, labeller select (riyu,... | AG2 (Riyu-D1) | 12:30 | [x] | #8 | [x] | [x] |
| AG2-P2-6 | Labelling (13): label as labeller A, dev clips first. Track blindness in `Clip.seen_by`. | AG2 (Riyu-D1) | 12:30 | [x] | #8 | [x] | [x] |
| AG2-P2-7 | Apply arbitration; freeze `testset_v1` (MVP set) by 12:30 via `POST /api/testset/freeze`. | AG2 (Riyu-D1) | 12:30 | [ ] | #8 | [ ] | [ ] |
| AG2-P2-PR | Phase 2 acceptance checks pass, status/ag2.md updated, PR open | AG2 (Riyu-D1) | 12:30 | [ ] | #8 | [ ] | [ ] |
| AG3-P2-1 | `dh/api/video.py`: proxy to `/api/v1/videos/stream` via `dh.clients.vss` (AG2), Range passed through, JWT... | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-2 | `dh/api/clips.py` real: list, detail (`?blind=1` hides hazards), tracks from `data/tracks/` (AG1). | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-3 | Sit screen (16.5, `web/sit.js`): Start disabled until segments are blob URLs, Space or click registers,... | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-4 | `dh/api/human.py`: `POST /api/human` scored with `dh.score.score_clip` (AG1), sessions in memory, one `HUMAN... | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-5 | Watch screen v0 (16.6, `web/watch.js`) from run files: boxes, windows, clicks, score. | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-6 | `dh/api/runs.py`: `GET /api/runs`, `GET /api/runs/{run_id}`. | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-7 | `dh/snapshot.py` (`make snapshot`): copy what the pod needs into `data/snapshot/`, fail over 900 KB (6.4,... | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-8 | Deploy the MVP (12:30-13:00). | AG3 (fmdplt33) | 12:30 | [x] | #15 | [x] | [x] |
| AG3-P2-PR | Phase 2 acceptance checks pass, status/ag3.md updated, PR open | AG3 (fmdplt33) | 12:30 | [x] | #15 | [ ] | [ ] |
| M-P2 | All three Phase 2 PRs reviewed, tested and merged | Merge bot | 12:30 | - |  | - | [ ] |

## Phase 3 (due 14:00)

| ID | Task | Owner | Due | Agent | PR | Gate | Merged |
|---|---|---|---|---|---|---|---|
| AG1-P3-1 | Verdict grid finished for every dev and candidate test clip (`data/grid/cosmos_verify_v2/<clip>.jsonl`), 2 in... | AG1 (mosesman831) | 14:00 | [x] | #20 | [x] | [x] |
| AG1-P3-2 | `dh/agents/yolo_cosmos.py`: `yolo_cosmos_gate` then `yolo_cosmos_async` (7.10.3, 7.10.4, 12.3). Latency sweep. | AG1 (mosesman831) | 14:00 | [x] | #20 | [x] | [x] |
| AG1-P3-3 | `vlm_wb` (7.10.5) only if Cosmos is slow or says HAZARD to everything (risk 6). | AG1 (mosesman831) | 14:00 | [x] | #20 | [x] | [x] |
| AG1-P3-4 | `dh/evals.py`: Weave EvaluationLogger (section 15), bootstrap, paired difference, matched chance (App E),... | AG1 (mosesman831) | 14:00 | [x] | #20 | [x] | [x] |
| AG1-P3-5 | `dh/windows.py` (7.7, App D) writing `data/proposals/<clip_id>.json`. AG2's labels API reveals it only after... | AG1 (mosesman831) | 14:00 | [x] | #20 | [x] | [x] |
| AG1-P3-6 | Threshold tuning on dev only (12.6). Nothing tuned on test. | AG1 (mosesman831) | 14:00 | [x] | #20 | [x] | [x] |
| AG1-P3-PR | Phase 3 acceptance checks pass, status/ag1.md updated, PR open | AG1 (mosesman831) | 14:00 | [x] | #20 | [x] | [x] |
| AG2-P3-1 | Mine more; get blind sits from Moses and fmd; label 8-10 more (13.7, 13.8 mix). | AG2 (Riyu-D1) | 14:00 | [ ] |  | [ ] | [ ] |
| AG2-P3-2 | `GET /api/clips/{clip_id}/proposal` serving AG1's `data/proposals/` after both labellers saved. | AG2 (Riyu-D1) | 14:00 | [x] | #22 | [x] | [x] |
| AG2-P3-3 | Agreement stats (13.5) into your status file. | AG2 (Riyu-D1) | 14:00 | [x] | #22 | [x] | [x] |
| AG2-P3-4 | Freeze `testset_v2` at 14:00 (10.6): commit file and hash. After this, no label or window changes. | AG2 (Riyu-D1) | 14:00 | [x] |  | [ ] | [ ] |
| AG2-P3-5 | `dh/store.py` and `dh/clients/vastdb.py` (7.13, 10.10): schema `developing_hazard`, table `hazards`. Never... | AG2 (Riyu-D1) | 14:00 | [x] | #22 | [x] | [x] |
| AG2-P3-6 | `dh/clients/embed.py` "more like this" (7.1 should) only if mining is short. | AG2 (Riyu-D1) | 14:00 | [ ] |  | [ ] | [ ] |
| AG2-P3-PR | Phase 3 acceptance checks pass, status/ag2.md updated, PR open | AG2 (Riyu-D1) | 14:00 | [ ] |  | [ ] | [ ] |
| AG3-P3-1 | Judge mode in the pod: name, role, "seen before?", side-by-side agent clicks after the clip. | AG3 (fmdplt33) | 14:00 | [x] | #17 | [x] | [x] |
| AG3-P3-2 | `dh/api/leaderboard.py` serving AG1's `data/leaderboard.json`; leaderboard screen (16.7) with interval bars,... | AG3 (fmdplt33) | 14:00 | [x] | #17 | [x] | [x] |
| AG3-P3-3 | `POST /api/runs` (dev) calling `dh.evals.start_run` (AG1). | AG3 (fmdplt33) | 14:00 | [x] | #17 | [x] | [x] |
| AG3-P3-4 | Watch screen: agent tabs, event feed, risk meter, "Open in Weave" links, labelled "recorded run, replayed". | AG3 (fmdplt33) | 14:00 | [x] | #17 | [x] | [x] |
| AG3-P3-5 | Redeploy after each merge to `main` that changes data. | AG3 (fmdplt33) | 14:00 | [x] | #17 | [x] | [x] |
| AG3-P3-PR | Phase 3 acceptance checks pass, status/ag3.md updated, PR open | AG3 (fmdplt33) | 14:00 | [x] | #17 | [x] | [x] |
| M-P3 | All three Phase 3 PRs reviewed, tested and merged | Merge bot | 14:00 | - |  | - | [ ] |

## Phase 4 (due 15:30)

| ID | Task | Owner | Due | Agent | PR | Gate | Merged |
|---|---|---|---|---|---|---|---|
| AG1-P4-1 | After AG2 freezes `testset_v2` at 14:00: final runs of every agent on test via EvaluationLogger; rebuild... | AG1 (mosesman831) | 15:30 | [ ] | #30 | [ ] | [ ] |
| AG1-P4-2 | Sanity checks in 14.5 with AG2. | AG1 (mosesman831) | 15:30 | [ ] | #30 | [ ] | [ ] |
| AG1-P4-3 | Stretch, in order, only if time: miss explanations via W&B LLM (`dh/explain.py`, 7.12, cached in... | AG1 (mosesman831) | 15:30 | [x] | #30 | [x] | [x] |
| AG1-P4-4 | Pick the demo clip and the miss for the demo (24.3). | AG1 (mosesman831) | 15:30 | [ ] | #30 | [ ] | [ ] |
| AG1-P4-5 | Numbers final by 15:30. No code after 15:30. | AG1 (mosesman831) | 15:30 | [ ] | #30 | [ ] | [ ] |
| AG1-P4-PR | Phase 4 acceptance checks pass, status/ag1.md updated, PR open | AG1 (mosesman831) | 15:30 | [ ] | #30 | [ ] | [ ] |
| AG2-P4-1 | Sanity checks (14.5) with AG1's numbers; write results in your status file. | AG2 (Riyu-D1) | 15:30 | [ ] | #29 | [ ] | [ ] |
| AG2-P4-2 | Write `runs` and `hazard_scores` tables to VastDB from AG1's run files (10.10), keyed by segment `source`. | AG2 (Riyu-D1) | 15:30 | [ ] | #29 | [ ] | [ ] |
| AG2-P4-3 | `scripts/secret_scan.sh` over the full history; result in the PR body. Decide repo access for reviewers with... | AG2 (Riyu-D1) | 15:30 | [x] | #29 | [x] | [x] |
| AG2-P4-4 | `SUBMISSION.md`: one-liner, 150-word description, stack, honest limitations line (25). | AG2 (Riyu-D1) | 15:30 | [x] | #29 | [x] | [x] |
| AG2-P4-PR | Phase 4 acceptance checks pass, status/ag2.md updated, PR open | AG2 (Riyu-D1) | 15:30 | [x] | #29 | [x] | [x] |
| AG3-P4-1 | Final snapshot from AG1's final runs (by 15:15) and final deploy. | AG3 (fmdplt33) | 15:30 | [ ] | #32 | [ ] | [ ] |
| AG3-P4-2 | Polish dark UI for the projector (1920x1080, score numbers >= 48 px). | AG3 (fmdplt33) | 15:30 | [x] | #32 | [x] | [x] |
| AG3-P4-3 | Stretch only if time: miss panel (16.8) via `POST /api/explain/...` serving precomputed explanations; SSE... | AG3 (fmdplt33) | 15:30 | [x] | #32 | [x] | [x] |
| AG3-P4-4 | `scripts/smoke.sh` on the deployed URL; every link opens logged out. | AG3 (fmdplt33) | 15:30 | [ ] | #32 | [ ] | [ ] |
| AG3-P4-5 | No code after 15:30. | AG3 (fmdplt33) | 15:30 | [x] | #32 | [ ] | [ ] |
| AG3-P4-PR | Phase 4 acceptance checks pass, status/ag3.md updated, PR open | AG3 (fmdplt33) | 15:30 | [ ] | #32 | [ ] | [ ] |
| M-P4 | All three Phase 4 PRs reviewed, tested and merged | Merge bot | 15:30 | - |  | - | [ ] |

## Submission (due 16:30)

| ID | Task | Owner | Done |
|---|---|---|---|
| S-1 | GitHub repo reviewers can access (secret scan first; SPEC files and NOTES-opus.md go public too) | mosesman831 | [ ] |
| S-2 | Demo video with shareable link | All humans | [ ] |
| S-3 | What we built and tools used (from SUBMISSION.md) | Riyu-D1 | [ ] |
| S-4 | Team names and contact emails | mosesman831 | [ ] |
| S-5 | Working website link (workshop portal App) | fmdplt33 | [ ] |
| S-6 | Screenshots: sit result, watch screen with Cosmos, leaderboard, miss explained | fmdplt33 | [ ] |
| S-7 | Weave project link, shareable | mosesman831 | [ ] |
