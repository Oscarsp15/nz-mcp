"""Tests for nz_export_ddl (MCP content blocks + catalog delegation)."""

from __future__ import annotations

import hashlib
from datetime import UTC
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
    """Default flow with output_path: header on, resource omitted (issue #129)."""
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
    assert out["meta"]["bytes_written"] > len(ddl.encode("utf-8"))  # includes header
    assert isinstance(out["meta"]["sha256"], str) and len(out["meta"]["sha256"]) == 64
    # Default: resource block omitted; only TextContent summary remains.
    assert all(block["type"] == "text" for block in out["content"])
    assert out["meta"]["resource_in_response"] is False
    assert out["meta"]["header_included"] is True
    # File on disk starts with the SET CATALOG header and contains the DDL body.
    raw = target.read_bytes()
    assert raw.startswith(b"-- Database: DB\n")
    assert b"SET CATALOG DB;\n" in raw
    assert raw.endswith(ddl.encode("utf-8"))


def test_nz_export_ddl_byte_identical_with_and_without_output_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Anchor: include_header=False keeps bytes byte-identical to the resource."""
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
            "include_header": False,
            "include_resource_in_response": True,
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
            # include_header=False so the digest equals the digest of the bare
            # DDL (anchors back-compat for callers that opt out of the header).
            "include_header": False,
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
    """Back-compat: when output_path is absent, meta.output_path stays None.

    Resource block must still be present and meta fields tied to disk export
    (preview, header_included, resource_in_response) all stay None.
    """
    _stub_view(monkeypatch, "CREATE VIEW v AS SELECT 1;\n")

    out = call_tool(
        "nz_export_ddl",
        {"object_type": "view", "database": "DB", "schema": "S", "name": "V"},
        config_path=two_profiles,
    )
    assert out["meta"]["output_path"] is None
    assert out["meta"]["bytes_written"] is None
    assert out["meta"]["sha256"] is None
    assert out["meta"]["preview"] is None
    assert out["meta"]["resource_in_response"] is None
    assert out["meta"]["header_included"] is None
    # Resource block is still present (no output_path → response unchanged).
    assert out["content"][0]["type"] == "resource"


def test_nz_export_ddl_table_with_output_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Default: table export with output_path writes header + DDL."""
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
    raw = target.read_bytes()
    assert raw.startswith(b"-- Database: DB\n")
    assert b"-- Object:   table S.T\n" in raw
    assert b"SET CATALOG DB;\n" in raw
    assert raw.endswith(b"CREATE TABLE t(i int);")


def test_nz_export_ddl_procedure_with_output_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Default: procedure export with output_path writes header + DDL, omits resource."""
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
    raw = target.read_bytes()
    assert raw.startswith(b"-- Database: DB\n")
    assert b"-- Object:   procedure S.P\n" in raw
    assert b"SET CATALOG DB;\n" in raw
    assert raw.endswith(body.encode("utf-8"))
    # Default: resource is omitted from the response, preview is populated.
    assert all(block["type"] == "text" for block in out["content"])
    assert isinstance(out["meta"]["preview"], str)
    assert out["meta"]["preview"].startswith("-- Database: DB")


# --- issue #129: response cap + SET CATALOG header ---------------------------


def test_nz_export_ddl_omits_resource_by_default_when_writing_to_disk(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Issue #129 cap fix: default with output_path drops the resource block."""
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

    types_seen = [block["type"] for block in out["content"]]
    assert "resource" not in types_seen
    assert types_seen == ["text"]
    assert out["meta"]["resource_in_response"] is False
    assert isinstance(out["meta"]["preview"], str)


def test_nz_export_ddl_keeps_resource_when_caller_opts_in(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Issue #129: include_resource_in_response=True restores prior behaviour."""
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
            "include_resource_in_response": True,
        },
        config_path=two_profiles,
    )

    assert out["content"][0]["type"] == "resource"
    assert out["content"][0]["resource"]["text"] == ddl
    assert out["meta"]["resource_in_response"] is True
    # Preview is only emitted when the resource is omitted; here it stays None.
    assert out["meta"]["preview"] is None


