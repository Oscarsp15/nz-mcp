"""Tests for session tools (nz_current_profile, nz_switch_profile)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import ProfileNotFoundError
from nz_mcp.tools.session import (
    CurrentProfileInput,
    SwitchProfileInput,
    nz_current_profile,
    nz_switch_profile,
)


def test_current_profile_returns_active(two_profiles: Path) -> None:
    out = nz_current_profile(CurrentProfileInput(), config_path=two_profiles)
    assert out.profile == "dev"
    assert out.mode == "read"
    assert out.host == "nz-dev.example.com"
    assert sorted(out.available_profiles) == ["dev", "prod"]


def test_current_profile_does_not_expose_password(two_profiles: Path) -> None:
    out = nz_current_profile(CurrentProfileInput(), config_path=two_profiles)
    dumped = out.model_dump()
    keys = {k.lower() for k in dumped}
    assert "password" not in keys
    assert "pwd" not in keys


def test_switch_profile_to_known(two_profiles: Path) -> None:
    out = nz_switch_profile(SwitchProfileInput(profile="prod"), config_path=two_profiles)
    assert out.switched_to == "prod"
    assert out.mode == "read"
    text = two_profiles.read_text(encoding="utf-8")
    assert 'active = "prod"' in text


def test_switch_profile_unknown_raises(two_profiles: Path) -> None:
    with pytest.raises(ProfileNotFoundError) as ei:
        nz_switch_profile(SwitchProfileInput(profile="ghost"), config_path=two_profiles)
    assert ei.value.context.get("available_profiles") == ["dev", "prod"]
    assert "dev" in (ei.value.context.get("hint_en") or "")


def test_switch_profile_does_not_elevate_mode(tmp_profiles: Path) -> None:
    """Even if a profile claims admin, the AI cannot pick it unless it exists with that mode."""
    tmp_profiles.write_text(
        'active = "low"\n'
        "[profiles.low]\n"
        'host = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n'
        "[profiles.high]\n"
        'host = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "admin"\n',
        encoding="utf-8",
    )
    out = nz_switch_profile(SwitchProfileInput(profile="high"), config_path=tmp_profiles)
    assert out.mode == "admin"  # the human granted admin; AI just selected a pre-defined profile

    out_low = nz_switch_profile(SwitchProfileInput(profile="low"), config_path=tmp_profiles)
    assert out_low.mode == "read"
