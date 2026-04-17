"""Unit tests for ``describe_table`` catalog orchestration."""

from __future__ import annotations

from typing import Any

import pytest

import nz_mcp.catalog.tables as tables_mod
from nz_mcp.catalog.tables import describe_table
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError, ObjectNotFoundError


class _RoutingCursor:
    """Return rows based on which catalog view the SQL targets."""

    def __init__(self, buckets: dict[str, Any]) -> None:
        self._buckets = buckets
        self.executed_sql: list[str] = []
        self.executed_params: list[tuple[str, str]] = []
        self.closed = False

    def execute(self, sql: str, params: tuple[str, str]) -> None:
        self.executed_sql.append(sql)
        self.executed_params.append(params)

    def fetchall(self) -> list[object]:
        sql_l = self.executed_sql[-1].lower()
        if "_v_relation_column" in sql_l:
            return list(self._buckets.get("columns", []))
        if "_v_table_dist_map" in sql_l:
            return list(self._buckets.get("dist", []))
        if "contype = 'f'" in sql_l:
            return list(self._buckets.get("fk", []))
        if "contype = 'p'" in sql_l:
            return list(self._buckets.get("pk", []))
        raise AssertionError(f"unexpected SQL bucket: {sql_l[:120]!r}")

    def close(self) -> None:
        self.closed = True


class _FakeConn:
    def __init__(self, cursor: _RoutingCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _RoutingCursor:
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


def test_describe_table_one_connection_four_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    buckets = {
        "columns": [
            ("ID", "INTEGER", True, None, 1),
            ("NM", "VARCHAR(10)", False, None, 2),
        ],
        "dist": [("ID", 1)],
        "pk": [("pk_cust", "ID", 1)],
        "fk": [],
    }
    cursor = _RoutingCursor(buckets)
    conn = _FakeConn(cursor)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: conn)
    monkeypatch.setattr(
        tables_mod,
        "resolve_query",
        lambda qid, _p: {
            "describe_table_columns": "SELECT ... FROM <BD>.._V_RELATION_COLUMN WHERE ...",
            "describe_table_distribution": "SELECT ... FROM <BD>.._V_TABLE_DIST_MAP WHERE ...",
            "describe_table_pk": (
                "SELECT ... FROM <BD>.._V_RELATION_KEYDATA WHERE ... AND CONTYPE = 'p' ..."
            ),
            "describe_table_fk": (
                "SELECT ... FROM <BD>.._V_RELATION_KEYDATA WHERE ... AND CONTYPE = 'f' ..."
            ),
        }[qid],
    )

    out = describe_table(_profile(), database="DB", schema="PUBLIC", table="T")

    assert len(cursor.executed_sql) == 4
    assert all(p == ("PUBLIC", "T") for p in cursor.executed_params)
    assert out["name"] == "T"
    assert out["kind"] == "TABLE"
    assert len(out["columns"]) == 2
    assert out["columns"][0]["type"] == "INTEGER"
    assert out["columns"][0]["nullable"] is False
    assert out["distribution"] == {"type": "HASH", "columns": ["ID"]}
    assert out["organized_on"] == []
    assert out["primary_key"] == ["ID"]
    assert out["foreign_keys"] == []
    assert conn.closed is True


def test_describe_table_random_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    buckets = {
        "columns": [("X", "INT", True, None, 1)],
        "dist": [],
        "pk": [],
        "fk": [],
    }
    cursor = _RoutingCursor(buckets)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: _FakeConn(cursor))
    monkeypatch.setattr(
        tables_mod,
        "resolve_query",
        lambda qid, _p: {
            "describe_table_columns": "_V_RELATION_COLUMN",
            "describe_table_distribution": "_V_TABLE_DIST_MAP",
            "describe_table_pk": "CONTYPE = 'p'",
            "describe_table_fk": "CONTYPE = 'f'",
        }[qid],
    )

    out = describe_table(_profile(), database="DB", schema="S", table="T")
    assert out["distribution"] == {"type": "RANDOM", "columns": []}


