"""Optional integration test for ``nz_describe_table`` against real Netezza."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.tools.describe_table import DescribeTableInput, nz_describe_table
from nz_mcp.tools.tables import ListTablesInput, nz_list_tables


@pytest.mark.integration
def test_real_nz_describe_table(
    integration_config_path: Path | None,
    integration_database: str,
    integration_schema: str,
) -> None:
    tables_out = nz_list_tables(
        ListTablesInput(database=integration_database, table_schema=integration_schema),
        config_path=integration_config_path,
    )
    if not tables_out.tables:
        pytest.skip(f"No tables in {integration_database}.{integration_schema} to describe")

    first = tables_out.tables[0].name
    out = nz_describe_table(
        DescribeTableInput(
            database=integration_database,
            table_schema=integration_schema,
            table=first,
        ),
        config_path=integration_config_path,
    )
    assert out.kind == "TABLE"
    assert isinstance(out.columns, list)
