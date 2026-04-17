"""Optional integration test: ``probe-catalog`` logic against real Netezza."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nz_mcp.catalog.probe import run_probe_catalog
from nz_mcp.catalog.queries import ALL_QUERIES
from nz_mcp.config import get_active_profile, get_profile


@pytest.mark.integration
def test_real_probe_catalog_run() -> None:
    if os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1":
        pytest.skip("Set NZ_MCP_RUN_INTEGRATION=1 to run integration tests against real Netezza")

    config_override = os.environ.get("NZ_MCP_INTEGRATION_PROFILES")
    config_path = Path(config_override) if config_override else None

    name = os.environ.get("NZ_MCP_INTEGRATION_PROFILE")
    profile = get_profile(name, path=config_path) if name else get_active_profile(path=config_path)

    run = run_probe_catalog(profile)
    assert run.profile_name == profile.name
    if run.config_error is None:
        assert len(run.results) == len(ALL_QUERIES)