def test_describe_table_foreign_key_cross_database(monkeypatch: pytest.MonkeyPatch) -> None:
    buckets = {
        "columns": [("OID", "INT", True, None, 1)],
        "dist": [],
        "pk": [],
        "fk": [
            (
                "fk_ord",
                "ORDER_ID",
                1,
                "OTHERDB",
                "ORD",
                "ORDERS",
                "ID",
                "a",
                "b",
            ),
            (
                "fk_ord",
                "LINE_NO",
                2,
                "OTHERDB",
                "ORD",
                "ORDERS",
                "LINENO",
                "a",
                "b",
            ),
        ],
    }
    cursor = _RoutingCursor(buckets)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: _FakeConn(cursor))
    monkeypatch.setattr(
        tables_mod,
        "resolve_query",
        lambda qid, _p: {
            "describe_table_columns": "_V_RELATION_COLUMN",
            "describe_table_distribution": "_V_TABLE_DIST_MAP",
            "describe_table_pk": "CONTYPE = 'p'",
            "describe_table_fk": "CONTYPE = 'f'",
        }[qid],
    )

    out = describe_table(_profile(), database="DB", schema="S", table="LINES")
    assert len(out["foreign_keys"]) == 1
    fk = out["foreign_keys"][0]
    assert fk["name"] == "fk_ord"
    assert fk["columns"] == ["ORDER_ID", "LINE_NO"]
    assert fk["references"]["database"] == "OTHERDB"
    assert fk["references"]["schema"] == "ORD"
    assert fk["references"]["table"] == "ORDERS"
    assert fk["references"]["columns"] == ["ID", "LINENO"]


def test_describe_table_raises_when_no_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    buckets: dict[str, Any] = {"columns": [], "dist": [], "pk": [], "fk": []}
    cursor = _RoutingCursor(buckets)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: _FakeConn(cursor))
    monkeypatch.setattr(
        tables_mod,
        "resolve_query",
        lambda qid, _p: "_V_RELATION_COLUMN" if qid == "describe_table_columns" else "x",
    )

    with pytest.raises(ObjectNotFoundError) as exc:
        describe_table(_profile(), database="DB", schema="S", table="MISSING")

    assert exc.value.code == "OBJECT_NOT_FOUND"


def test_describe_table_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomCursor(_RoutingCursor):
        def fetchall(self) -> list[object]:
            raise RuntimeError("boom")

    cursor = _BoomCursor(
        {
            "columns": [("ID", "INT", True, None, 1)],
            "dist": [],
            "pk": [],
            "fk": [],
        },
    )
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "secret")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: _FakeConn(cursor))
    monkeypatch.setattr(
        tables_mod,
        "resolve_query",
        lambda qid, _p: "_V_RELATION_COLUMN",
    )

    with pytest.raises(NetezzaError) as exc:
        describe_table(_profile(), database="DB", schema="S", table="T")

    assert "boom" in exc.value.context["detail"]
    assert "secret" not in exc.value.context["detail"]


def test_describe_table_routing_detects_pk_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """PK query uses _V_RELATION_KEYDATA and CONTYPE P; ensure we route before FK."""
    buckets = {
        "columns": [("ID", "INT", True, None, 1)],
        "dist": [],
        "pk": [("pk1", "ID", 1)],
        "fk": [],
    }
    cursor = _RoutingCursor(buckets)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda *_a, **_k: _FakeConn(cursor))
    monkeypatch.setattr(
        tables_mod,
        "resolve_query",
        lambda qid, _p: {
            "describe_table_columns": "_V_RELATION_COLUMN",
            "describe_table_distribution": "_V_TABLE_DIST_MAP",
            "describe_table_pk": ("FROM <BD>.._V_RELATION_KEYDATA WHERE ... CONTYPE = 'p' ..."),
            "describe_table_fk": ("FROM <BD>.._V_RELATION_KEYDATA WHERE ... CONTYPE = 'f' ..."),
        }[qid],
    )

    describe_table(_profile(), database="DB", schema="S", table="T")
    joined = "\n".join(cursor.executed_sql).lower()
    assert "contype = 'p'" in joined
    assert "contype = 'f'" in joined
