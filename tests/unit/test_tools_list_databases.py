"""Tests for ``nz_list_databases`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nz_mcp.config import MAX_ROWS_CAP
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
    assert out.truncated is False
    assert out.hint is None


# ── issue #305: max_rows / truncated / hint, same pattern as nz_list_procedures ──


def _fake_databases(count: int) -> list[dict[str, str]]:
    return [{"name": f"DB{i}", "owner": "ADMIN"} for i in range(count)]


def test_nz_list_databases_under_cap_is_not_truncated(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.databases.list_databases",
        lambda *_a, **_k: _fake_databases(3),
    )
    out = nz_list_databases(ListDatabasesInput(max_rows=10), config_path=two_profiles)
    assert len(out.databases) == 3
    assert out.truncated is False
    assert out.hint is None


def test_nz_list_databases_truncates_and_hints(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.databases.list_databases",
        lambda *_a, **_k: _fake_databases(150),
    )
    out = nz_list_databases(ListDatabasesInput(max_rows=5), config_path=two_profiles)
    assert len(out.databases) == 5
    assert out.databases[0].name == "DB0"
    assert out.truncated is True
    assert out.hint is not None
    assert "150" in out.hint
    assert "pattern" in out.hint
    assert "max_rows" in out.hint


def test_nz_list_databases_defaults_to_profile_max_rows(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Without max_rows the active profile default (100) applies."""
    monkeypatch.setattr(
        "nz_mcp.tools.databases.list_databases",
        lambda *_a, **_k: _fake_databases(101),
    )
    out = nz_list_databases(ListDatabasesInput(), config_path=two_profiles)
    assert len(out.databases) == 100
    assert out.truncated is True


def test_list_databases_input_rejects_max_rows_over_cap() -> None:
    with pytest.raises(ValidationError):
        ListDatabasesInput.model_validate({"max_rows": MAX_ROWS_CAP + 1})


def test_nz_list_databases_propagates_typed_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise_list_databases(_profile: object, pattern: str | None = None) -> list[dict[str, str]]:
        raise NetezzaError(operation="list_databases", detail="permission denied")

    monkeypatch.setattr("nz_mcp.tools.databases.list_databases", _raise_list_databases)

    with pytest.raises(NetezzaError) as exc:
        nz_list_databases(ListDatabasesInput(), config_path=two_profiles)

    assert exc.value.code == "NETEZZA_ERROR"
