"""Unit tests for nz_execute_ddl catalog helper and env guard."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest

from nz_mcp.catalog.execute_ddl import execute_ddl
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, InvalidInputError, NetezzaError

_PROC = (
    "CREATE OR REPLACE PROCEDURE DBO.NZMCP_SMOKE()\n"
    "RETURNS INT4\n"
    "LANGUAGE NZPLSQL AS\n"
    "BEGIN_PROC\n"
    "BEGIN\n"
    "  RAISE NOTICE 'hi';\n"
    "  RETURN 1;\n"
    "END;\n"
    "END_PROC;\n"
)
_VIEW = "CREATE OR REPLACE VIEW DBO.V_SMOKE AS SELECT 1 AS C"


def _profile(*, database: str = "DESA_MODELOS", mode: Literal["admin"] = "admin") -> Profile:
    return Profile(name="p", host="h", port=5480, database=database, user="u", mode=mode)


class _FakeCursor:
    def __init__(self) -> None:
        self.sql: str | None = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.sql = sql

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self) -> None:
        self._c = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self._c

    def close(self) -> None:
        pass


def test_dry_run_procedure_returns_sql() -> None:
    out = execute_ddl(
        _profile(),
        sql=_PROC,
        input_path=None,
        statement_type="procedure",
        dry_run=True,
        confirm=False,
    )
    assert out["dry_run"] is True
    assert out["executed"] is False
    assert "LANGUAGE NZPLSQL AS" in out["sql_to_execute"]


def test_dry_run_view_returns_sql() -> None:
    out = execute_ddl(
        _profile(),
        sql=_VIEW,
        input_path=None,
        statement_type="view",
        dry_run=True,
        confirm=False,
    )
    assert out["dry_run"] is True
    assert out["sql_to_execute"].startswith("CREATE OR REPLACE VIEW")


def test_exactly_one_of_sql_or_input_path() -> None:
    with pytest.raises(InvalidInputError, match="exactly one"):
        execute_ddl(
            _profile(),
            sql=_VIEW,
            input_path="/abs/x.sql",
            statement_type="view",
            dry_run=True,
            confirm=False,
        )
    with pytest.raises(InvalidInputError, match="exactly one"):
        execute_ddl(
            _profile(),
            sql=None,
            input_path=None,
            statement_type="view",
            dry_run=True,
            confirm=False,
        )


def test_type_mismatch_view_declared_but_procedure_given() -> None:
    with pytest.raises(InvalidInputError, match="view"):
        execute_ddl(
            _profile(),
            sql=_PROC,
            input_path=None,
            statement_type="view",
            dry_run=True,
            confirm=False,
        )


def test_type_mismatch_procedure_declared_but_view_given() -> None:
    with pytest.raises(InvalidInputError, match="procedure"):
        execute_ddl(
            _profile(),
            sql=_VIEW,
            input_path=None,
            statement_type="procedure",
            dry_run=True,
            confirm=False,
        )


def test_empty_sql_rejected() -> None:
    with pytest.raises(InvalidInputError, match="empty"):
        execute_ddl(
            _profile(),
            sql="   ",
            input_path=None,
            statement_type="view",
            dry_run=True,
            confirm=False,
        )


def test_prod_ref_rejected_in_non_prod_profile() -> None:
    with pytest.raises(GuardRejectedError) as ei:
        execute_ddl(
            _profile(database="DESA_MODELOS"),
            sql="CREATE OR REPLACE VIEW DBO.V AS SELECT * FROM PROD_ANALITICA..T",
            input_path=None,
            statement_type="view",
            dry_run=True,
            confirm=False,
        )
    assert ei.value.code == "PROD_REF_IN_NONPROD"
    assert "PROD_ANALITICA" in str(ei.value.context.get("refs"))


def test_prod_ref_rejected_without_allow_prod_reads_flag() -> None:
    # Acceptance #1: same call without the flag still rejects (fail-closed default).
    with pytest.raises(GuardRejectedError) as ei:
        execute_ddl(
            _profile(database="DESA_MODELOS"),
            sql="CREATE OR REPLACE VIEW DBO.V AS SELECT * FROM PROD_ANALITICA..T",
            input_path=None,
            statement_type="view",
            dry_run=True,
            confirm=False,
            allow_prod_reads=False,
        )
    assert ei.value.code == "PROD_REF_IN_NONPROD"


def test_prod_ref_allowed_when_allow_prod_reads_true() -> None:
    # Acceptance #2: caller certifies reads-only; guard is skipped, DDL validates.
    out = execute_ddl(
        _profile(database="DESA_MODELOS"),
        sql="CREATE OR REPLACE VIEW DBO.V AS SELECT * FROM PROD_ANALITICA..T",
        input_path=None,
        statement_type="view",
        dry_run=True,
        confirm=False,
        allow_prod_reads=True,
    )
    assert out["dry_run"] is True
    assert out["executed"] is False
    assert "PROD_ANALITICA" in out["sql_to_execute"]


def test_non_prod_ddl_compiles_regardless_of_flag() -> None:
    # Acceptance #3: a SP with no PROD_ refs behaves identically with or without the flag.
    for flag in (False, True):
        out = execute_ddl(
            _profile(database="DESA_MODELOS"),
            sql=_PROC,
            input_path=None,
            statement_type="procedure",
            dry_run=True,
            confirm=False,
            allow_prod_reads=flag,
        )
        assert out["dry_run"] is True
        assert "LANGUAGE NZPLSQL AS" in out["sql_to_execute"]


def test_allow_prod_reads_still_enforces_other_guards() -> None:
    # The flag skips ONLY the env guard: statement_type mismatch still rejects.
    with pytest.raises(InvalidInputError, match="view"):
        execute_ddl(
            _profile(database="DESA_MODELOS"),
            sql=_PROC,
            input_path=None,
            statement_type="view",
            dry_run=True,
            confirm=False,
            allow_prod_reads=True,
        )


def test_prod_ref_allowed_in_prod_profile() -> None:
    out = execute_ddl(
        _profile(database="PROD_ANALITICA"),
        sql="CREATE OR REPLACE VIEW DBO.V AS SELECT * FROM PROD_ANALITICA..T",
        input_path=None,
        statement_type="view",
        dry_run=True,
        confirm=False,
    )
    assert out["dry_run"] is True


def test_confirm_required_when_not_dry_run() -> None:
    with pytest.raises(InvalidInputError) as ei:
        execute_ddl(
            _profile(),
            sql=_VIEW,
            input_path=None,
            statement_type="view",
            dry_run=False,
            confirm=False,
        )
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_input_path_is_read(tmp_path: Path) -> None:
    f = tmp_path / "v.sql"
    f.write_text(_VIEW, encoding="utf-8")
    out = execute_ddl(
        _profile(),
        sql=None,
        input_path=str(f),
        statement_type="view",
        dry_run=True,
        confirm=False,
    )
    assert out["sql_to_execute"].startswith("CREATE OR REPLACE VIEW")


def test_input_path_missing_maps_to_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError):
        execute_ddl(
            _profile(),
            sql=None,
            input_path=str(tmp_path / "nope.sql"),
            statement_type="view",
            dry_run=True,
            confirm=False,
        )


def test_execute_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.execute_ddl.open_connection", lambda _p, _w: _FakeConn())
    monkeypatch.setattr("nz_mcp.catalog.execute_ddl.get_password", lambda _n: "pw")
    out = execute_ddl(
        _profile(),
        sql=_VIEW,
        input_path=None,
        statement_type="view",
        dry_run=False,
        confirm=True,
    )
    assert out["executed"] is True
    assert out["dry_run"] is False


def test_execute_failure_wrapped_as_netezza_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomCursor:
        def execute(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("boom")

        def close(self) -> None:
            pass

    class _BoomConn:
        def cursor(self) -> _BoomCursor:
            return _BoomCursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr("nz_mcp.catalog.execute_ddl.open_connection", lambda _p, _w: _BoomConn())
    monkeypatch.setattr("nz_mcp.catalog.execute_ddl.get_password", lambda _n: "pw")
    with pytest.raises(NetezzaError):
        execute_ddl(
            _profile(),
            sql=_VIEW,
            input_path=None,
            statement_type="view",
            dry_run=False,
            confirm=True,
        )


def test_invalid_statement_type_rejected() -> None:
    with pytest.raises(InvalidInputError, match="procedure' or 'view"):
        execute_ddl(
            _profile(),
            sql=_VIEW,
            input_path=None,
            statement_type="table",
            dry_run=True,
            confirm=False,
        )


def test_wrong_statement_for_tool_when_guard_returns_non_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nz_mcp.sql_guard import ParsedStatement, StatementKind

    monkeypatch.setattr(
        "nz_mcp.catalog.execute_ddl.guard_validate",
        lambda *_a, **_k: ParsedStatement(kind=StatementKind.SELECT, has_where=False, raw="X"),
    )
    with pytest.raises(GuardRejectedError) as ei:
        execute_ddl(
            _profile(),
            sql=_VIEW,
            input_path=None,
            statement_type="view",
            dry_run=True,
            confirm=False,
        )
    assert ei.value.code == "WRONG_STATEMENT_FOR_TOOL"


def test_tool_handler_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_mcp.tools.execute_ddl import ExecuteDdlInput, nz_execute_ddl

    monkeypatch.setattr("nz_mcp.tools.execute_ddl.get_active_profile", lambda **_k: _profile())
    out = nz_execute_ddl(
        ExecuteDdlInput(sql=_VIEW, statement_type="view", dry_run=True, confirm=False),
    )
    assert out.dry_run is True
    assert out.executed is False
    assert out.sql_to_execute.startswith("CREATE OR REPLACE VIEW")
