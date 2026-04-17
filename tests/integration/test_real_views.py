"""Integration tests for view tools against real Netezza."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nz_mcp.tools.views import GetViewDdlInput, ListViewsInput, nz_get_view_ddl, nz_list_views


@pytest.mark.integration
def test_real_nz_list_views() -> None:
    if os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1":
        pytest.skip("Set NZ_MCP_RUN_INTEGRATION=1 to run integration tests against real Netezza")

    config_override = os.environ.get("NZ_MCP_INTEGRATION_PROFILES")
    config_path = Path(config_override) if config_override else None

    out = nz_list_views(
        ListViewsInput(database="DEV", view_schema="PUBLIC"),
        config_path=config_path,
    )
    assert isinstance(out.views, list)


@pytest.mark.integration
def test_real_nz_get_view_ddl() -> None:
    if os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1":
        pytest.skip("Set NZ_MCP_RUN_INTEGRATION=1 to run integration tests against real Netezza")

    config_override = os.environ.get("NZ_MCP_INTEGRATION_PROFILES")
    config_path = Path(config_override) if config_override else None

    listed = nz_list_views(
        ListViewsInput(database="DEV", view_schema="PUBLIC"),
        config_path=config_path,
    )
    if not listed.views:
        pytest.skip("No views in PUBLIC to fetch DDL for")

    first = listed.views[0].name
    out = nz_get_view_ddl(
        GetViewDdlInput(database="DEV", view_schema="PUBLIC", view=first),
        config_path=config_path,
    )
    assert isinstance(out.ddl, str)
    assert len(out.ddl) > 0
