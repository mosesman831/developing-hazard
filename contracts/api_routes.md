# API routes (contract)

From SPEC 11.1. All paths relative to the app root; the pod strips `/app`. Browser URLs must be relative (`api/clips`, not `/api/clips`). Response shapes: `score.schema.json`, `clip.schema.json`, `hazard.schema.json`, `examples/`.

| Method | Path | Module (owner) | Mode | Phase due |
|---|---|---|---|---|
| GET | `/health` | `dh/server.py` (AG3) | both | 1 |
| GET | `/api/health` -> `{ok, vss_ok, cosmos_ok, wandb_ok, testset_id, mode}` | `dh/api/health.py` (AG3) | both | 1 |
| GET | `/api/clips` | `dh/api/clips.py` (AG3) | both | 1 (examples), 2 (real) |
| GET | `/api/clips/{clip_id}` (`?blind=1` hides hazards) | `dh/api/clips.py` (AG3) | both | 1 |
| GET | `/video?source=` proxy to VSS `/api/v1/videos/stream`, Range passed, JWT server-side, only sources in clips.json | `dh/api/video.py` (AG3), uses `dh.clients.vss` (AG2) | both | 2 |
| GET | `/api/clips/{clip_id}/tracks` | `dh/api/clips.py` (AG3) reads `data/tracks/` | both | 2 |
| GET | `/api/clips/{clip_id}/proposal` (only after both labellers saved) | `dh/api/labels.py` (AG2) reads `data/proposals/` | dev | 3 |
| PUT | `/api/hazards/{hazard_id}` body `{labeller, ws, we, type, description}` | `dh/api/labels.py` (AG2) | dev | 2 |
| POST | `/api/hazards` | `dh/api/labels.py` (AG2) | dev | 2 |
| POST | `/api/clips/{clip_id}/status` body `{status: "no_hazard" or "rejected"}` | `dh/api/labels.py` (AG2) | dev | 2 |
| POST | `/api/testset/freeze` | `dh/api/labels.py` (AG2) | dev | 2 |
| POST | `/api/runs` `{agent, config, testset_id, latency_mode}` | `dh/api/runs.py` (AG3), calls `dh.evals.start_run` (AG1) | dev | 3 |
| GET | `/api/runs` | `dh/api/runs.py` (AG3) reads `data/runs/` | both | 2 |
| GET | `/api/runs/{run_id}` | `dh/api/runs.py` (AG3) | both | 2 |
| POST | `/api/human` `{name, role, blind, clip_id, clicks[]}` -> scored | `dh/api/human.py` (AG3), uses `dh.score.score_clip` (AG1) | both | 2 |
| GET | `/api/leaderboard` | `dh/api/leaderboard.py` (AG3) reads `data/leaderboard.json` (AG1) | both | 3 |
| POST | `/api/explain/{run_id}/{hazard_id}` | `dh/api/runs.py` (AG3) reads `data/cache/explain/` (AG1) | both | 4 |
| GET | `/api/runs/{run_id}/stream?clip=` SSE | `dh/api/runs.py` (AG3) | both | 4 (stretch) |

`dh/server.py` mounts the routers. It includes `dh.api.labels.router` only when `DH_MODE=dev`, inside `try/except ImportError`, so AG3 never waits on AG2's file existing.
