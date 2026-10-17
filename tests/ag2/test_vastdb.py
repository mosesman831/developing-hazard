"""VastDB client tests. The database SDK is faked. No network connection."""

from __future__ import annotations

import ast
import builtins
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "dh" / "clients" / "vastdb.py"

DATA_VIP = "http://data-vip.test"
QUERY_VIP = "http://query-engine.test"
ACCESS = "test-access-key"
SECRET = "test-secret-value"
DB_BUCKET = "team-db"
CHUNKS_BUCKET = "team-chunks"
SEGMENTS_BUCKET = "team-segments"


def _row(**extra) -> dict:
    row = {
        "hazard_id": "c07_h1",
        "clip_id": "c07",
        "type": "pedestrian_crossing",
        "window_start": 16.2,
        "window_end": 19.0,
        "segment_source": "s3://example/segments/one.mp4",
        "original_video": "s3://example/chunks/one.mp4",
        "labeller_a": "riyu",
        "labeller_b": "fmd",
        "agreed": True,
        "testset_id": "testset_v1",
    }
    row.update(extra)
    return row


def _env(monkeypatch: pytest.MonkeyPatch, *, bucket: str = DB_BUCKET) -> None:
    monkeypatch.setenv("S3_ENDPOINT", DATA_VIP)
    monkeypatch.setenv("VDB_ENDPOINT", QUERY_VIP)
    monkeypatch.setenv("ACCESS_KEY", ACCESS)
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("VASTDB_BUCKET", bucket)
    monkeypatch.setenv("S3_CHUNKS_BUCKET", CHUNKS_BUCKET)
    monkeypatch.setenv("S3_SEGMENTS_BUCKET", SEGMENTS_BUCKET)


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("unexpected network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)


class _ArrowSchema:
    def __init__(self, fields):
        self.fields = fields


class _ArrowTable:
    def __init__(self, data, schema):
        self.data = data
        self.schema = schema


class _InsertedTable:
    def __init__(self, name, state):
        self.name = name
        self.state = state

    def insert(self, arrow):
        self.state["inserts"].append({"table": self.name, "arrow": arrow})


def _install_sdk(monkeypatch: pytest.MonkeyPatch, *, schema_exists: bool, table_exists: bool):
    state = {
        "connects": [],
        "creates": [],
        "lookups": [],
        "inserts": [],
        "entered": False,
    }

    class FakeSchemaHandle:
        def table(self, name, fail_if_missing=False):
            state["lookups"].append(("table", name, fail_if_missing))
            if table_exists:
                return _InsertedTable(name, state)
            return None

        def create_table(self, name, columns, fail_if_exists=False):
            state["creates"].append(("table", name, columns, fail_if_exists))
            return _InsertedTable(name, state)

    class FakeBucket:
        def __init__(self, name):
            self.name = name

        def schema(self, name, fail_if_missing=False):
            state["lookups"].append(("schema", name, fail_if_missing))
            if schema_exists:
                return FakeSchemaHandle()
            return None

        def create_schema(self, name, fail_if_exists=False):
            state["creates"].append(("schema", name, fail_if_exists))
            return FakeSchemaHandle()

    class FakeTx:
        def __enter__(self):
            state["entered"] = True
            return self

        def __exit__(self, *_args):
            return False

        def bucket(self, name):
            state["bucket"] = name
            return FakeBucket(name)

    class FakeSession:
        def transaction(self):
            return FakeTx()

    def connect(**kwargs):
        state["connects"].append(kwargs)
        return FakeSession()

    pyarrow = type(sys)("pyarrow")
    pyarrow.utf8 = lambda: "utf8"
    pyarrow.float64 = lambda: "float64"
    pyarrow.bool_ = lambda: "bool"
    pyarrow.schema = lambda fields: _ArrowSchema(fields)
    pyarrow.table = lambda data, schema: _ArrowTable(data, schema)

    vastdb = type(sys)("vastdb")
    vastdb.connect = connect
    monkeypatch.setitem(sys.modules, "pyarrow", pyarrow)
    monkeypatch.setitem(sys.modules, "vastdb", vastdb)
    return state


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_source_has_no_em_dash():
    text = CLIENT_PATH.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text


def test_top_level_imports_are_stdlib():
    assert _top_level_imports(CLIENT_PATH) <= sys.stdlib_module_names


def test_database_packages_are_imported_inside_the_write():
    tree = ast.parse(CLIENT_PATH.read_text(encoding="utf-8"))
    nested: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                nested.update(alias.name.split(".")[0] for alias in child.names)
    assert {"vastdb", "pyarrow"} <= nested


def test_import_works_when_database_packages_are_missing(monkeypatch: pytest.MonkeyPatch):
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".", 1)[0] in {"vastdb", "pyarrow"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    import importlib

    import dh.clients.vastdb as client

    reloaded = importlib.reload(client)
    assert reloaded.SCHEMA_NAME == "developing_hazard"
    assert reloaded.TABLE_NAME == "hazards"
    assert reloaded.ROW_COLUMNS[0] == "hazard_id"
    assert "segment_source" in reloaded.ROW_COLUMNS


def test_project_row_drops_vector_columns():
    import dh.clients.vastdb as client

    row = _row(vectors_visual=[0.1, 0.2], object_counts={"person": 3})
    projected = client.project_row(row)
    assert list(projected) == list(client.ROW_COLUMNS)
    assert "vectors_visual" not in projected
    assert "object_counts" not in projected
    assert projected["hazard_id"] == "c07_h1"
    assert isinstance(projected["hazard_id"], str)


def test_refuses_protected_names_before_connect(monkeypatch: pytest.MonkeyPatch):
    import dh.clients.vastdb as client

    _block_network(monkeypatch)
    _env(monkeypatch)
    state = _install_sdk(monkeypatch, schema_exists=False, table_exists=False)

    with pytest.raises(client.VastDBError, match="vss-collection"):
        client.write_hazards([_row()], schema="vss-collection")
    with pytest.raises(client.VastDBError, match="vss-prompts-events"):
        client.write_hazards([_row()], table="vss-prompts-events")
    with pytest.raises(client.VastDBError, match="(?i)vss-collection"):
        client.assert_safe_target("VSS-COLLECTION", "hazards", DB_BUCKET)
    with pytest.raises(client.VastDBError, match="developing_hazard"):
        client.write_hazards([_row()], schema="hackathon")
    assert state["connects"] == []


def test_refuses_media_buckets_before_connect(monkeypatch: pytest.MonkeyPatch):
    import dh.clients.vastdb as client

    _block_network(monkeypatch)
    state = _install_sdk(monkeypatch, schema_exists=False, table_exists=False)

    _env(monkeypatch, bucket=CHUNKS_BUCKET)
    with pytest.raises(client.VastDBError, match="S3_CHUNKS_BUCKET"):
        client.write_hazards([_row()])

    _env(monkeypatch, bucket=SEGMENTS_BUCKET)
    with pytest.raises(client.VastDBError, match="S3_SEGMENTS_BUCKET"):
        client.write_hazards([])

    assert state["connects"] == []


def test_empty_rows_do_not_connect(monkeypatch: pytest.MonkeyPatch):
    import dh.clients.vastdb as client

    _block_network(monkeypatch)
    _env(monkeypatch)
    state = _install_sdk(monkeypatch, schema_exists=False, table_exists=False)
    assert client.write_hazards([]) == 0
    assert state["connects"] == []


def test_missing_column_does_not_connect(monkeypatch: pytest.MonkeyPatch):
    import dh.clients.vastdb as client

    _block_network(monkeypatch)
    _env(monkeypatch)
    state = _install_sdk(monkeypatch, schema_exists=False, table_exists=False)
    bad = _row()
    del bad["segment_source"]
    with pytest.raises(ValueError, match="segment_source"):
        client.write_hazards([bad])
    assert state["connects"] == []


def test_write_uses_data_vip_and_named_columns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import dh.clients.vastdb as client

    _block_network(monkeypatch)
    _env(monkeypatch)
    state = _install_sdk(monkeypatch, schema_exists=False, table_exists=False)
    rows = [
        _row(segment_source="s3://example/segments/a.mp4", vectors_visual=[0.2] * 256),
        _row(segment_source="s3://example/segments/b.mp4", hazard_id="c07_h1"),
    ]
    count = client.write_hazards(rows)
    assert count == 2
    assert state["entered"] is True
    assert len(state["connects"]) == 1
    connect = state["connects"][0]
    assert connect["endpoint"] == DATA_VIP
    assert connect["endpoint"] != QUERY_VIP
    assert connect["access"] == ACCESS
    assert connect["secret"] == SECRET
    assert connect["ssl_verify"] is False
    assert state["bucket"] == DB_BUCKET
    assert ("schema", "developing_hazard", False) in state["creates"]
    created_tables = [item for item in state["creates"] if item[0] == "table"]
    assert created_tables[0][1] == "hazards"
    assert created_tables[0][3] is False
    field_names = [field[0] for field in created_tables[0][2].fields]
    assert field_names == list(client.ROW_COLUMNS)
    inserted = state["inserts"][0]["arrow"]
    assert list(inserted.data) == list(client.ROW_COLUMNS)
    assert inserted.data["segment_source"] == [
        "s3://example/segments/a.mp4",
        "s3://example/segments/b.mp4",
    ]
    assert "vectors_visual" not in inserted.data
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err
    assert ACCESS not in captured.out
    assert ACCESS not in captured.err


def test_write_inserts_when_schema_and_table_exist(monkeypatch: pytest.MonkeyPatch):
    import dh.clients.vastdb as client

    _block_network(monkeypatch)
    _env(monkeypatch)
    state = _install_sdk(monkeypatch, schema_exists=True, table_exists=True)
    assert client.write_hazards([_row()]) == 1
    assert state["creates"] == []
    assert state["lookups"][0] == ("schema", "developing_hazard", False)
    assert state["lookups"][1] == ("table", "hazards", False)
    assert state["inserts"][0]["table"] == "hazards"


def test_sdk_errors_redact_secrets(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    import dh.clients.vastdb as client

    _block_network(monkeypatch)
    _env(monkeypatch)
    state = _install_sdk(monkeypatch, schema_exists=True, table_exists=True)

    def connect(**kwargs):
        state["connects"].append(kwargs)
        raise RuntimeError(f"denied {kwargs['secret']} at {kwargs['endpoint']}")

    sys.modules["vastdb"].connect = connect
    with pytest.raises(RuntimeError) as exc:
        client.write_hazards([_row()])
    message = str(exc.value)
    assert SECRET not in message
    assert ACCESS not in message
    assert DATA_VIP not in message
    assert "[redacted]" in message
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err
