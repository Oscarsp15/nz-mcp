"""The reported version must never drift from the package (issue #352)."""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from nz_mcp import _FALLBACK_VERSION, current_version


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


def test_fallback_version_matches_pyproject() -> None:
    """The source fallback must stay in sync with the declared project version.

    This is the drift guard: 0.1.0a4 and 0.1.0a5 shipped with a stale constant because the
    release bump only touched ``pyproject.toml``.
    """
    assert _pyproject_version() == _FALLBACK_VERSION


def test_current_version_falls_back_to_the_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running from source (no distribution metadata) reports the packaged constant."""

    def _missing(_name: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", _missing)
    assert current_version() == _FALLBACK_VERSION
