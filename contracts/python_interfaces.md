# Cross-agent Python interfaces (contract)

Only these imports cross agent boundaries. Anything else is private to its owner. Until the real module is merged, the consumer uses a local stub inside its own files (for example `dh/api/_stubs.py` for AG3) that returns `contracts/examples/` data.

## `dh.score` (AG1). Stdlib only: the pod imports it.

```python
SCORER_VERSION: str          # "score_v1"
PATTERN_VERSION: str         # "PATTERN_V1"

def score_clip(clicks: list[float], hazards: list[dict], duration_s: float) -> dict:
    """clicks: clip-time seconds, any order. hazards: hazard.schema.json dicts for this clip.
    Returns {"clip_score": int, "pattern": {"flag": bool, "reasons": [str]},
             "hazard_points": {hazard_id: int},
             "hazards": [{"hazard_id", "window": [ws, we], "points", "first_click"}]}"""
```

## `dh.evals` (AG1)

```python
def start_run(agent: str, config: dict, testset_id: str, latency_mode: str) -> str:
    """Runs synchronously on the VM, writes data/runs/<run_id>/run.json + clips.jsonl, returns run_id."""
def build_leaderboard(testset_id: str) -> dict:
    """Writes and returns data/leaderboard.json in the shape of examples/leaderboard.json."""
```

## `dh.clients.vss` (AG2)

```python
class VSS:
    def __init__(self, base_url: str | None = None): ...   # $INGRESS_URL/api/v1, or in-cluster URL in the pod
    def search(self, query: str, filters: dict | None = None, top_k: int = 30) -> list[dict]: ...
    def stream(self, source: str, range_header: str | None = None) -> "requests.Response":  # stream=True
    def detections(self, source: str) -> dict: ...         # raw /videos/detections JSON
```

JWT from `POST /auth/login`, re-login on 401, never logged. Must import with only `requests` installed (the pod has no numpy).

## `dh.clips` (AG2)

```python
def load_clips() -> list[dict]          # data/clips.json
def load_hazards() -> list[dict]        # data/hazards.json
def load_testset(testset_id: str | None = None) -> dict   # latest frozen if None
def clip_meta(clip: dict) -> dict       # clip_meta.schema.json; never hazard fields
```

Stdlib only (the pod imports it).

## `dh.config` (AG1)

`DATA_DIR`, `MODE`, and the defaults in SPEC 19. Stdlib only. Read env lazily.

## Data paths

| Path | Owner (only writer) |
|---|---|
| `data/candidates.jsonl`, `data/clips.json`, `data/hazards.json`, `data/testset_v*.json` | AG2 |
| `data/det/`, `data/tracks/`, `data/grid/`, `data/proposals/`, `data/runs/`, `data/leaderboard.json`, `data/cache/explain/` | AG1 |
| `data/humans.jsonl`, `data/snapshot/` | AG3 |

`data/hazards.json` is written by the labels API (AG2 code) when anyone labels through the dev server. Commits of it go in AG2's PR only.
