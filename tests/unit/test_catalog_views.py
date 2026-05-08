"""Tests for view catalog queries."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from nz_mcp.catalog.views import get_view_ddl, list_views
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError


class _FakeListCursor:
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


class _FakeDdlCursor:
    def __init__(self, one: object | None) -> None:
        self._one = one
        self.closed = False
        self.executed_sql: str | None = None
        self.executed_params: tuple[str, str] | None = None

    def execute(self, sql: str, params: tuple[str, str]) -> None:
        self.executed_sql = sql
        self.executed_params = params

    def fetchone(self) -> object | None:
        return self._one

    def close(self) -> None:
        self.closed = True


class _FakeListConnection:
    def __init__(self, cursor: _FakeListCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeListCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class _FakeDdlConnection:
    def __init__(self, cursor: _FakeDdlCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeDdlCursor:
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


def test_list_views_queries_catalog_with_optional_like(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeListCursor(rows=[("V1", "A"), ("V2", "A")])
    connection = _FakeListConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr(
        "nz_mcp.catalog.views.open_connection",
        lambda *_a, **_k: connection,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: (
            "SELECT VIEWNAME AS NAME, OWNER, X FROM <BD>.._V_VIEW "
            "WHERE SCHEMA = UPPER(?) AND (? IS NULL OR VIEWNAME LIKE UPPER(?)) "
            "ORDER BY VIEWNAME"
        ),
    )

    out = list_views(_profile(), database="ANALYTICS", schema="PUBLIC", pattern="V%")
    assert out == [
        {"name": "V1", "owner": "A"},
        {"name": "V2", "owner": "A"},
    ]
    assert cursor.executed_params == ("PUBLIC", "V%", "V%")
    assert "_v_view" in (cursor.executed_sql or "").lower()
    assert "ANALYTICS.." in (cursor.executed_sql or "")


def test_list_views_dict_row_with_name_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeListCursor(rows=[{"NAME": "V1", "OWNER": "O", "CREATEDATE": None}])
    connection = _FakeListConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT VIEWNAME AS NAME, OWNER FROM <BD>.._V_VIEW",
    )
    assert list_views(_profile(), database="DB", schema="S") == [{"name": "V1", "owner": "O"}]


def test_list_views_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom(_FakeListCursor):
        def execute(
            self,
            sql: str,
            params: tuple[str, str | None, str | None],
        ) -> None:
            _ = (sql, params)
            raise RuntimeError("catalog down")

    cursor = _Boom(rows=[])
    connection = _FakeListConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "secret-pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT VIEWNAME AS NAME FROM <BD>.._V_VIEW",
    )

    with pytest.raises(NetezzaError) as exc:
        list_views(_profile(), database="X", schema="Y")

    assert "catalog down" in exc.value.context["detail"]
    assert "secret-pw" not in exc.value.context["detail"]


# ── issue #123: case-insensitive ``pattern`` matching ───────────────────────


class _CaseInsensitiveLikeListCursor:
    """Fake cursor that simulates Netezza's ``LIKE UPPER(?)`` semantics."""

    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.executed_sql: str | None = None
        self.executed_params: tuple[str, str | None, str | None] | None = None
        self.closed = False

    def execute(self, sql: str, params: tuple[str, str | None, str | None]) -> None:
        self.executed_sql = sql
        self.executed_params = params

    def fetchall(self) -> list[tuple[str, str]]:
        if self.executed_params is None:
            return []
        _, marker, pattern = self.executed_params
        if marker is None or pattern is None:
            return [(n, "OWN") for n in self._names]
        upper = pattern.upper()
        if "%" not in upper:
            return [(n, "OWN") for n in self._names if n == upper]
        needle = upper.strip("%")
        return [(n, "OWN") for n in self._names if needle in n]

    def close(self) -> None:
        self.closed = True


class _CaseInsensitiveListConnection:
    def __init__(self, cursor: _CaseInsensitiveLikeListCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _CaseInsensitiveLikeListCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "pattern",
    [
        "v_CONTINGENCIACREDITOSFULL",
        "V_CONTINGENCIACREDITOSFULL",
        "V_contingenciacreditosFULL",
        "%contingenciacreditosfull%",
        "%CONTINGENCIACREDITOSFULL%",
    ],
    ids=[
        "all-lower-prefix",
        "all-upper",
        "mixed-case",
        "lower-with-wildcards",
        "upper-with-wildcards",
    ],
)
def test_list_views_pattern_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    pattern: str,
) -> None:
    """Issue #123: pattern in any case matches Netezza's upper-case ``VIEWNAME``."""
    cursor = _CaseInsensitiveLikeListCursor(names=["V_CONTINGENCIACREDITOSFULL"])
    connection = _CaseInsensitiveListConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)

    out = list_views(_profile(), database="PROD_MAESTROBI", schema="DBO", pattern=pattern)

    assert out == [{"name": "V_CONTINGENCIACREDITOSFULL", "owner": "OWN"}]
    assert cursor.executed_sql is not None
    assert "LIKE UPPER(?)" in " ".join(cursor.executed_sql.split())


def test_list_views_rejects_bad_row_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeListCursor(rows=[("only",)])
    connection = _FakeListConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT VIEWNAME AS NAME, OWNER FROM <BD>.._V_VIEW",
    )

    with pytest.raises(NetezzaError) as exc:
        list_views(_profile(), database="D", schema="S")

    assert "Unexpected row shape" in exc.value.context["detail"]


def test_get_view_ddl_returns_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeDdlCursor(one=("CREATE VIEW ...",))
    connection = _FakeDdlConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: (
            "SELECT DEFINITION FROM <BD>.._V_VIEW WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?)"
        ),
    )

    assert get_view_ddl(_profile(), database="DB", schema="PUB", view="V1") == "CREATE VIEW ..."
    assert cursor.executed_params == ("PUB", "V1")


def test_get_view_ddl_dict_row(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeDdlCursor(one={"DEFINITION": "CREATE VIEW X AS SELECT 1"})
    connection = _FakeDdlConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT DEFINITION FROM <BD>.._V_VIEW WHERE A=1",
    )

    assert "CREATE VIEW X" in get_view_ddl(_profile(), database="DB", schema="S", view="X")


def test_get_view_ddl_raises_when_no_row(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeDdlCursor(one=None)
    connection = _FakeDdlConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT DEFINITION FROM <BD>.._V_VIEW WHERE 1=0",
    )

    with pytest.raises(NetezzaError) as exc:
        get_view_ddl(_profile(), database="DB", schema="S", view="MISSING")

    assert "No view definition" in exc.value.context["detail"]


def test_get_view_ddl_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom(_FakeDdlCursor):
        def execute(self, sql: str, params: tuple[str, str]) -> None:
            _ = (sql, params)
            raise RuntimeError("driver boom")

    cursor = _Boom(one=None)
    connection = _FakeDdlConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pwd-123")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT DEFINITION FROM <BD>.._V_VIEW",
    )

    with pytest.raises(NetezzaError) as exc:
        get_view_ddl(_profile(), database="DB", schema="S", view="V")

    assert "driver boom" in exc.value.context["detail"]
    assert "pwd-123" not in exc.value.context["detail"]


def test_get_view_ddl_rejects_dict_without_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeDdlCursor(one={"OWNER": "X"})
    connection = _FakeDdlConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT 1 FROM <BD>.._V_VIEW",
    )

    with pytest.raises(NetezzaError) as exc:
        get_view_ddl(_profile(), database="D", schema="S", view="V")

    assert "DEFINITION" in exc.value.context["detail"]
