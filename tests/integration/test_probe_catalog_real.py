"""Optional integration test: ``probe-catalog`` logic against real Netezza."""

from __future__ import annotations

import pytest

from nz_mcp.catalog.probe import run_probe_catalog
from nz_mcp.catalog.queries import ALL_QUERIES
from nz_mcp.config import Profile


@pytest.mark.integration
def test_real_probe_catalog_run(integration_profile: Profile) -> None:
    run = run_probe_catalog(integration_profile)
    assert run.profile_name == integration_profile.name
    if run.config_error is None:
        assert len(run.results) == len(ALL_QUERIES)
