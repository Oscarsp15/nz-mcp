"""Tests for CLI internal helpers (profile writing, Claude Desktop snippet)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nz_mcp.cli import _claude_desktop_snippet, _ensure_config_dir, _ProfileDraft, _write_profile
from nz_mcp.config import PermissionMode, get_profile, list_profile_names, load_profiles_file
from nz_mcp.secret import Secret


def _draft(
    *,
    host: str = "h",
    port: int = 5480,
    database: str = "DB",
    user: str = "u",
    mode: PermissionMode = "read",
    security_level: int = 2,
    ca_certs: str | None = None,
) -> _ProfileDraft:
    return _ProfileDraft(
        host=host,
        port=port,
        database=database,
        user=user,
        password=Secret("pw123456"),
        mode=mode,
        security_level=security_level,
        ca_certs=ca_certs,
    )


def test_ensure_config_dir_idempotent(tmp_profiles: Path) -> None:
    _ensure_config_dir()
    _ensure_config_dir()  # second call must not raise


@pytest.mark.parametrize("set_active", [True, False])
def test_write_profile_creates_block(tmp_profiles: Path, set_active: bool) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=set_active)
    file = load_profiles_file(tmp_profiles)
    assert list(file.profiles) == ["dev"]
    assert get_profile("dev", path=tmp_profiles).host == "h"
    assert file.active == ("dev" if set_active else None)


def test_write_profile_never_persists_the_password(tmp_profiles: Path) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=True)
    assert "pw123456" not in tmp_profiles.read_text(encoding="utf-8")


def test_write_profile_appends_second(tmp_profiles: Path) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=True)
    _write_profile(name="prod", draft=_draft(host="h2", mode="write"), set_active=False)
    file = load_profiles_file(tmp_profiles)
    assert list_profile_names(tmp_profiles) == ["dev", "prod"]
    # active stays as dev (already present)
    assert file.active == "dev"


def test_write_profile_same_name_replaces_section(tmp_profiles: Path) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=True)
    _write_profile(
        name="dev",
        draft=_draft(host="h2", port=5481, database="DB2", user="u2", mode="write"),
        set_active=True,
    )
    content = tmp_profiles.read_text(encoding="utf-8")
    assert content.count("[profiles.dev]") == 1
    # The file must still load: a duplicated section made tomllib reject the whole file.
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == "h2"
    assert profile.port == 5481
    assert profile.database == "DB2"
    assert profile.mode == "write"


def test_write_profile_persists_security_fields(tmp_profiles: Path) -> None:
    _write_profile(
        name="dev",
        draft=_draft(security_level=3, ca_certs="/etc/ssl/nz.pem"),
        set_active=True,
    )
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.security_level == 3
    assert profile.ca_certs == "/etc/ssl/nz.pem"


def test_write_profile_overwrite_keeps_unmanaged_fields(tmp_profiles: Path) -> None:
    """Overwriting must not drop config the wizard never asks for (issue #167)."""
    _write_profile(name="dev", draft=_draft(), set_active=True)
    raw = tmp_profiles.read_text(encoding="utf-8")
    extra = '[profiles.dev.catalog_overrides]\nlist_databases = "SELECT 1"\n'
    tmp_profiles.write_text(raw + extra, encoding="utf-8")

    _write_profile(name="dev", draft=_draft(host="h2", port=5481), set_active=True)

    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == "h2"
    assert profile.catalog_overrides == {"list_databases": "SELECT 1"}


def test_write_profile_overwrite_clears_ca_certs_when_dropped(tmp_profiles: Path) -> None:
    """An empty answer to the CA prompt must not resurrect the previous path."""
    _write_profile(name="dev", draft=_draft(ca_certs="/etc/ssl/nz.pem"), set_active=True)
    _write_profile(name="dev", draft=_draft(ca_certs=None), set_active=True)
    assert get_profile("dev", path=tmp_profiles).ca_certs is None


def test_claude_desktop_snippet_substitutes_the_profile_name() -> None:
    block = json.loads(_claude_desktop_snippet("dev"))
    server = block["mcpServers"]["netezza"]
    assert server["command"] == "nz-mcp"
    assert server["args"] == ["serve"]
    assert server["env"]["NZ_MCP_PROFILE"] == "dev"
