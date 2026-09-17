"""Unit tests for the nz_call_procedure catalog helper."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Literal

import pytest
from nzpy import ProgrammingError

from nz_mcp.catalog.call import (
    _count_signature_args,
    _fetch_return_value,
    _is_timeout_exc,
    _json_scalar,
    _read_notices,
    call_procedure,
)
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, InvalidInputError, NetezzaError, QueryTimeoutError


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
    monkeypatch.setattr(
        "nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _FakeConn(cursor)
    )
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
    monkeypatch.setattr(
        "nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _FakeConn(cursor)
    )
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

    monkeypatch.setattr("nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _BoomConn())
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


def test_read_notices_empty_when_no_attr() -> None:
    class _NoCursorAttr:
        pass

    assert _read_notices(_NoCursorAttr()) == []
    assert _read_notices(object()) == []


def test_read_notices_strips_whitespace() -> None:
    class _C:
        notices: ClassVar[list[str]] = ["  hello  ", "", "  "]

    assert _read_notices(_C()) == ["hello"]


def test_is_timeout_exc_timeout_error() -> None:
    assert _is_timeout_exc(TimeoutError("timed out")) is True


def test_is_timeout_exc_oserror_with_message() -> None:
    assert _is_timeout_exc(OSError("The read operation timed out")) is True


def test_is_timeout_exc_generic_runtime_error() -> None:
    assert _is_timeout_exc(RuntimeError("boom")) is False


def test_notices_preserved_in_error_context_when_execute_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTICE messages emitted before a mid-proc failure must survive in the error."""

    class _PartialCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
            # Populate notices before raising, simulating a proc that emits
            # RAISE NOTICE then fails.
            self.notices = ["step 1 done", "step 2 done"]
            raise RuntimeError("mid-proc error")

    cursor = _PartialCursor()
    monkeypatch.setattr(
        "nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _FakeConn(cursor)
    )
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    with pytest.raises(NetezzaError) as ei:
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
    assert ei.value.context.get("partial_notices") == ["step 1 done", "step 2 done"]


def test_notices_empty_in_error_context_when_cursor_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoomCursor:
        notices: ClassVar[list[str]] = []

        def execute(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("boom")

        def close(self) -> None:
            pass

    class _BoomConn:
        def cursor(self) -> _BoomCursor:
            return _BoomCursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr("nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _BoomConn())
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    with pytest.raises(NetezzaError) as ei:
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
    assert ei.value.context.get("partial_notices") == []


def test_timeout_raises_query_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A socket timeout must surface as QueryTimeoutError with orphan_session_risk flag."""

    class _TimeoutCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
            self.notices = ["proc started"]
            raise TimeoutError("The read operation timed out")

    cursor = _TimeoutCursor()
    monkeypatch.setattr(
        "nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _FakeConn(cursor)
    )
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    with pytest.raises(QueryTimeoutError) as ei:
        call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="DBO",
            procedure="P",
            args=None,
            signature=None,
            dry_run=False,
            confirm=True,
            timeout_s=30,
        )
    assert ei.value.context.get("orphan_session_risk") is True
    assert ei.value.context.get("partial_notices") == ["proc started"]


def test_timeout_oserror_raises_query_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An OSError with 'timed out' in the message must also surface as QueryTimeoutError."""

    class _OsTimeoutCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
            raise OSError("The read operation timed out")

    cursor = _OsTimeoutCursor()
    monkeypatch.setattr(
        "nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _FakeConn(cursor)
    )
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    with pytest.raises(QueryTimeoutError):
        call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="DBO",
            procedure="P",
            args=None,
            signature=None,
            dry_run=False,
            confirm=True,
            timeout_s=30,
        )


def test_no_timeout_passes_none_when_timeout_s_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """When timeout_s=None, open_connection must receive timeout=None (no socket limit)."""
    received_timeout: list[int | None] = []

    def _capture(_p: object, _w: object, *, timeout: int | None = -1, **_kw: object) -> _FakeConn:
        received_timeout.append(timeout)
        return _FakeConn(_FakeCursor())

    monkeypatch.setattr("nz_mcp.catalog.call.open_connection", _capture)
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
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
    assert received_timeout == [None]


def test_explicit_timeout_s_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """When timeout_s is given, open_connection must receive that value as timeout."""
    received_timeout: list[int | None] = []

    def _capture(_p: object, _w: object, *, timeout: int | None = -1, **_kw: object) -> _FakeConn:
        received_timeout.append(timeout)
        return _FakeConn(_FakeCursor())

    monkeypatch.setattr("nz_mcp.catalog.call.open_connection", _capture)
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    call_procedure(
        _profile(),
        database="DESA_MODELOS",
        schema="DBO",
        procedure="P",
        args=None,
        signature=None,
        dry_run=False,
        confirm=True,
        timeout_s=45,
    )
    assert received_timeout == [45]


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


# ── issue #310: return_value keeps the procedure's native type ───────────────


def test_json_scalar_preserves_native_numbers() -> None:
    assert _json_scalar(42) == 42
    assert isinstance(_json_scalar(42), int)
    assert _json_scalar(3.5) == 3.5
    assert _json_scalar(True) is True
    assert _json_scalar("x") == "x"
    assert _json_scalar(None) is None


def test_json_scalar_normalises_decimal() -> None:
    integral = _json_scalar(Decimal("42"))
    assert integral == 42
    assert isinstance(integral, int)
    assert _json_scalar(Decimal("42.50")) == 42.5


def test_json_scalar_serialises_other_types_to_string() -> None:
    assert _json_scalar(date(2026, 1, 2)) == "2026-01-02"
    assert _json_scalar(b"ab") == "ab"


def test_fetch_return_value_keeps_int() -> None:
    assert _fetch_return_value(_FakeCursor(row=(42,))) == 42


def test_fetch_return_value_accepts_bare_scalar_row() -> None:
    class _ScalarCursor(_FakeCursor):
        def fetchone(self) -> Any:
            return 7

    assert _fetch_return_value(_ScalarCursor()) == 7


def test_execute_returns_native_int_not_string(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor(row=(42,), notices=[])
    monkeypatch.setattr(
        "nz_mcp.catalog.call.open_connection", lambda _p, _w, **_kw: _FakeConn(cursor)
    )
    monkeypatch.setattr("nz_mcp.catalog.call.get_password", lambda _n: "pw")
    out = call_procedure(
        _profile(),
        database="DESA_MODELOS",
        schema="DBO",
        procedure="MYPROC",
        args=None,
        signature=None,
        dry_run=False,
        confirm=True,
        timeout_s=None,
    )
    assert out["return_value"] == 42
    assert isinstance(out["return_value"], int)


def test_tool_output_model_accepts_native_int() -> None:
    from nz_mcp.tools.call_procedure import CallProcedureOutput

    out = CallProcedureOutput.model_validate(
        {
            "dry_run": False,
            "call_sql": "CALL DBO.P(?)",
            "executed": True,
            "return_value": 42,
            "messages": [],
            "duration_ms": 3,
        }
    )
    assert out.return_value == 42
    assert isinstance(out.return_value, int)
