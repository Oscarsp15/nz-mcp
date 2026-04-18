"""config.py — profiles loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.config import (
    get_active_profile,
    get_profile,
    list_profile_names,
    load_profiles_file,
    update_profile_fields,
)
from nz_mcp.errors import InvalidProfileError, ProfileNotFoundError


def test_load_missing_file_returns_empty(tmp_profiles: Path) -> None:
    file = load_profiles_file(tmp_profiles)
    assert file.profiles == {}
    assert file.active is None


def test_get_profile_unknown_raises(tmp_profiles: Path) -> None:
    with pytest.raises(ProfileNotFoundError):
        get_profile("ghost", path=tmp_profiles)


def test_active_profile_with_two(two_profiles: Path) -> None:
    profile = get_active_profile(path=two_profiles)
    assert profile.name == "dev"
    assert profile.mode == "read"


def test_list_profile_names(two_profiles: Path) -> None:
    names = list_profile_names(path=two_profiles)
    assert names == ["dev", "prod"]


def test_invalid_toml_raises(tmp_profiles: Path) -> None:
    tmp_profiles.write_text("not = valid = toml\n", encoding="utf-8")
    with pytest.raises(InvalidProfileError):
        load_profiles_file(tmp_profiles)


def test_invalid_profile_schema_raises(tmp_profiles: Path) -> None:
    tmp_profiles.write_text(
        "[profiles.bad]\nhost = 1\n",  # host must be string, missing required fields
        encoding="utf-8",
    )
    with pytest.raises(InvalidProfileError):
        get_profile("bad", path=tmp_profiles)


def test_single_profile_inferred_as_active(tmp_profiles: Path) -> None:
    tmp_profiles.write_text(
        '[profiles.only]\nhost = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n',
        encoding="utf-8",
    )
    profile = get_active_profile(path=tmp_profiles)
    assert profile.name == "only"


def test_update_profile_fields_changes_mode(two_profiles: Path) -> None:
    updated = update_profile_fields("dev", two_profiles, mode="write")
    assert updated is not None
    assert updated.mode == "write"
    assert get_profile("dev", path=two_profiles).mode == "write"


def test_update_profile_fields_noop_returns_none(two_profiles: Path) -> None:
    assert update_profile_fields("dev", two_profiles) is None


def test_update_profile_fields_unknown_profile(two_profiles: Path) -> None:
    with pytest.raises(ProfileNotFoundError):
        update_profile_fields("nope", two_profiles, mode="read")
