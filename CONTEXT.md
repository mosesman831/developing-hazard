# CONTEXT - shared coordination for the three build agents

Read this first, every phase. It says who owns what, what each agent may not touch, and where status lives.

## The design, and why it cannot conflict

- **One agent per human, one GitHub name each.** AG1 = `mosesman831`, AG2 = `Riyu-D1`, AG3 = `fmdplt33`. Each agent works only for its human and only on its own paths.
- **Every path has exactly one owner.** The ownership map below is exhaustive. If a file is not listed for you, you do not edit it.
- **Status is not kept in this file.** Each agent writes only `status/agN.md` (its own file). This file (CONTEXT.md) is edited only by Moses or the merge bot, never inside an agent's phase PR. Three agents editing one shared table would conflict on every PR; three separate files never do.
- **Shared formats live in `contracts/`** and were written before the day, so all three can start Phase 1 against `contracts/examples/` without waiting for each other.
- **Cross-agent code goes through the interfaces in `contracts/python_interfaces.md` only.** If you need something another agent has not merged yet, stub it inside your own files.
- **The Makefile and package markers are shared and frozen.** Your make targets go in your own `mk/agN.mk`. Your tests go in your own `tests/agN/`.

## Branch and PR rules (all agents)

1. Branch from latest `main`, named `agN/phase-X` (for example `ag2/phase-3`). A second PR in the same phase: `agN/phase-X-b`.
2. **Only open a PR into `main`. NEVER push to `main`. NEVER merge any PR, your own or anyone else's.** The Hackathon PR merge bot checks and merges.
3. Only edit paths you own. The merge bot rejects a PR that touches any other path.
4. Update `status/agN.md` inside the same PR.
5. PR title: `[AGN] Phase X: <summary>`. PR body: what was done, acceptance checks run with output, handoffs, anything blocked.
6. Stop at the end of the phase and wait. Moses starts the next phase for all three agents at once.
7. Contract changes: a separate PR labelled `contract-change`, touching only `contracts/` and your status file. Do not build on it until merged.
8. Never commit secrets, tokens, `.env`, media (`*.mp4`, frames) or anything under `data/clips/`, `data/frames/`, `data/cache/` except `data/cache/explain/` (AG1).

## Ownership map

### Shared and frozen (no agent edits; Moses or a `contract-change` PR only)

`README.md`, `SPEC.md`, `SUMMARY.md`, `NOTES-opus.md`, `CONTEXT.md`, `SPEC-mosesman831.md`, `SPEC-riyud1.md`, `SPEC-fmdplt.md`, `contracts/**`, `Makefile`, `pyproject.toml`, `.gitignore`, `dh/__init__.py`, `dh/clients/__init__.py`, `dh/agents/__init__.py`, `dh/api/__init__.py`, `status/merge.md` (merge bot only).

### Shared, row-owned: `CHECKLIST.md`

Every agent may edit `CHECKLIST.md`, but only its own rows (IDs starting `AG1-`, `AG2-`, `AG3-`) and only to tick `[ ]` to `[x]`. The merge bot ticks `M-` rows; humans tick timeline and `S-` rows. If two PRs conflict only in `CHECKLIST.md`, the merge bot resolves it by keeping every `[x]`.

If you need a new dependency in `pyproject.toml`, say so in your PR body and status file; Moses adds it.

### AG1 - `mosesman831` - agent and scorer

| Owns | Notes |
|---|---|
| `dh/config.py`, `dh/models.py` | config defaults (SPEC 19), pydantic models mirroring `contracts/` |
| `dh/clients/yolo.py`, `dh/clients/cosmos.py`, `dh/clients/wandb_llm.py` | GPU and W&B clients |
| `dh/dets.py`, `dh/track.py`, `dh/risk.py`, `dh/windows.py`, `dh/grid.py`, `dh/replay.py` | detection to risk pipeline, proposer, verdict grid, replayer |
| `dh/score.py`, `dh/baselines.py` | DVSA scorer (stdlib only), random clickers |
| `dh/agents/*.py` except `__init__.py` | `base`, `yolo_naive`, `yolo_risk`, `yolo_cosmos`, `llm_wb` |
| `dh/evals.py`, `dh/explain.py` | Weave EvaluationLogger, bootstrap, matched chance, miss explanations |
| `prompts/**` | versioned prompts |
| `mk/ag1.mk`, `tests/ag1/**` | |
| `data/det/**`, `data/tracks/**`, `data/grid/**`, `data/proposals/**`, `data/runs/**`, `data/leaderboard.json`, `data/cache/explain/**` | outputs |
| `status/ag1.md` | |

