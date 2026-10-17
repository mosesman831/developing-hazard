"""VastDB client for schema ``developing_hazard`` (SPEC 7.13, 10.10).

Connects to the data VIP in ``S3_ENDPOINT``. The VSS index tables and the
media buckets are refused before any write. Credentials are never logged.
"""

from __future__ import annotations

import os
from typing import Any

SCHEMA_NAME = "developing_hazard"
TABLE_NAME = "hazards"
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
    if schema != SCHEMA_NAME or table != TABLE_NAME:
        raise VastDBError("refusing to write outside developing_hazard.hazards")
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


def connect():
    """Open a vastdb session on the data VIP. Does not print the keys."""
    import vastdb

    return vastdb.connect(
        endpoint=_endpoint(_require("S3_ENDPOINT")),
        access=_require("ACCESS_KEY"),
        secret=_require("SECRET_KEY"),
        ssl_verify=False,
    )


def insert_hazard_rows(rows: list[dict[str, Any]]) -> int:
    """Create ``developing_hazard.hazards`` if needed and insert rows.

    Returns the number of rows inserted. An empty list inserts nothing.
    """
    bucket = _require("VASTDB_BUCKET")
    refuse(SCHEMA_NAME, TABLE_NAME, bucket)
    if not rows:
        return 0
    import pyarrow as pa
    import vastdb

    columns = hazard_arrow_schema()
    payload = []
    for row in rows:
        payload.append({name: row.get(name) for name in HAZARD_FIELDS})
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
        table = schema.table(TABLE_NAME, fail_if_missing=False)
        if table is None:
            table = schema.create_table(TABLE_NAME, columns=columns, fail_if_exists=False)
        table.insert(arrow)
    return len(payload)
