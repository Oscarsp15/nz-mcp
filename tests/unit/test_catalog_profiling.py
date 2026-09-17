"""Tests for column profiling catalog queries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pytest

from nz_mcp.catalog.profiling import _stringify, profile_column
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, ObjectNotFoundError


class _FakeCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.closed = False

    def execute(self, sql: str, params: tuple[str, str]) -> None:
        return None

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


def _wire_catalog(monkeypatch: pytest.MonkeyPatch, rows: list[object]) -> None:
    connection = _FakeConnection(_FakeCursor(rows))
    monkeypatch.setattr("nz_mcp.catalog.profiling.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.profiling.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.profiling.resolve_query",
        lambda _query_id, _profile: (
            "SELECT ATTNAME AS COLUMN_NAME FROM <BD>.._V_RELATION_COLUMN "
            "WHERE SCHEMA = UPPER(?) AND NAME = UPPER(?)"
        ),
    )


def _wire_execute(monkeypatch: pytest.MonkeyPatch, *, aggregate: list[object]) -> list[str]:
    seen: list[str] = []

    def _exec(_profile: object, sql: str, *, max_rows: int, timeout_s: int) -> dict[str, object]:
        seen.append(sql)
        if "GROUP BY" in sql:
            return {"rows": [["A", 60], ["B", 35]], "row_count": 2}
        return {"rows": [aggregate], "row_count": 1}

    monkeypatch.setattr("nz_mcp.catalog.profiling.execute_select", _exec)
    return seen


def test_profile_column_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_catalog(monkeypatch, rows=[("ID",), ("FECHA",)])
    seen = _wire_execute(
        monkeypatch,
        aggregate=[100, 5, 3, "2026-04-01", "2026-06-30"],
    )

    out = profile_column(_profile(), "DEV", "PUBLIC", "T", "FECHA", top_n=10, timeout_s=30)

    assert out["total"] == 100
    assert out["nulls"] == 5
    assert out["null_pct"] == 5.0
    assert out["distinct"] == 3
    assert out["min"] == "2026-04-01"
    assert out["max"] == "2026-06-30"
    assert out["top_values"] == [{"value": "A", "count": 60}, {"value": "B", "count": 35}]
    top_sql = next(sql for sql in seen if "GROUP BY" in sql)
    assert "LIMIT 10" in top_sql


def test_profile_column_empty_table_reports_zero_nulls(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_catalog(monkeypatch, rows=[("ID",)])
    _wire_execute(monkeypatch, aggregate=[0, None, 0, None, None])

    out = profile_column(_profile(), "DEV", "PUBLIC", "T", "ID", top_n=10, timeout_s=30)

    assert out["total"] == 0
    assert out["nulls"] == 0
    assert out["null_pct"] == 0.0
    assert out["min"] is None
    assert out["max"] is None


def test_profile_column_table_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_catalog(monkeypatch, rows=[])
    _wire_execute(monkeypatch, aggregate=[0, None, 0, None, None])

    with pytest.raises(ObjectNotFoundError) as exc:
        profile_column(_profile(), "DEV", "PUBLIC", "MISSING", "ID", top_n=10, timeout_s=30)
    assert exc.value.context["object_type"] == "table"


def test_profile_column_column_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_catalog(monkeypatch, rows=[("ID",), ("OTRA",)])
    _wire_execute(monkeypatch, aggregate=[0, None, 0, None, None])

    with pytest.raises(ObjectNotFoundError) as exc:
        profile_column(_profile(), "DEV", "PUBLIC", "T", "FECHA", top_n=10, timeout_s=30)
    assert exc.value.context["object_type"] == "column"
    assert exc.value.context["column"] == "FECHA"


def test_profile_column_rejects_cross_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_catalog(monkeypatch, rows=[("ID",)])
    _wire_execute(monkeypatch, aggregate=[1, 0, 1, None, None])

    with pytest.raises(InvalidInputError):
        profile_column(_profile(), "OTRA_BD", "PUBLIC", "T", "ID", top_n=10, timeout_s=30)


def test_stringify_uses_isoformat_for_dates() -> None:
    assert _stringify(date(2026, 4, 1)) == "2026-04-01"
    assert _stringify(None) is None
    assert _stringify(42) == "42"