**AG1 CAN'T:** edit `dh/mine.py`, `dh/clips.py`, `dh/frames.py`, `dh/store.py`, `dh/clients/vss.py`, `dh/clients/vastdb.py`, `dh/clients/embed.py`, `dh/api/**`, `dh/server.py`, `dh/snapshot.py`, `web/**`, `deploy/**`, `scripts/**`, `requirements-pod.txt`, any AG2 or AG3 `data/` path (including `data/hazards.json` and test sets), any shared file, `main`. Must not read `data/hazards.json` from inside `dh/agents/` (SPEC App F).

### AG2 - `Riyu-D1` - clips and labels

| Owns | Notes |
|---|---|
| `dh/clients/vss.py`, `dh/clients/vastdb.py`, `dh/clients/embed.py` | VSS (search, stream, detections), VastDB, Cosmos Embed |
| `dh/mine.py`, `dh/clips.py`, `dh/frames.py`, `dh/store.py` | discovery, 30 s chunk clips, frames, VastDB persistence |
| `dh/api/labels.py` | label, proposal, clip status and test-set freeze routes (dev mode) |
| `web/label.js` | blind-sit-then-label screen |
| `scripts/secret_scan.sh` | |
| `mk/ag2.mk`, `tests/ag2/**` | |
| `data/candidates.jsonl`, `data/clips.json`, `data/hazards.json`, `data/testset_v*.json` | |
| `SUBMISSION.md` | submission text draft |
| `status/ag2.md` | |

**AG2 CAN'T:** edit any AG1 path (scorer, agents, risk, `dh/config.py`, `dh/models.py`, prompts, runs), `dh/server.py`, `dh/api/*.py` other than `labels.py`, `web/*` other than `label.js` (including `index.html`, `app.js`, `player.js`, `style.css`), `deploy/**`, `scripts/smoke.sh`, any shared file, `main`. Never re-ingest without telling Moses; never write to the chunks or segments buckets.

### AG3 - `fmdplt33` - app and deploy

| Owns | Notes |
|---|---|
| `dh/server.py` | FastAPI app, mounts routers, dev and demo modes |
| `dh/api/health.py`, `dh/api/clips.py`, `dh/api/video.py`, `dh/api/runs.py`, `dh/api/human.py`, `dh/api/leaderboard.py`, `dh/api/_stubs.py` | data-serving routes |
| `dh/snapshot.py` | pod snapshot builder and budget check |
| `web/**` except `web/label.js` | `index.html`, `app.js`, `player.js`, `sit.js`, `watch.js`, `leaderboard.js`, `style.css`, `fonts/` |
| `deploy/**`, `requirements-pod.txt`, `.env.example` | |
| `scripts/smoke.sh` | |
| `mk/ag3.mk`, `tests/ag3/**` | |
| `data/humans.jsonl`, `data/snapshot/**` | |
| `status/ag3.md` | |

**AG3 CAN'T:** edit any AG1 path (in particular `dh/score.py`: import it, never copy or change it), any AG2 path (`dh/api/labels.py`, `web/label.js`, `dh/clients/vss.py`, `dh/clips.py`, `data/hazards.json`, test sets), any shared file, `main`.

`web/index.html` (AG3) must load `label.js` with a `<script type="module" src="label.js">` tag from Phase 1, and `app.js` routes `#/label/:clipId` to the function `label.js` exports (`export function mountLabel(el, clipId, api)`), so AG2 never needs to touch AG3 files.

## Phases (Saturday 17 October, BST)

| Phase | Window | Goal | Gate |
|---|---|---|---|
| 1 | 09:30-10:30 | Scaffolding, go/no-go probes, stubs against `contracts/examples/` | Go/no-go at 10:00; contracts frozen at 10:30 |
| 2 | 10:30-12:30 | Core MVP: real clips and labels, scorer, YOLO agents, app shows scored runs | Gaming check before 12:30; MVP deployed |
| 3 | 12:30-14:00 | Integration, Cosmos grid and agents, Weave, leaderboard, judge mode | Test set frozen 14:00 |
| 4 | 14:00-15:30 | Final eval runs, polish, stretch, final deploy | Code freeze 15:30 |

15:30-16:30 is humans only: demo video, submission, rehearsal.

## Status

| Agent | Human | Status file | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|---|---|
| AG1 | mosesman831 | [status/ag1.md](status/ag1.md) | see file | see file | see file | see file |
| AG2 | Riyu-D1 | [status/ag2.md](status/ag2.md) | see file | see file | see file | see file |
| AG3 | fmdplt33 | [status/ag3.md](status/ag3.md) | see file | see file | see file | see file |
| Merge bot | - | [status/merge.md](status/merge.md) | | | | |

Status values: `Not started`, `In progress`, `PR open`, `Merged`, `Blocked`.

## Log

Each agent logs in its own status file, newest first. The merge bot logs merges and rejections in `status/merge.md`. Nothing is logged here.
