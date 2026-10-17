# AG1 status (mosesman831)

Only AG1 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | PR open | ag1/phase-1 | | 2026-10-17 11:00 |
| 2 | Not started | ag1/phase-2 | | |
| 3 | Not started | ag1/phase-3 | | |
| 4 | Not started | ag1/phase-4 | | |

## Now

Doing: Phase 1 PR (late: due 10:30, opened after 11:00 BST)
Next: wait for the merge bot. Do not start Phase 2.
Blocked: go/no-go questions 2 and 3 were not measured. This laptop has no team config file (`/config/*.config` or `DH_CONFIG`) and the GPU, VSS, and W&B settings are unset. `dh.clients.vss` is not merged yet (AG2).

## Handoffs ready for others

- `dh.score.score_clip(clicks, hazards, duration_s)` returns `clip_score`, `pattern`, `hazard_points`, `hazards`. `SCORER_VERSION` is `score_v1`. `PATTERN_VERSION` is `PATTERN_V1`. Stdlib only.
- `dh.config` exposes SPEC 19 defaults lazily, plus `DATA_DIR` and `MODE`. `USERNAME` and `PASSWORD` prefer the team config file over the OS environment.

## Needs from others

- AG2: `dh.clients.vss.detections` and two PIE segment ids, so question 2 (fps, pedestrians boxed) can be measured.
- A team config on the machine that runs the probe (`DH_CONFIG` or `/config/<team>.config`) with `COSMOS3_REASON_URL`, `GPU_BEARER_TOKEN`, `YOLO_URL`, `WANDB_API_KEY`, `WANDB_TEAM`, `WANDB_PROJECT`, `INGRESS_URL`, `USERNAME`, `PASSWORD`. Do not commit that file.

## Go/no-go (SPEC 20.1 questions 2 and 3)

Probe: `py -3.14 tests/ag1/probe_gonogo.py` on this laptop. No numbers were invented.

Question 2. Do per-frame boxes exist for PIE segments, with pedestrians boxed in most frames?

- Not measured. `dh.clients.vss` does not import (AG2 has not merged it). `INGRESS_URL` and `PASSWORD` are unset. There is no team config file, so the Windows `USERNAME` was not treated as the team user.
- fps: not measured
- pedestrians boxed: not measured

Question 3. Is the median Cosmos verify call under about 3 s? Model id? Does the endpoint accept `video_frames`?

- Not measured. `COSMOS3_REASON_URL` and `GPU_BEARER_TOKEN` are unset.
- median_s: not measured
- model_id: not measured
- video_frames_accepted: not measured

W&B inference: not run (`WANDB_API_KEY` unset). `weave.init`: not called (`WANDB_TEAM`, `WANDB_PROJECT`, or `WANDB_API_KEY` unset). `weave` is not installed in the Python 3.14 interpreter used here; the clients fall back to a no-op decorator so import still works.

## Checks

- `py -3.14 -m pytest -q tests` : 34 passed in 0.26s (`tests/ag1` only; no other agent tests exist yet).
- `py -3.14 -c "import dh.config, dh.models, dh.score"` : ok (`score_v1`, `PATTERN_V1`).
- `make` is not on PATH on this laptop, so `make test` could not be run. The Makefile recipe is `python -m pytest -q tests`, which is the command above.
- `make detect`, `grid`, `propose`, `run`, `eval` are stubbed in `mk/ag1.mk` and print `not yet`. Not executed here because `make` is missing.

## Log (newest first)

- 2026-10-17 11:00 BST: Phase 1 code complete and late. Scorer implements SPEC 9.1-9.3 (points and `PATTERN_V1`), not only the points skeleton. Pattern tests from SPEC 9.7 are in `tests/ag1/test_score.py`. Probes blocked as above.
- 2026-10-17 10:37 BST: Started Phase 1 from `main` on `ag1/phase-1`, after the 10:30 due time.
