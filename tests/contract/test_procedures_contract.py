"""Contract tests for ``nz_get_procedure_ddl`` input/output schema (issue #105)."""

from __future__ import annotations

import pytest

from nz_mcp.tools.procedures import (
    GetFindTableReferencesInput,
    GetFindTableReferencesOutput,
    GetProcedureDdlInput,
    GetProcedureDdlOutput,
    GetProcedureSizeInput,
    GetProcedureSizeOutput,
    GetProcedureTableLogicInput,
    GetProcedureTableLogicOutput,
)


@pytest.mark.contract
def test_input_accepts_variant_raw() -> None:
    inp = GetProcedureDdlInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "procedure": "SP", "variant": "raw"}
    )
    assert inp.variant == "raw"


@pytest.mark.contract
def test_input_accepts_variant_clean() -> None:
    inp = GetProcedureDdlInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "procedure": "SP", "variant": "clean"}
    )
    assert inp.variant == "clean"


@pytest.mark.contract
def test_input_variant_defaults_to_raw() -> None:
    """Omitting variant must default to 'raw' for back-compat."""
    inp = GetProcedureDdlInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "procedure": "SP"}
    )
    assert inp.variant == "raw"


@pytest.mark.contract
def test_input_rejects_unknown_variant() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureDdlInput.model_validate(
            {"database": "D", "schema": "PUBLIC", "procedure": "SP", "variant": "pretty"}
        )


@pytest.mark.contract
def test_output_has_size_bytes_raw_and_clean_fields() -> None:
    """Output schema must expose size_bytes_raw and size_bytes_clean."""
    fields = GetProcedureDdlOutput.model_fields
    assert "size_bytes_raw" in fields
    assert "size_bytes_clean" in fields


@pytest.mark.contract
def test_output_size_bytes_is_size_of_returned_variant() -> None:
    """size_bytes must equal the byte length of the ddl field."""
    ddl_text = (
        "CREATE OR REPLACE PROCEDURE S.P() RETURNS INT LANGUAGE NZPLSQL AS\n"
        "BEGIN_PROC\n"
        "  NULL;\n"
        "END_PROC;"
    )
    out = GetProcedureDdlOutput(
        ddl=ddl_text,
        size_bytes=len(ddl_text.encode("utf-8")),
        size_bytes_raw=len(ddl_text.encode("utf-8")),
        size_bytes_clean=len(ddl_text.encode("utf-8")),
        warning=None,
        duration_ms=0,
    )
    assert out.size_bytes == len(out.ddl.encode("utf-8"))


@pytest.mark.contract
def test_output_rejects_extra_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureDdlOutput.model_validate(
            {
                "ddl": "x",
                "size_bytes": 1,
                "size_bytes_raw": 1,
                "size_bytes_clean": 1,
                "warning": None,
                "duration_ms": 0,
                "unexpected_field": True,
            }
        )


# ── nz_get_procedure_size ─────────────────────────────────────────────────────


@pytest.mark.contract
def test_size_input_accepts_schema_alias() -> None:
    inp = GetProcedureSizeInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "procedure": "SP"}
    )
    assert inp.procedure_schema == "PUBLIC"


@pytest.mark.contract
def test_size_output_has_required_fields() -> None:
    out = GetProcedureSizeOutput.model_validate(
        {
            "name": "SP",
            "signature": "SP(INT)",
            "size_bytes_raw": 100,
            "size_bytes_clean": 80,
            "lines_raw": 10,
            "lines_clean": 8,
            "sections_detected": ["header", "body"],
            "duration_ms": 5,
        }
    )
    assert out.size_bytes_raw == 100
    assert out.sections_detected == ["header", "body"]


@pytest.mark.contract
def test_size_output_rejects_extra_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureSizeOutput.model_validate(
            {
                "name": "SP",
                "signature": "SP(INT)",
                "size_bytes_raw": 100,
                "size_bytes_clean": 80,
                "lines_raw": 10,
                "lines_clean": 8,
                "sections_detected": [],
                "duration_ms": 0,
                "unexpected_field": True,
            }
        )


# ── nz_get_procedure_table_logic (issue #109) ────────────────────────────────


@pytest.mark.contract
def test_table_logic_input_accepts_schema_alias_and_defaults_kinds() -> None:
    inp = GetProcedureTableLogicInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "procedure": "SP", "table": "FOO"}
    )
    assert inp.procedure_schema == "PUBLIC"
    assert inp.kinds == ["create", "insert"]


@pytest.mark.contract
def test_table_logic_input_accepts_kinds_subset() -> None:
    inp = GetProcedureTableLogicInput.model_validate(
        {
            "database": "D",
            "schema": "PUBLIC",
            "procedure": "SP",
            "table": "FOO",
            "kinds": ["create"],
        }
    )
    assert inp.kinds == ["create"]


