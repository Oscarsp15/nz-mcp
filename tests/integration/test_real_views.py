"""Integration tests for view tools against real Netezza."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.tools.views import GetViewDdlInput, ListViewsInput, nz_get_view_ddl, nz_list_views


@pytest.mark.integration
def test_real_nz_list_views(
    integration_config_path: Path | None,
    integration_database: str,
    integration_schema: str,
) -> None:
    out = nz_list_views(
        ListViewsInput(database=integration_database, view_schema=integration_schema),
        config_path=integration_config_path,
    )
    assert isinstance(out.views, list)


@pytest.mark.integration
def test_real_nz_get_view_ddl(
    integration_config_path: Path | None,
    integration_database: str,
    integration_schema: str,
) -> None:
    listed = nz_list_views(
        ListViewsInput(database=integration_database, view_schema=integration_schema),
        config_path=integration_config_path,
    )
    if not listed.views:
        pytest.skip(f"No views in {integration_database}.{integration_schema} to fetch DDL for")

    first = listed.views[0].name
    out = nz_get_view_ddl(
        GetViewDdlInput(
            database=integration_database,
            view_schema=integration_schema,
            view=first,
        ),
        config_path=integration_config_path,
    )
    assert isinstance(out.ddl, str)
    assert len(out.ddl) > 0
