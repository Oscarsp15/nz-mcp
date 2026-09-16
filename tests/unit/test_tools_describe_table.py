"""Tests for ``nz_describe_table`` MCP tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import NetezzaError, ObjectNotFoundError
from nz_mcp.tools.describe_table import DescribeTableInput, nz_describe_table


def test_describe_table_input_accepts_wire_keys() -> None:
    parsed = DescribeTableInput.model_validate(
        {"database": "DEV", "schema": "PUBLIC", "table": "T"},
    )
    assert parsed.table_schema == "PUBLIC"
    assert parsed.table == "T"


def test_nz_describe_table_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    payload: dict[str, object] = {
        "name": "T",
        "kind": "TABLE",
        "columns": [
            {"name": "ID", "type": "INTEGER", "nullable": False, "default": None},
        ],
        "distribution": {"type": "RANDOM", "columns": []},
        "organized_on": [],
        "primary_key": [],
        "foreign_keys": [],
    }

    def _fake_describe(
        _profile: object,
        database: str,
        schema: str,
        table: str,
    ) -> dict[str, object]:
        assert database == "DEV"
        assert schema == "PUBLIC"
        assert table == "t"
        return payload

    monkeypatch.setattr("nz_mcp.tools.describe_table.describe_table", _fake_describe)

    out = nz_describe_table(
        DescribeTableInput(database="DEV", table_schema="PUBLIC", table="t"),
        config_path=two_profiles,
    )

    assert out.name == "T"
    assert out.columns[0].sql_type == "INTEGER"


def test_nz_describe_table_view_kind_omits_distribution(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Issue #295: a view's kind is VIEW and distribution is absent, not a fake RANDOM."""
    payload: dict[str, object] = {
        "name": "V_MODELOVERSION",
        "kind": "VIEW",
        "columns": [
            {"name": "ID", "type": "INTEGER", "nullable": False, "default": None},
        ],
        "organized_on": [],
        "primary_key": [],
        "foreign_keys": [],
    }

    monkeypatch.setattr(
        "nz_mcp.tools.describe_table.describe_table",
        lambda *_a, **_kw: payload,
    )

    out = nz_describe_table(
        DescribeTableInput(database="DEV", table_schema="DBO", table="V_MODELOVERSION"),
        config_path=two_profiles,
    )

    assert out.kind == "VIEW"
    assert out.distribution is None


def test_nz_describe_table_external_table_kind(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    payload: dict[str, object] = {
        "name": "STG_S3_ORDERS",
        "kind": "EXTERNAL TABLE",
        "columns": [
            {"name": "ID", "type": "INTEGER", "nullable": False, "default": None},
        ],
        "distribution": {"type": "RANDOM", "columns": []},
        "organized_on": [],
        "primary_key": [],
        "foreign_keys": [],
    }

    monkeypatch.setattr(
        "nz_mcp.tools.describe_table.describe_table",
        lambda *_a, **_kw: payload,
    )

    out = nz_describe_table(
        DescribeTableInput(database="DEV", table_schema="DBO", table="STG_S3_ORDERS"),
        config_path=two_profiles,
    )

    assert out.kind == "EXTERNAL TABLE"
    assert out.distribution is not None
    assert out.distribution.dist_type == "RANDOM"


def test_nz_describe_table_propagates_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(*_a: object, **_k: object) -> dict[str, object]:
        raise ObjectNotFoundError(detail="missing")

    monkeypatch.setattr("nz_mcp.tools.describe_table.describe_table", _raise)

    with pytest.raises(ObjectNotFoundError):
        nz_describe_table(
            DescribeTableInput(database="DEV", table_schema="PUBLIC", table="X"),
            config_path=two_profiles,
        )


def test_nz_describe_table_propagates_netezza_error(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(*_a: object, **_k: object) -> dict[str, object]:
        raise NetezzaError(operation="describe_table", detail="driver")

    monkeypatch.setattr("nz_mcp.tools.describe_table.describe_table", _raise)

    with pytest.raises(NetezzaError):
        nz_describe_table(
            DescribeTableInput(database="DEV", table_schema="PUBLIC", table="X"),
            config_path=two_profiles,
        )
