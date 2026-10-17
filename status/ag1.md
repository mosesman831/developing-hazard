# AG1 status (mosesman831)

Only AG1 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Merged | ag1/phase-1 | #6 | 2026-10-17 11:05 |
| 2 | Merged | ag1/phase-2 | #9 | 2026-10-17 11:47 |
| 3 | Merged | ag1/phase-3 | #20 | 2026-10-17 13:30 |
| 4 | In progress | ag1/phase-4-c | | 2026-10-17 14:59 |

## Now

Doing: final runs on frozen `testset_v2`.
Next: the PR for these runs.
Blocked: AG1-P4-2 stays unticked. There is still no agreed window, so the MAE in 14.5 (e) is not computed. `data/hazards.json` was not edited.

### Pod snapshot

`pod_budget_kb` in `dh/config.py` is 1024. `dh.snapshot.budget_bytes()` is 1024 times 1024, which is 1,048,576 bytes. `build_snapshot(Path('/tmp/dh-ag1-p4c-snap'))` printed 1040096. That is under the budget. `/tmp` output was not committed. `dh/snapshot.py` was not edited.

Track files still keep `t` and `xyxy` only. Tracks stay 5 fps, top 3. They were not thinned.

## Phase 4

`data/testset_v2.json` is frozen. sha256 `5cdfa089e6bbef8d341ca07e08c8756e5fed4b153d57d41c9580934bc7e9b308`. 17 clips, 18 hazards, max 90. `data/leaderboard.json` is rebuilt for `testset_v2`. Labels were not edited.

`c30` to `c33` had no `data/det/` file. Detections were loaded through the VSS client and written to `data/det/c30.jsonl`, `c31.jsonl`, `c32.jsonl`, and `c33.jsonl`. Those four clips have no `data/grid/cosmos_verify_v2/` file. On them the gate gets `is_hazard` false, and the async arm's first-rise clicks are not confirmed by a stored verdict.

Stored `risk_curve` values in the four new run files keep every 10th sample plus the last sample. The scores come from the full replay. The curves were shortened so `build_snapshot` stays under 1,048,576 bytes. It printed 1040096.

| Agent | Run | Score | pct | ci90 | lift vs chance | weave |
|---|---|---|---|---|---|---|
| `yolo_risk` | `r_yolo_risk_20261017T145932` | 15/90 | 0.16666666666666666 | 0.05263157894736842 to 0.3333333333333333 | 0.06947777777777941 | https://wandb.ai/vastdata/team-36/r/call/01a14a29-3145-755a-82cd-711097bbd319 |
| `yolo_cosmos_async` | `r_yolo_cosmos_async_20261017T145942` | 9/90 | 0.1 | 0.0 to 0.2235294117647059 | -0.03628888888888904 | https://wandb.ai/vastdata/team-36/r/call/01a14a29-5350-7fcb-8d69-c7cf9be3d6aa |
| `yolo_cosmos_gate` | `r_yolo_cosmos_gate_20261017T145939` | 0/90 | 0.0 | 0.0 to 0.0 | 0.0 | https://wandb.ai/vastdata/team-36/r/call/01a14a29-49ca-7a06-8677-aff25fbd0fcd |
| `yolo_naive` | `r_yolo_naive_20261017T145936` | 0/90 | 0.0 | 0.0 to 0.0 | 0.0 | https://wandb.ai/vastdata/team-36/r/call/01a14a29-4011-7431-aba4-28ba6c359b6f |

`yolo_risk` `pattern_rate` 0.0, `hit_rate` 0.16666666666666666, `median_reaction_s` 0.20000000000000018. Points: c07 5, c16 5, c31 5. `yolo_naive` `pattern_rate` 1.0 (every clip flagged). `yolo_cosmos_async` points: c07 5, c14 4. `latency_mode` is `zero`, so each run's `mean_latency_s` is 0.0.

The human row `fmd` 4/5, pct 0.8, is the existing sit on c01 in `data/humans.jsonl`. c01 is not in `testset_v2`. `data/humans.jsonl` was not edited.

`python -m dh.evals --split test` uses `testset_v2` only when that file is in the data directory. A fixture under `tests/ag1/fixtures/split_test/` proves the command and `build_leaderboard("testset_v2")` on a temp directory. The fixture sha256 is of those fixture files only. It is not a hash of the real test set.

### Sanity checks (dev)

AG2 must record these same numbers in `status/ag2.md`. AG1 did not edit that file. AG1-P4-2 is not ticked.