def test_nz_export_ddl_header_contains_set_catalog_and_no_credentials(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Header is well-formed and never leaks host/user/password (rule 1)."""
    ddl = "CREATE VIEW v AS SELECT 1;\n"
    _stub_view(monkeypatch, ddl)
    target = tmp_path / "v.sql"

    call_tool(
        "nz_export_ddl",
        {
            "object_type": "view",
            "database": "PROD_ANALITICA",
            "schema": "DBO",
            "name": "V_FOO",
            "output_path": str(target),
        },
        config_path=two_profiles,
    )

    text = target.read_text(encoding="utf-8")
    assert text.startswith("-- Database: PROD_ANALITICA\n")
    assert "-- Schema:   DBO\n" in text
    assert "-- Object:   view DBO.V_FOO\n" in text
    assert "SET CATALOG PROD_ANALITICA;\n" in text
    # Adversarial: the header must not leak any connection metadata that could
    # be used to authenticate. The profile name is allowed (safe metadata).
    forbidden = ["password", "PASSWORD", "host=", "user=", "secret"]
    for needle in forbidden:
        assert needle not in text, f"Header leaked sensitive token: {needle!r}"


def test_nz_export_ddl_include_header_false_keeps_byte_identity(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Issue #129: include_header=False preserves byte-identity with the resource."""
    ddl = "CREATE VIEW v AS SELECT 99;\n"
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
            "include_header": False,
            "include_resource_in_response": True,
        },
        config_path=two_profiles,
    )

    assert target.read_bytes() == ddl.encode("utf-8")
    expected_sha = hashlib.sha256(ddl.encode("utf-8")).hexdigest()
    assert out["meta"]["sha256"] == expected_sha
    assert out["meta"]["header_included"] is False
    # Resource present and identical to disk content.
    assert out["content"][0]["type"] == "resource"
    assert out["content"][0]["resource"]["text"] == ddl


def test_nz_export_ddl_sha256_reflects_file_on_disk_when_header_present(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """Issue #129: reported sha256 is the file's digest, not the resource's."""
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
            "include_resource_in_response": True,
        },
        config_path=two_profiles,
    )

    on_disk = target.read_bytes()
    assert out["meta"]["sha256"] == hashlib.sha256(on_disk).hexdigest()
    # And the on-disk digest differs from the resource digest because the
    # header was prepended.
    resource_text = out["content"][0]["resource"]["text"]
    assert resource_text == ddl  # resource is still bare
    assert out["meta"]["sha256"] != hashlib.sha256(ddl.encode("utf-8")).hexdigest()


def test_build_header_block_pure_function_no_credentials() -> None:
    """Adversarial unit test on the pure header builder."""
    from datetime import datetime

    from nz_mcp.tools.export_ddl import build_header_block

    header = build_header_block(
        database="PROD_ANALITICA",
        schema="DBO",
        name="PI_X",
        object_type="procedure",
        profile_name="uaipscrea1",
        timestamp_utc=datetime(2026, 5, 8, 5, 30, 0, tzinfo=UTC),
        nz_mcp_version="0.1.0a0",
    )

    assert header == (
        "-- Database: PROD_ANALITICA\n"
        "-- Schema:   DBO\n"
        "-- Object:   procedure DBO.PI_X\n"
        "-- Exported: 2026-05-08T05:30:00Z by uaipscrea1 (nz-mcp v0.1.0a0)\n"
        "SET CATALOG PROD_ANALITICA;\n"
        "\n"
    )
    # The profile name is the only identity-shaped field allowed.
    for forbidden in ("password", "host=", "user=", "secret", "Authorization"):
        assert forbidden not in header


def test_build_header_block_handles_special_characters() -> None:
    """Header must remain a valid SQL comment block even with unusual chars."""
    from datetime import datetime

    from nz_mcp.tools.export_ddl import build_header_block

    header = build_header_block(
        database="PROD_ÑANDU",
        schema='WEIRD"NAME',
        name="O'BRIEN",
        object_type="table",
        profile_name="uaipscrea1",
        timestamp_utc=datetime(2026, 5, 8, 5, 30, 0, tzinfo=UTC),
        nz_mcp_version="0.1.0a0",
    )

    # Each comment line still starts with '-- ' (no premature CR/LF, no NUL).
    for line in header.splitlines():
        if line:
            assert line.startswith("--") or line.startswith("SET CATALOG")
    # The body characters survived unchanged.
    assert "PROD_ÑANDU" in header
    assert "O'BRIEN" in header
    assert 'WEIRD"NAME' in header


def test_build_header_block_normalises_naive_datetime_to_utc() -> None:
    """Naive (no tzinfo) datetimes are coerced via astimezone with UTC."""
    from datetime import datetime

    from nz_mcp.tools.export_ddl import build_header_block

    aware = datetime(2026, 5, 8, 5, 30, 0, tzinfo=UTC)
    header = build_header_block(
        database="DB",
        schema="S",
        name="N",
        object_type="view",
        profile_name="p",
        timestamp_utc=aware,
        nz_mcp_version="0.1.0",
    )
    # The 'Z' suffix anchors UTC ISO-8601.
    assert "2026-05-08T05:30:00Z" in header


def test_nz_export_ddl_default_meta_includes_header_flag(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, tmp_path: Path
) -> None:
    """meta.header_included tracks whether the file got the SET CATALOG header."""
    _stub_view(monkeypatch, "CREATE VIEW v AS SELECT 1;\n")
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
    assert out["meta"]["header_included"] is True
