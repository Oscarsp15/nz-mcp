"""Tests for nz_table_sample, nz_table_stats, nz_get_table_ddl."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.tools.tables import (
    GetTableDdlInput,
    TableSampleInput,
    TableStatsInput,
    nz_get_table_ddl,
    nz_table_sample,
    nz_table_stats,
)


def test_nz_table_sample_wire_schema_key(two_profiles: Path) -> None:
    parsed = TableSampleInput.model_validate(
        {"database": "DEV", "schema": "PUBLIC", "table": "T", "rows": 5},
    )
    assert parsed.table_schema == "PUBLIC"


def test_nz_table_sample_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:

    def _sample(
        _profile: object,
        database: str,
        schema: str,
        table: str,
        *,
        rows: int,
        timeout_s: int,
    ) -> dict[str, object]:
        assert database == "DEV"
        assert schema == "PUBLIC"
        assert table == "T"
        assert rows == 10
        return {
            "columns": [{"name": "c", "type": "INT"}],
            "rows": [[42]],
            "row_count": 1,
            "truncated": False,
            "duration_ms": 5,
            "hint_key": None,
            "hint_fmt": {},
        }

    monkeypatch.setattr("nz_mcp.tools.tables.get_table_sample", _sample)

    out = nz_table_sample(
        TableSampleInput(database="DEV", table_schema="PUBLIC", table="T"),
        config_path=two_profiles,
    )
    assert out.rows == [[42]]
    assert out.row_count == 1


def test_nz_table_stats_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:

    def _stats(_p: object, **_kw: object) -> dict[str, object]:
        return {
            "row_count": 100,
            "size_bytes_used": 1024,
            "size_used_human": "1.0 KiB",
            "size_bytes_allocated": 2048,
            "size_allocated_human": "2.0 KiB",
            "skew": 1.2,
            "skew_class": "moderate",
            "stats_last_analyzed": None,
            "table_created": "2026-01-01",
        }

    monkeypatch.setattr("nz_mcp.tools.tables.get_table_stats", _stats)

    out = nz_table_stats(
        TableStatsInput(database="DEV", table_schema="PUBLIC", table="T"),
        config_path=two_profiles,
    )
    assert out.row_count == 100
    assert out.skew == 1.2
    assert out.skew_class == "moderate"
    assert out.stats_last_analyzed is None
    assert out.duration_ms >= 0


def test_nz_get_table_ddl_notes(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:

    def _get_ddl(
        _profile: object,
        database: str,
        schema: str,
        table: str,
        *,
        include_constraints: bool,
    ) -> dict[str, object]:
        assert database == "DEV" and schema == "PUBLIC" and table == "T"
        assert include_constraints is True
        return {"ddl": "CREATE TABLE X (\n);\n", "reconstructed": True}

    monkeypatch.setattr("nz_mcp.tools.tables.get_table_ddl", _get_ddl)

    out = nz_get_table_ddl(
        GetTableDdlInput(database="DEV", table_schema="PUBLIC", table="T"),
        config_path=two_profiles,
    )
    assert out.reconstructed is True
    assert len(out.notes) == 3
    assert any("SHOW TABLE" in n for n in out.notes)
    assert any("_v_relation_column" in n for n in out.notes)
    assert out.duration_ms >= 0
