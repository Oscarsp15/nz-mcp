"""Tests for the nz_find_duplicates MCP tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nz_mcp.errors import InvalidInputError, ObjectNotFoundError
from nz_mcp.tools.find_duplicates import FindDuplicatesInput, nz_find_duplicates


def test_find_duplicates_input_accepts_wire_schema_key() -> None:
    parsed = FindDuplicatesInput.model_validate(
        {"database": "DEV", "schema": "DBO", "table": "T", "key_columns": ["A", "B"]},
    )
    assert parsed.table_schema == "DBO"
    assert parsed.key_columns == ["A", "B"]
    assert parsed.limit == 10


def test_find_duplicates_rejects_empty_key_columns() -> None:
    with pytest.raises(ValidationError):
        FindDuplicatesInput.model_validate(
            {"database": "DEV", "schema": "DBO", "table": "T", "key_columns": []},
        )


def test_find_duplicates_rejects_limit_over_cap() -> None:
    with pytest.raises(ValidationError):
        FindDuplicatesInput.model_validate(
            {
                "database": "DEV",
                "schema": "DBO",
                "table": "T",
                "key_columns": ["A"],
                "limit": 101,
            },
        )


def test_find_duplicates_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_find_duplicates(
        _profile: object,
        database: str,
        schema: str,
        table: str,
        key_columns: list[str],
        *,
        limit: int,
        timeout_s: int,
    ) -> dict[str, object]:
        assert (database, schema, table) == ("DEV", "DBO", "T")
        assert key_columns == ["CODCREDITO"]
        assert limit == 5
        return {
            "duplicate_groups": 3,
            "duplicate_rows": 7,
            "sample": [{"key": ["12345"], "count": 3}],
            "truncated": False,
        }

    monkeypatch.setattr("nz_mcp.tools.find_duplicates.find_duplicates", _fake_find_duplicates)
    out = nz_find_duplicates(
        FindDuplicatesInput(
            database="DEV",
            table_schema="DBO",
            table="T",
            key_columns=["CODCREDITO"],
            limit=5,
        ),
        config_path=two_profiles,
    )
    assert out.duplicate_groups == 3
    assert out.duplicate_rows == 7
    assert out.sample[0].key == ["12345"]
    assert out.sample[0].count == 3
    assert out.truncated is False
    assert out.hint is None


def test_find_duplicates_truncated_sets_hint(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_find_duplicates(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "duplicate_groups": 12,
            "duplicate_rows": 40,
            "sample": [{"key": ["x"], "count": 2}],
            "truncated": True,
        }

    monkeypatch.setattr("nz_mcp.tools.find_duplicates.find_duplicates", _fake_find_duplicates)
    out = nz_find_duplicates(
        FindDuplicatesInput(
            database="DEV",
            table_schema="DBO",
            table="T",
            key_columns=["A"],
            limit=1,
        ),
        config_path=two_profiles,
    )
    assert out.truncated is True
    assert out.hint is not None
    assert "12" in out.hint


def test_find_duplicates_propagates_object_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_find_duplicates(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ObjectNotFoundError(code="OBJECT_NOT_FOUND", obj="T")

    monkeypatch.setattr("nz_mcp.tools.find_duplicates.find_duplicates", _fake_find_duplicates)
    with pytest.raises(ObjectNotFoundError):
        nz_find_duplicates(
            FindDuplicatesInput(database="DEV", table_schema="DBO", table="T", key_columns=["A"]),
            config_path=two_profiles,
        )


def test_find_duplicates_propagates_invalid_column(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_find_duplicates(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise InvalidInputError(detail="Column(s) NOPE do not exist.")

    monkeypatch.setattr("nz_mcp.tools.find_duplicates.find_duplicates", _fake_find_duplicates)
    with pytest.raises(InvalidInputError):
        nz_find_duplicates(
            FindDuplicatesInput(
                database="DEV", table_schema="DBO", table="T", key_columns=["NOPE"]
            ),
            config_path=two_profiles,
        )
