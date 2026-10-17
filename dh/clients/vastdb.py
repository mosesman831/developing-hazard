"""VastDB client for schema ``developing_hazard`` (SPEC 7.13, 10.10).

Connects to the data VIP in ``S3_ENDPOINT``. The VSS index tables and the
media buckets are refused before any write. Credentials are never logged.
"""

from __future__ import annotations

import os
from typing import Any

SCHEMA_NAME = "developing_hazard"
TABLE_NAME = "hazards"
RUNS_TABLE = "runs"
HAZARD_SCORES_TABLE = "hazard_scores"
ALLOWED_TABLES = frozenset({TABLE_NAME, RUNS_TABLE, HAZARD_SCORES_TABLE})
PROTECTED_TABLES = frozenset({"vss-collection", "vss-prompts-events"})

HAZARD_FIELDS = (
    "hazard_id",
    "clip_id",
    "type",
    "window_start",
    "window_end",
    "segment_source",
    "original_video",
    "labeller_a",
    "labeller_b",
    "agreed",
    "testset_id",
)


class VastDBError(RuntimeError):
    """A VastDB call failed. The message does not include credentials."""


def _lookup(name: str) -> str | None:
    try:
        from dh.config import env
    except ImportError:
        env = None
    raw = env(name) if env is not None else os.environ.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _require(name: str) -> str:
    value = _lookup(name)
    if value is None:
        raise VastDBError(f"missing environment variable {name}")
    return value


def _endpoint(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return f"http://{url}"


def refuse(schema: str, table: str, bucket: str) -> None:
    """Raise before a write to an index table or a media bucket."""
    if table in PROTECTED_TABLES or schema in PROTECTED_TABLES:
        raise VastDBError("refusing to write a VSS index table")
    if schema != SCHEMA_NAME or table not in ALLOWED_TABLES:
        raise VastDBError("refusing to write outside developing_hazard allowlist")
    media = {_lookup("S3_CHUNKS_BUCKET"), _lookup("S3_SEGMENTS_BUCKET")}
    media.discard(None)
    if bucket in media:
        raise VastDBError("refusing to write a media bucket")
    own = _lookup("VASTDB_BUCKET")
    if own and bucket != own:
        raise VastDBError("refusing to write another team's bucket")


def hazard_arrow_schema():
    """PyArrow schema for the hazards table. Imported only when called."""
    import pyarrow as pa

    return pa.schema(
        [
            ("hazard_id", pa.utf8()),
            ("clip_id", pa.utf8()),
            ("type", pa.utf8()),
            ("window_start", pa.float64()),
            ("window_end", pa.float64()),
            ("segment_source", pa.utf8()),
            ("original_video", pa.utf8()),
            ("labeller_a", pa.utf8()),
            ("labeller_b", pa.utf8()),
            ("agreed", pa.bool_()),
            ("testset_id", pa.utf8()),
        ]
    )


RUN_FIELDS = (
    "run_id",
    "agent",
    "agent_config",
    "testset_id",
    "testset_sha256",
    "scorer_version",
    "pattern_version",
    "latency_mode",
    "git_sha",
    "score",
    "max",
    "pct",
    "hit_rate",
    "pattern_rate",
    "lift_vs_chance",
    "median_reaction_s",
    "mean_latency_s",
    "weave_url",
)

HAZARD_SCORE_FIELDS = (
    "run_id",
    "clip_id",
    "hazard_id",
    "points",
    "first_click_t",
    "window_start",
    "window_end",
    "latency_s",
    "segment_source",
)


def runs_arrow_schema():
    """PyArrow schema for the runs table. Imported only when called."""
    import pyarrow as pa

    return pa.schema(
        [
            ("run_id", pa.utf8()),
            ("agent", pa.utf8()),
            ("agent_config", pa.utf8()),
            ("testset_id", pa.utf8()),
            ("testset_sha256", pa.utf8()),
            ("scorer_version", pa.utf8()),
            ("pattern_version", pa.utf8()),
            ("latency_mode", pa.utf8()),
            ("git_sha", pa.utf8()),
            ("score", pa.int64()),
            ("max", pa.int64()),
            ("pct", pa.float64()),
            ("hit_rate", pa.float64()),
            ("pattern_rate", pa.float64()),
            ("lift_vs_chance", pa.float64()),
            ("median_reaction_s", pa.float64()),
            ("mean_latency_s", pa.float64()),
            ("weave_url", pa.utf8()),
        ]
    )


def hazard_scores_arrow_schema():
    """PyArrow schema for the hazard_scores table. Imported only when called."""
    import pyarrow as pa

    return pa.schema(
        [
            ("run_id", pa.utf8()),
            ("clip_id", pa.utf8()),
            ("hazard_id", pa.utf8()),
            ("points", pa.int64()),
            ("first_click_t", pa.float64()),
            ("window_start", pa.float64()),
            ("window_end", pa.float64()),
            ("latency_s", pa.float64()),
            ("segment_source", pa.utf8()),
        ]
    )


def connect():
    """Open a vastdb session on the data VIP. Does not print the keys."""
    import vastdb

    return vastdb.connect(
        endpoint=_endpoint(_require("S3_ENDPOINT")),
        access=_require("ACCESS_KEY"),
        secret=_require("SECRET_KEY"),
        ssl_verify=False,
    )


def _insert_table(
    table_name: str,
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    schema_fn,
) -> int:
    bucket = _require("VASTDB_BUCKET")
    refuse(SCHEMA_NAME, table_name, bucket)
    if not rows:
        return 0
    import pyarrow as pa
    import vastdb

    columns = schema_fn()
    payload = [{name: row.get(name) for name in fields} for row in rows]
    arrow = pa.Table.from_pylist(payload, schema=columns)
    session = vastdb.connect(
        endpoint=_endpoint(_require("S3_ENDPOINT")),
        access=_require("ACCESS_KEY"),
        secret=_require("SECRET_KEY"),
        ssl_verify=False,
    )
    with session.transaction() as tx:
        stored = tx.bucket(bucket)
        schema = stored.schema(SCHEMA_NAME, fail_if_missing=False)
        if schema is None:
            schema = stored.create_schema(SCHEMA_NAME, fail_if_exists=False)
        table = schema.table(table_name, fail_if_missing=False)
        if table is None:
            table = schema.create_table(table_name, columns=columns, fail_if_exists=False)
        table.insert(arrow)
    return len(payload)


def insert_hazard_rows(rows: list[dict[str, Any]]) -> int:
    """Create ``developing_hazard.hazards`` if needed and insert rows.

    Returns the number of rows inserted. An empty list inserts nothing.
    """
    return _insert_table(TABLE_NAME, rows, HAZARD_FIELDS, hazard_arrow_schema)


def insert_run_rows(rows: list[dict[str, Any]]) -> int:
    """Create ``developing_hazard.runs`` if needed and insert rows."""
    return _insert_table(RUNS_TABLE, rows, RUN_FIELDS, runs_arrow_schema)


def insert_hazard_score_rows(rows: list[dict[str, Any]]) -> int:
    """Create ``developing_hazard.hazard_scores`` if needed and insert rows."""
    return _insert_table(
        HAZARD_SCORES_TABLE,
        rows,
        HAZARD_SCORE_FIELDS,
        hazard_scores_arrow_schema,
    )
