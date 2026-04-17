"""Integration test for ``nz_list_tables`` against real Netezza."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nz_mcp.tools.tables import ListTablesInput, nz_list_tables


@pytest.mark.integration
def test_real_nz_list_tables() -> None:
    if os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1":
        pytest.skip("Set NZ_MCP_RUN_INTEGRATION=1 to run integration tests against real Netezza")

    config_override = os.environ.get("NZ_MCP_INTEGRATION_PROFILES")
    config_path = Path(config_override) if config_override else None

    out = nz_list_tables(
        ListTablesInput(database="DEV", table_schema="PUBLIC"),
        config_path=config_path,
    )
    assert isinstance(out.tables, list)
