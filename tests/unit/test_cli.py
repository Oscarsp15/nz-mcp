"""CLI smoke tests via typer.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nz_mcp import __version__
from nz_mcp.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_list_profiles_empty(tmp_profiles: Path) -> None:
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    assert "sin perfiles" in result.stdout


def test_list_profiles_with_two(two_profiles: Path) -> None:
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    assert "dev" in result.stdout
    assert "prod" in result.stdout


def test_serve_is_stub() -> None:
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    assert "stub" in result.output


def test_doctor_smoke_ok(two_profiles: Path) -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "nz-mcp" in out
    assert "python" in out


def _fail_keyring_backend() -> object:
    from keyring.backends.fail import Keyring as FailKeyring

    return FailKeyring()  # type: ignore[no-untyped-call]


def test_doctor_exit_1_when_keyring_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    import keyring as kr

    monkeypatch.setattr(kr, "get_keyring", _fail_keyring_backend)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
