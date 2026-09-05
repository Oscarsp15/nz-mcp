"""Fixtures shared by the role scenarios.

Every scenario drives the same entry point a client uses -- ``server.call_tool`` --
against three profiles that differ only in ``mode``. Nothing here fakes a tool or a
catalog function: the only replaced boundary is ``nzpy.connect``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nzpy
import pytest

from nz_mcp.auth import store_password
from nz_mcp.server import call_tool
from tests.scenarios.netezza_double import FakeNetezza

PASSWORD = "scenario-secret"

# One profile per mode, same host/user: a scenario switches profile to change what it
# is allowed to do, never to change where it points.
_PROFILES = (
    ("analyst", "read"),
    ("engineer", "write"),
    ("dba", "admin"),
)


@dataclass(frozen=True, slots=True)
class ToolSession:
    """Calls tools the way a client does and keeps the driver double reachable."""

    config_path: Path
    netezza: FakeNetezza

    def raw(self, tool: str, **arguments: Any) -> dict[str, Any]:
        return call_tool(tool, arguments, config_path=self.config_path)

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        """Return the ``result`` payload, failing loudly on an error envelope."""
        out = self.raw(tool, **arguments)
        assert "error" not in out, f"{tool} failed: {out.get('error')}"
        return dict(out["result"])

    def error(self, tool: str, **arguments: Any) -> dict[str, Any]:
        """Return the ``error`` payload, failing when the call unexpectedly succeeded."""
        out = self.raw(tool, **arguments)
        assert "error" in out, f"{tool} was expected to fail, got: {out}"
        return dict(out["error"])


@pytest.fixture
def netezza() -> FakeNetezza:
    """A bare in-memory server; each scenario seeds the objects it needs."""
    return FakeNetezza()


@pytest.fixture
def scenario_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write ``profiles.toml`` with one profile per mode and store their passwords."""
    home = tmp_path / "nz-mcp"
    home.mkdir()
    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    from nz_mcp import config

    monkeypatch.setattr(config, "config_dir", lambda: home)

    lines = ['active = "analyst"\n']
    for name, mode in _PROFILES:
        lines.append(
            f"\n[profiles.{name}]\n"
            'host = "nz.example.com"\n'
            "port = 5480\n"
            'database = "DEV"\n'
            f'user = "svc_{name}"\n'
            f'mode = "{mode}"\n'
            "max_rows_default = 100\n"
            "timeout_s_default = 30\n"
        )
    profiles_file = home / "profiles.toml"
    profiles_file.write_text("".join(lines), encoding="utf-8")
    for name, _mode in _PROFILES:
        store_password(name, PASSWORD)
    return profiles_file


@pytest.fixture
def session(
    scenario_profiles: Path,
    netezza: FakeNetezza,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ToolSession]:
    """Wire the driver double into ``nzpy.connect`` and hand back a tool session."""
    monkeypatch.setattr(nzpy, "connect", netezza.connect)
    yield ToolSession(config_path=scenario_profiles, netezza=netezza)
