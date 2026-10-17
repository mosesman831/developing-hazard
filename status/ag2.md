# AG2 status (Riyu-D1)

Only AG2 edits this file, inside its own PR.

| Phase | Status | Branch | PR | Updated (BST) |
|---|---|---|---|---|
| 1 | Both halves on branch | ag2/phase-1 | opening | 2026-10-17 10:54 |
| 2 | Not started | ag2/phase-2 | | |
| 3 | Not started | ag2/phase-3 | | |
| 4 | Not started | ag2/phase-4 | | |

## Now

Doing: Both Phase 1 halves are on `ag2/phase-1`. `web/label.js` and `mk/ag2.mk` came in from `origin/ag2/phase-1-ui` (`c357783`).
Next: Go/no-go probes wait on VSS credentials.
Blocked: probes were not run (see Log).

## Handoffs ready for others

- `dh.clients.vss.VSS`: `login`, `search`, `stream`, `detections`. Re-login on HTTP 401. Timeouts 30 s, and 120 s for video. `requests` only.
- `dh.clips`: `load_clips`, `load_hazards`, `load_testset`, `clip_meta`, and `define_chunk_clip` (six segments at 0, 5, 10, 15, 20, 25 s; onset under 5 s prepends the previous chunk).
- `dh.api.labels.router`: PUT `/api/hazards/{hazard_id}`, POST `/api/hazards`, POST `/api/clips/{clip_id}/status`, POST `/api/testset/freeze`, GET `/api/clips/{clip_id}/proposal`. Files come from `DH_DATA_DIR` (default `data`).
- `web/label.js`: `export function mountLabel(el, clipId, api)`.
- `mk/ag2.mk`: `mine`, `build`, `freeze` stubs.

## Needs from others

- AG3 for go/no-go question 4 (a segment playing through the pod proxy).
- `INGRESS_URL`, `USERNAME` and `PASSWORD` in the environment, or the single `/config/*.config`, before the 10 queries or a chunk count can be run.

## Log (newest first)

- 2026-10-17 10:54 BST. Merged `origin/ag2/phase-1-ui` (`c357783`) into `ag2/phase-1`. That commit adds `web/label.js` and `mk/ag2.mk`. Both files are now on this branch. Python, tests, and this status file were kept. After the merge, `python -m pytest -q tests/ag2` (via `/tmp/ag2-dev/bin/python`, `PYTHONPATH=/workspace`) reported `18 passed, 1 warning`. The warning is Starlette's `httpx` deprecation inside FastAPI's TestClient. Probes remain not run.
- 2026-10-17 10:52 BST. Probes were not run. `INGRESS_URL`, `USERNAME` and `PASSWORD` are unset, and `/config` has no team config file. No chunk count and no hazard count were taken, so near-miss mode (SPEC 20.2) is not flagged. Go/no-go question 1 is unanswered. Question 4 was not run: it needs AG3's pod proxy as well as credentials. The VSS UI was not opened and set01 was not scrubbed.
- Acceptance, both exit 0. System Python has no `requests`, so the import used a virtualenv with only `requests` installed, and pytest used a second virtualenv with `requests`, `fastapi`, `httpx` and `pytest`. `PYTHONPATH=/workspace`.
  - `/tmp/ag2-requests/bin/python -c "import dh.clients.vss, dh.clips"` (no output, exit 0). A separate check imported `dh.clips` before `requests` was loaded.
  - `/tmp/ag2-dev/bin/python -m pytest -q tests/ag2`: `18 passed, 1 warning`. The warning is Starlette's `httpx` deprecation inside FastAPI's TestClient. Loaders read `contracts/examples/`. PUT `/api/hazards/c07_h1` and POST `/api/hazards` round-trip through a FastAPI TestClient that mounts only `dh.api.labels.router`, against a temp copy of the examples. The copy under `contracts/examples/` is unchanged.
- `weave.op` is not applied. SPEC.md says every client is wrapped in it, and also says the pod does not install weave. Wrapping the client would risk tracing `self`, which holds the password and the JWT. Phase 1 requires this module to import with only `requests`. Flagged here rather than imported.
- Not edited: `CHECKLIST.md`, `CONTEXT.md`, `SPEC*.md`, `contracts/`, `Makefile`, `pyproject.toml`.
- Implementation commit `c754e3c8031c8a8c413565255cf76d86dc99f7dd`. UI commit `c3577834d15e32f474989b70679cf3c167485ce9`. Nothing was pushed to `main`. The phase branch was not merged into `main`.
