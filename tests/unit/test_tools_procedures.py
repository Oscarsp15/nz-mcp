"""Tests for procedure MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.tools.procedures import (
    DescribeProcedureInput,
    GetProcedureDdlInput,
    GetProcedureSectionInput,
    ListProceduresInput,
    nz_describe_procedure,
    nz_get_procedure_ddl,
    nz_get_procedure_section,
    nz_list_procedures,
)


def test_list_input_accepts_schema_alias() -> None:
    p = ListProceduresInput.model_validate({"database": "D", "schema": "PUBLIC"})
    assert p.procedure_schema == "PUBLIC"


def test_nz_list_procedures_happy(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_list(
        _profile: object,
        database: str,
        schema: str,
        pattern: str | None = None,
    ) -> list[dict[str, str]]:
        assert database == "D"
        assert schema == "PUBLIC"
        assert pattern is None
        return [
            {
                "name": "SP1",
                "owner": "ADMIN",
                "language": "NZPLSQL",
                "arguments": "(INT)",
                "returns": "INT",
            },
        ]

    monkeypatch.setattr("nz_mcp.tools.procedures.list_procedures", _fake_list)
    out = nz_list_procedures(
        ListProceduresInput(database="D", procedure_schema="PUBLIC"),
        config_path=two_profiles,
    )
    assert len(out.procedures) == 1
    assert out.procedures[0].name == "SP1"


def test_nz_describe_procedure_happy(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_describe(
        *_a: object,
        **_k: object,
    ) -> dict[str, object]:
        return {
            "name": "SP",
            "owner": "ADMIN",
            "language": "NZPLSQL",
            "arguments": [{"name": "x", "type": "INT"}],
            "returns": "INT",
            "created_at": None,
            "lines": 3,
            "sections_detected": ["header", "body"],
        }

    monkeypatch.setattr("nz_mcp.tools.procedures.describe_procedure", _fake_describe)
    out = nz_describe_procedure(
        DescribeProcedureInput(database="D", procedure_schema="PUBLIC", procedure="SP"),
        config_path=two_profiles,
    )
    assert out.name == "SP"
    assert out.arguments[0].name == "x"


def test_nz_get_procedure_ddl_happy(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_ddl(*_a: object, **_k: object) -> str:
        return "CREATE OR REPLACE PROCEDURE ..."

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", _fake_ddl)
    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(database="D", procedure_schema="PUBLIC", procedure="SP"),
        config_path=two_profiles,
    )
    assert "CREATE OR REPLACE" in out.ddl


def test_nz_get_procedure_section_happy(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_sec(*_a: object, **_k: object) -> dict[str, object]:
        return {
            "section": "body",
            "from_line": 2,
            "to_line": 5,
            "content": "x",
            "truncated": False,
        }

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_section", _fake_sec)
    out = nz_get_procedure_section(
        GetProcedureSectionInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="SP",
            section="body",
        ),
        config_path=two_profiles,
    )
    assert out.section == "body"
    assert out.from_line == 2
