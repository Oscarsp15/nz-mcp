"""Unit tests for nz_compare_rows tool and catalog layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nz_mcp.catalog.compare_rows import _scalar, _values, compare_rows
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile() -> Profile:
    return Profile(
        name="test",
        host="localhost",
        port=5480,
        database="DESA_MODELOS",
        user="testuser",
        mode="read",
    )


def _make_cursor(side_effects: list[list[object]]) -> MagicMock:
    """Cursor whose successive fetchall() calls return the provided lists."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = side_effects
    return cursor


# ---------------------------------------------------------------------------
# _scalar
# ---------------------------------------------------------------------------


def test_scalar_from_tuple_row() -> None:
    assert _scalar([(42,)]) == 42


def test_scalar_from_list_row() -> None:
    assert _scalar([[7]]) == 7


def test_scalar_from_raw_value() -> None:
    assert _scalar([99]) == 99


def test_scalar_empty() -> None:
    assert _scalar([]) == 0


def test_scalar_none_cell() -> None:
    assert _scalar([(None,)]) == 0


# ---------------------------------------------------------------------------
# _values
# ---------------------------------------------------------------------------


def test_values_from_tuple_rows() -> None:
    assert _values([("A",), ("B",)]) == ["A", "B"]


def test_values_none_cell_becomes_empty_string() -> None:
    assert _values([(None,)]) == [""]


def test_values_empty() -> None:
    assert _values([]) == []


# ---------------------------------------------------------------------------
# compare_rows — happy path
# ---------------------------------------------------------------------------


