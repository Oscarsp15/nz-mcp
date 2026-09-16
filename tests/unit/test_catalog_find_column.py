"""Tests for the ``nz_find_column`` catalog query."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from nz_mcp.catalog.tables import find_columns
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError

_FindColumnParams = tuple[str, str | None, str | None, str | None, str | None]


class _FakeCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.closed = False
        self.executed_sql: str | None = None
        self.executed_params: _FindColumnParams | None = None

    def execute(self, sql: str, params: _FindColumnParams) -> None:
        self.executed_sql = sql
        self.executed_params = params

    def fetchall(self) -> Sequence[object]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _profile() -> Profile:
    return Profile(
        name="dev",
        host="nz-dev.example.com",
        port=5480,
        database="DEV",
        user="svc_dev",
        mode="read",
    )


_BASE_SQL = (
    "SELECT SCHEMA, NAME, ATTNAME, FORMAT_TYPE FROM <BD>.._V_RELATION_COLUMN "
    "WHERE TYPE IN ('TABLE', 'VIEW') AND ATTNAME LIKE UPPER(?) "
    "AND (? IS NULL OR SCHEMA LIKE UPPER(?)) AND (? IS NULL OR NAME LIKE UPPER(?)) "
    "ORDER BY SCHEMA, NAME, ATTNAME"
)


def test_find_columns_queries_catalog_with_optional_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(
        rows=[
            ("DBO", "CUSTOMERS", "NUMDOCUMENTO", "CHARACTER VARYING(12)"),
            ("ADMIN", "PRODUCTS", "NUMDOCUMENTO", "BIGINT"),
        ]
    )
    connection = _FakeConnection(cursor)

    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda _query_id, _profile: _BASE_SQL,
    )

    out = find_columns(
        _profile(),
        database="ANALYTICS",
        column_pattern="%NUMDOCUMENTO%",
        schema_pattern="DB%",
        table_pattern=None,
    )

    assert out == [
        {
            "schema": "DBO",
            "table": "CUSTOMERS",
            "column": "NUMDOCUMENTO",
            "type": "CHARACTER VARYING(12)",
        },
        {"schema": "ADMIN", "table": "PRODUCTS", "column": "NUMDOCUMENTO", "type": "BIGINT"},
    ]
    assert cursor.executed_sql is not None
    assert "_v_relation_column" in cursor.executed_sql.lower()
    assert "<bd>" not in cursor.executed_sql.lower()
    assert "ANALYTICS.." in cursor.executed_sql
    assert cursor.executed_params == ("%NUMDOCUMENTO%", "DB%", "DB%", None, None)
    assert cursor.closed is True
    assert connection.closed is True


def test_find_columns_accepts_dict_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(
        rows=[{"SCHEMA": "DBO", "NAME": "T1", "ATTNAME": "COL1", "FORMAT_TYPE": "INTEGER"}]
    )
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr("nz_mcp.catalog.tables.resolve_query", lambda _qid, _profile: _BASE_SQL)

    out = find_columns(_profile(), database="DB", column_pattern="COL%")
    assert out == [{"schema": "DBO", "table": "T1", "column": "COL1", "type": "INTEGER"}]


def test_find_columns_no_match_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr("nz_mcp.catalog.tables.resolve_query", lambda _qid, _profile: _BASE_SQL)

    out = find_columns(_profile(), database="DB", column_pattern="NOPE%")
    assert out == []


def test_find_columns_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomCursor(_FakeCursor):
        def execute(self, sql: str, params: _FindColumnParams) -> None:
            _ = (sql, params)
            raise RuntimeError("catalog unavailable")

    cursor = _BoomCursor(rows=[])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "known-test-pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr("nz_mcp.catalog.tables.resolve_query", lambda _qid, _profile: _BASE_SQL)

    with pytest.raises(NetezzaError) as exc:
        find_columns(_profile(), database="MYDB", column_pattern="X%")

    assert exc.value.code == "NETEZZA_ERROR"
    assert "catalog unavailable" in exc.value.context["detail"]
    assert "known-test-pw" not in exc.value.context["detail"]
    assert cursor.closed is True
    assert connection.closed is True


def test_find_columns_rejects_bad_row_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[("ONLYONE", "TWO")])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr("nz_mcp.catalog.tables.resolve_query", lambda _qid, _profile: _BASE_SQL)

    with pytest.raises(NetezzaError):
        find_columns(_profile(), database="DB", column_pattern="X%")


def test_find_columns_rejects_dict_missing_required_key(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[{"SCHEMA": "DBO", "NAME": "T1"}])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr("nz_mcp.catalog.tables.resolve_query", lambda _qid, _profile: _BASE_SQL)

    with pytest.raises(NetezzaError) as exc:
        find_columns(_profile(), database="MYDB", column_pattern="X%")

    assert "Catalog query must return" in exc.value.context["detail"]
