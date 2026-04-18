"""Unit tests for JSON Schema inlining in MCP tool adapters (issue #73)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import types

from nz_mcp.server import _inline_refs, _to_mcp_tool, list_tools
from nz_mcp.tools.registry import TOOLS


def _assert_no_defs_refs(obj: Any) -> None:
    """Fail if any internal JSON Schema ref to ``#/$defs/...`` remains."""
    if isinstance(obj, dict):
        ref = obj.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            pytest.fail(f"Unresolved internal $ref: {ref}")
        assert "$defs" not in obj
        for v in obj.values():
            _assert_no_defs_refs(v)
    elif isinstance(obj, list):
        for x in obj:
            _assert_no_defs_refs(x)


def test_inline_refs_simple() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "$defs": {
            "Widget": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            }
        },
        "properties": {
            "item": {"$ref": "#/$defs/Widget"},
        },
    }
    out = _inline_refs(schema)
    assert "$defs" not in out
    assert out["properties"]["item"]["type"] == "object"
    assert out["properties"]["item"]["properties"]["id"]["type"] == "integer"


def test_inline_refs_nested() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "$defs": {
            "Inner": {"type": "boolean"},
            "Outer": {
                "type": "object",
                "properties": {"inner": {"$ref": "#/$defs/Inner"}},
            },
        },
        "properties": {"o": {"$ref": "#/$defs/Outer"}},
    }
    out = _inline_refs(schema)
    assert "$defs" not in out
    assert out["properties"]["o"]["properties"]["inner"]["type"] == "boolean"


def test_inline_refs_no_defs() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
    }
    out = _inline_refs(schema)
    assert out == schema


def test_inline_refs_preserves_siblings() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "$defs": {"X": {"type": "string", "title": "orig"}},
        "properties": {
            "a": {"$ref": "#/$defs/X", "description": "overridden"},
        },
    }
    out = _inline_refs(schema)
    assert out["properties"]["a"]["description"] == "overridden"
    assert out["properties"]["a"]["type"] == "string"


def test_inline_refs_definitions_alias() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "definitions": {"Legacy": {"type": "string"}},
        "properties": {"z": {"$ref": "#/definitions/Legacy"}},
    }
    out = _inline_refs(schema)
    assert "definitions" not in out
    assert out["properties"]["z"]["type"] == "string"


def test_inline_refs_cycle_keeps_ref() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"next": {"$ref": "#/$defs/Node"}},
            }
        },
        "properties": {"root": {"$ref": "#/$defs/Node"}},
    }
    out = _inline_refs(schema)
    assert "$defs" not in out
    n = out["properties"]["root"]["properties"]["next"]
    assert n.get("$ref") == "#/$defs/Node"


def test_inline_refs_unresolved_ref_walks_other_keys() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "$defs": {"Other": {"type": "string"}},
        "properties": {
            "bad": {"$ref": "#/$defs/Missing", "x": 1},
        },
    }
    out = _inline_refs(schema)
    assert out["properties"]["bad"]["$ref"] == "#/$defs/Missing"
    assert out["properties"]["bad"]["x"] == 1


def test_to_mcp_tool_output_schema_no_refs_for_list_databases() -> None:
    listings = {x.name: x for x in list_tools()}
    listing = listings["nz_list_databases"]
    tool = _to_mcp_tool(listing)
    assert tool.outputSchema is not None
    result = tool.outputSchema["properties"]["result"]
    _assert_no_defs_refs(result)
    assert "#/$defs/" not in json.dumps(tool.outputSchema)


@pytest.mark.contract
def test_mcp_tool_model_validate_list_tools() -> None:
    """MCP SDK must accept every tool schema we emit (no PointerToNowhere)."""
    for listing in list_tools():
        tool = _to_mcp_tool(listing)
        types.Tool.model_validate(tool.model_dump())


def test_all_tool_output_schemas_inline_internal_refs() -> None:
    for spec in TOOLS.values():
        raw = spec.output_model.model_json_schema()
        inlined = _inline_refs(raw)
        assert "#/$defs/" not in json.dumps(inlined)
