"""Issue #81 optional smoke against a real Netezza profile (DDL dry_run / DROP IF EXISTS)."""

from __future__ import annotations

import os

import pytest

from nz_mcp.tools.ddl import (
    ColumnDef,
    CreateTableInput,
    DistributionInput,
    DropTableInput,
    nz_create_table,
    nz_drop_table,
)

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1",
    reason="Set NZ_MCP_RUN_INTEGRATION=1 and configure a live admin profile.",
)
def test_issue81_create_table_dry_run_returns_ddl_only() -> None:
    db = os.environ.get("NZ_MCP_TEST_DATABASE", "DESA_MODELOS")
    schema = os.environ.get("NZ_MCP_TEST_SCHEMA", "DBO")
    out = nz_create_table(
        CreateTableInput(
            database=db,
            table_schema=schema,
            table="NZ_MCP_ISSUE81_DRYRUN",
            columns=[ColumnDef(name="ID", type="INT")],
            distribution=DistributionInput(type="RANDOM", columns=[]),
            dry_run=True,
        ),
    )
    assert out.dry_run is True
    assert out.executed is False
    assert "CREATE TABLE" in out.ddl_to_execute
    assert "DISTRIBUTE ON" in out.ddl_to_execute


@pytest.mark.skipif(
    os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1",
    reason="Set NZ_MCP_RUN_INTEGRATION=1 and configure a live admin profile.",
)
def test_issue81_drop_table_if_exists_missing_table_ok() -> None:
    db = os.environ.get("NZ_MCP_TEST_DATABASE", "DESA_MODELOS")
    schema = os.environ.get("NZ_MCP_TEST_SCHEMA", "DBO")
    out = nz_drop_table(
        DropTableInput(
            database=db,
            table_schema=schema,
            table="NZ_MCP_NONEXISTENT_DROP_81",
            confirm=True,
            if_exists=True,
        ),
    )
    assert out.dropped is True
