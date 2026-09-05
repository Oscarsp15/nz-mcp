"""Integration test for ``nz_list_tables`` against real Netezza."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.tools.tables import ListTablesInput, nz_list_tables


@pytest.mark.integration
def test_real_nz_list_tables(
    integration_config_path: Path | None,
    integration_database: str,
    integration_schema: str,
) -> None:
    out = nz_list_tables(
        ListTablesInput(database=integration_database, table_schema=integration_schema),
        config_path=integration_config_path,
    )
    assert isinstance(out.tables, list)
