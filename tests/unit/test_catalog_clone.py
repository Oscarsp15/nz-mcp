"""Unit tests for catalog clone helpers."""

from __future__ import annotations

from typing import Any, Literal

import pytest

from nz_mcp.catalog.clone import clone_procedure
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, NetezzaError, ProcedureAlreadyExistsError


def _profile(*, mode: Literal["read", "write", "admin"] = "admin") -> Profile:
    return Profile(
        name="p",
        host="h",
        port=5480,
        database="DEV",
        user="u",
        mode=mode,
    )


_SAMPLE_DDL = (
    "CREATE OR REPLACE PROCEDURE PUBLIC.SRC(X INT)\n"
    "RETURNS VOID\n"
    "LANGUAGE NZPLSQL AS\n"
    "BEGIN_PROC\n"
    "  SELECT 1 FROM OTHERDB..FOO;\n"
    "END_PROC\n"
)

_REAL_NZPLSQL_BODY_DDL = (
    "CREATE OR REPLACE PROCEDURE DBO.TGT(DATE)\n"
    "RETURNS INTEGER\n"
    "LANGUAGE NZPLSQL AS\n"
    "DECLARE\n"
    "  v_campo VARCHAR(10000);\n"
    "BEGIN\n"
    "  RETURN 0;\n"
    "END;\n"
)


def test_clone_dry_run_real_shaped_nzplsql_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.get_procedure_ddl",
        lambda *_a, **_k: _REAL_NZPLSQL_BODY_DDL,
    )
    monkeypatch.setattr("nz_mcp.catalog.clone.list_procedures", lambda *_a, **_k: [])

    out = clone_procedure(
        _profile(),
        source_database="DEV",
        source_schema="DBO",
        source_procedure="TGT",
        source_signature=None,
        target_database="DEV",
        target_schema="DBO",
        target_procedure="TGT_CLONE",
        replace_if_exists=False,
        transformations=None,
        dry_run=True,
        confirm=False,
    )
    assert out["dry_run"] is True
    assert "VARCHAR(10000)" in out["ddl_to_execute"]
    assert "DECLARE" in out["ddl_to_execute"]


def test_clone_dry_run_returns_ddl_and_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.get_procedure_ddl",
        lambda *_a, **_k: _SAMPLE_DDL,
    )
    monkeypatch.setattr("nz_mcp.catalog.clone.list_procedures", lambda *_a, **_k: [])

    out = clone_procedure(
        _profile(),
        source_database="DEV",
        source_schema="PUBLIC",
        source_procedure="SRC",
        source_signature=None,
        target_database="DEV",
        target_schema="PUBLIC",
        target_procedure="TGT",
        replace_if_exists=False,
        transformations=[
            {"from": "SELECT 1", "to": "SELECT 2", "regex": False},
        ],
        dry_run=True,
        confirm=False,
    )
    assert out["dry_run"] is True
    assert out["executed"] is False
    assert "CREATE PROCEDURE PUBLIC.TGT" in out["ddl_to_execute"]
    assert "SELECT 2" in out["ddl_to_execute"]
    assert any("OTHERDB" in w for w in out["warnings"])


def test_clone_too_many_transformations() -> None:
    with pytest.raises(InvalidInputError):
        clone_procedure(
            _profile(),
            source_database="DEV",
            source_schema="PUBLIC",
            source_procedure="SRC",
            source_signature=None,
            target_database="DEV",
            target_schema="PUBLIC",
            target_procedure="TGT",
            replace_if_exists=True,
            transformations=[{"from": str(i), "to": "x", "regex": False} for i in range(25)],
            dry_run=True,
            confirm=False,
        )


def test_clone_procedure_already_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.get_procedure_ddl",
        lambda *_a, **_k: _SAMPLE_DDL,
    )
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.list_procedures",
        lambda *_a, **_k: [
            {"name": "TGT", "owner": "U", "language": "NZPLSQL", "arguments": "()", "returns": ""}
        ],
    )

    with pytest.raises(ProcedureAlreadyExistsError):
        clone_procedure(
            _profile(),
            source_database="DEV",
            source_schema="PUBLIC",
            source_procedure="SRC",
            source_signature=None,
            target_database="DEV",
            target_schema="PUBLIC",
            target_procedure="TGT",
            replace_if_exists=False,
            transformations=None,
            dry_run=True,
            confirm=False,
        )


