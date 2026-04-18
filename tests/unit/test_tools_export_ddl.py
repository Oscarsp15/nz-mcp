"""Tests for nz_export_ddl (MCP content blocks + catalog delegation)."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import types

from nz_mcp.server import call_tool
from nz_mcp.tools.export_ddl import ExportDdlInput, nz_export_ddl


def test_nz_export_ddl_table(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_get_table_ddl(_profile: object, **_kwargs: object) -> dict[str, object]:
        return {"ddl": "CREATE TABLE x(i int);", "reconstructed": True}

    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_table_ddl", _fake_get_table_ddl)

    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "table",
            "database": "DB",
            "schema": "PUB",
            "name": "T1",
            "include_constraints": True,
        },
        config_path=two_profiles,
    )
    assert "content" in out
    assert "meta" in out
    assert out["meta"]["object_type"] == "table"
    assert out["meta"]["schema"] == "PUB"
    assert out["meta"]["name"] == "T1"
    assert out["meta"]["reconstructed"] is True
    assert len(out["content"]) == 2
    assert out["content"][0]["type"] == "resource"
    assert out["content"][0]["resource"]["mimeType"] == "text/sql"
    assert "CREATE TABLE" in out["content"][0]["resource"]["text"]


def test_nz_export_ddl_view(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_get_view_ddl(_profile: object, **_kwargs: object) -> str:
        return "CREATE VIEW v AS SELECT 1;"

    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_view_ddl", _fake_get_view_ddl)

    out = call_tool(
        "nz_export_ddl",
        {"object_type": "view", "database": "DB", "schema": "S", "name": "V1"},
        config_path=two_profiles,
    )
    assert out["meta"]["object_type"] == "view"
    assert "nz-mcp://ddl/" in out["meta"]["resource_uri"]


def test_nz_export_ddl_procedure(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    body = "x" * (101 * 1024)

    def _fake_get_procedure_ddl(_profile: object, **_kwargs: object) -> str:
        return f"CREATE OR REPLACE PROCEDURE p() AS BEGIN {body} END;"

    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_procedure_ddl", _fake_get_procedure_ddl)

    out = call_tool(
        "nz_export_ddl",
        {"object_type": "procedure", "database": "DB", "schema": "S", "name": "P1"},
        config_path=two_profiles,
    )
    assert out["meta"]["object_type"] == "procedure"
    assert out["meta"]["warning"] is not None
    assert out["meta"]["size_bytes"] > 100 * 1024


def test_nz_export_ddl_direct_returns_mcp_blocks(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.export_ddl.get_view_ddl",
        lambda *_a, **_k: "CREATE VIEW v AS SELECT 1;",
    )
    params = ExportDdlInput(object_type="view", database="DB", schema="S", name="V")
    blocks, meta = nz_export_ddl(params, config_path=two_profiles)
    assert isinstance(blocks[0], types.EmbeddedResource)
    assert isinstance(blocks[1], types.TextContent)
    assert meta.object_schema == "S"

