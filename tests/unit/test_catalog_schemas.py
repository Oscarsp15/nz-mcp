"""Tests for schema catalog queries."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from nz_mcp.catalog.schemas import list_schemas
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


def test_list_schemas_queries_catalog_with_optional_like(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[("PUBLIC", "ADMIN"), ("STG", "ETL")])
    connection = _FakeConnection(cursor)

    monkeypatch.setattr("nz_mcp.catalog.schemas.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.schemas.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.schemas.resolve_query",
        lambda _query_id, _profile: (
            "SELECT SCHEMA, OWNER FROM <BD>.._V_SCHEMA WHERE (? IS NULL OR SCHEMA LIKE UPPER(?))"
        ),
    )

    out = list_schemas(_profile(), database="ANALYTICS", pattern="P%")

    assert out == [
        {"name": "PUBLIC", "owner": "ADMIN"},
        {"name": "STG", "owner": "ETL"},
    ]
    assert cursor.executed_sql is not None
    assert "_v_schema" in cursor.executed_sql.lower()
    assert "<bd>" not in cursor.executed_sql.lower()
    assert "ANALYTICS.." in cursor.executed_sql
    assert cursor.executed_params == ("P%", "P%")
    assert cursor.closed is True
    assert connection.closed is True


def test_list_schemas_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple[str | None, str | None]) -> None:
            _ = (sql, params)
            raise RuntimeError("catalog unavailable")

    cursor = _BoomCursor(rows=[])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.schemas.get_password", lambda _name: "known-test-pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.schemas.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.schemas.resolve_query",
        lambda _query_id, _profile: "SELECT SCHEMA, OWNER FROM <BD>.._V_SCHEMA",
    )

    with pytest.raises(NetezzaError) as exc:
        list_schemas(_profile(), database="MYDB", pattern=None)

    assert exc.value.code == "NETEZZA_ERROR"
    assert "catalog unavailable" in exc.value.context["detail"]
    assert "known-test-pw" not in exc.value.context["detail"]
    assert cursor.closed is True
    assert connection.closed is True


def test_list_schemas_rejects_bad_row_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(rows=[("ONLYONE",)])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.schemas.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.schemas.open_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.schemas.resolve_query",
        lambda _query_id, _profile: "SELECT SCHEMA, OWNER FROM <BD>.._V_SCHEMA",
    )

    with pytest.raises(NetezzaError) as exc:
        list_schemas(_profile(), database="MYDB")

    assert "Unexpected row shape" in exc.value.context["detail"]


# ── issue #123: case-insensitive ``pattern`` matching ───────────────────────


class _CaseInsensitiveSchemaCursor(_FakeCursor):
    """Stub cursor that simulates Netezza's ``LIKE UPPER(?)`` semantics."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(rows=[])
        self._names = names

    def execute(self, sql: str, params: tuple[str | None, str | None]) -> None:
        super().execute(sql, params)
        marker, pattern = params
        if marker is None or pattern is None:
            self.rows = [(n, "OWN") for n in self._names]
            return
        upper = pattern.upper()
        if "%" in upper:
            needle = upper.strip("%")
            self.rows = [(n, "OWN") for n in self._names if needle in n]
        else:
            self.rows = [(n, "OWN") for n in self._names if n == upper]


@pytest.mark.parametrize(
    "pattern",
    ["dbo", "DBO", "Dbo"],
    ids=["all-lower", "all-upper", "mixed-case"],
)
def test_list_schemas_pattern_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    pattern: str,
) -> None:
    """Issue #123: a pattern in any case must match the upper-case catalog ``SCHEMA``."""
    cursor = _CaseInsensitiveSchemaCursor(names=["DBO", "ETL"])
    connection = _FakeConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.schemas.get_password", lambda _name: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.schemas.open_connection",
        lambda *_args, **_kwargs: connection,
    )

    out = list_schemas(_profile(), database="PROD_MAESTROBI", pattern=pattern)

    assert out == [{"name": "DBO", "owner": "OWN"}]
    assert cursor.executed_sql is not None
    assert "LIKE UPPER(?)" in " ".join(cursor.executed_sql.split())
