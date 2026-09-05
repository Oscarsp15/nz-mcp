"""Tests for CLI internal helpers (profile writing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.cli import _ensure_config_dir, _write_profile
from nz_mcp.config import get_profile, list_profile_names, load_profiles_file


def test_ensure_config_dir_idempotent(tmp_profiles: Path) -> None:
    _ensure_config_dir()
    _ensure_config_dir()  # second call must not raise


@pytest.mark.parametrize("set_active", [True, False])
def test_write_profile_creates_block(tmp_profiles: Path, set_active: bool) -> None:
    _write_profile(
        name="dev",
        host="h",
        port=5480,
        database="DB",
        user="u",
        mode="read",
        set_active=set_active,
    )
    file = load_profiles_file(tmp_profiles)
    assert list(file.profiles) == ["dev"]
    assert get_profile("dev", path=tmp_profiles).host == "h"
    assert file.active == ("dev" if set_active else None)


def test_write_profile_appends_second(tmp_profiles: Path) -> None:
    _write_profile(
        name="dev", host="h", port=5480, database="DB", user="u", mode="read", set_active=True
    )
    _write_profile(
        name="prod", host="h2", port=5480, database="P", user="u", mode="write", set_active=False
    )
    file = load_profiles_file(tmp_profiles)
    assert list_profile_names(tmp_profiles) == ["dev", "prod"]
    # active stays as dev (already present)
    assert file.active == "dev"


def test_write_profile_same_name_replaces_section(tmp_profiles: Path) -> None:
    _write_profile(
        name="dev", host="h", port=5480, database="DB", user="u", mode="read", set_active=True
    )
    _write_profile(
        name="dev", host="h2", port=5481, database="DB2", user="u2", mode="write", set_active=True
    )
    content = tmp_profiles.read_text(encoding="utf-8")
    assert content.count("[profiles.dev]") == 1
    # The file must still load: a duplicated section made tomllib reject the whole file.
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == "h2"
    assert profile.port == 5481
    assert profile.database == "DB2"
    assert profile.mode == "write"


def test_write_profile_overwrite_keeps_unmanaged_fields(tmp_profiles: Path) -> None:
    """Overwriting must not drop TLS settings the wizard never asks for (issue #167)."""
    _write_profile(
        name="dev", host="h", port=5480, database="DB", user="u", mode="read", set_active=True
    )
    raw = tmp_profiles.read_text(encoding="utf-8")
    tmp_profiles.write_text(
        raw + 'security_level = 3\nca_certs = "/etc/ssl/nz.pem"\n', encoding="utf-8"
    )

    _write_profile(
        name="dev", host="h2", port=5481, database="DB2", user="u2", mode="write", set_active=True
    )

    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == "h2"
    assert profile.security_level == 3
    assert profile.ca_certs == "/etc/ssl/nz.pem"
