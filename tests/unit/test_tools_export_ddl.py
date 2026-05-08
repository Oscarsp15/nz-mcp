"""Tests for nz_export_ddl (MCP content blocks + catalog delegation)."""

from __future__ import annotations

import hashlib
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
    params = ExportDdlInput(object_type="view", database="DB", object_schema="S", name="V")
    blocks, meta = nz_export_ddl(params, config_path=two_profiles)
    assert isinstance(blocks[0], types.EmbeddedResource)
    assert isinstance(blocks[1], types.TextContent)
    assert meta.object_schema == "S"


# --- output_path: writes to disk ---------------------------------------------


def _stub_view(monkeypatch: pytest.MonkeyPatch, ddl: str) -> None:
    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_view_ddl", lambda *_a, **_k: ddl)


def test_nz_export_ddl_writes_file_when_output_path_given(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    ddl = "CREATE VIEW v AS SELECT 1;\n"
    _stub_view(monkeypatch, ddl)
    target = tmp_path / "v.sql"

    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "view",
            "database": "DB",
            "schema": "S",
            "name": "V",
            "output_path": str(target),
        },
        config_path=two_profiles,
    )

    assert out["meta"]["output_path"] == str(target)
    assert out["meta"]["bytes_written"] == len(ddl.encode("utf-8"))
    assert isinstance(out["meta"]["sha256"], str) and len(out["meta"]["sha256"]) == 64
    # Resource block is still present (resource + path policy chosen, ADR 0013).
    assert out["content"][0]["type"] == "resource"
    assert out["content"][0]["resource"]["text"] == ddl
    # File on disk is byte-identical to the resource text.
    assert target.read_bytes() == ddl.encode("utf-8")


def test_nz_export_ddl_byte_identical_with_and_without_output_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Anchor: bytes written to disk match the resource block text exactly."""
    ddl = "SELECT A.FECHACORTE,\n  CASE WHEN B.X NOTNULL THEN 1 ELSE 0 END\nFROM DBO.T A;\n"
    _stub_view(monkeypatch, ddl)

    no_path = call_tool(
        "nz_export_ddl",
        {"object_type": "view", "database": "DB", "schema": "S", "name": "V"},
        config_path=two_profiles,
    )
    target = tmp_path / "v.sql"
    with_path = call_tool(
        "nz_export_ddl",
        {
            "object_type": "view",
            "database": "DB",
            "schema": "S",
            "name": "V",
            "output_path": str(target),
        },
        config_path=two_profiles,
    )

    resource_text_no_path = no_path["content"][0]["resource"]["text"]
    resource_text_with_path = with_path["content"][0]["resource"]["text"]
    assert resource_text_no_path == resource_text_with_path == ddl
    assert target.read_bytes() == ddl.encode("utf-8")
    assert target.read_text(encoding="utf-8") == resource_text_with_path


def test_nz_export_ddl_overwrite_required_when_file_exists(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    _stub_view(monkeypatch, "CREATE VIEW v AS SELECT 1;\n")
    target = tmp_path / "v.sql"
    target.write_text("placeholder", encoding="utf-8")

    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "view",
            "database": "DB",
            "schema": "S",
            "name": "V",
            "output_path": str(target),
        },
        config_path=two_profiles,
    )
    assert out["error"]["code"] == "INVALID_INPUT"
    assert "overwrite=True" in out["error"]["context"]["detail"]
    # Original file untouched.
    assert target.read_text(encoding="utf-8") == "placeholder"


def test_nz_export_ddl_overwrite_true_replaces_file(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    ddl = "CREATE VIEW v2 AS SELECT 99;\n"
    _stub_view(monkeypatch, ddl)
    target = tmp_path / "v.sql"
    target.write_text("OLD", encoding="utf-8")

    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "view",
            "database": "DB",
            "schema": "S",
            "name": "V",
            "output_path": str(target),
            "overwrite": True,
        },
        config_path=two_profiles,
    )

    assert "error" not in out
    assert target.read_text(encoding="utf-8") == ddl
    expected_sha = hashlib.sha256(ddl.encode("utf-8")).hexdigest()
    assert out["meta"]["sha256"] == expected_sha


def test_nz_export_ddl_rejects_traversal_before_touching_netezza(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Path policy short-circuits before any catalog query runs."""

    def _explode(*_a: object, **_k: object) -> str:
        raise AssertionError("get_view_ddl must not be called when path is invalid")

    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_view_ddl", _explode)
    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_table_ddl", _explode)
    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_procedure_ddl", _explode)

    poisoned = str(tmp_path / "sub" / ".." / "v.sql")
    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "view",
            "database": "DB",
            "schema": "S",
            "name": "V",
            "output_path": poisoned,
        },
        config_path=two_profiles,
    )

    assert out["error"]["code"] == "INVALID_INPUT"
    assert "path traversal" in out["error"]["context"]["detail"]


def test_nz_export_ddl_rejects_relative_path_before_touching_netezza(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _explode(*_a: object, **_k: object) -> str:
        raise AssertionError("get_view_ddl must not be called when path is invalid")

    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_view_ddl", _explode)

    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "view",
            "database": "DB",
            "schema": "S",
            "name": "V",
            "output_path": "relative/path.sql",
        },
        config_path=two_profiles,
    )
    assert out["error"]["code"] == "INVALID_INPUT"
    assert "absoluto" in out["error"]["context"]["detail"]


def test_nz_export_ddl_no_output_path_keeps_old_meta_shape(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Back-compat: when output_path is absent, meta.output_path stays None."""
    _stub_view(monkeypatch, "CREATE VIEW v AS SELECT 1;\n")

    out = call_tool(
        "nz_export_ddl",
        {"object_type": "view", "database": "DB", "schema": "S", "name": "V"},
        config_path=two_profiles,
    )
    assert out["meta"]["output_path"] is None
    assert out["meta"]["bytes_written"] is None
    assert out["meta"]["sha256"] is None


def test_nz_export_ddl_table_with_output_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.export_ddl.get_table_ddl",
        lambda *_a, **_k: {"ddl": "CREATE TABLE t(i int);", "reconstructed": True},
    )
    target = tmp_path / "t.sql"

    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "table",
            "database": "DB",
            "schema": "S",
            "name": "T",
            "output_path": str(target),
        },
        config_path=two_profiles,
    )

    assert out["meta"]["output_path"] == str(target)
    assert target.read_bytes() == b"CREATE TABLE t(i int);"


def test_nz_export_ddl_procedure_with_output_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    body = "CREATE OR REPLACE PROCEDURE p() AS BEGIN END;\n"
    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_procedure_ddl", lambda *_a, **_k: body)
    target = tmp_path / "p.sql"

    out = call_tool(
        "nz_export_ddl",
        {
            "object_type": "procedure",
            "database": "DB",
            "schema": "S",
            "name": "P",
            "output_path": str(target),
        },
        config_path=two_profiles,
    )

    assert out["meta"]["output_path"] == str(target)
    assert out["meta"]["size_bytes"] == len(body.encode("utf-8"))
    assert target.read_bytes() == body.encode("utf-8")
