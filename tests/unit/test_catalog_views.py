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
        # Issue #125: track every statement executed on this cursor in order
        # so tests can assert that ``SET CATALOG <db>`` was issued *before* the
        # ``SELECT DEFINITION FROM <BD>.._V_VIEW`` query.
        self.statements: list[tuple[str, tuple[str, str] | None]] = []

    def execute(self, sql: str, params: tuple[str, str] | None = None) -> None:
        self.executed_sql = sql
        if params is not None:
            self.executed_params = params
        self.statements.append((sql, params))

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
        def execute(self, sql: str, params: tuple[str, str] | None = None) -> None:
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


# ── issue #125: cross-database DDL fetch needs ``SET CATALOG`` ─────────────────


class _CrossDbDdlCursor:
    """Fake cursor that simulates Netezza's lazy ``DEFINITION`` resolution.

    ``_V_VIEW.DEFINITION`` only resolves to the real CREATE VIEW source when
    the session's current catalog matches the database that owns the view; on
    cross-database lookups Netezza projects the literal sentinel ``Not a
    view`` instead. This fake mirrors that behaviour so we can anchor the fix
    against a deterministic stub.
    """

    def __init__(
        self,
        *,
        target_db: str,
        session_db: str,
        real_definition: str,
    ) -> None:
        self._target_db = target_db.upper()
        self._session_db = session_db.upper()
        self._real_definition = real_definition
        self.statements: list[tuple[str, tuple[str, str] | None]] = []
        self.closed = False

    def execute(self, sql: str, params: tuple[str, str] | None = None) -> None:
        self.statements.append((sql, params))
        upper = sql.strip().upper()
        if upper.startswith("SET CATALOG"):
            # Mimic the real driver: SET CATALOG mutates the session catalog.
            self._session_db = upper.removeprefix("SET CATALOG").strip().rstrip(";")

    def fetchone(self) -> object | None:
        # The last statement is the SELECT for DEFINITION; the projected value
        # depends on whether the session catalog matches the target DB.
        if self._session_db == self._target_db:
            return (self._real_definition,)
        return ("Not a view",)

    def close(self) -> None:
        self.closed = True


class _CrossDbConnection:
    def __init__(self, cursor: _CrossDbDdlCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _CrossDbDdlCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def test_get_view_ddl_emits_set_catalog_before_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #125: SET CATALOG <db> must precede the SELECT to _V_VIEW."""
    cursor = _FakeDdlCursor(one=("CREATE VIEW PROD_MAESTROBI.DBO.V AS SELECT 1",))
    connection = _FakeDdlConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: (
            "SELECT DEFINITION FROM <BD>.._V_VIEW WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?)"
        ),
    )

    out = get_view_ddl(
        _profile(),
        database="prod_maestrobi",
        schema="DBO",
        view="V_CONTINGENCIACREDITOSFULL",
    )

    assert out.startswith("CREATE VIEW")
    # First statement must be SET CATALOG with the validated/normalized DB id.
    assert len(cursor.statements) == 2
    set_catalog_sql, set_catalog_params = cursor.statements[0]
    assert set_catalog_sql.upper().startswith("SET CATALOG ")
    assert "PROD_MAESTROBI" in set_catalog_sql.upper()
    assert set_catalog_params is None
    # Second statement is the actual SELECT against _V_VIEW.
    select_sql, select_params = cursor.statements[1]
    assert "_V_VIEW" in select_sql.upper()
    assert "PROD_MAESTROBI.." in select_sql.upper()
    assert select_params == ("DBO", "V_CONTINGENCIACREDITOSFULL")


def test_get_view_ddl_returns_not_a_view_without_set_catalog_when_unfixed() -> None:
    """Pure regression anchor: prove the cross-DB fake returns the sentinel.

    This exercises the fake itself (not ``get_view_ddl``) to lock in the
    contract: when no ``SET CATALOG`` is issued and the session catalog does
    not match the target database, Netezza returns ``"Not a view"``. If this
    invariant ever stops holding, the fix tests below would silently start
    passing for the wrong reason.
    """
    cursor = _CrossDbDdlCursor(
        target_db="PROD_MAESTROBI",
        session_db="DESA_MODELOS",
        real_definition="CREATE OR REPLACE VIEW DBO.V AS SELECT 1",
    )
    cursor.execute(
        (
            "SELECT DEFINITION FROM PROD_MAESTROBI.._V_VIEW "
            "WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?)"
        ),
        ("DBO", "V"),
    )
    assert cursor.fetchone() == ("Not a view",)


def test_get_view_ddl_cross_db_fix_returns_real_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #125: with ``SET CATALOG``, cross-DB DEFINITION resolves correctly."""
    cursor = _CrossDbDdlCursor(
        target_db="PROD_MAESTROBI",
        session_db="DESA_MODELOS",
        real_definition=(
            "CREATE OR REPLACE VIEW DBO.V_CONTINGENCIACREDITOSFULL AS "
            "SELECT * FROM DBO.CONTINGENCIACREDITOSFULL"
        ),
    )
    connection = _FakeDdlConnection(cursor)  # type: ignore[arg-type]
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: (
            "SELECT DEFINITION FROM <BD>.._V_VIEW WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?)"
        ),
    )

    out = get_view_ddl(
        _profile(),
        database="PROD_MAESTROBI",
        schema="DBO",
        view="V_CONTINGENCIACREDITOSFULL",
    )

    # Without the fix we would get "Not a view"; with SET CATALOG we get DDL.
    assert out != "Not a view"
    assert out.startswith("CREATE OR REPLACE VIEW")
    assert "CONTINGENCIACREDITOSFULL" in out


def test_get_view_ddl_validates_database_identifier_before_set_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #125: a malformed ``database`` must not reach the cursor.

    The DB identifier is interpolated literally into ``SET CATALOG <db>``
    (Netezza does not accept parameter binding for it), so the validator from
    ``catalog.identifier`` is the only line of defense. We pin that no
    ``SET CATALOG`` (and no SELECT) is issued for an invalid identifier.
    """
    from nz_mcp.errors import InvalidInputError

    cursor = _FakeDdlCursor(one=("CREATE VIEW X AS SELECT 1",))
    connection = _FakeDdlConnection(cursor)
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", lambda *_a, **_k: connection)
    monkeypatch.setattr(
        "nz_mcp.catalog.views.resolve_query",
        lambda _i, _p: "SELECT DEFINITION FROM <BD>.._V_VIEW WHERE A=1",
    )

    with pytest.raises(InvalidInputError):
        get_view_ddl(_profile(), database="DB; DROP TABLE T --", schema="S", view="V")

    # No statements should have been issued against the cursor.
    assert cursor.statements == []
