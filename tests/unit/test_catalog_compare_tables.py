"""Unit tests for ``compare_tables`` catalog function."""

from __future__ import annotations

from typing import Any

import pytest

import nz_mcp.catalog.tables as tables_mod
from nz_mcp.catalog.tables import compare_tables
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, NetezzaError, ObjectNotFoundError

_MOCK_QUERY = (
    "SELECT ATTNAME, FORMAT_TYPE, ATTNOTNULL, COLDEFAULT, ATTNUM "
    "FROM <BD>.._V_RELATION_COLUMN WHERE SCHEMA = UPPER(?) AND NAME = UPPER(?)"
)


class _CompareCursor:
    """Mock cursor returning columns for table A then table B."""

    def __init__(self, rows_a: list[Any], rows_b: list[Any]) -> None:
        self.rows_a = rows_a
        self.rows_b = rows_b
        self.executed_sql: list[str] = []
        self.executed_params: list[tuple[str, ...]] = []
        self.closed = False
        self._call_count = 0

    def execute(self, sql: str, params: tuple[str, ...]) -> None:
        self.executed_sql.append(sql)
        self.executed_params.append(params)
        self._call_count += 1

    def fetchall(self) -> list[object]:
        if self._call_count == 1:
            return list(self.rows_a)
        if self._call_count == 2:
            return list(self.rows_b)
        return []

    def close(self) -> None:
        self.closed = True


