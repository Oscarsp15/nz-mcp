"""Tests for the ``nz_compare_tables`` tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nz_mcp.errors import NetezzaError, ObjectNotFoundError
from nz_mcp.tools.compare_tables import CompareTablesInput, nz_compare_tables


def test_nz_compare_tables_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_compare(
        _profile: object,
        database_a: str,
        schema_a: str,
        table_a: str,
        database_b: str,
        schema_b: str,
        table_b: str,
    ) -> dict[str, Any]:
        assert database_a == "DEV"
        assert schema_a == "ADMIN"
        assert table_a == "TAB_A"
        assert database_b == "DEV"
        assert schema_b == "ADMIN"
        assert table_b == "TAB_B"
        return {
            "identical": False,
            "columns_in_a": 2,
            "columns_in_b": 2,
            "columns_in_common": 1,
            "only_in_a": [{"column": "EXTRA_A", "type": "DATE", "nullable": True, "position": 2}],
            "only_in_b": [
                {"column": "EXTRA_B", "type": "TIMESTAMP", "nullable": False, "position": 2}
            ],
            "type_mismatches": [
                {
                    "column": "NUMDOC",
                    "type_a": "VARCHAR(12)",
                    "type_b": "VARCHAR(4000)",
                    "nullable_a": True,
                    "nullable_b": False,
                }
            ],
            "position_mismatches": [],
        }

    monkeypatch.setattr("nz_mcp.tools.compare_tables.compare_tables", _fake_compare)

    out = nz_compare_tables(
        CompareTablesInput(
            database="DEV",
            schema_a="ADMIN",
            table_a="TAB_A",
            table_b="TAB_B",
        ),
        config_path=two_profiles,
    )

    assert out.identical is False
    assert out.columns_in_a == 2
    assert out.columns_in_b == 2
    assert out.columns_in_common == 1
    assert len(out.only_in_a) == 1
    assert out.only_in_a[0].column == "EXTRA_A"
    assert len(out.only_in_b) == 1
    assert out.only_in_b[0].column == "EXTRA_B"
    assert len(out.type_mismatches) == 1
    assert out.type_mismatches[0].type_a == "VARCHAR(12)"
    assert out.duration_ms >= 0


def test_nz_compare_tables_cross_database(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_compare(
        _profile: object,
        database_a: str,
        schema_a: str,
        table_a: str,
        database_b: str,
        schema_b: str,
        table_b: str,
    ) -> dict[str, Any]:
        assert database_a == "DEV"
        assert schema_a == "SCHEMA_1"
        assert table_a == "TAB_A"
        assert database_b == "PROD"
        assert schema_b == "SCHEMA_2"
        assert table_b == "TAB_B"
        return {
            "identical": True,
            "columns_in_a": 1,
            "columns_in_b": 1,
            "columns_in_common": 1,
            "only_in_a": [],
            "only_in_b": [],
            "type_mismatches": [],
            "position_mismatches": [],
        }

    monkeypatch.setattr("nz_mcp.tools.compare_tables.compare_tables", _fake_compare)

    out = nz_compare_tables(
        CompareTablesInput(
            database="DEV",
            schema_a="SCHEMA_1",
            table_a="TAB_A",
            database_b="PROD",
            schema_b="SCHEMA_2",
            table_b="TAB_B",
        ),
        config_path=two_profiles,
    )

    assert out.identical is True


def test_nz_compare_tables_propagates_object_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(*_a: object, **_k: object) -> dict[str, Any]:
        raise ObjectNotFoundError(
            detail="Table 'MISSING' not found",
            object_type="table",
            database="DEV",
            schema="ADMIN",
            table="MISSING",
        )

    monkeypatch.setattr("nz_mcp.tools.compare_tables.compare_tables", _raise)

    with pytest.raises(ObjectNotFoundError) as exc:
        nz_compare_tables(
            CompareTablesInput(
                database="DEV",
                schema_a="ADMIN",
                table_a="MISSING",
                table_b="TAB_B",
            ),
            config_path=two_profiles,
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"


def test_nz_compare_tables_propagates_netezza_error(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(*_a: object, **_k: object) -> dict[str, Any]:
        raise NetezzaError(operation="compare_tables", detail="connection dropped")

    monkeypatch.setattr("nz_mcp.tools.compare_tables.compare_tables", _raise)

    with pytest.raises(NetezzaError) as exc:
        nz_compare_tables(
            CompareTablesInput(
                database="DEV",
                schema_a="ADMIN",
                table_a="TAB_A",
                table_b="TAB_B",
            ),
            config_path=two_profiles,
        )
    assert exc.value.code == "NETEZZA_ERROR"
