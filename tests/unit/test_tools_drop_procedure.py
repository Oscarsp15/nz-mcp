"""Unit tests for nz_drop_procedure (catalog helper + tool)."""

from __future__ import annotations

from typing import Any, Literal

import pytest

from nz_mcp.catalog.ddl import _validate_signature_types, execute_drop_procedure
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, NetezzaError


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
    def __init__(self, cursor: _FakeCursor) -> None:
        self._c = cursor

    def cursor(self) -> _FakeCursor:
        return self._c

    def close(self) -> None:
        pass


def test_validate_signature_types() -> None:
    assert _validate_signature_types("(DATE, VARCHAR(20))") == "DATE, VARCHAR(20)"
    assert _validate_signature_types("NUMERIC(10,2), INT4") == "NUMERIC(10,2), INT4"
    assert _validate_signature_types("()") == ""
    assert _validate_signature_types("CHARACTER VARYING(20)") == "CHARACTER VARYING(20)"


def test_validate_signature_rejects_injection() -> None:
    with pytest.raises(InvalidInputError):
        _validate_signature_types("INT4); DROP TABLE X --")


def test_database_mismatch_rejected() -> None:
    with pytest.raises(InvalidInputError, match="active profile database"):
        execute_drop_procedure(
            _profile(),
            "OTHER_DB",
            "DBO",
            "P",
            "INT4",
            if_exists=True,
        )


def test_if_exists_noop_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.ddl.list_procedures", lambda *_a, **_k: [])
    out = execute_drop_procedure(
        _profile(), "DESA_MODELOS", "DBO", "MISSING", "INT4", if_exists=True
    )
    assert out["dropped"] is False
    assert out["duration_ms"] == 0


def test_execute_success(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor()
    monkeypatch.setattr(
        "nz_mcp.catalog.ddl.list_procedures",
        lambda *_a, **_k: [{"name": "P", "owner": "U"}],
    )
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _FakeConn(cursor))
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    out = execute_drop_procedure(_profile(), "DESA_MODELOS", "DBO", "P", "INT4", if_exists=True)
    assert out["dropped"] is True
    assert cursor.sql == "DROP PROCEDURE DBO.P(INT4)"


def test_execute_without_if_exists_skips_catalog_check(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = _FakeCursor()

    def _boom(*_a: object, **_k: object) -> list[dict[str, str]]:
        raise AssertionError("list_procedures must not be called when if_exists=False")

    monkeypatch.setattr("nz_mcp.catalog.ddl.list_procedures", _boom)
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _FakeConn(cursor))
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    out = execute_drop_procedure(
        _profile(),
        "DESA_MODELOS",
        "DBO",
        "P",
        "(DATE, VARCHAR(20))",
        if_exists=False,
    )
    assert out["dropped"] is True
    assert cursor.sql == "DROP PROCEDURE DBO.P(DATE, VARCHAR(20))"


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

    monkeypatch.setattr("nz_mcp.catalog.ddl.list_procedures", lambda *_a, **_k: [{"name": "P"}])
    monkeypatch.setattr("nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _BoomConn())
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    with pytest.raises(NetezzaError):
        execute_drop_procedure(_profile(), "DESA_MODELOS", "DBO", "P", "INT4", if_exists=False)


def test_tool_requires_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_mcp.tools.drop_procedure import DropProcedureInput, nz_drop_procedure

    monkeypatch.setattr("nz_mcp.tools.drop_procedure.get_active_profile", lambda **_k: _profile())
    with pytest.raises(InvalidInputError) as ei:
        nz_drop_procedure(
            DropProcedureInput.model_validate(
                {
                    "database": "DESA_MODELOS",
                    "schema": "DBO",
                    "procedure": "P",
                    "signature": "INT4",
                    "confirm": False,
                },
            ),
        )
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_tool_handler_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_mcp.tools.drop_procedure import DropProcedureInput, nz_drop_procedure

    monkeypatch.setattr("nz_mcp.tools.drop_procedure.get_active_profile", lambda **_k: _profile())
    monkeypatch.setattr(
        "nz_mcp.catalog.ddl.list_procedures",
        lambda *_a, **_k: [{"name": "P"}],
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.ddl.open_connection", lambda _p, _w: _FakeConn(_FakeCursor())
    )
    monkeypatch.setattr("nz_mcp.catalog.ddl.get_password", lambda _n: "pw")
    out = nz_drop_procedure(
        DropProcedureInput.model_validate(
            {
                "database": "DESA_MODELOS",
                "schema": "DBO",
                "procedure": "P",
                "signature": "INT4",
                "confirm": True,
            },
        ),
    )
    assert out.dropped is True
