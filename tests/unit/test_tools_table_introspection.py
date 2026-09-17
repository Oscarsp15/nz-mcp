"""Tests for nz_table_sample, nz_table_stats, nz_get_table_ddl."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import NetezzaError
from nz_mcp.tools.tables import (
    GetTableDdlInput,
    TableSampleInput,
    TableStatsBatchInput,
    TableStatsInput,
    nz_get_table_ddl,
    nz_table_sample,
    nz_table_stats,
    nz_table_stats_batch,
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


def _batch_stats_row(name: str) -> dict[str, object]:
    return {
        "name": name,
        "row_count": 100,
        "size_bytes_used": 1024,
        "size_used_human": "1.0 KiB",
        "size_bytes_allocated": 2048,
        "size_allocated_human": "2.0 KiB",
        "skew": 0.05,
        "skew_class": "balanced",
        "table_created": None,
    }


def test_nz_table_stats_batch_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    two_profiles: Path,
) -> None:
    def _batch(_p: object, **kwargs: object) -> list[dict[str, object]]:
        assert kwargs["order_by"] == "size"
        return [_batch_stats_row("A"), _batch_stats_row("B"), _batch_stats_row("C")]

    monkeypatch.setattr("nz_mcp.tools.tables.get_table_stats_batch", _batch)

    out = nz_table_stats_batch(
        TableStatsBatchInput(database="DEV", table_schema="PUBLIC", top_n=2),
        config_path=two_profiles,
    )
    assert [t.name for t in out.tables] == ["A", "B"]
    assert out.order_by == "size"
    assert out.truncated is True
    assert out.hint is not None
    assert out.duration_ms >= 0


def test_nz_table_stats_batch_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
    two_profiles: Path,
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.tables.get_table_stats_batch",
        lambda _p, **_kw: [_batch_stats_row("A")],
    )

    out = nz_table_stats_batch(
        TableStatsBatchInput(database="DEV", table_schema="PUBLIC", top_n=20),
        config_path=two_profiles,
    )
    assert out.truncated is False
    assert out.hint is None


def test_nz_table_stats_batch_typed_error(
    monkeypatch: pytest.MonkeyPatch,
    two_profiles: Path,
) -> None:
    def _boom(_p: object, **_kw: object) -> list[dict[str, object]]:
        raise NetezzaError(operation="get_table_stats_batch", detail="permission denied")

    monkeypatch.setattr("nz_mcp.tools.tables.get_table_stats_batch", _boom)

    with pytest.raises(NetezzaError):
        nz_table_stats_batch(
            TableStatsBatchInput(database="DEV", table_schema="PUBLIC"),
            config_path=two_profiles,
        )