(a) Gaming check. Run `r_yolo_risk_20261017T122620` (`testset_id` `dev`). `run.json` totals: score 6, max 15, pct 0.4. Click counts in `clips.jsonl`, in clip order c01 to c06: 0, 1, 3, 1, 1, 1.

`dh.baselines.random_at_k`, seed 0, `random_draws_per_k` 200 from `dh/config.py`. Clips are the six dev clips in `data/clips.json` with windows from `data/hazards.json` (c02, c04, and c06 have no hazard).

| k | random@k pct |
|---|---|
| 1 | 0.07566666666666666 |
| 2 | 0.1589999999999998 |
| 4 | 0.22833333333333333 |
| 6 | 0.3310000000000002 |
| 8 | 0.4613333333333334 |

`random_at_k(3)` on the same clips is 0.1916666666666666. The run's own per-clip counts are not one k. `matched_chance` on those counts, seed 0, `random_draws_matched` 1000, is 0.07979999999999972. The run pct minus that figure is 0.3202000000000003, which is the `lift_vs_chance` stored on the run.

random@6 is under this run's pct. random@8 is over it. A random clicker with this run's own click counts does not come close to the run.

(b) `yolo_naive` dev run `r_yolo_naive_20261017T122551`. `run.json` totals `pattern_rate` is 0.8333333333333334. In that run's `clips.jsonl`, c01 is not flagged and the other five clips are.

(c) Verifier false alarms. Dev grid `data/grid/cosmos_verify_v2` for c01 to c06: 315 points, 0 errors. A point has no labelled hazard within 3 s when its `t` is more than 3 s outside every window on that clip in `data/hazards.json` (a clip with no window counts every point). 270 points are in that set. 4 of them have stored `is_hazard` true. The share is 4/270, which is 0.014814814814814815. That is not yes on everything. The gate is not useless. `data/hazards.json` was not edited.

(d) Blind humans, `data/humans.jsonl` read only. `fmd` session `h_92a39e35` is one sit on c01 with `clip_score` 4. The `smoke` row `h_74f0758e` is a test entry, not a human. `data/humans.jsonl` was not edited.

(e) Window proposal against a human-agreed window: blocked. All 21 hazards in `data/hazards.json` have only labeller `riyu`. None have two labellers, so there is no agreed window. MAE was not computed.

### Miss explanations

`dh/explain.py` writes `data/cache/explain/<run_id>/<hazard_id>.json` with `approved` false. Only Moses sets `approved` true. The text is the model reply. `llm_wb` and the I-24 test were not started.

One cache file: `data/cache/explain/r_yolo_risk_20261017T122620/c01_h1.json`. That hazard is the only 0 or 1 on the dev `yolo_risk` run. The call used the first id from `list_models`, `deepseek-ai/DeepSeek-V4-Flash-0731`. `approved` is true.

### Demo clip proposal

Moses approved 14:52. AG1-P4-4 is ticked.

Demo clip: c03. Every agent has a dev run that includes it.

- `r_yolo_risk_20261017T122620`: c03 clip score 3. Clicks at 0.8, 6.4, and 18.6. Hazard `c03_h1` points 3. The window in `data/hazards.json` is 5.0 s to 8.5 s.
- `r_yolo_naive_20261017T122551`: c03 has 50 clicks, the pattern flag is set, clip score 0.
- `r_yolo_cosmos_gate_20261017T122905` (`testset_id` `dev`): c03 has no clicks, clip score 0.
- `r_yolo_cosmos_async_20261017T122908`: c03 has 3 clicks, clip score 0.

Miss to show: c01 on those same four runs. Every one has clip score 0. On the `yolo_risk` run, `c01_h1` points are 0 and there are no clicks. The window is 20.0 s to 24.0 s. The cached explanation is approved.

Judge clip: c33. `data/clips.json` has split `test` and `seen_by` `riyu` only. `data/hazards.json` has two windows there, `c33_h1` and `c33_h2`. The four `testset_v2` runs include c33. Each of those clip scores is 0. There is no cosmos grid file for c33.

## Phase 3

Verdict grids, Cosmos agents, dev-only tuning, and `data/leaderboard.json`. Test clips were not used for tuning or for the leaderboard scores. `testset_v2` is not frozen. AG3 Phase 2 is not merged; this phase started because AG1 Phase 2 and AG2 Phase 2 are on `main` and the dev clips are there.

`COSMOS3_REASON_URL` is unset in the team config. The grid used the GPU skill's Cosmos port 8001 and model `nvidia/cosmos3-nano-reasoner`. Two calls in flight. Prompt `cosmos_verify_v2`.

