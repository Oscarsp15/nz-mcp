"""CLI smoke tests via typer.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path

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
