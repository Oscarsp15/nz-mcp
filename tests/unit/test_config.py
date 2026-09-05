"""config.py — profiles loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.config import (
    get_active_profile,
    get_profile,
    list_profile_names,
    load_profiles_file,
    remove_profile,
    update_profile_fields,
    upsert_profile,
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


def test_security_level_defaults_to_preferred_secured(tmp_profiles: Path) -> None:
    tmp_profiles.write_text(
        '[profiles.only]\nhost = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n',
        encoding="utf-8",
    )
    # Secure-by-default: no security_level in the file negotiates SSL (preferred-secured).
    assert get_profile("only", path=tmp_profiles).security_level == 2


def test_security_level_explicit_value_is_loaded(tmp_profiles: Path) -> None:
    tmp_profiles.write_text(
        "[profiles.saas]\n"
        'host = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n'
        "security_level = 3\n",
        encoding="utf-8",
    )
    assert get_profile("saas", path=tmp_profiles).security_level == 3


@pytest.mark.parametrize("bad", [-1, 4, 99])
def test_security_level_out_of_range_rejected(tmp_profiles: Path, bad: int) -> None:
    tmp_profiles.write_text(
        "[profiles.bad]\n"
        'host = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n'
        f"security_level = {bad}\n",
        encoding="utf-8",
    )
    with pytest.raises(InvalidProfileError):
        get_profile("bad", path=tmp_profiles)


def test_ca_certs_defaults_to_none(tmp_profiles: Path) -> None:
    tmp_profiles.write_text(
        '[profiles.only]\nhost = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n',
        encoding="utf-8",
    )
    # No CA bundle configured: certificate verification is skipped (opt-in only).
    assert get_profile("only", path=tmp_profiles).ca_certs is None


def test_ca_certs_explicit_path_is_loaded(tmp_profiles: Path) -> None:
    tmp_profiles.write_text(
        "[profiles.saas]\n"
        'host = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n'
        'ca_certs = "/etc/nz/ca.pem"\n',
        encoding="utf-8",
    )
    assert get_profile("saas", path=tmp_profiles).ca_certs == "/etc/nz/ca.pem"


def test_unknown_profile_field_still_rejected(tmp_profiles: Path) -> None:
    tmp_profiles.write_text(
        "[profiles.bad]\n"
        'host = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n'
        "skip_cert_verification = true\n",
        encoding="utf-8",
    )
    # extra="forbid" is preserved: typos or unsupported keys must not pass silently.
    with pytest.raises(InvalidProfileError):
        get_profile("bad", path=tmp_profiles)


# --- upsert_profile -----------------------------------------------------------


def _block(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "host": "h",
        "port": 5480,
        "database": "DB",
        "user": "u",
        "mode": "read",
    }
    base.update(overrides)
    return base


def test_upsert_profile_creates_section(tmp_profiles: Path) -> None:
    upsert_profile("dev", _block(), path=tmp_profiles, set_active=True)
    file = load_profiles_file(tmp_profiles)
    assert file.active == "dev"
    assert list(file.profiles) == ["dev"]


def test_upsert_profile_replaces_instead_of_duplicating(tmp_profiles: Path) -> None:
    upsert_profile("dev", _block(), path=tmp_profiles)
    upsert_profile("dev", _block(host="h2", mode="write"), path=tmp_profiles)
    content = tmp_profiles.read_text(encoding="utf-8")
    assert content.count("[profiles.dev]") == 1
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == "h2"
    assert profile.mode == "write"


def test_upsert_profile_keeps_other_profiles(two_profiles: Path) -> None:
    upsert_profile("dev", _block(host="new-host"), path=two_profiles)
    assert list_profile_names(two_profiles) == ["dev", "prod"]
    assert get_profile("prod", path=two_profiles).host == "nz-prod.example.com"


def test_upsert_profile_invalid_block_leaves_file_untouched(two_profiles: Path) -> None:
    before = two_profiles.read_text(encoding="utf-8")
    with pytest.raises(InvalidProfileError):
        upsert_profile("dev", _block(port=0), path=two_profiles)
    assert two_profiles.read_text(encoding="utf-8") == before


# --- remove_profile -----------------------------------------------------------


def test_remove_profile_deletes_section(two_profiles: Path) -> None:
    was_active = remove_profile("prod", path=two_profiles)
    assert was_active is False
    assert list_profile_names(two_profiles) == ["dev"]
    assert "[profiles.prod]" not in two_profiles.read_text(encoding="utf-8")


def test_remove_profile_clears_active_when_it_was_active(two_profiles: Path) -> None:
    was_active = remove_profile("dev", path=two_profiles)
    assert was_active is True
    file = load_profiles_file(two_profiles)
    assert file.active is None
    assert list(file.profiles) == ["prod"]


def test_remove_profile_unknown_raises(two_profiles: Path) -> None:
    with pytest.raises(ProfileNotFoundError):
        remove_profile("ghost", path=two_profiles)


def test_remove_profile_missing_file_raises(tmp_profiles: Path) -> None:
    with pytest.raises(ProfileNotFoundError):
        remove_profile("dev", path=tmp_profiles)


def test_remove_last_profile_leaves_loadable_file(tmp_profiles: Path) -> None:
    upsert_profile("only", _block(), path=tmp_profiles, set_active=True)
    remove_profile("only", path=tmp_profiles)
    file = load_profiles_file(tmp_profiles)
    assert file.profiles == {}
    assert file.active is None
