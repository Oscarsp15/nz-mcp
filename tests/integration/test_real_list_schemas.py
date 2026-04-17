"""Integration test for ``nz_list_schemas`` against real Netezza."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nz_mcp.tools.schemas import ListSchemasInput, nz_list_schemas


@pytest.mark.integration
def test_real_nz_list_schemas() -> None:
    if os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1":
        pytest.skip("Set NZ_MCP_RUN_INTEGRATION=1 to run integration tests against real Netezza")

    config_override = os.environ.get("NZ_MCP_INTEGRATION_PROFILES")
    config_path = Path(config_override) if config_override else None

    out = nz_list_schemas(ListSchemasInput(database="DEV"), config_path=config_path)
    assert isinstance(out.schemas, list)
