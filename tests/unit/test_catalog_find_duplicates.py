"""Unit tests for the ``find_duplicates`` catalog helper."""

from __future__ import annotations

from typing import Any

import pytest

from nz_mcp.catalog.tables import find_duplicates
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, ObjectNotFoundError


def _profile(*, database: str = "DEV") -> Profile:
    return Profile(name="a", host="h", port=5480, database=database, user="u", mode="admin")


class _ColumnCursor:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params or ()))

    def fetchall(self) -> list[Any]:
        return self._rows

    def close(self) -> None:
        pass


class _Conn:
    def __init__(self, cursor: _ColumnCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _ColumnCursor:
        return self._cursor

    def close(self) -> None:
        pass


def _patch_columns(monkeypatch: pytest.MonkeyPatch, rows: list[Any]) -> None:
    cursor = _ColumnCursor(rows)
    monkeypatch.setattr("nz_mcp.catalog.tables.open_connection", lambda *_a, **_k: _Conn(cursor))
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _n: "pw")


def test_find_duplicates_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_columns(monkeypatch, [("CODCREDITO", "BIGINT")])
    calls: list[str] = []

    def _fake_execute_select(
        _profile: Profile,
        sql: str,
        *,
        max_rows: int,
        timeout_s: int,
    ) -> dict[str, Any]:
        calls.append(sql)
        if "DUP_GROUPS" in sql:
            return {"rows": [[3, 7]]}
        return {"rows": [["12345", 3], ["999", 2]]}

    monkeypatch.setattr("nz_mcp.catalog.tables.execute_select", _fake_execute_select)

    out = find_duplicates(_profile(), "DEV", "DBO", "T", ["CODCREDITO"], limit=10, timeout_s=30)

    assert out == {
        "duplicate_groups": 3,
        "duplicate_rows": 7,
        "sample": [
            {"key": ["12345"], "count": 3},
            {"key": ["999"], "count": 2},
        ],
        "truncated": False,
    }
    assert any("GROUP BY CODCREDITO HAVING COUNT(*) > 1" in sql for sql in calls)
    assert any("HAVING COUNT(*) > 1" in sql and "DUP_GROUPS" in sql for sql in calls)


def test_find_duplicates_marks_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_columns(monkeypatch, [("A", "INT4")])

    def _fake_execute_select(
        _profile: Profile,
        sql: str,
        *,
        max_rows: int,
        timeout_s: int,
    ) -> dict[str, Any]:
        if "DUP_GROUPS" in sql:
            return {"rows": [[12, 40]]}
        return {"rows": [["x", 2]]}

    monkeypatch.setattr("nz_mcp.catalog.tables.execute_select", _fake_execute_select)

    out = find_duplicates(_profile(), "DEV", "DBO", "T", ["A"], limit=1, timeout_s=30)
    assert out["duplicate_groups"] == 12
    assert out["truncated"] is True


def test_find_duplicates_table_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_columns(monkeypatch, [])
    with pytest.raises(ObjectNotFoundError):
        find_duplicates(_profile(), "DEV", "DBO", "T", ["A"], limit=10, timeout_s=30)


def test_find_duplicates_key_column_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_columns(monkeypatch, [("B", "INT4")])
    with pytest.raises(InvalidInputError, match="NOPE"):
        find_duplicates(_profile(), "DEV", "DBO", "T", ["NOPE"], limit=10, timeout_s=30)


def test_find_duplicates_rejects_empty_key_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_columns(monkeypatch, [("A", "INT4")])
    with pytest.raises(InvalidInputError):
        find_duplicates(_profile(), "DEV", "DBO", "T", [], limit=10, timeout_s=30)


def test_find_duplicates_rejects_repeated_key_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_columns(monkeypatch, [("A", "INT4")])
    with pytest.raises(InvalidInputError, match="duplicate"):
        find_duplicates(_profile(), "DEV", "DBO", "T", ["A", "A"], limit=10, timeout_s=30)


def test_find_duplicates_database_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_columns(monkeypatch, [("A", "INT4")])
    with pytest.raises(InvalidInputError, match="active profile database"):
        find_duplicates(_profile(), "OTHER", "DBO", "T", ["A"], limit=10, timeout_s=30)
