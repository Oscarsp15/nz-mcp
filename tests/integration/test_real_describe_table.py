"""Optional integration test for ``nz_describe_table`` against real Netezza."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nz_mcp.tools.describe_table import DescribeTableInput, nz_describe_table
from nz_mcp.tools.tables import ListTablesInput, nz_list_tables


@pytest.mark.integration
def test_real_nz_describe_table() -> None:
    if os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1":
        pytest.skip("Set NZ_MCP_RUN_INTEGRATION=1 to run integration tests against real Netezza")

    config_override = os.environ.get("NZ_MCP_INTEGRATION_PROFILES")
    config_path = Path(config_override) if config_override else None

    tables_out = nz_list_tables(
        ListTablesInput(database="DEV", table_schema="PUBLIC"),
        config_path=config_path,
    )
    if not tables_out.tables:
        pytest.skip("No tables in PUBLIC to describe")

    first = tables_out.tables[0].name
    out = nz_describe_table(
        DescribeTableInput(database="DEV", table_schema="PUBLIC", table=first),
        config_path=config_path,
    )
    assert out.kind == "TABLE"
    assert isinstance(out.columns, list)