@pytest.mark.contract
def test_table_logic_input_rejects_unknown_kind() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureTableLogicInput.model_validate(
            {
                "database": "D",
                "schema": "PUBLIC",
                "procedure": "SP",
                "table": "FOO",
                "kinds": ["update"],
            }
        )


@pytest.mark.contract
def test_table_logic_input_requires_table() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureTableLogicInput.model_validate(
            {"database": "D", "schema": "PUBLIC", "procedure": "SP"}
        )


@pytest.mark.contract
def test_table_logic_output_has_required_fields() -> None:
    out = GetProcedureTableLogicOutput.model_validate(
        {
            "table": "FOO",
            "statements": [
                {
                    "kind": "CREATE TEMP TABLE",
                    "sql": "CREATE TEMP TABLE FOO AS SELECT 1;",
                    "line_start": 10,
                    "line_end": 12,
                    "size_bytes": 35,
                }
            ],
            "count": 1,
            "not_found": False,
            "duration_ms": 5,
        }
    )
    assert out.count == 1
    assert out.not_found is False
    assert out.statements[0].kind == "CREATE TEMP TABLE"


@pytest.mark.contract
def test_table_logic_output_rejects_extra_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureTableLogicOutput.model_validate(
            {
                "table": "FOO",
                "statements": [],
                "count": 0,
                "not_found": True,
                "duration_ms": 0,
                "unexpected_field": True,
            }
        )


@pytest.mark.contract
def test_table_logic_statement_kind_constrained() -> None:
    """Each ``StatementItem.kind`` must be one of the three contract-defined values."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureTableLogicOutput.model_validate(
            {
                "table": "FOO",
                "statements": [
                    {
                        "kind": "MERGE INTO",
                        "sql": "MERGE INTO FOO USING BAR ON 1;",
                        "line_start": 1,
                        "line_end": 1,
                        "size_bytes": 30,
                    }
                ],
                "count": 1,
                "not_found": False,
                "duration_ms": 0,
            }
        )


# ── nz_find_table_references (issue #107) ────────────────────────────────────


@pytest.mark.contract
def test_find_table_references_input_accepts_schema_alias_and_minimal() -> None:
    inp = GetFindTableReferencesInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "table": "FOO"}
    )
    assert inp.procedure_schema == "PUBLIC"
    assert inp.table_database is None
    assert inp.table_schema is None
    assert inp.pattern is None


@pytest.mark.contract
def test_find_table_references_input_accepts_all_fields() -> None:
    inp = GetFindTableReferencesInput.model_validate(
        {
            "database": "D",
            "schema": "PUBLIC",
            "table": "FOO",
            "table_database": "DB1",
            "table_schema": "S1",
            "pattern": "SP_%",
        }
    )
    assert inp.table_database == "DB1"
    assert inp.table_schema == "S1"
    assert inp.pattern == "SP_%"


@pytest.mark.contract
def test_find_table_references_input_rejects_extra_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetFindTableReferencesInput.model_validate(
            {
                "database": "D",
                "schema": "PUBLIC",
                "table": "FOO",
                "kinds": ["read"],  # not part of this tool
            }
        )


@pytest.mark.contract
def test_find_table_references_input_requires_table() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetFindTableReferencesInput.model_validate({"database": "D", "schema": "PUBLIC"})


@pytest.mark.contract
def test_find_table_references_output_has_required_fields() -> None:
    out = GetFindTableReferencesOutput.model_validate(
        {
            "references": [
                {
                    "procedure_name": "SP_X",
                    "signature": "SP_X(INT)",
                    "usage": "both",
                    "occurrences_read": 2,
                    "occurrences_write": 1,
                    "last_altered": "2026-04-15 10:30:00",
                }
            ],
            "scanned_count": 10,
            "match_count": 1,
            "truncated": False,
            "duration_ms": 12,
        }
    )
    assert out.match_count == 1
    assert out.references[0].usage == "both"


@pytest.mark.contract
def test_find_table_references_output_rejects_unknown_usage() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetFindTableReferencesOutput.model_validate(
            {
                "references": [
                    {
                        "procedure_name": "SP_X",
                        "signature": "SP_X()",
                        "usage": "delete",  # not in Literal["read","write","both"]
                        "occurrences_read": 0,
                        "occurrences_write": 1,
                        "last_altered": "",
                    }
                ],
                "scanned_count": 1,
                "match_count": 1,
                "truncated": False,
                "duration_ms": 0,
            }
        )


@pytest.mark.contract
def test_find_table_references_output_rejects_extra_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetFindTableReferencesOutput.model_validate(
            {
                "references": [],
                "scanned_count": 0,
                "match_count": 0,
                "truncated": False,
                "duration_ms": 0,
                "unexpected_field": True,
            }
        )
