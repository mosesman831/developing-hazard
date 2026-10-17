"""Agents must not import label stores or carry hazard fields on ClipMeta."""

from __future__ import annotations

import ast
from pathlib import Path

BANNED_MODULES = {"dh.store", "dh.clients.vss", "dh.clients.vastdb"}
BANNED_STRINGS = {
    "hazards" + ".json",
    "reasoning" + "_content",
    "object" + "_counts",
    "cap" + "tion",
}

_AGENTS = Path(__file__).resolve().parents[2] / "dh" / "agents"


def test_agents_do_not_read_labels():
    paths = sorted(_AGENTS.glob("*.py"))
    assert paths, _AGENTS
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in BANNED_MODULES, path
            if isinstance(node, ast.Import):
                assert not {alias.name for alias in node.names} & BANNED_MODULES, path
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in BANNED_STRINGS, path


def test_clip_meta_has_no_labels():
    from dh.models import ClipMeta

    assert not {"hazards", "window_start", "window_end"} & set(ClipMeta.model_fields)
