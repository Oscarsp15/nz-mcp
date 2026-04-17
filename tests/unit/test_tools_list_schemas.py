"""Tests for ``nz_list_schemas`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import NetezzaError
from nz_mcp.tools.schemas import ListSchemasInput, nz_list_schemas


def test_nz_list_schemas_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_list_schemas(
        _profile: object,
        database: str,
        pattern: str | None = None,
    ) -> list[dict[str, str]]:
        assert database == "DEV"
        assert pattern == "P%"
        return [
            {"name": "PUBLIC", "owner": "ADMIN"},
            {"name": "PRD", "owner": "DBA"},
        ]

    monkeypatch.setattr("nz_mcp.tools.schemas.list_schemas", _fake_list_schemas)
    out = nz_list_schemas(
        ListSchemasInput(database="DEV", pattern="P%"),
        config_path=two_profiles,
    )

    assert [item.name for item in out.schemas] == ["PUBLIC", "PRD"]
    assert [item.owner for item in out.schemas] == ["ADMIN", "DBA"]


def test_nz_list_schemas_propagates_typed_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise_list_schemas(
        _profile: object,
        database: str,
        pattern: str | None = None,
    ) -> list[dict[str, str]]:
        raise NetezzaError(operation="list_schemas", detail="denied")

    monkeypatch.setattr("nz_mcp.tools.schemas.list_schemas", _raise_list_schemas)

    with pytest.raises(NetezzaError) as exc:
        nz_list_schemas(ListSchemasInput(database="DEV"), config_path=two_profiles)

    assert exc.value.code == "NETEZZA_ERROR"
