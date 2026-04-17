"""Unit tests for catalog DDL helpers."""

from __future__ import annotations

from typing import Any

import pytest

from nz_mcp.catalog.ddl import execute_create_table, execute_drop_table, execute_truncate
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate


def _admin_profile() -> Profile:
    return Profile(
        name="a",
        host="h",
        port=5480,
        database="DEV",
        user="u",
        mode="admin",
    )


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params or ()))

    @property
    def rowcount(self) -> int:
        return 0

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        pass


def test_execute_create_table_validates_core_and_distributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: fake)
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")

    prof = _admin_profile()
    out = execute_create_table(
        prof,
        database="DEV",
        schema="PUBLIC",
        table="T1",
        columns=[{"name": "ID", "type": "INTEGER", "nullable": False}],
        distribution=None,
        organized_on=None,
        if_not_exists=True,
    )
    assert out["created"] is True
    sql = out["ddl_executed"]
    assert "CREATE TABLE IF NOT EXISTS PUBLIC.T1" in sql
    assert "ID INTEGER NOT NULL" in sql
    assert "DISTRIBUTE ON RANDOM" in sql
    assert fake.cursor_obj.executed[0][0] == sql
    core = sql.split("\nDISTRIBUTE ON")[0]
    assert guard_validate(core, mode="admin").kind is StatementKind.CREATE


def test_execute_create_table_hash_and_organize(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: fake)
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")

    prof = _admin_profile()
    out = execute_create_table(
        prof,
        database="DEV",
        schema="PUBLIC",
        table="T2",
        columns=[{"name": "ID", "type": "INTEGER"}],
        distribution={"type": "HASH", "columns": ["ID"]},
        organized_on=["ID"],
        if_not_exists=False,
    )
    sql = str(out["ddl_executed"])
    assert "CREATE TABLE PUBLIC.T2" in sql
    assert "ORGANIZE ON (ID)" in sql
    assert "DISTRIBUTE ON HASH (ID)" in sql


def test_execute_create_table_wrong_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _FakeConn())
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    prof = _admin_profile()
    with pytest.raises(InvalidInputError):
        execute_create_table(
            prof,
            database="OTHER",
            schema="PUBLIC",
            table="T",
            columns=[{"name": "ID", "type": "INTEGER"}],
            distribution=None,
            organized_on=None,
            if_not_exists=True,
        )


def test_execute_truncate_and_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: fake)
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    prof = _admin_profile()

    t_out = execute_truncate(prof, "DEV", "PUBLIC", "T")
    assert t_out["truncated"] is True
    assert "duration_ms" in t_out
    assert "TRUNCATE TABLE PUBLIC.T" in fake.cursor_obj.executed[0][0]

    d_out = execute_drop_table(prof, "DEV", "PUBLIC", "T", if_exists=True)
    assert d_out["dropped"] is True
    assert "DROP TABLE IF EXISTS PUBLIC.T" in fake.cursor_obj.executed[-1][0]


def test_execute_drop_table_if_not_exists_false(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: fake)
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    prof = _admin_profile()
    execute_drop_table(prof, "DEV", "PUBLIC", "T", if_exists=False)
    assert fake.cursor_obj.executed[0][0] == "DROP TABLE PUBLIC.T"


class _BoomCursor:
    def execute(self, *_a: object, **_k: object) -> None:
        raise RuntimeError("nz oops")

    @property
    def rowcount(self) -> int:
        return 0

    def close(self) -> None:
        pass


class _BoomConn:
    def cursor(self) -> _BoomCursor:
        return _BoomCursor()

    def close(self) -> None:
        pass


def test_invalid_column_type_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _FakeConn())
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    prof = _admin_profile()
    with pytest.raises(InvalidInputError):
        execute_create_table(
            prof,
            database="DEV",
            schema="PUBLIC",
            table="T",
            columns=[{"name": "ID", "type": "INTEGER; DROP"}],
            distribution=None,
            organized_on=None,
            if_not_exists=True,
        )


def test_invalid_default_type_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _FakeConn())
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    prof = _admin_profile()
    with pytest.raises(InvalidInputError):
        execute_create_table(
            prof,
            database="DEV",
            schema="PUBLIC",
            table="T",
            columns=[{"name": "ID", "type": "INTEGER", "default": [1, 2]}],
            distribution=None,
            organized_on=None,
            if_not_exists=True,
        )


def test_distribution_hash_requires_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _FakeConn())
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    prof = _admin_profile()
    with pytest.raises(InvalidInputError):
        execute_create_table(
            prof,
            database="DEV",
            schema="PUBLIC",
            table="T",
            columns=[{"name": "ID", "type": "INTEGER"}],
            distribution={"type": "HASH", "columns": []},
            organized_on=None,
            if_not_exists=True,
        )


def test_execute_propagates_netezza_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _BoomConn())
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    prof = _admin_profile()
    with pytest.raises(NetezzaError):
        execute_truncate(prof, "DEV", "PUBLIC", "T")
