# AG1 status (mosesman831)

Only AG1 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Merged | ag1/phase-1 | #6 | 2026-10-17 11:05 |
| 2 | Committed, push blocked | ag1/phase-2 | | 2026-10-17 11:36 |
| 3 | Not started | ag1/phase-3 | | |
| 4 | Not started | ag1/phase-4 | | |

## Now

Doing: Phase 2 is committed on `ag1/phase-2` (`d17f811`). The pull request is not open.
Next: push `ag1/phase-2` and open the PR once GitHub credentials exist on this machine. Do not start Phase 3.
Blocked:
- Push. `git push` failed: no GitHub username, `gh` is not installed, and there is no SSH key. `sudo` cannot install packages (`/etc/sudoers` is not usable).
- Blind human sits (AG1-P2-8). The 11:00-11:15 BST window has passed and this session has no AG3 sit screen. No blind clicks exist, so `PATTERN_V1` was not retuned.

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

- 2026-10-17 11:36 BST: Commit `d17f811` is local only. Push blocked (no GitHub credentials).
- 2026-10-17 11:34 BST: Phase 2 code complete, before the 12:30 due time. Blind sit missed. `PATTERN_V1` frozen.
- 2026-10-17 11:05 BST: Phase 1 PR #6 opened. https://github.com/mosesman831/developing-hazard/pull/6
- 2026-10-17 11:00 BST: Phase 1 code complete and late. Scorer implements SPEC 9.1-9.3. Probes blocked.
- 2026-10-17 10:37 BST: Started Phase 1 from `main` on `ag1/phase-1`.
