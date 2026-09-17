"""Tests for ``nz_list_schemas`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nz_mcp.config import MAX_ROWS_CAP
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
    assert out.truncated is False
    assert out.hint is None


# ── issue #305: max_rows / truncated / hint, same pattern as nz_list_procedures ──


def _fake_schemas(count: int) -> list[dict[str, str]]:
    return [{"name": f"SCH{i}", "owner": "ADMIN"} for i in range(count)]


def test_nz_list_schemas_under_cap_is_not_truncated(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.schemas.list_schemas",
        lambda *_a, **_k: _fake_schemas(3),
    )
    out = nz_list_schemas(
        ListSchemasInput(database="DEV", max_rows=10),
        config_path=two_profiles,
    )
    assert len(out.schemas) == 3
    assert out.truncated is False
    assert out.hint is None


def test_nz_list_schemas_truncates_and_hints(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.schemas.list_schemas",
        lambda *_a, **_k: _fake_schemas(150),
    )
    out = nz_list_schemas(
        ListSchemasInput(database="DEV", max_rows=5),
        config_path=two_profiles,
    )
    assert len(out.schemas) == 5
    assert out.schemas[0].name == "SCH0"
    assert out.truncated is True
    assert out.hint is not None
    assert "150" in out.hint
    assert "pattern" in out.hint
    assert "max_rows" in out.hint


def test_nz_list_schemas_defaults_to_profile_max_rows(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Without max_rows the active profile default (100) applies."""
    monkeypatch.setattr(
        "nz_mcp.tools.schemas.list_schemas",
        lambda *_a, **_k: _fake_schemas(101),
    )
    out = nz_list_schemas(ListSchemasInput(database="DEV"), config_path=two_profiles)
    assert len(out.schemas) == 100
    assert out.truncated is True


def test_list_schemas_input_rejects_max_rows_over_cap() -> None:
    with pytest.raises(ValidationError):
        ListSchemasInput.model_validate({"database": "DEV", "max_rows": MAX_ROWS_CAP + 1})


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