class _FakeConn:
    def __init__(self, cursor: _CompareCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _CompareCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _profile() -> Profile:
    return Profile(
        name="dev",
        host="h.example.com",
        port=5480,
        database="DEV",
        user="u",
        mode="read",
    )


def test_compare_tables_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    cols = [
        ("ID", "INTEGER", True, None, 1),
        ("NAME", "VARCHAR(50)", False, None, 2),
    ]
    cursor = _CompareCursor(rows_a=cols, rows_b=cols)
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    out = compare_tables(
        _profile(),
        database_a="DEV",
        schema_a="ADMIN",
        table_a="CUSTOMERS",
        database_b="DEV",
        schema_b="ADMIN",
        table_b="CUSTOMERS_COPY",
    )

    assert out["identical"] is True
    assert out["columns_in_a"] == 2
    assert out["columns_in_b"] == 2
    assert out["columns_in_common"] == 2
    assert out["only_in_a"] == []
    assert out["only_in_b"] == []
    assert out["type_mismatches"] == []
    assert out["position_mismatches"] == []
    assert conn.closed is True
    assert cursor.closed is True


def test_compare_tables_only_in_a_and_b(monkeypatch: pytest.MonkeyPatch) -> None:
    cols_a = [
        ("ID", "INTEGER", True, None, 1),
        ("EXTRA_A", "DATE", False, None, 2),
    ]
    cols_b = [
        ("ID", "INTEGER", True, None, 1),
        ("EXTRA_B", "TIMESTAMP", False, None, 2),
    ]
    cursor = _CompareCursor(rows_a=cols_a, rows_b=cols_b)
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    out = compare_tables(
        _profile(),
        database_a="DEV",
        schema_a="ADMIN",
        table_a="TAB_A",
        database_b="DEV",
        schema_b="ADMIN",
        table_b="TAB_B",
    )

    assert out["identical"] is False
    assert out["columns_in_a"] == 2
    assert out["columns_in_b"] == 2
    assert out["columns_in_common"] == 1
    assert out["only_in_a"] == [
        {"column": "EXTRA_A", "type": "DATE", "nullable": True, "position": 2}
    ]
    assert out["only_in_b"] == [
        {"column": "EXTRA_B", "type": "TIMESTAMP", "nullable": True, "position": 2}
    ]
    assert out["type_mismatches"] == []
    assert out["position_mismatches"] == []


def test_compare_tables_type_and_nullability_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    cols_a = [
        ("NUMDOC", "VARCHAR(12)", True, None, 1),
        ("STATUS", "CHAR(1)", True, None, 2),
    ]
    cols_b = [
        ("NUMDOC", "VARCHAR(4000)", False, None, 1),
        ("STATUS", "CHAR(1)", False, None, 2),
    ]
    cursor = _CompareCursor(rows_a=cols_a, rows_b=cols_b)
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    out = compare_tables(
        _profile(),
        database_a="DEV",
        schema_a="ADMIN",
        table_a="TAB_A",
        database_b="DEV",
        schema_b="ADMIN",
        table_b="TAB_B",
    )

    assert out["identical"] is False
    assert len(out["type_mismatches"]) == 2
    assert out["type_mismatches"][0] == {
        "column": "NUMDOC",
        "type_a": "VARCHAR(12)",
        "type_b": "VARCHAR(4000)",
        "nullable_a": False,
        "nullable_b": True,
    }
    assert out["type_mismatches"][1] == {
        "column": "STATUS",
        "type_a": "CHAR(1)",
        "type_b": "CHAR(1)",
        "nullable_a": False,
        "nullable_b": True,
    }


def test_compare_tables_position_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    cols_a = [
        ("COL_A", "INTEGER", True, None, 1),
        ("COL_B", "VARCHAR(10)", True, None, 2),
    ]
    cols_b = [
        ("COL_B", "VARCHAR(10)", True, None, 1),
        ("COL_A", "INTEGER", True, None, 2),
    ]
    cursor = _CompareCursor(rows_a=cols_a, rows_b=cols_b)
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    out = compare_tables(
        _profile(),
        database_a="DEV",
        schema_a="ADMIN",
        table_a="TAB_A",
        database_b="DEV",
        schema_b="ADMIN",
        table_b="TAB_B",
    )

    assert out["identical"] is False
    assert len(out["position_mismatches"]) == 2
    assert out["position_mismatches"][0] == {
        "column": "COL_A",
        "position_a": 1,
        "position_b": 2,
    }
    assert out["position_mismatches"][1] == {
        "column": "COL_B",
        "position_a": 2,
        "position_b": 1,
    }


def test_compare_tables_dict_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    dict_cols_a: list[Any] = [
        {"COLUMN_NAME": "ID", "DATA_TYPE": "BIGINT", "NOT_NULL": True, "ATTNUM": 1},
    ]
    dict_cols_b: list[Any] = [
        {"COLUMN_NAME": "id", "DATA_TYPE": "BIGINT", "NOT_NULL": True, "ATTNUM": 1},
    ]
    cursor = _CompareCursor(rows_a=dict_cols_a, rows_b=dict_cols_b)
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    out = compare_tables(
        _profile(),
        database_a="DEV",
        schema_a="ADMIN",
        table_a="TAB_A",
        database_b="DEV",
        schema_b="ADMIN",
        table_b="TAB_B",
    )

    assert out["identical"] is True


def test_compare_tables_missing_table_a(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _CompareCursor(rows_a=[], rows_b=[("ID", "INTEGER", True, None, 1)])
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    with pytest.raises(ObjectNotFoundError) as exc:
        compare_tables(
            _profile(),
            database_a="DEV",
            schema_a="ADMIN",
            table_a="NO_SUCH_TABLE_A",
            database_b="DEV",
            schema_b="ADMIN",
            table_b="TAB_B",
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"
    assert exc.value.context["table"] == "NO_SUCH_TABLE_A"


def test_compare_tables_missing_table_b(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _CompareCursor(rows_a=[("ID", "INTEGER", True, None, 1)], rows_b=[])
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    with pytest.raises(ObjectNotFoundError) as exc:
        compare_tables(
            _profile(),
            database_a="DEV",
            schema_a="ADMIN",
            table_a="TAB_A",
            database_b="DEV",
            schema_b="ADMIN",
            table_b="NO_SUCH_TABLE_B",
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"
    assert exc.value.context["table"] == "NO_SUCH_TABLE_B"


def test_compare_tables_driver_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ErrorConn:
        def cursor(self) -> Any:
            raise RuntimeError("network down")

        def close(self) -> None:
            pass

    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: _ErrorConn())
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    with pytest.raises(NetezzaError) as exc:
        compare_tables(
            _profile(),
            database_a="DEV",
            schema_a="ADMIN",
            table_a="TAB_A",
            database_b="DEV",
            schema_b="ADMIN",
            table_b="TAB_B",
        )
    assert exc.value.code == "NETEZZA_ERROR"


def test_compare_tables_dict_row_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = [{"COLUMN_NAME": "ID", "DATA_TYPE": "INTEGER"}]
    cursor = _CompareCursor(rows_a=bad, rows_b=[("ID", "INTEGER", True, None, 1)])
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    with pytest.raises(NetezzaError) as exc:
        compare_tables(
            _profile(),
            database_a="DEV",
            schema_a="ADMIN",
            table_a="TAB_A",
            database_b="DEV",
            schema_b="ADMIN",
            table_b="TAB_B",
        )
    assert exc.value.code == "NETEZZA_ERROR"


def test_compare_tables_unexpected_row_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _CompareCursor(rows_a=["not-a-row"], rows_b=[("ID", "INTEGER", True, None, 1)])
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _MOCK_QUERY)

    with pytest.raises(NetezzaError) as exc:
        compare_tables(
            _profile(),
            database_a="DEV",
            schema_a="ADMIN",
            table_a="TAB_A",
            database_b="DEV",
            schema_b="ADMIN",
            table_b="TAB_B",
        )
    assert exc.value.code == "NETEZZA_ERROR"


def test_compare_tables_invalid_identifier() -> None:
    with pytest.raises(InvalidInputError):
        compare_tables(
            _profile(),
            database_a="DEV; DROP DATABASE",
            schema_a="ADMIN",
            table_a="TAB_A",
            database_b="DEV",
            schema_b="ADMIN",
            table_b="TAB_B",
        )
