"""VastDB writer for schema developing_hazard, table hazards (SPEC 7.13, 10.10).

Connects only to the data VIP in S3_ENDPOINT, with ACCESS_KEY, SECRET_KEY and
VASTDB_BUCKET. Those values are read from the environment when a call runs.
They are never printed or logged, and they are not stored in this file.
vastdb and pyarrow are imported only inside the write, so importing this module
works when those packages are missing.
"""

from __future__ import annotations

import os

SCHEMA_NAME = "developing_hazard"
TABLE_NAME = "hazards"

ROW_COLUMNS = (
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

_PROTECTED = frozenset({"vss-collection", "vss-prompts-events"})
PROTECTED_TABLES = _PROTECTED
HAZARD_FIELDS = ROW_COLUMNS


class VastDBError(RuntimeError):
    """A VastDB call failed. The message does not include credentials."""


_REQUIRED_TEXT = ("hazard_id", "clip_id", "type")
_OPTIONAL_TEXT = (
    "segment_source",
    "original_video",
    "labeller_a",
    "labeller_b",
    "testset_id",
)


def _optional_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _require_env(name: str) -> str:
    value = _optional_env(name)
    if value is None:
        raise VastDBError(f"missing environment variable {name}")
    return value


def _is_protected(name: str) -> bool:
    return name.strip().casefold() in _PROTECTED


def _normalise_endpoint(endpoint: str) -> str:
    """Data VIP. A bare host is treated as http, matching the write skill."""
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return f"http://{endpoint}"


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def assert_safe_target(schema: str, table: str, bucket: str) -> None:
    """Raise if a write would touch the index, the prompts table, or a media bucket.

    This runs before any database import or connection.
    """
    schema_name = schema.strip()
    table_name = table.strip()
    bucket_name = bucket.strip()
    if _is_protected(schema_name) or _is_protected(table_name):
        refused = schema_name if _is_protected(schema_name) else table_name
        raise VastDBError(f"refusing to write a VSS index table {refused}")
    if schema_name != SCHEMA_NAME:
        raise VastDBError("schema name must be developing_hazard")
    if table_name != TABLE_NAME:
        raise VastDBError("table name must be hazards")
    own = _optional_env("VASTDB_BUCKET")
    if own is not None and bucket_name != own:
        raise VastDBError("refusing to write another team's bucket")
    chunks = _optional_env("S3_CHUNKS_BUCKET")
    segments = _optional_env("S3_SEGMENTS_BUCKET")
    if chunks is not None and bucket_name == chunks:
        raise VastDBError("refusing bucket that matches S3_CHUNKS_BUCKET")
    if segments is not None and bucket_name == segments:
        raise VastDBError("refusing bucket that matches S3_SEGMENTS_BUCKET")


def _as_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def project_row(row: dict) -> dict:
    """Keep the named hazard columns and drop anything else, including vectors."""
    if not isinstance(row, dict):
        raise ValueError("each row must be an object")
    missing = [name for name in ROW_COLUMNS if name not in row]
    if missing:
        raise ValueError("row is missing columns: " + ", ".join(missing))
    projected = {name: row[name] for name in ROW_COLUMNS}
    for name in _REQUIRED_TEXT:
        if not isinstance(projected[name], str):
            raise ValueError(f"{name} must be a string")
    for name in _OPTIONAL_TEXT:
        value = projected[name]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
    if not isinstance(projected["agreed"], bool):
        raise ValueError("agreed must be a boolean")
    projected["window_start"] = _as_number(projected["window_start"], "window_start")
    projected["window_end"] = _as_number(projected["window_end"], "window_end")
    return projected


def _arrow_schema(pa):
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


def write_hazards(
    rows: list[dict],
    *,
    schema: str = SCHEMA_NAME,
    table: str = TABLE_NAME,
) -> int:
    """Create developing_hazard.hazards if needed and insert one batch of rows.

    Reads S3_ENDPOINT, ACCESS_KEY, SECRET_KEY and VASTDB_BUCKET at call time.
    Refuses a protected schema, a protected table, or a chunks or segments
    bucket before importing the database client. VDB_ENDPOINT is not used.
    """
    schema_name = schema.strip()
    table_name = table.strip()
    bucket = _require_env("VASTDB_BUCKET")
    assert_safe_target(schema_name, table_name, bucket)
    prepared = [project_row(row) for row in rows]
    if not prepared:
        return 0

    endpoint = _normalise_endpoint(_require_env("S3_ENDPOINT"))
    access = _require_env("ACCESS_KEY")
    secret = _require_env("SECRET_KEY")
    secrets = (access, secret, endpoint, bucket)

    import pyarrow as pa
    import vastdb

    arrow_schema = _arrow_schema(pa)
    payload = {name: [item[name] for item in prepared] for name in ROW_COLUMNS}
    arrow = pa.table(payload, schema=arrow_schema)
    try:
        session = vastdb.connect(
            endpoint=endpoint,
            access=access,
            secret=secret,
            ssl_verify=False,
        )
        with session.transaction() as tx:
            bucket_handle = tx.bucket(bucket)
            schema_handle = bucket_handle.schema(schema_name, fail_if_missing=False)
            if schema_handle is None:
                schema_handle = bucket_handle.create_schema(
                    schema_name,
                    fail_if_exists=False,
                )
            table_handle = schema_handle.table(table_name, fail_if_missing=False)
            if table_handle is None:
                table_handle = schema_handle.create_table(
                    table_name,
                    columns=arrow_schema,
                    fail_if_exists=False,
                )
            table_handle.insert(arrow)
    except Exception as exc:
        message = _redact(str(exc), secrets).strip() or "VastDB write failed"
        raise VastDBError(message) from None
    return len(prepared)


def refuse(schema: str, table: str, bucket: str) -> None:
    """Raise before a write to an index table or a media bucket."""
    assert_safe_target(schema, table, bucket)


def insert_hazard_rows(rows: list[dict]) -> int:
    """Insert hazard rows. Same guard and column list as ``write_hazards``."""
    return write_hazards(rows)
