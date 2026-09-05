"""Shared pytest fixtures.

Notes:
- ``isolated_keyring`` autouse: every test gets a fresh in-memory keyring backend.
- Explicitly enabled integration tests are the single exception: they authenticate against
  a real Netezza with the credential of a real profile, so keyring reads go through to the
  OS backend. Writes stay blocked even there (see ``_readonly_real_keyring``).
- ``tmp_profiles`` writes a ``profiles.toml`` under ``tmp_path`` and points config there.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import keyring as _keyring
import pytest

from nz_mcp import config

#: Opt-in switch for the integration suite; see docs/standards/testing.md.
RUN_INTEGRATION_ENV = "NZ_MCP_RUN_INTEGRATION"

#: Only tests living under this directory may ever reach the real OS keyring.
INTEGRATION_DIR = Path(__file__).parent / "integration"


class _TestKeyringBackend:
    """Stub backend so ``nz_mcp doctor`` sees keyring as available in tests.

    CI runners are often headless; the real default is often ``FailKeyring``, which would
    make ``doctor`` exit 1 and break smoke tests unrelated to keyring behavior.
    """

    __slots__ = ()


def _uses_real_keyring(request: pytest.FixtureRequest) -> bool:
    """Whether this test is allowed to read the real OS keyring.

    Three conditions must hold at once, so a unit test can never reach the real keyring by
    accident: the opt-in env var is set, the test carries the ``integration`` marker, and
    the test module lives under ``tests/integration/``.
    """
    if os.environ.get(RUN_INTEGRATION_ENV) != "1":
        return False
    if request.node.get_closest_marker("integration") is None:
        return False
    module_path = getattr(request.node, "path", None)
    if module_path is None:  # pragma: no cover - pytest always sets ``path`` on items
        return False
    return INTEGRATION_DIR in Path(module_path).parents


def _readonly_real_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let reads reach the OS keyring, but fail loudly on any write.

    Integration tests only consume a credential stored beforehand by the developer; none of
    them may create, overwrite or delete an entry in the real keyring.
    """

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "integration tests must not write to the real keyring; "
            "store the profile password with `nz-mcp set-password` instead",
        )

    monkeypatch.setattr(_keyring, "set_password", _blocked)
    monkeypatch.setattr(_keyring, "delete_password", _blocked)


@pytest.fixture(autouse=True)
def isolated_keyring(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace keyring globals with an in-memory store."""
    if _uses_real_keyring(request):
        _readonly_real_keyring(monkeypatch)
        return

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
