"""Contract tests for ``nz_get_procedure_ddl`` input/output schema (issue #105)."""

from __future__ import annotations

import pytest

from nz_mcp.tools.procedures import GetProcedureDdlInput, GetProcedureDdlOutput


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
def test_input_model_dump_default_variant() -> None:
    """Ensure Pydantic .model_dump() serializes the default variant appropriately."""
    inp = GetProcedureDdlInput(database="D", procedure_schema="PUBLIC", procedure="SP")
    dumped = inp.model_dump()
    assert dumped["variant"] == "raw"


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
