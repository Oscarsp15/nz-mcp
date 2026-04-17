"""Tests for database catalog queries."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from nz_mcp.catalog.databases import list_databases
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError


class _FakeCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.closed = False
        self.executed_sql: str | None = None
        self.executed_params: tuple[str | None, str | None] | None = None

    def execute(self, sql: str, params: tuple[str | None, str | None]) -> None:
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


def test_list_databases_queries_catalog_with_optional_like(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[("DEV", "ADMIN"), ("DATA", "DBA")])
    connection = _FakeConnection(cursor)

    monkeypatch.setattr("nz_mcp.catalog.databases.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.resolve_query",
        lambda _query_id, _profile: "SELECT DATABASE, OWNER FROM _V_DATABASE",
    )

    out = list_databases(_profile(), pattern="D%")

    assert out == [{"name": "DEV", "owner": "ADMIN"}, {"name": "DATA", "owner": "DBA"}]
    assert cursor.executed_sql is not None and "_v_database" in cursor.executed_sql.lower()
    assert cursor.executed_params == ("D%", "D%")
    assert cursor.closed is True
    assert connection.closed is True


def test_list_databases_wraps_driver_errors_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoomCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple[str | None, str | None]) -> None:
            _ = (sql, params)
            raise RuntimeError("catalog unavailable")

    cursor = _BoomCursor(rows=[])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.databases.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.resolve_query",
        lambda _query_id, _profile: "SELECT DATABASE, OWNER FROM _V_DATABASE",
    )

    with pytest.raises(NetezzaError) as exc:
        list_databases(_profile(), pattern=None)

    assert exc.value.code == "NETEZZA_ERROR"
    assert "catalog unavailable" in exc.value.context["detail"]
    assert cursor.closed is True
    assert connection.closed is True


def test_list_databases_rejects_unexpected_row_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_rows: list[object] = [("DEV",)]

    class _BadCursor(_FakeCursor):
        def __init__(self) -> None:
            self.rows = bad_rows
            self.closed = False
            self.executed_sql = None
            self.executed_params = None

        def fetchall(self) -> Sequence[object]:
            return self.rows

    cursor = _BadCursor()
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.databases.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.resolve_query",
        lambda _query_id, _profile: "SELECT DATABASE, OWNER FROM _V_DATABASE",
    )

    with pytest.raises(NetezzaError) as exc:
        list_databases(_profile())

    assert exc.value.code == "NETEZZA_ERROR"


def test_list_databases_fails_with_clear_error_on_override_semantic_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DictCursor(_FakeCursor):
        def __init__(self) -> None:
            super().__init__(rows=[])

        def fetchall(self) -> Sequence[object]:
            return [{"DBNAME": "DEV", "DBOWNER": "ADMIN"}]

    cursor = _DictCursor()
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.databases.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.databases.resolve_query",
        lambda _query_id, _profile: "SELECT DBNAME, DBOWNER FROM _V_DATABASE",
    )

    with pytest.raises(NetezzaError) as exc:
        list_databases(_profile())

    assert exc.value.code == "NETEZZA_ERROR"
    assert "DATABASE and OWNER columns" in exc.value.context["detail"]