def test_compare_rows_happy(tmp_path: Path) -> None:
    profile = _profile()

    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [("CODCREDITO",)],  # existence check table A
        [("CODCREDITO",)],  # existence check table B
        [(37466,)],  # only_in_a count
        [(0,)],  # only_in_b count
        [(33000,)],  # in_both count
        [(0,)],  # null_keys_a
        [(0,)],  # null_keys_b
        [("CR001",), ("CR002",)],  # sample_only_in_a
        [],  # sample_only_in_b
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor  # non-context-manager usage (closing())

    with (
        patch("nz_mcp.catalog.compare_rows.get_password", return_value="secret"),
        patch("nz_mcp.catalog.compare_rows.open_connection", return_value=conn),
    ):
        result = compare_rows(
            profile,
            database="DESA_MODELOS",
            schema_a="DBO",
            table_a="EFE_MC_CREDITOS",
            key_a="CODCREDITO",
            schema_b="DBO",
            table_b="EFE_MC_CREDITOS_CANAL_VM",
            key_b="CODCREDITO",
            limit=10,
        )

    assert result["only_in_a"] == 37466
    assert result["only_in_b"] == 0
    assert result["in_both"] == 33000
    assert result["null_keys_a"] == 0
    assert result["null_keys_b"] == 0
    assert result["sample_only_in_a"] == ["CR001", "CR002"]
    assert result["sample_only_in_b"] == []
    assert isinstance(result["duration_ms"], int)
    assert result["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# compare_rows — SQL uses fully-qualified db.schema.table references
# ---------------------------------------------------------------------------


def test_compare_rows_sql_is_fully_qualified() -> None:
    """Regression: reference tables as db.schema.table, never db..schema.table."""
    profile = _profile()

    cursor = MagicMock()
    cursor.fetchall.side_effect = [[(0,)]] * 9
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with (
        patch("nz_mcp.catalog.compare_rows.get_password", return_value="secret"),
        patch("nz_mcp.catalog.compare_rows.open_connection", return_value=conn),
    ):
        compare_rows(
            profile,
            database="DESA_MODELOS",
            schema_a="DBO",
            table_a="A",
            key_a="ID",
            schema_b="DBO",
            table_b="B",
            key_b="ID",
            limit=10,
        )

    sqls = [call.args[0] for call in cursor.execute.call_args_list]
    assert sqls
    for sql in sqls:
        if "_V_RELATION_COLUMN" in sql:  # catalog existence check
            continue
        assert ".." not in sql
        assert "DESA_MODELOS.DBO.A" in sql or "DESA_MODELOS.DBO.B" in sql


# ---------------------------------------------------------------------------
# compare_rows — driver error wraps to NetezzaError
# ---------------------------------------------------------------------------


def test_compare_rows_driver_error_wraps() -> None:
    profile = _profile()

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.side_effect = RuntimeError("connection reset")
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor

    with (
        patch("nz_mcp.catalog.compare_rows.get_password", return_value="secret"),
        patch("nz_mcp.catalog.compare_rows.open_connection", return_value=conn),
        pytest.raises(NetezzaError),
    ):
        compare_rows(
            profile,
            database="DESA_MODELOS",
            schema_a="DBO",
            table_a="A",
            key_a="ID",
            schema_b="DBO",
            table_b="B",
            key_b="ID",
            limit=10,
        )


# ---------------------------------------------------------------------------
# compare_rows — missing table raises OBJECT_NOT_FOUND (issue #302)
# ---------------------------------------------------------------------------


def test_compare_rows_missing_table_raises_object_not_found() -> None:
    from nz_mcp.errors import ObjectNotFoundError

    profile = _profile()

    cursor = MagicMock()
    cursor.fetchall.side_effect = [[("ID",)], []]  # A exists, B missing
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with (
        patch("nz_mcp.catalog.compare_rows.get_password", return_value="secret"),
        patch("nz_mcp.catalog.compare_rows.open_connection", return_value=conn),
        pytest.raises(ObjectNotFoundError),
    ):
        compare_rows(
            profile,
            database="DESA_MODELOS",
            schema_a="DBO",
            table_a="A",
            key_a="ID",
            schema_b="DBO",
            table_b="MISSING_TABLE",
            key_b="ID",
            limit=10,
        )


# ---------------------------------------------------------------------------
# compare_rows — invalid identifier is rejected before opening connection
# ---------------------------------------------------------------------------


def test_compare_rows_invalid_table_identifier() -> None:
    from nz_mcp.errors import InvalidInputError

    profile = _profile()

    with pytest.raises(InvalidInputError):
        compare_rows(
            profile,
            database="DESA_MODELOS",
            schema_a="DBO",
            table_a="bad-name!",  # contains invalid characters
            key_a="ID",
            schema_b="DBO",
            table_b="B",
            key_b="ID",
            limit=10,
        )


# ---------------------------------------------------------------------------
# Tool layer — happy path via call_tool
# ---------------------------------------------------------------------------


def test_nz_compare_rows_tool_happy(two_profiles: Path) -> None:
    """call_tool wires input → catalog → output correctly."""
    from nz_mcp.server import call_tool

    payload = {
        "only_in_a": 5,
        "only_in_b": 2,
        "in_both": 100,
        "null_keys_a": 0,
        "null_keys_b": 1,
        "sample_only_in_a": ["K1", "K2", "K3", "K4", "K5"],
        "sample_only_in_b": ["X1", "X2"],
        "duration_ms": 42,
    }

    with patch("nz_mcp.tools.compare_rows.compare_rows", return_value=payload):
        out = call_tool(
            "nz_compare_rows",
            {
                "database": "DESA_MODELOS",
                "schema_a": "DBO",
                "table_a": "TABLE_A",
                "key_a": "ID",
                "schema_b": "DBO",
                "table_b": "TABLE_B",
                "key_b": "ID",
            },
            config_path=two_profiles,
        )

    assert "result" in out
    r = out["result"]
    assert r["only_in_a"] == 5
    assert r["only_in_b"] == 2
    assert r["in_both"] == 100
    assert r["null_keys_a"] == 0
    assert r["null_keys_b"] == 1
    assert r["sample_only_in_a"] == ["K1", "K2", "K3", "K4", "K5"]
    assert r["sample_only_in_b"] == ["X1", "X2"]
    assert r["truncated"] is False
    assert r["hint"] is None
    assert r["duration_ms"] == 42


# ---------------------------------------------------------------------------
# Tool layer — truncated samples produce a localized hint
# ---------------------------------------------------------------------------


def test_nz_compare_rows_tool_truncated_hint(two_profiles: Path) -> None:
    """When a difference exceeds the returned sample, truncated=True and hint is set."""
    from nz_mcp.server import call_tool

    payload = {
        "only_in_a": 37466,
        "only_in_b": 0,
        "in_both": 33000,
        "null_keys_a": 0,
        "null_keys_b": 0,
        "sample_only_in_a": ["CR001", "CR002"],
        "sample_only_in_b": [],
        "duration_ms": 820,
    }

    with patch("nz_mcp.tools.compare_rows.compare_rows", return_value=payload):
        out = call_tool(
            "nz_compare_rows",
            {
                "database": "DESA_MODELOS",
                "schema_a": "DBO",
                "table_a": "TABLE_A",
                "key_a": "ID",
                "schema_b": "DBO",
                "table_b": "TABLE_B",
                "key_b": "ID",
                "limit": 2,
            },
            config_path=two_profiles,
        )

    assert "result" in out
    r = out["result"]
    assert r["truncated"] is True
    assert isinstance(r["hint"], str)
    assert "37464" in r["hint"]  # 37466 only_in_a - 2 sampled


# ---------------------------------------------------------------------------
# Tool layer — permission denied on write profile
# ---------------------------------------------------------------------------


def test_nz_compare_rows_available_in_read_mode(two_profiles: Path) -> None:
    """nz_compare_rows is read-mode; a read profile must NOT be denied."""
    from nz_mcp.tools.registry import TOOLS

    spec = TOOLS["nz_compare_rows"]
    assert spec.mode == "read"


# ---------------------------------------------------------------------------
# Tool layer — invalid input
# ---------------------------------------------------------------------------


def test_nz_compare_rows_tool_missing_required_field(two_profiles: Path) -> None:
    from nz_mcp.server import call_tool

    out = call_tool(
        "nz_compare_rows",
        {"database": "DESA_MODELOS"},  # missing all other required fields
        config_path=two_profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "INVALID_INPUT"
