"""Integration test for ``nz_list_databases`` against real Netezza."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.tools.databases import ListDatabasesInput, nz_list_databases


@pytest.mark.integration
def test_real_nz_list_databases(integration_config_path: Path | None) -> None:
    out = nz_list_databases(ListDatabasesInput(), config_path=integration_config_path)
    assert isinstance(out.databases, list)
