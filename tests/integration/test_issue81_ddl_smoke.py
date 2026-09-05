"""Issue #81 optional smoke against a real Netezza profile (DDL dry_run / DROP IF EXISTS)."""

from __future__ import annotations

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


def test_issue81_create_table_dry_run_returns_ddl_only(
    integration_database: str,
    integration_schema: str,
) -> None:
    out = nz_create_table(
        CreateTableInput(
            database=integration_database,
            table_schema=integration_schema,
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


def test_issue81_drop_table_if_exists_missing_table_ok(
    integration_database: str,
    integration_schema: str,
) -> None:
    out = nz_drop_table(
        DropTableInput(
            database=integration_database,
            table_schema=integration_schema,
            table="NZ_MCP_NONEXISTENT_DROP_81",
            confirm=True,
            if_exists=True,
        ),
    )
    assert out.dropped is True