### Grid

`data/grid/cosmos_verify_v2/` has one jsonl for each of the 26 clips (c01-c26). 1518 points, 0 errors, 23 HAZARD (1.5%), median latency 0.953 s. Dev false-alarm points (no labelled window within 3 s): 4 of 270 (1.5%). That is not "HAZARD to everything", and the median is under 3 s, so `vlm_wb` stays unbuilt.

c01 stored detections failed for all six segments (cache is empty). Its grid is the 10 dev checkpoint times, from streamed frames.

### Dev scores (not the test set)

Tuning grid on dev only (`theta_up` in {0.5, 0.6, 0.7}, EMA weight in {0.4, 0.7}). Best: `theta_up` 0.7, `ema_weight` 0.7. The published default 0.6 / 0.4 scored 0 on the same six dev clips. `yolo_cosmos_gate` `theta_trig` in {0.35, 0.45, 0.55} all scored 0 on dev, so the published 0.45 stays. No test clip was loaded.

| Agent | Score | pct | ci90 | lift vs chance | Notes |
|---|---|---|---|---|---|
| `yolo_risk` (tuned) | 6/15 | 0.40 | 0.00 to 0.60 | 0.32 | `pattern_rate` 0. Run `r_yolo_risk_20261017T122620` |
| `yolo_naive` | 0/15 | 0 | 0 to 0 | 0 | `pattern_rate` 0.83 |
| `yolo_cosmos_gate` | 0/15 | 0 | 0 to 0 | 0 | measured mean latency 0.94 s |
| `yolo_cosmos_async` | 0/15 | 0 | 0 to 0 | -0.13 | clicks outside the windows |

Latency sweep for the gate on dev (`zero`, `fixed:0.5`, `fixed:1`, `fixed:2`, `fixed:4`) stayed at score 0. Latency did not move the score; the verdicts did not land scoring clicks. Those runs use `testset_id` `dev-latency` so they do not replace the headline rows.

Label sensitivity for the tuned `yolo_risk` run: `riyu` pct 0.40. `fmd` has no windows, so that labeller was skipped.

### Weave

Project `vastdata/team-36`. Headline traces:

- `yolo_risk`: https://wandb.ai/vastdata/team-36/r/call/01a1499c-e4b1-765a-8306-26fbd6469e24
- `yolo_cosmos_gate`: https://wandb.ai/vastdata/team-36/r/call/01a1499f-733b-7758-af66-49f6c2042b1c
- `yolo_cosmos_async`: https://wandb.ai/vastdata/team-36/r/call/01a1499f-8129-7d6b-95d6-7b63cee224df
- `yolo_naive`: https://wandb.ai/vastdata/team-36/r/call/01a1499c-7947-7f59-9210-6433c2d3caba

## Handoffs

- `data/leaderboard.json` (`testset_id` `testset_v2`, max 90). Every agent row has `ci90`, `lift_vs_chance`, and a Weave link.
- `data/grid/cosmos_verify_v2/`, `data/tracks/`, `data/proposals/`, `data/det/`.
- `dh.evals.start_run` now runs `yolo_cosmos_gate` and `yolo_cosmos_async` and looks up the grid. `build_leaderboard` writes the file above.

## Checks

- `.venv/bin/python -m pytest -q tests/ag1`: 113 passed. `make` is still not installed, so `make test` was the pytest recipe.

## Log (newest first)

- 2026-10-17 14:59 BST: Final `testset_v2` runs and leaderboard. `c01_h1` explanation approved. Moses approved the demo clip at 14:52.
- 2026-10-17 14:12 BST: Phase 4 dev sanity checks, fixture path for `--split test`, and one miss explanation.
- 2026-10-17 12:45 BST: PR #20 opened. https://github.com/mosesman831/developing-hazard/pull/20
- 2026-10-17 12:42 BST: Phase 3 grids and dev leaderboard. Tuning did not touch test clips.
- 2026-10-17 11:47 BST: Phase 2 PR #9 opened.

## Phase 2

Shipped the MVP scorer path: full `PATTERN_V1` aggregates, replayer, detections cache, tracker, risk, `yolo_naive`, `yolo_risk`, baselines, and `start_run`. The verdict grid is an offline stub. Cosmos fill is Phase 3.

Assumption: a track is heading in only when `abs(vx)` is above `0.01 * frame width` px/s (19.2 px/s on a 1920-wide frame). Recorded in `dh/risk.py`. Not tuned.

### Run

`python -m dh.evals --agent yolo_risk --split dev` (the `make run` recipe; `make` is not installed).

