"""Tests for ``nz_list_databases`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import NetezzaError
from nz_mcp.tools.databases import ListDatabasesInput, nz_list_databases


def test_nz_list_databases_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_list_databases(_profile: object, pattern: str | None = None) -> list[dict[str, str]]:
        assert pattern == "D%"
        return [
            {"name": "DEV", "owner": "ADMIN"},
            {"name": "DATA", "owner": "DBA"},
        ]

    monkeypatch.setattr("nz_mcp.tools.databases.list_databases", _fake_list_databases)
    out = nz_list_databases(ListDatabasesInput(pattern="D%"), config_path=two_profiles)

    assert [item.name for item in out.databases] == ["DEV", "DATA"]
    assert [item.owner for item in out.databases] == ["ADMIN", "DBA"]


def test_nz_list_databases_propagates_typed_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise_list_databases(_profile: object, pattern: str | None = None) -> list[dict[str, str]]:
        raise NetezzaError(operation="list_databases", detail="permission denied")

    monkeypatch.setattr("nz_mcp.tools.databases.list_databases", _raise_list_databases)

    with pytest.raises(NetezzaError) as exc:
        nz_list_databases(ListDatabasesInput(), config_path=two_profiles)

    assert exc.value.code == "NETEZZA_ERROR"
