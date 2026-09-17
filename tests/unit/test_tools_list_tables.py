"""Tests for ``nz_list_tables`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nz_mcp.errors import NetezzaError
from nz_mcp.tools.tables import ListTablesInput, TableItem, nz_list_tables


def test_list_tables_input_accepts_wire_schema_key() -> None:
    parsed = ListTablesInput.model_validate({"database": "DEV", "schema": "PUBLIC"})
    assert parsed.table_schema == "PUBLIC"


def test_list_tables_input_object_type_defaults_to_table() -> None:
    parsed = ListTablesInput.model_validate({"database": "DEV", "schema": "PUBLIC"})
    assert parsed.object_type == "TABLE"


def test_list_tables_input_accepts_all_and_external_table() -> None:
    for value in ("EXTERNAL TABLE", "ALL"):
        parsed = ListTablesInput.model_validate(
            {"database": "DEV", "schema": "PUBLIC", "object_type": value},
        )
        assert parsed.object_type == value


def test_list_tables_input_rejects_unknown_object_type() -> None:
    with pytest.raises(ValidationError):
        ListTablesInput.model_validate(
            {"database": "DEV", "schema": "PUBLIC", "object_type": "VIEW"},
        )


def test_nz_list_tables_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_list_tables(
        _profile: object,
        database: str,
        schema: str,
        pattern: str | None = None,
        object_type: str = "TABLE",
    ) -> list[dict[str, str]]:
        assert database == "DEV"
        assert schema == "PUBLIC"
        assert pattern == "C%"
        assert object_type == "TABLE"
        return [
            {"name": "CUSTOMERS", "kind": "TABLE"},
            {"name": "CONFIG", "kind": "TABLE"},
        ]

    monkeypatch.setattr("nz_mcp.tools.tables.list_tables", _fake_list_tables)
    out = nz_list_tables(
        ListTablesInput(database="DEV", table_schema="PUBLIC", pattern="C%"),
        config_path=two_profiles,
    )

    assert [t.name for t in out.tables] == ["CUSTOMERS", "CONFIG"]
    assert [t.kind for t in out.tables] == ["TABLE", "TABLE"]


def test_nz_list_tables_passes_object_type_through(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_list_tables(
        _profile: object,
        database: str,
        schema: str,
        pattern: str | None = None,
        object_type: str = "TABLE",
    ) -> list[dict[str, str]]:
        assert object_type == "EXTERNAL TABLE"
        return [{"name": "STG_S3_ORDERS", "kind": "EXTERNAL TABLE"}]

    monkeypatch.setattr("nz_mcp.tools.tables.list_tables", _fake_list_tables)
    out = nz_list_tables(
        ListTablesInput(
            database="DEV",
            table_schema="PUBLIC",
            object_type="EXTERNAL TABLE",
        ),
        config_path=two_profiles,
    )

    assert out.tables == [TableItem(name="STG_S3_ORDERS", kind="EXTERNAL TABLE")]


def test_nz_list_tables_propagates_typed_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise_list_tables(
        _profile: object,
        database: str,
        schema: str,
        pattern: str | None = None,
        object_type: str = "TABLE",
    ) -> list[dict[str, str]]:
        raise NetezzaError(operation="list_tables", detail="denied")

    monkeypatch.setattr("nz_mcp.tools.tables.list_tables", _raise_list_tables)

    with pytest.raises(NetezzaError) as exc:
        nz_list_tables(
            ListTablesInput(database="DEV", table_schema="PUBLIC"),
            config_path=two_profiles,
        )

    assert exc.value.code == "NETEZZA_ERROR"