- Clips: `contracts/examples/clips.json` clip `c07`, test set `testset_v0` (`sha256` `EXAMPLE`). AG2 has not merged real dev clips.
- Detections: none. No `data/det/c07.jsonl`, and the runner does not call the network.
- Run: `data/runs/r_yolo_risk_20261017T113337/`
- Result: 0 clicks, clip score 0, `lift_vs_chance` 0.0. `git_sha` in the file is `ff345e9` (main at the time of the run).

### Gaming check (SPEC 14.5)

`PATTERN_V1` is frozen at the published defaults. Rules were not changed. There are no blind human clicks to tune against.

Example clip `c07`, hazard `c07_h1`, window 16.2 s to 19.0 s, 200 draws, seed 0, real `score_clip`:

| Clicker | pct |
|---|---|
| `yolo_risk` on a synthetic person in the corridor from 16.2 s to 19.0 s (not written to `data/det/`) | 0.80 (one click at 17.0 s, 4 points) |
| `random@matched` at that same click count (k=1) | 0.082 |
| `random@1` | 0.082 |
| `random@2` | 0.124 |
| `random@4` | 0.185 |
| `random@6` | 0.284 |
| `random@8` | 0.355 |

Lift versus matched chance on that synthetic sit: 0.718. Random does not come close.

The committed run has no boxes, so both `yolo_risk` and matched chance score 0 there. That tie is an empty frame, not a pattern failure.

`yolo_naive` on a longer synthetic burst (person visible 15.6 s to 19.4 s) made 7 evenly spaced clicks and was zeroed by `P3_rhythm`.

Irregular human-like patterns on a 30 s clip are not flagged: 3 clicks `[10.0, 16.4, 22.0]`, 4 clicks `[8.0, 12.2, 16.5, 24.0]`, 5 clicks `[4.0, 9.5, 14.0, 16.6, 25.0]`, each scoring 5 on `c07_h1`. Five perfectly even clicks `[3, 6, 9, 12, 15]` flag `P3_rhythm` and score 0. Left as specified.

## Handoffs ready for others

- `dh.score.score_clip`, `SCORER_VERSION` `score_v1`, `PATTERN_VERSION` `PATTERN_V1`, plus `click_time` and `aggregate` (SPEC 9.4 and 9.5). Stdlib only.
- `dh.evals.start_run(agent, config, testset_id, latency_mode)` writes `data/runs/<run_id>/run.json` and `clips.jsonl`. `build_leaderboard` raises `NotImplementedError` until Phase 3.
- `dh.replay.sit_clip` and `dh.replay.replay` (generator, no look-ahead).
- Example run above. No `data/tracks/` file yet: there are no real detections to track.

## Needs from others

- AG2: real `data/clips.json`, `data/hazards.json`, and a detection sidecar (or `dh.clients.vss.detections` against a live ingress) before `yolo_risk` can be scored on footage rather than the example clip.
- AG3: a sit screen so the human blind sit (AG1-P2-8) can happen. It missed 11:00-11:15 BST.
- `make` is not installed on this machine. Recipes were run with `.venv/bin/python`.

## Checks

- `.venv/bin/python -m pytest -q tests`: 100 passed in 1.91s (AG1 and AG2).
- `.venv/bin/python -m dh.evals --agent yolo_risk --split dev`: wrote `r_yolo_risk_20261017T113337`.
- `make test` and `make run` could not be executed: `make` is not on PATH, and installing it needs a working `sudo` (this session's sudoers file is not usable).

## Go/no-go (still open from Phase 1)

Questions 2 and 3 were not measured. No team config file, and GPU, VSS, and W&B settings are unset. See the Phase 1 log below. Do not treat any number in the gaming table as a Cosmos or VSS measurement.

## Log (newest first)

- 2026-10-17 11:47 BST: PR #9 opened. https://github.com/mosesman831/developing-hazard/pull/9
- 2026-10-17 11:36 BST: Commit `d17f811` was local only until GitHub auth was available.
- 2026-10-17 11:34 BST: Phase 2 code complete, before the 12:30 due time. Blind sit missed. `PATTERN_V1` frozen.
- 2026-10-17 11:05 BST: Phase 1 PR #6 opened. https://github.com/mosesman831/developing-hazard/pull/6
- 2026-10-17 11:00 BST: Phase 1 code complete and late. Scorer implements SPEC 9.1-9.3. Probes blocked.
- 2026-10-17 10:37 BST: Started Phase 1 from `main` on `ag1/phase-1`.
