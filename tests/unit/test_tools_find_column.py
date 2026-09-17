"""Tests for the ``nz_find_column`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import NetezzaError
from nz_mcp.tools.find_column import FindColumnInput, nz_find_column


def test_nz_find_column_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_find_columns(
        _profile: object,
        database: str,
        column_pattern: str,
        schema_pattern: str | None = None,
        table_pattern: str | None = None,
    ) -> list[dict[str, str]]:
        assert database == "DEV"
        assert column_pattern == "%NUMDOCUMENTO%"
        assert schema_pattern == "DB%"
        assert table_pattern is None
        return [
            {
                "schema": "DBO",
                "table": "CUSTOMERS",
                "column": "NUMDOCUMENTO",
                "type": "VARCHAR(12)",
            },
        ]

    monkeypatch.setattr("nz_mcp.tools.find_column.find_columns", _fake_find_columns)
    out = nz_find_column(
        FindColumnInput(database="DEV", column_pattern="%NUMDOCUMENTO%", schema_pattern="DB%"),
        config_path=two_profiles,
    )

    assert len(out.columns) == 1
    match = out.columns[0]
    assert match.model_dump(by_alias=True) == {
        "schema": "DBO",
        "table": "CUSTOMERS",
        "column": "NUMDOCUMENTO",
        "type": "VARCHAR(12)",
    }
    assert out.truncated is False
    assert out.hint is None
    assert out.duration_ms >= 0


def test_nz_find_column_no_match_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr("nz_mcp.tools.find_column.find_columns", lambda *_a, **_k: [])
    out = nz_find_column(
        FindColumnInput(database="DEV", column_pattern="NOPE%"),
        config_path=two_profiles,
    )
    assert out.columns == []
    assert out.truncated is False


def test_nz_find_column_propagates_typed_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise_find_columns(*_a: object, **_k: object) -> list[dict[str, str]]:
        raise NetezzaError(operation="find_column", detail="denied")

    monkeypatch.setattr("nz_mcp.tools.find_column.find_columns", _raise_find_columns)

    with pytest.raises(NetezzaError) as exc:
        nz_find_column(
            FindColumnInput(database="DEV", column_pattern="X%"),
            config_path=two_profiles,
        )
    assert exc.value.code == "NETEZZA_ERROR"


def _fake_rows(count: int) -> list[dict[str, str]]:
    return [
        {"schema": "DBO", "table": f"T{i}", "column": "COL", "type": "INTEGER"}
        for i in range(count)
    ]


def test_nz_find_column_under_cap_is_not_truncated(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr("nz_mcp.tools.find_column.find_columns", lambda *_a, **_k: _fake_rows(3))
    out = nz_find_column(
        FindColumnInput(database="DEV", column_pattern="COL%", max_rows=10),
        config_path=two_profiles,
    )
    assert len(out.columns) == 3
    assert out.truncated is False
    assert out.hint is None


def test_nz_find_column_truncates_and_hints(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr("nz_mcp.tools.find_column.find_columns", lambda *_a, **_k: _fake_rows(5))
    out = nz_find_column(
        FindColumnInput(database="DEV", column_pattern="COL%", max_rows=2),
        config_path=two_profiles,
    )
    assert len(out.columns) == 2
    assert out.truncated is True
    assert out.hint is not None
