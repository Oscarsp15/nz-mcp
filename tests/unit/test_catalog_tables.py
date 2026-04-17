"""Tests for table catalog queries."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from nz_mcp.catalog.tables import list_tables
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError


class _FakeCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.closed = False
        self.executed_sql: str | None = None
        self.executed_params: tuple[str, str | None, str | None] | None = None

    def execute(
        self,
        sql: str,
        params: tuple[str, str | None, str | None],
    ) -> None:
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


def test_list_tables_queries_catalog_with_optional_like(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[("T1", "OWN"), ("T2", "OWN")])
    connection = _FakeConnection(cursor)

    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda _query_id, _profile: (
            "SELECT TABLENAME AS NAME, OWNER FROM <BD>.._V_TABLE "
            "WHERE SCHEMA = UPPER(?) AND OBJTYPE='TABLE' "
            "AND (? IS NULL OR TABLENAME LIKE ?) ORDER BY TABLENAME"
        ),
    )

    out = list_tables(_profile(), database="ANALYTICS", schema="PUBLIC", pattern="T%")

    assert out == [
        {"name": "T1", "kind": "TABLE"},
        {"name": "T2", "kind": "TABLE"},
    ]
    assert cursor.executed_sql is not None
    assert "_v_table" in cursor.executed_sql.lower()
    assert "<bd>" not in cursor.executed_sql.lower()
    assert "ANALYTICS.." in cursor.executed_sql
    assert cursor.executed_params == ("PUBLIC", "T%", "T%")
    assert cursor.closed is True
    assert connection.closed is True


def test_list_tables_accepts_dict_rows_with_name_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[{"NAME": "T1", "OWNER": "O"}])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda _query_id, _profile: "SELECT TABLENAME AS NAME, OWNER FROM <BD>.._V_TABLE",
    )

    out = list_tables(_profile(), database="DB", schema="S", pattern=None)
    assert out == [{"name": "T1", "kind": "TABLE"}]


def test_list_tables_accepts_dict_rows_with_tablename(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[{"TABLENAME": "T1", "OWNER": "O"}])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda _query_id, _profile: "SELECT TABLENAME, OWNER FROM <BD>.._V_TABLE",
    )

    out = list_tables(_profile(), database="DB", schema="S", pattern=None)
    assert out == [{"name": "T1", "kind": "TABLE"}]


def test_list_tables_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomCursor(_FakeCursor):
        def execute(
            self,
            sql: str,
            params: tuple[str, str | None, str | None],
        ) -> None:
            _ = (sql, params)
            raise RuntimeError("catalog unavailable")

    cursor = _BoomCursor(rows=[])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "known-test-pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda _query_id, _profile: "SELECT TABLENAME AS NAME, OWNER FROM <BD>.._V_TABLE",
    )

    with pytest.raises(NetezzaError) as exc:
        list_tables(_profile(), database="MYDB", schema="PUB", pattern=None)

    assert exc.value.code == "NETEZZA_ERROR"
    assert "catalog unavailable" in exc.value.context["detail"]
    assert "known-test-pw" not in exc.value.context["detail"]
    assert cursor.closed is True
    assert connection.closed is True


def test_list_tables_rejects_bad_row_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[("ONLYONE",)])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda _query_id, _profile: "SELECT TABLENAME AS NAME, OWNER FROM <BD>.._V_TABLE",
    )

    with pytest.raises(NetezzaError) as exc:
        list_tables(_profile(), database="MYDB", schema="X")

    assert "Unexpected row shape" in exc.value.context["detail"]


def test_list_tables_rejects_dict_without_name(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[{"OWNER": "O"}])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda _query_id, _profile: "SELECT TABLENAME AS NAME, OWNER FROM <BD>.._V_TABLE",
    )

    with pytest.raises(NetezzaError) as exc:
        list_tables(_profile(), database="MYDB", schema="X")

    assert "Catalog query must return" in exc.value.context["detail"]
