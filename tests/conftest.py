"""Shared pytest fixtures.

Notes:
- ``isolated_keyring`` autouse: every test gets a fresh in-memory keyring backend.
- ``tmp_profiles`` writes a ``profiles.toml`` under ``tmp_path`` and points config there.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import keyring as _keyring
import pytest

from nz_mcp import config


class _TestKeyringBackend:
    """Stub backend so ``nz_mcp doctor`` sees keyring as available in tests.

    CI runners are often headless; the real default is often ``FailKeyring``, which would
    make ``doctor`` exit 1 and break smoke tests unrelated to keyring behavior.
    """

    __slots__ = ()


@pytest.fixture(autouse=True)
def isolated_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace keyring globals with an in-memory store."""
    store: dict[tuple[str, str], str] = {}

    def _set(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def _get(service: str, username: str) -> str | None:
        return store.get((service, username))

    def _delete(service: str, username: str) -> None:
        store.pop((service, username), None)

    def _get_keyring() -> _TestKeyringBackend:
        return _TestKeyringBackend()

    monkeypatch.setattr(_keyring, "set_password", _set)
    monkeypatch.setattr(_keyring, "get_password", _get)
    monkeypatch.setattr(_keyring, "delete_password", _delete)
    monkeypatch.setattr(_keyring, "get_keyring", _get_keyring)


@pytest.fixture
def tmp_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Provide an isolated profiles.toml path and point NZ_MCP_HOME to it."""
    home = tmp_path / "nz-mcp"
    home.mkdir()
    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(config, "config_dir", lambda: home)
    profiles_file = home / "profiles.toml"
    yield profiles_file


@pytest.fixture
def two_profiles(tmp_profiles: Path) -> Path:
    """Pre-populate two profiles (dev/prod) with active=dev."""
    tmp_profiles.write_text(
        'active = "dev"\n'
        "\n[profiles.dev]\n"
        'host = "nz-dev.example.com"\nport = 5480\n'
        'database = "DEV"\nuser = "svc_dev"\nmode = "read"\n'
        "max_rows_default = 100\ntimeout_s_default = 30\n"
        "\n[profiles.prod]\n"
        'host = "nz-prod.example.com"\nport = 5480\n'
        'database = "PROD"\nuser = "svc_prod"\nmode = "read"\n'
        "max_rows_default = 100\ntimeout_s_default = 30\n",
        encoding="utf-8",
    )
    return tmp_profiles
