"""Unit tests for the nz_call_procedure catalog helper."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from nzpy import ProgrammingError

from nz_mcp.catalog.call import _count_signature_args, call_procedure
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, InvalidInputError, NetezzaError


def _profile(*, database: str = "DESA_MODELOS", mode: Literal["admin"] = "admin") -> Profile:
    return Profile(name="p", host="h", port=5480, database=database, user="u", mode=mode)


class _FakeCursor:
    def __init__(self, *, row: Any = ("42",), notices: list[str] | None = None) -> None:
        self.description: Any = [("RET", 23)]
        self._row = row
        self.notices = notices if notices is not None else ["NOTICE: hello from proc"]
        self.executed_sql: str | None = None
        self.params: tuple[Any, ...] | None = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed_sql = sql
        self.params = params

    def fetchone(self) -> Any:
        return self._row

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._c = cursor

    def cursor(self) -> _FakeCursor:
        return self._c

    def close(self) -> None:
        pass


def test_count_signature_args() -> None:
    assert _count_signature_args("(INTEGER, VARCHAR(20))") == 2
    assert _count_signature_args("()") == 0
    assert _count_signature_args("") == 0
    assert _count_signature_args("(DATE)") == 1
    assert _count_signature_args("INTEGER, NUMERIC(10,2), DATE") == 3


def test_dry_run_returns_parameterized_sql() -> None:
    out = call_procedure(
        _profile(),
        database="DESA_MODELOS",
        schema="DBO",
        procedure="MYPROC",
        args=[1, "x"],
        signature=None,
        dry_run=True,
        confirm=False,
        timeout_s=None,
    )
    assert out["dry_run"] is True
    assert out["executed"] is False
    assert out["call_sql"] == "CALL DBO.MYPROC(?, ?)"


def test_database_mismatch_rejected() -> None:
    with pytest.raises(InvalidInputError, match="active profile database"):
        call_procedure(
            _profile(),
            database="OTHER_DB",
            schema="DBO",
            procedure="P",
            args=None,
            signature=None,
            dry_run=True,
            confirm=False,
            timeout_s=None,
        )


def test_arg_count_signature_mismatch_rejected() -> None:
    with pytest.raises(InvalidInputError, match="does not match the signature"):
        call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="DBO",
            procedure="P",
            args=[1],
            signature="(INTEGER, VARCHAR)",
            dry_run=True,
            confirm=False,
            timeout_s=None,
        )


def test_prod_ref_rejected_in_non_prod() -> None:
    with pytest.raises(GuardRejectedError) as ei:
        call_procedure(
            _profile(database="DESA_MODELOS"),
            database="DESA_MODELOS",
            schema="PROD_X",
            procedure="RUN",
            args=None,
            signature=None,
            dry_run=True,
            confirm=False,
            timeout_s=None,
        )
    assert ei.value.code == "PROD_REF_IN_NONPROD"


def test_too_many_args_rejected() -> None:
    with pytest.raises(InvalidInputError, match="Too many arguments"):
        call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="DBO",
            procedure="P",
            args=list(range(101)),
            signature=None,
            dry_run=True,
            confirm=False,
            timeout_s=None,
        )


def test_confirm_required_when_not_dry_run() -> None:
    with pytest.raises(InvalidInputError) as ei:
        call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="DBO",
            procedure="P",
            args=None,
            signature=None,
            dry_run=False,
            confirm=False,
            timeout_s=None,
        )
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_execute_captures_return_value_and_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(row=("42",), notices=["NOTICE: step 1 done", "NOTICE: step 2 done"])
    monkeypatch.setattr("nz_mcp.catalog.call.open_connection", lambda _p, _w: _FakeConn(cursor))
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    out = call_procedure(
        _profile(),
        database="DESA_MODELOS",
        schema="DBO",
        procedure="MYPROC",
        args=[7],
        signature=None,
        dry_run=False,
        confirm=True,
        timeout_s=60,
    )
    assert out["executed"] is True
    assert out["return_value"] == "42"
    assert out["messages"] == ["NOTICE: step 1 done", "NOTICE: step 2 done"]
    assert cursor.params == (7,)


def test_execute_no_result_set_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoResultCursor(_FakeCursor):
        def fetchone(self) -> Any:
            raise ProgrammingError("no result set")

    cursor = _NoResultCursor(notices=[])
    monkeypatch.setattr("nz_mcp.catalog.call.open_connection", lambda _p, _w: _FakeConn(cursor))
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    out = call_procedure(
        _profile(),
        database="DESA_MODELOS",
        schema="DBO",
        procedure="P",
        args=None,
        signature=None,
        dry_run=False,
        confirm=True,
        timeout_s=None,
    )
    assert out["executed"] is True
    assert out["return_value"] is None
    assert out["messages"] == []


def test_execute_failure_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr("nz_mcp.catalog.call.open_connection", lambda _p, _w: _BoomConn())
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    with pytest.raises(NetezzaError):
        call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="DBO",
            procedure="P",
            args=None,
            signature=None,
            dry_run=False,
            confirm=True,
            timeout_s=None,
        )


def test_tool_handler_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_mcp.tools.call_procedure import CallProcedureInput, nz_call_procedure

    monkeypatch.setattr("nz_mcp.tools.call_procedure.get_active_profile", lambda **_k: _profile())
    out = nz_call_procedure(
        CallProcedureInput.model_validate(
            {"database": "DESA_MODELOS", "schema": "DBO", "procedure": "MYPROC", "args": [1]},
        ),
    )
    assert out.dry_run is True
    assert out.executed is False
    assert out.call_sql == "CALL DBO.MYPROC(?)"
