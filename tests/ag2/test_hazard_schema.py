"""Validate hazards against contracts/hazard.schema.json."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "hazard.schema.json"
HAZARDS_PATH = ROOT / "data" / "hazards.json"

HAZARD_TYPES = {
    "pedestrian_crossing",
    "vehicle_pulling_out",
    "vehicle_cut_in",
    "lead_vehicle_braking",
    "cyclist",
    "vehicle_turning_across",
    "other",
}
REQUIRED_KEYS = {
    "hazard_id",
    "clip_id",
    "type",
    "window_start",
    "window_end",
    "labellers",
    "agreed",
}


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_pure_python(hazard: dict) -> None:
    missing = REQUIRED_KEYS - hazard.keys()
    assert not missing, f"missing keys: {sorted(missing)}"
    assert hazard["type"] in HAZARD_TYPES
    assert isinstance(hazard["labellers"], dict)
    assert isinstance(hazard["agreed"], bool)
    assert hazard["window_end"] > hazard["window_start"]


def _validate_hazard(hazard: dict, schema: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        _validate_pure_python(hazard)
        return
    jsonschema.validate(instance=hazard, schema=schema)


def test_hazards_json_matches_schema_if_present():
    if not HAZARDS_PATH.is_file():
        pytest.skip("data/hazards.json is not present")
    schema = _load_schema()
    hazards = json.loads(HAZARDS_PATH.read_text(encoding="utf-8"))
    assert isinstance(hazards, list)
    for hazard in hazards:
        _validate_hazard(hazard, schema)
        assert hazard["window_end"] > hazard["window_start"]
