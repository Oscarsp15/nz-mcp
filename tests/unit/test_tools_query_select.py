"""Tests for ``nz_query_select``."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import GuardRejectedError
from nz_mcp.tools.query import QuerySelectInput, nz_query_select, hint_from_execute_payload


def test_query_select_rejects_insert(two_profiles: Path) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        nz_query_select(
            QuerySelectInput(sql="INSERT INTO t (a) VALUES (1)"),
            config_path=two_profiles,
        )
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


def test_query_select_rejects_explain_statement(two_profiles: Path) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        nz_query_select(
            QuerySelectInput(sql="EXPLAIN SELECT 1"),
            config_path=two_profiles,
        )
    assert exc.value.code == "WRONG_STATEMENT_FOR_TOOL"


def test_query_select_rejects_show(two_profiles: Path) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        nz_query_select(
            QuerySelectInput(sql="SHOW DATABASES"),
            config_path=two_profiles,
        )
    assert exc.value.code == "WRONG_STATEMENT_FOR_TOOL"


def test_query_select_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    seen: dict[str, object] = {}

    def _inject(sql: str, max_rows: int) -> str:
        seen["inject_max"] = max_rows
        assert "SELECT" in sql.upper()
        return sql

    def _exec(_profile: object, sql: str, *, max_rows: int, timeout_s: int) -> dict[str, object]:
        seen["exec_sql"] = sql
        seen["exec_max_rows"] = max_rows
        seen["exec_timeout"] = timeout_s
        return {
            "columns": [{"name": "x", "type": "int"}],
            "rows": [[1]],
            "row_count": 1,
            "truncated": False,
            "duration_ms": 12,
            "hint_key": None,
            "hint_fmt": {},
        }

    monkeypatch.setattr("nz_mcp.tools.query.inject_limit", _inject)
    monkeypatch.setattr("nz_mcp.tools.query.execute_select", _exec)

    out = nz_query_select(
        QuerySelectInput(sql="SELECT 1 AS x"),
        config_path=two_profiles,
    )
    assert out.row_count == 1
    assert out.rows == [[1]]
    assert out.columns[0].name == "x"
    assert out.hint is None
    assert seen["inject_max"] == 100  # profile default
    assert seen["exec_max_rows"] == 100
    assert seen["exec_timeout"] == 30


def test_hint_from_execute_payload_bytes_truncation() -> None:
    h = hint_from_execute_payload(
        {
            "hint_key": "HINT.RESULT_TRUNCATED_BY_BYTES",
            "hint_fmt": {"max_kb": 100},
        },
    )
    assert h is not None and "100" in h


def test_query_select_surfaces_truncation_hint(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _exec(_p: object, _sql: str, *, max_rows: int, timeout_s: int) -> dict[str, object]:
        return {
            "columns": [{"name": "x", "type": "int"}],
            "rows": [[1]],
            "row_count": 1,
            "truncated": True,
            "duration_ms": 1,
            "hint_key": "HINT.RESULT_TRUNCATED_BY_BYTES",
            "hint_fmt": {"max_kb": 100},
        }

    monkeypatch.setattr("nz_mcp.tools.query.inject_limit", lambda sql, _m: sql)
    monkeypatch.setattr("nz_mcp.tools.query.execute_select", _exec)

    out = nz_query_select(QuerySelectInput(sql="SELECT 1"), config_path=two_profiles)
    assert out.truncated is True
    assert out.hint is not None
