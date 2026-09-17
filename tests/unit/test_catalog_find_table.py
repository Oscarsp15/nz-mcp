"""Tests for the cross-database table/view name search (``find_tables``)."""

from __future__ import annotations

from typing import Any

import pytest

import nz_mcp.catalog.tables as tables_mod
from nz_mcp.catalog.tables import find_tables
from nz_mcp.config import Profile
from nz_mcp.errors import InputTooBroadError, NetezzaError, ObjectNotFoundError

_SQL = (
    "SELECT SCHEMA, NAME, KIND FROM <BD>.._V_TABLE "
    "UNION ALL SELECT SCHEMA, VIEWNAME AS NAME, KIND FROM <BD>.._V_VIEW"
)


class _FakeCursor:
    def __init__(self, results_by_db: dict[str, list[object]]) -> None:
        self._results_by_db = results_by_db
        self._current = ""
        self.executed_sql: list[str] = []
        self.closed = False

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed_sql.append(sql)
        self._current = sql

    def fetchall(self) -> list[object]:
        for db_name, rows in self._results_by_db.items():
            if f"{db_name}.." in self._current:
                return list(rows)
        return []

    def close(self) -> None:
        self.closed = True


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _profile() -> Profile:
    return Profile(name="dev", host="h", port=5480, database="DEV", user="u", mode="read")


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    databases: list[str],
    results_by_db: dict[str, list[object]],
) -> _FakeCursor:
    cursor = _FakeCursor(results_by_db)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(
        tables_mod,
        "list_databases",
        lambda _p, pattern=None: [{"name": name} for name in databases],
    )
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: _FakeConn(cursor))
    monkeypatch.setattr(tables_mod, "resolve_query", lambda _qid, _p: _SQL)
    return cursor


def test_find_tables_scans_every_visible_database(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _wire(
        monkeypatch,
        databases=["DB1", "DB2"],
        results_by_db={
            "DB1": [("DBO", "T_A", "TABLE")],
            "DB2": [("DBO", "T_B", "EXTERNAL TABLE")],
        },
    )

    rows, truncated = find_tables(
        _profile(),
        table_pattern="T%",
        database=None,
        schema_pattern=None,
        object_type="ALL",
        max_rows=10,
    )

    assert truncated is False
    assert rows == [
        {"database": "DB1", "schema": "DBO", "name": "T_A", "kind": "TABLE"},
        {"database": "DB2", "schema": "DBO", "name": "T_B", "kind": "EXTERNAL TABLE"},
    ]
    assert len(cursor.executed_sql) == 2


def test_find_tables_stops_after_one_extra_match(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _wire(
        monkeypatch,
        databases=["DB1", "DB2"],
        results_by_db={
            "DB1": [("DBO", "A", "TABLE"), ("DBO", "B", "TABLE"), ("DBO", "C", "TABLE")],
            "DB2": [("DBO", "D", "TABLE")],
        },
    )

    rows, truncated = find_tables(
        _profile(),
        table_pattern="T%",
        database=None,
        schema_pattern=None,
        object_type="TABLE",
        max_rows=2,
    )

    assert truncated is True
    assert len(rows) == 3  # max_rows + 1, enough to know more exist
    # DB2 is never queried: the scan stopped as soon as one extra match was found.
    assert len(cursor.executed_sql) == 1


def test_find_tables_single_database_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _wire(
        monkeypatch,
        databases=["DB1", "DB2"],
        results_by_db={"DB2": [("DBO", "T_B", "TABLE")]},
    )

    rows, truncated = find_tables(
        _profile(),
        table_pattern="T%",
        database="db2",
        schema_pattern=None,
        object_type="TABLE",
        max_rows=10,
    )

    assert truncated is False
    assert rows == [{"database": "DB2", "schema": "DBO", "name": "T_B", "kind": "TABLE"}]
    assert len(cursor.executed_sql) == 1


def test_find_tables_rejects_invisible_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, databases=["DB1"], results_by_db={})

    with pytest.raises(ObjectNotFoundError) as exc:
        find_tables(
            _profile(),
            table_pattern="T%",
            database="NOPE",
            schema_pattern=None,
            object_type="TABLE",
            max_rows=10,
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"


def test_find_tables_bad_row_shape_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, databases=["DB1"], results_by_db={"DB1": [("ONLY_ONE",)]})

    with pytest.raises(NetezzaError) as exc:
        find_tables(
            _profile(),
            table_pattern="T%",
            database=None,
            schema_pattern=None,
            object_type="TABLE",
            max_rows=10,
        )
    assert "row shape" in exc.value.context["detail"]


# --- cost guard (issue #361) --------------------------------------------------


def test_find_tables_refuses_a_wildcard_only_pattern_without_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pattern of wildcards matches everything: refuse before opening a connection."""
    cursor = _wire(monkeypatch, databases=["DB1", "DB2"], results_by_db={})
    opened: list[object] = []

    def _no_connection(*args: object, **_kwargs: object) -> object:
        opened.append(args)
        raise AssertionError("the guard must refuse before opening a connection")

    monkeypatch.setattr(tables_mod, "open_connection", _no_connection)

    with pytest.raises(InputTooBroadError) as exc:
        find_tables(
            _profile(),
            table_pattern="%",
            database=None,
            schema_pattern=None,
            object_type="TABLE",
            max_rows=10,
        )

    assert exc.value.code == "INPUT_TOO_BROAD"
    assert exc.value.context["scanned"] == 2
    assert exc.value.context["pattern"] == "%"
    assert exc.value.context["hint_es"]
    assert exc.value.context["hint_en"]
    assert opened == []
    assert cursor.executed_sql == []


def test_find_tables_allows_a_specific_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _wire(
        monkeypatch,
        databases=["DB1", "DB2"],
        results_by_db={"DB1": [("DBO", "T_A", "TABLE")]},
    )

    rows, truncated = find_tables(
        _profile(),
        table_pattern="T%",
        database=None,
        schema_pattern=None,
        object_type="TABLE",
        max_rows=10,
    )

    assert truncated is False
    assert [row["name"] for row in rows] == ["T_A"]
    assert len(cursor.executed_sql) == 2


def test_find_tables_named_database_is_never_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The escape the hint points at: naming a database bounds the sweep to one."""
    cursor = _wire(
        monkeypatch,
        databases=["DB1"],
        results_by_db={"DB1": [("DBO", "T_A", "TABLE")]},
    )

    rows, _truncated = find_tables(
        _profile(),
        table_pattern="%",
        database="db1",
        schema_pattern=None,
        object_type="TABLE",
        max_rows=10,
    )

    assert [row["name"] for row in rows] == ["T_A"]
    assert len(cursor.executed_sql) == 1


@pytest.mark.parametrize(
    ("pattern", "narrows"),
    [
        ("%", False),
        ("%%", False),
        ("_", False),
        ("%_%", False),
        ("____", False),
        ("T%", True),
        ("%T%", True),
        ("ventas", True),
        ("v_ntas", True),
    ],
)
def test_narrows_anything_tells_a_search_from_a_sweep(pattern: str, narrows: bool) -> None:
    assert tables_mod._narrows_anything(pattern) is narrows