def test_clone_confirm_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.get_procedure_ddl",
        lambda *_a, **_k: _SAMPLE_DDL,
    )
    monkeypatch.setattr("nz_mcp.catalog.clone.list_procedures", lambda *_a, **_k: [])

    with pytest.raises(InvalidInputError) as ei:
        clone_procedure(
            _profile(),
            source_database="DEV",
            source_schema="PUBLIC",
            source_procedure="SRC",
            source_signature=None,
            target_database="DEV",
            target_schema="PUBLIC",
            target_procedure="NEW1",
            replace_if_exists=True,
            transformations=None,
            dry_run=False,
            confirm=False,
        )
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_clone_executes_and_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.get_procedure_ddl",
        lambda *_a, **_k: _SAMPLE_DDL,
    )
    calls = 0

    def _list(_p: object, _db: str, _sch: str, pattern: object = None) -> list[dict[str, str]]:
        nonlocal calls
        calls += 1
        if calls >= 2:
            return [
                {
                    "name": "NEW1",
                    "owner": "U",
                    "language": "NZPLSQL",
                    "arguments": "()",
                    "returns": "",
                }
            ]
        return []

    monkeypatch.setattr("nz_mcp.catalog.clone.list_procedures", _list)
    monkeypatch.setattr("nz_mcp.catalog.clone.open_connection", lambda _p, _w: _FakeConn())
    monkeypatch.setattr("nz_mcp.catalog.clone.get_password", lambda _n: "pw")

    out = clone_procedure(
        _profile(),
        source_database="DEV",
        source_schema="PUBLIC",
        source_procedure="SRC",
        source_signature=None,
        target_database="DEV",
        target_schema="PUBLIC",
        target_procedure="NEW1",
        replace_if_exists=True,
        transformations=None,
        dry_run=False,
        confirm=True,
    )
    assert out["executed"] is True
    assert out["duration_ms"] is not None


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


def test_clone_execute_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.get_procedure_ddl",
        lambda *_a, **_k: _SAMPLE_DDL,
    )
    monkeypatch.setattr("nz_mcp.catalog.clone.list_procedures", lambda *_a, **_k: [])

    class _BadConn:
        def cursor(self) -> object:
            return _BoomCursor()

        def close(self) -> None:
            pass

    class _BoomCursor:
        def execute(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("exec failed")

        def close(self) -> None:
            pass

    monkeypatch.setattr("nz_mcp.catalog.clone.open_connection", lambda _p, _w: _BadConn())
    monkeypatch.setattr("nz_mcp.catalog.clone.get_password", lambda _n: "pw")

    with pytest.raises(NetezzaError):
        clone_procedure(
            _profile(),
            source_database="DEV",
            source_schema="PUBLIC",
            source_procedure="SRC",
            source_signature=None,
            target_database="DEV",
            target_schema="PUBLIC",
            target_procedure="Z",
            replace_if_exists=True,
            transformations=None,
            dry_run=False,
            confirm=True,
        )


def test_transformation_regex_no_match_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.clone.get_procedure_ddl",
        lambda *_a, **_k: _SAMPLE_DDL,
    )
    monkeypatch.setattr("nz_mcp.catalog.clone.list_procedures", lambda *_a, **_k: [])

    out = clone_procedure(
        _profile(),
        source_database="DEV",
        source_schema="PUBLIC",
        source_procedure="SRC",
        source_signature=None,
        target_database="DEV",
        target_schema="PUBLIC",
        target_procedure="Z",
        replace_if_exists=True,
        transformations=[{"from": r"nomatch\d+", "to": "x", "regex": True}],
        dry_run=True,
        confirm=False,
    )
    assert any("regex matched no" in w for w in out["warnings"])
