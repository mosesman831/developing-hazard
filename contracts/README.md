# Contracts

The shared formats every agent builds against. Written before the day so all three agents can start Phase 1 in parallel against `examples/`.

## Rules

- Frozen at the end of Phase 1 (10:30). After that, any change is a PR labelled `contract-change`, touching only `contracts/` (plus the proposing agent's own status file), reviewed by the merge bot and Moses before anyone builds on it.
- No agent edits `contracts/` inside a normal phase PR. The merge bot rejects any phase PR that touches it.
- Adding an optional field is a contract change too. Removing or renaming a field after 12:30 is not allowed.
- Example data in `examples/` is placeholder. Never present its numbers.

## Files

| File | Shape | Written by | Read by |
|---|---|---|---|
| `candidate.schema.json` | `data/candidates.jsonl` rows (SPEC 10.1) | AG2 | AG2 |
| `clip.schema.json` | `data/clips.json` array (SPEC 10.2) | AG2 | AG1, AG3 |
| `clip_meta.schema.json` | what an agent is allowed to see (SPEC 7.9, App F) | AG1 | AG1 |
| `hazard.schema.json` | `data/hazards.json` array (SPEC 10.5) | AG2 | AG1, AG3 |
| `testset.schema.json` | `data/testset_vN.json` (SPEC 10.6) | AG2 | AG1, AG3 |
| `track.schema.json` | `data/det/<clip>.jsonl`, `data/tracks/<clip>.jsonl` (SPEC 10.3, 10.4) | AG1 | AG3 (overlays) |
| `click_event.schema.json` | clicks, calls, SSE events (SPEC 10.8, 11.3) | AG1 | AG3 |
| `score.schema.json` | ClipResult, Run, human score response (SPEC 10.7, 10.8, 11.2) | AG1 | AG3 |
| `human_session.schema.json` | `data/humans.jsonl` (SPEC 10.9) | AG3 | AG1 (human baseline) |
| `api_routes.md` | HTTP routes and which module serves each | AG2, AG3 | all |
| `python_interfaces.md` | function signatures that cross agent boundaries | all | all |

## Validating

`python -m jsonschema` is not a dependency. Each agent's tests load the schema with `json` and check required keys on its own outputs (a 20-line helper in its own `tests/agN/` folder; do not share a helper file).
