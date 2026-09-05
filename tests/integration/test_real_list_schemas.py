"""Integration test for ``nz_list_schemas`` against real Netezza."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.tools.schemas import ListSchemasInput, nz_list_schemas


@pytest.mark.integration
def test_real_nz_list_schemas(
    integration_config_path: Path | None,
    integration_database: str,
) -> None:
    out = nz_list_schemas(
        ListSchemasInput(database=integration_database),
        config_path=integration_config_path,
    )
    assert isinstance(out.schemas, list)
