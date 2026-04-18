"""Tests for table sampling, statistics, and DDL reconstruction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nz_mcp.catalog import tables as tables_mod
from nz_mcp.catalog.tables import (
    _parse_table_stats_row,
    get_table_ddl,
    get_table_sample,
    get_table_stats,
    skew_class,
)
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, ObjectNotFoundError


def _profile_dev() -> Profile:
    return Profile(
        name="dev",
        host="h",
        port=5480,
        database="DEV",
        user="u",
        mode="read",
    )


def test_get_table_sample_rejects_database_mismatch() -> None:
    with pytest.raises(InvalidInputError):
        get_table_sample(
            _profile_dev(),
            database="OTHER",
            schema="PUBLIC",
            table="T",
            rows=5,
            timeout_s=30,
        )


def test_get_table_sample_runs_guarded_select(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _exec(
        _profile: object,
        sql: str,
        *,
        max_rows: int,
        timeout_s: int,
    ) -> dict[str, object]:
        captured["sql"] = sql
        captured["max_rows"] = max_rows
        return {
            "columns": [{"name": "n", "type": "int"}],
            "rows": [[1]],
            "row_count": 1,
            "truncated": False,
            "duration_ms": 1,
            "hint_key": None,
            "hint_fmt": {},
        }

    monkeypatch.setattr(tables_mod, "execute_select", _exec)

    out = get_table_sample(
        _profile_dev(),
        database="DEV",
        schema="PUBLIC",
        table="T",
        rows=3,
        timeout_s=30,
    )
    assert out["row_count"] == 1
    assert "PUBLIC.T" in str(captured["sql"]).upper()
    assert captured["max_rows"] == 3


def test_parse_table_stats_tuple() -> None:
    p = _parse_table_stats_row((10, 1024, 2048, 2.5, None))
    assert p["row_count"] == 10
    assert p["size_bytes_used"] == 1024
    assert p["size_bytes_allocated"] == 2048
    assert p["skew"] == 2.5
    assert p["table_created"] is None
    assert p.get("stats_last_analyzed") is None


def test_parse_table_stats_dict_ignores_stats_last_analyzed_column() -> None:
    p = _parse_table_stats_row(
        {
            "ROW_COUNT": 1,
            "SIZE_BYTES_USED": 100,
            "SIZE_BYTES_ALLOCATED": 200,
            "SKEW": None,
            "TABLE_CREATED": None,
            "STATS_LAST_ANALYZED": "2024-03-12",
        },
    )
    assert p["stats_last_analyzed"] is None


def test_skew_class_bands() -> None:
    assert skew_class(None) is None
    assert skew_class(0.05) == "balanced"
    assert skew_class(0.1) == "moderate"
    assert skew_class(0.2) == "moderate"
    assert skew_class(0.3) == "moderate"
    assert skew_class(0.31) == "severe"


def test_parse_table_stats_dict_datetime() -> None:
    dt = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    p = _parse_table_stats_row(
        {
            "ROW_COUNT": 1,
            "SIZE_BYTES_USED": 100,
            "SIZE_BYTES_ALLOCATED": 200,
            "SKEW": None,
            "TABLE_CREATED": dt,
        },
    )
    assert "2026-04-01" in (p["table_created"] or "")


def test_get_table_stats_missing_row(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Cur:
        def execute(self, _sql: str, _params: tuple[str, str]) -> None:
            return None

        def fetchall(self) -> list[object]:
            return []

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda _p, _pw: _Conn())

    with pytest.raises(ObjectNotFoundError):
        get_table_stats(_profile_dev(), database="DEV", schema="PUBLIC", table="Z")


def test_get_table_ddl_builds_from_describe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tables_mod,
        "describe_table",
        lambda *_a, **_kw: {
            "name": "T",
            "kind": "TABLE",
            "columns": [{"name": "ID", "type": "INT", "nullable": False, "default": None}],
            "distribution": {"type": "HASH", "columns": ["ID"]},
            "primary_key": ["ID"],
            "foreign_keys": [],
        },
    )

    out = get_table_ddl(
        _profile_dev(),
        database="DEV",
        schema="PUBLIC",
        table="T",
        include_constraints=True,
    )
    assert "CREATE TABLE PUBLIC.T" in out["ddl"]
    assert out["reconstructed"] is True
