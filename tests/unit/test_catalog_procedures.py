"""Unit tests for catalog procedure helpers (no DB)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.catalog import procedures as proc
from nz_mcp.config import Profile, get_active_profile
from nz_mcp.errors import (
    InvalidInputError,
    NetezzaError,
    ObjectNotFoundError,
    OverloadAmbiguousError,
    SectionNotFoundError,
)

_DUMMY_PROFILE = Profile(
    name="dev",
    host="h",
    port=5480,
    database="D",
    user="u",
    mode="read",
)


def test_parse_procedure_arguments_named() -> None:
    out = proc.parse_procedure_arguments("(P_SOURCE VARCHAR(10), P_ID INTEGER)")
    assert out[0]["name"] == "P_SOURCE"
    assert "VARCHAR" in out[0]["type"]
    assert out[1]["name"] == "P_ID"


def test_parse_procedure_arguments_unnamed_types() -> None:
    out = proc.parse_procedure_arguments("(VARCHAR, INTEGER)")
    assert out[0]["name"] == "arg1"
    assert out[0]["type"] == "VARCHAR"
    assert out[1]["name"] == "arg2"


def test_parse_procedure_arguments_empty() -> None:
    assert proc.parse_procedure_arguments("") == []


def test_ddl_get_tuple_row() -> None:
    row = ("MYPROC", "ADMIN", "(X INT)", "INT", "BEGIN\nEND;", "(X INT)")
    assert proc._ddl_get(row, "PROCEDURE") == "MYPROC"
    assert proc._ddl_get(row, "OWNER") == "ADMIN"
    assert proc._ddl_get(row, "PROCEDURESOURCE") == "BEGIN\nEND;"
    assert proc._ddl_get(row, "PROCEDURESIGNATURE") == "(X INT)"


def test_pick_procedure_row_single() -> None:
    r = {"PROCEDURE": "P", "PROCEDURESIGNATURE": "( )"}
    assert proc._pick_procedure_row([r], None, "P") is r


def test_pick_procedure_row_ambiguous() -> None:
    a = {"PROCEDURE": "P", "PROCEDURESIGNATURE": "(INT)"}
    b = {"PROCEDURE": "P", "PROCEDURESIGNATURE": "(VARCHAR)"}
    with pytest.raises(OverloadAmbiguousError):
        proc._pick_procedure_row([a, b], None, "P")


def test_pick_procedure_row_by_signature() -> None:
    a = {"PROCEDURE": "P", "PROCEDURESIGNATURE": "( INT )"}
    b = {"PROCEDURE": "P", "PROCEDURESIGNATURE": "( VARCHAR )"}
    got = proc._pick_procedure_row([a, b], "(INT)", "P")
    assert got is a


def test_pick_procedure_row_signature_mismatch() -> None:
    a = {"PROCEDURE": "P", "PROCEDURESIGNATURE": "(INT)"}
    with pytest.raises(ObjectNotFoundError):
        proc._pick_procedure_row([a], "(BOOL)", "P")


def test_get_procedure_section_range_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    long_src = "\n".join([f"-- {i}" for i in range(600)])
    row = {
        "PROCEDURE": "P",
        "OWNER": "O",
        "ARGUMENTS": "()",
        "RETURNS": "",
        "PROCEDURESOURCE": long_src,
        "PROCEDURESIGNATURE": "()",
    }

    def _fake_fetch(*_a: object, **_k: object) -> list[object]:
        return [row]

    def _fake_pick(rows: list[object], *_x: object) -> object:
        return rows[0]

    monkeypatch.setattr(proc, "_fetch_procedure_rows", _fake_fetch)
    monkeypatch.setattr(proc, "_pick_procedure_row", _fake_pick)
    out = proc.get_procedure_section(
        _DUMMY_PROFILE, "DB", "SCH", "P", "range", from_line=1, to_line=600
    )
    assert out["truncated"] is True
    assert out["to_line"] == 500


def test_get_procedure_section_body_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    src = "CREATE P AS BEGIN_PROC\nDECLARE x INT;\nEND_PROC;\n"
    row = {
        "PROCEDURE": "P",
        "OWNER": "O",
        "ARGUMENTS": "()",
        "RETURNS": "",
        "PROCEDURESOURCE": src,
        "PROCEDURESIGNATURE": "()",
    }

    def _fake_fetch(*_a: object, **_k: object) -> list[object]:
        return [row]

    def _fake_pick(rows: list[object], *_x: object) -> object:
        return rows[0]

    monkeypatch.setattr(proc, "_fetch_procedure_rows", _fake_fetch)
    monkeypatch.setattr(proc, "_pick_procedure_row", _fake_pick)
    with pytest.raises(SectionNotFoundError):
        proc.get_procedure_section(_DUMMY_PROFILE, "DB", "SCH", "P", "body")


def test_get_procedure_section_invalid_range_order(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        "PROCEDURE": "P",
        "OWNER": "O",
        "ARGUMENTS": "()",
        "RETURNS": "",
        "PROCEDURESOURCE": "X",
        "PROCEDURESIGNATURE": "()",
    }

    monkeypatch.setattr(proc, "_fetch_procedure_rows", lambda *_a, **_k: [row])
    monkeypatch.setattr(proc, "_pick_procedure_row", lambda rows, *_x: rows[0])
    with pytest.raises(InvalidInputError):
        proc.get_procedure_section(_DUMMY_PROFILE, "D", "S", "P", "range", from_line=2, to_line=1)


def test_list_procedures_driver_error(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    profile = get_active_profile(path=two_profiles)
    monkeypatch.setattr("nz_mcp.catalog.procedures.get_password", lambda _n: "pw")

    class _Conn:
        def cursor(self) -> _Conn:
            return self

        def execute(self, *_a: object, **_k: object) -> None:
            msg = "driver failed"
            raise OSError(msg)

        def close(self) -> None:
            return

    monkeypatch.setattr(proc, "open_connection", lambda *_a, **_k: _Conn())
    with pytest.raises(NetezzaError):
        proc.list_procedures(profile, "DEV", "PUBLIC", None)


def test_build_procedure_ddl() -> None:
    row = (
        "SP",
        "ADMIN",
        "(X INT)",
        "INT",
        "BEGIN_PROC\nBEGIN\nEND;\nEND_PROC;",
        "(X INT)",
    )
    ddl = proc._build_procedure_ddl("DB1", row)
    assert "CREATE OR REPLACE PROCEDURE DB1.SP" in ddl
    assert "LANGUAGE NZPLSQL AS" in ddl
    assert "BEGIN_PROC" in ddl
