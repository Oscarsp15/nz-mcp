"""Unit tests for nz_switch_database."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.config import get_profile
from nz_mcp.errors import InvalidInputError, ObjectNotFoundError
from nz_mcp.tools.session import SwitchDatabaseInput, nz_switch_database


def _write_profile(path: Path, *, database: str = "DESA_MODELOS") -> None:
    path.write_text(
        'active = "nzsaas"\n'
        "\n[profiles.nzsaas]\n"
        'host = "10.51.10.242"\nport = 5480\n'
        f'database = "{database}"\nuser = "UAIPSCREA1"\nmode = "admin"\n',
        encoding="utf-8",
    )


def test_switch_to_visible_database_updates_profile(
    tmp_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_profile(tmp_profiles)
    monkeypatch.setattr(
        "nz_mcp.tools.session.list_databases",
        lambda _p: [
            {"name": "DESA_MODELOS", "owner": "U"},
            {"name": "DESA_MAESTROBI", "owner": "U"},
        ],
    )
    out = nz_switch_database(
        SwitchDatabaseInput(database="desa_maestrobi"), config_path=tmp_profiles
    )
    assert out.switched_to == "DESA_MAESTROBI"
    assert out.previous_database == "DESA_MODELOS"
    assert out.profile == "nzsaas"
    assert out.mode == "admin"
    # persisted
    assert get_profile("nzsaas", path=tmp_profiles).database == "DESA_MAESTROBI"


def test_switch_same_database_is_noop(tmp_profiles: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_profile(tmp_profiles)

    def _boom(_p: object) -> list[dict[str, str]]:
        raise AssertionError("list_databases must not be called on a no-op switch")

    monkeypatch.setattr("nz_mcp.tools.session.list_databases", _boom)
    out = nz_switch_database(SwitchDatabaseInput(database="DESA_MODELOS"), config_path=tmp_profiles)
    assert out.switched_to == "DESA_MODELOS"
    assert out.previous_database == "DESA_MODELOS"


def test_switch_to_invisible_database_raises(
    tmp_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_profile(tmp_profiles)
    monkeypatch.setattr(
        "nz_mcp.tools.session.list_databases",
        lambda _p: [{"name": "DESA_MODELOS", "owner": "U"}],
    )
    with pytest.raises(ObjectNotFoundError) as ei:
        nz_switch_database(SwitchDatabaseInput(database="NOPE_DB"), config_path=tmp_profiles)
    assert ei.value.context["database"] == "NOPE_DB"
    assert "DESA_MODELOS" in ei.value.context["available"]
    # profile unchanged
    assert get_profile("nzsaas", path=tmp_profiles).database == "DESA_MODELOS"


def test_switch_invalid_identifier_raises(tmp_profiles: Path) -> None:
    _write_profile(tmp_profiles)
    with pytest.raises(InvalidInputError) as ei:
        nz_switch_database(SwitchDatabaseInput(database="bad-name!"), config_path=tmp_profiles)
    assert ei.value.code == "INVALID_DATABASE_NAME"
