"""Tests for CLI internal helpers (profile writing, atomic write)."""
from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.cli import _atomic_write, _ensure_config_dir, _write_profile


def test_atomic_write_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.toml"
    _atomic_write(target, "hello = 1\n")
    assert target.read_text(encoding="utf-8") == "hello = 1\n"


def test_atomic_write_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "out.toml"
    _atomic_write(target, "a = 1\n")
    _atomic_write(target, "b = 2\n")
    assert target.read_text(encoding="utf-8") == "b = 2\n"


def test_ensure_config_dir_idempotent(tmp_profiles: Path) -> None:  # noqa: ARG001
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
    content = tmp_profiles.read_text(encoding="utf-8")
    assert "[profiles.dev]" in content
    assert 'host = "h"' in content
    if set_active:
        assert 'active = "dev"' in content


def test_write_profile_appends_second(tmp_profiles: Path) -> None:
    _write_profile(name="dev", host="h", port=5480, database="DB", user="u", mode="read", set_active=True)
    _write_profile(name="prod", host="h2", port=5480, database="P", user="u", mode="write", set_active=False)
    content = tmp_profiles.read_text(encoding="utf-8")
    assert "[profiles.dev]" in content
    assert "[profiles.prod]" in content
    # active stays as dev (already present)
    assert content.count('active = ') == 1
