"""Fixtures for the integration suite (real Netezza, no driver double).

These tests only run when ``NZ_MCP_RUN_INTEGRATION=1`` is exported and a live profile is
reachable (VPN). See ``docs/standards/testing.md`` for the exact command.

Coordinates (database/schema) are never hardcoded: they default to the active profile, so
the suite is runnable on any installation, and can be overridden per environment with
``NZ_MCP_TEST_DATABASE`` / ``NZ_MCP_TEST_SCHEMA``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nz_mcp.config import Profile, get_active_profile, get_profile

RUN_INTEGRATION_ENV = "NZ_MCP_RUN_INTEGRATION"

_SKIP_REASON = (
    "Set NZ_MCP_RUN_INTEGRATION=1 (and connect the VPN) to run the integration suite "
    "against a real Netezza."
)


@pytest.fixture(autouse=True)
def require_live_netezza() -> None:
    """Skip the whole integration suite unless it is explicitly enabled.

    Autouse and local to ``tests/integration/``: without the opt-in these tests never open
    a socket and never read the developer's keyring.
    """
    if os.environ.get(RUN_INTEGRATION_ENV) != "1":
        pytest.skip(_SKIP_REASON)


@pytest.fixture
def integration_config_path() -> Path | None:
    """Optional ``profiles.toml`` override via ``NZ_MCP_INTEGRATION_PROFILES``."""
    override = os.environ.get("NZ_MCP_INTEGRATION_PROFILES")
    return Path(override) if override else None


@pytest.fixture
def integration_profile(integration_config_path: Path | None) -> Profile:
    """Profile under test: ``NZ_MCP_INTEGRATION_PROFILE`` or the active one."""
    name = os.environ.get("NZ_MCP_INTEGRATION_PROFILE")
    if name:
        return get_profile(name, path=integration_config_path)
    return get_active_profile(path=integration_config_path)


@pytest.fixture
def integration_database(integration_profile: Profile) -> str:
    """Database to query: ``NZ_MCP_TEST_DATABASE`` or the profile's own database.

    DDL tools reject any database other than the active profile's one, so defaulting to the
    profile keeps read and write tests on the same coordinates.
    """
    return os.environ.get("NZ_MCP_TEST_DATABASE") or integration_profile.database


@pytest.fixture
def integration_schema() -> str:
    """Schema to query: ``NZ_MCP_TEST_SCHEMA`` or the Netezza default ``DBO``."""
    return os.environ.get("NZ_MCP_TEST_SCHEMA") or "DBO"
