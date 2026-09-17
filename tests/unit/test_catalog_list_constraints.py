"""Tests for the ``nz_list_constraints`` catalog query."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from nz_mcp.catalog.tables import list_constraints
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError, ObjectNotFoundError

_Params = tuple[str | None, ...]


class _FakeCursor:
    """Returns one canned result per ``execute()`` call, in call order."""

    def __init__(self, result_queue: list[list[object]]) -> None:
        self._queue = list(result_queue)
        self.closed = False
        self.calls: list[tuple[str, _Params]] = []
        self._current: list[object] = []

    def execute(self, sql: str, params: _Params) -> None:
        self.calls.append((sql, params))
        self._current = self._queue.pop(0) if self._queue else []

    def fetchall(self) -> Sequence[object]:
        return self._current

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
    "SELECT RELATION, CONSTRAINTNAME, CONTYPE, ATTNAME, CONSEQ "
    "FROM <BD>.._V_RELATION_KEYDATA "
    "WHERE SCHEMA = UPPER(?) AND CONTYPE IN ('p', 'f', 'u') "
    "AND (? IS NULL OR RELATION = UPPER(?)) "
    "ORDER BY RELATION, CONSTRAINTNAME, CONSEQ"
)
_OBJTYPE_SQL = "SELECT OBJTYPE FROM <BD>.._V_TABLE WHERE SCHEMA = UPPER(?) AND TABLENAME = UPPER(?)"


def _patch(monkeypatch: pytest.MonkeyPatch, connection: _FakeConnection) -> None:
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.resolve_query",
        lambda query_id, _profile: (
            _OBJTYPE_SQL if query_id == "describe_table_objtype" else _BASE_SQL
        ),
    )


def test_list_constraints_groups_multi_column_keys_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(
        result_queue=[
            [
                ("EFE_MC_CREDITOS", "PK_X", "p", "CODCREDITO", 1),
                ("EFE_MC_CREDITOS", "UQ_X", "u", "COL_B", 2),
                ("EFE_MC_CREDITOS", "UQ_X", "u", "COL_A", 1),
            ]
        ]
    )
    connection = _FakeConnection(cursor)
    _patch(monkeypatch, connection)

    out = list_constraints(_profile(), database="ANALYTICS", schema="DBO", table=None)

    assert out == [
        {"table": "EFE_MC_CREDITOS", "name": "PK_X", "type": "p", "columns": ["CODCREDITO"]},
        {"table": "EFE_MC_CREDITOS", "name": "UQ_X", "type": "u", "columns": ["COL_A", "COL_B"]},
    ]
    sql, params = cursor.calls[0]
    assert "_v_relation_keydata" in sql.lower()
    assert "<bd>" not in sql.lower()
    assert "ANALYTICS.." in sql
    assert params == ("DBO", None, None)
    assert cursor.closed is True
    assert connection.closed is True


def test_list_constraints_no_table_filter_never_checks_existence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(result_queue=[[]])
    connection = _FakeConnection(cursor)
    _patch(monkeypatch, connection)

    out = list_constraints(_profile(), database="DB", schema="DBO")
    assert out == []
    assert len(cursor.calls) == 1


def test_list_constraints_with_existing_table_and_no_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(result_queue=[[("TABLE",)], []])
    connection = _FakeConnection(cursor)
    _patch(monkeypatch, connection)

    out = list_constraints(_profile(), database="DB", schema="DBO", table="BAMURE_CLIENTE")
    assert out == []
    assert len(cursor.calls) == 2
    assert cursor.calls[1][1] == ("DBO", "BAMURE_CLIENTE", "BAMURE_CLIENTE")


def test_list_constraints_missing_table_raises_object_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(result_queue=[[]])
    connection = _FakeConnection(cursor)
    _patch(monkeypatch, connection)

    with pytest.raises(ObjectNotFoundError) as exc:
        list_constraints(_profile(), database="DB", schema="DBO", table="NOPE")

    assert exc.value.context["object_type"] == "table"
    assert len(cursor.calls) == 1
    assert cursor.closed is True
    assert connection.closed is True


def test_list_constraints_accepts_dict_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(
        result_queue=[
            [
                {
                    "RELATION": "T1",
                    "CONSTRAINTNAME": "PK_T1",
                    "CONTYPE": "p",
                    "ATTNAME": "ID",
                    "CONSEQ": 1,
                }
            ]
        ]
    )
    connection = _FakeConnection(cursor)
    _patch(monkeypatch, connection)

    out = list_constraints(_profile(), database="DB", schema="DBO")
    assert out == [{"table": "T1", "name": "PK_T1", "type": "p", "columns": ["ID"]}]


def test_list_constraints_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomCursor(_FakeCursor):
        def execute(self, sql: str, params: _Params) -> None:
            _ = (sql, params)
            raise RuntimeError("catalog unavailable")

    cursor = _BoomCursor(result_queue=[])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.tables.get_password", lambda _name: "known-test-pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.tables.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr("nz_mcp.catalog.tables.resolve_query", lambda _qid, _profile: _BASE_SQL)

    with pytest.raises(NetezzaError) as exc:
        list_constraints(_profile(), database="MYDB", schema="DBO")

    assert exc.value.code == "NETEZZA_ERROR"
    assert "catalog unavailable" in exc.value.context["detail"]
    assert "known-test-pw" not in exc.value.context["detail"]
    assert cursor.closed is True
    assert connection.closed is True


def test_list_constraints_rejects_bad_row_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(result_queue=[[("ONLYONE", "TWO")]])
    connection = _FakeConnection(cursor)
    _patch(monkeypatch, connection)

    with pytest.raises(NetezzaError):
        list_constraints(_profile(), database="DB", schema="DBO")


def test_list_constraints_rejects_dict_missing_required_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(result_queue=[[{"RELATION": "T1", "CONSTRAINTNAME": "PK_T1"}]])
    connection = _FakeConnection(cursor)
    _patch(monkeypatch, connection)

    with pytest.raises(NetezzaError) as exc:
        list_constraints(_profile(), database="DB", schema="DBO")

    assert "Catalog query must return" in exc.value.context["detail"]
