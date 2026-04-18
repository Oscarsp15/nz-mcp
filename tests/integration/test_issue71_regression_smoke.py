"""Issue #71 structural smoke against a real Netezza profile (optional)."""

from __future__ import annotations

import os

import pytest

from nz_mcp.tools.describe_table import DescribeTableInput, nz_describe_table
from nz_mcp.tools.procedures import (
    GetProcedureDdlInput,
    GetProcedureSectionInput,
    nz_get_procedure_ddl,
    nz_get_procedure_section,
)

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1",
    reason="Set NZ_MCP_RUN_INTEGRATION=1 and configure a live profile.",
)
def test_describe_ddl_section_smoke() -> None:
    db = os.environ.get("NZ_MCP_TEST_DATABASE", "DESA_MODELOS")
    schema = os.environ.get("NZ_MCP_TEST_SCHEMA", "DBO")
    table = os.environ.get("NZ_MCP_TEST_TABLE", "BASECOMERCIAL_EFECTIVO_MC")
    proc = os.environ.get("NZ_MCP_TEST_PROCEDURE", "AGRUPAR_ALERTAS")

    dt = nz_describe_table(DescribeTableInput(database=db, schema=schema, table=table))
    assert dt.distribution.dist_type in ("HASH", "RANDOM")
    if dt.distribution.dist_type == "HASH":
        assert len(dt.distribution.columns) >= 1

    ddl = nz_get_procedure_ddl(
        GetProcedureDdlInput(database=db, schema=schema, procedure=proc),
    )
    assert "CREATE OR REPLACE PROCEDURE" in ddl.ddl

    body = nz_get_procedure_section(
        GetProcedureSectionInput(
            database=db,
            schema=schema,
            procedure=proc,
            section="body",
        ),
    )
    assert body.content.strip()
