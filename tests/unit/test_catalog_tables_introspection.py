"""Tests for table sampling, statistics, and DDL reconstruction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nz_mcp.catalog import tables as tables_mod
from nz_mcp.catalog.formatters import format_bytes_iec
from nz_mcp.catalog.tables import (
    _parse_table_stats_batch_row,
    _parse_table_stats_row,
    get_table_ddl,
    get_table_sample,
    get_table_stats,
    get_table_stats_batch,
    skew_class,
)
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, InvalidInputError, NetezzaError, ObjectNotFoundError


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


def test_get_table_sample_composes_where_and_order_by(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _exec(
        _profile: object,
        sql: str,
        *,
        max_rows: int,
        timeout_s: int,
    ) -> dict[str, object]:
        captured["sql"] = sql
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "duration_ms": 1,
            "hint_key": None,
            "hint_fmt": {},
        }

    monkeypatch.setattr(tables_mod, "execute_select", _exec)

    get_table_sample(
        _profile_dev(),
        database="DEV",
        schema="PUBLIC",
        table="T",
        rows=5,
        timeout_s=30,
        where="ID > 10",
        order_by="ID DESC",
    )
    sql = str(captured["sql"]).upper()
    assert "WHERE ID > 10" in sql
    assert "ORDER BY ID DESC" in sql
    assert "LIMIT 5" in sql


def test_get_table_sample_rejects_stacked_where_fragment() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        get_table_sample(
            _profile_dev(),
            database="DEV",
            schema="PUBLIC",
            table="T",
            rows=5,
            timeout_s=30,
            where="1=1; DROP TABLE PUBLIC.T",
        )
    assert exc.value.code == "STACKED_NOT_ALLOWED"


def test_get_table_sample_rejects_stacked_order_by_fragment() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        get_table_sample(
            _profile_dev(),
            database="DEV",
            schema="PUBLIC",
            table="T",
            rows=5,
            timeout_s=30,
            order_by="ID; DELETE FROM PUBLIC.T",
        )
    assert exc.value.code == "STACKED_NOT_ALLOWED"


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


def test_parse_table_stats_epoch_int_converted_to_iso() -> None:
    """Issue #312: integer epoch from driver must become ISO-8601, not a raw number string."""
    p = _parse_table_stats_row((10, 1024, 2048, None, 1789541796))
    created = p["table_created"]
    assert created is not None
    assert created[0].isdigit(), "should start with a year digit"
    assert "T" in created, "ISO-8601 datetime requires a T separator"
    assert "1789541796" not in created, "raw epoch must not appear in output"


def test_parse_table_stats_epoch_string_converted_to_iso() -> None:
    """Integer delivered as a string (some driver versions) also converts to ISO."""
    p = _parse_table_stats_row(
        {
            "ROW_COUNT": 5,
            "SIZE_BYTES_USED": 512,
            "SIZE_BYTES_ALLOCATED": 1024,
            "SKEW": None,
            "TABLE_CREATED": "1789541796",
        },
    )
    created = p["table_created"]
    assert created is not None
    assert "T" in created
    assert "1789541796" not in created


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


class _BatchCursor:
    def __init__(self, rows: list[object], *, error: Exception | None = None) -> None:
        self._rows = rows
        self._error = error
        self.sql = ""
        self.params: tuple[object, ...] | None = None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.sql = sql
        self.params = params
        if self._error is not None:
            raise self._error

    def fetchall(self) -> list[object]:
        return self._rows

    def close(self) -> None:
        return None


class _BatchConnection:
    def __init__(self, cursor: _BatchCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _BatchCursor:
        return self._cursor

    def close(self) -> None:
        return None


def _patch_batch_driver(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[object],
    *,
    error: Exception | None = None,
) -> _BatchCursor:
    cursor = _BatchCursor(rows, error=error)
    monkeypatch.setattr(tables_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(tables_mod, "open_connection", lambda _p, _pw: _BatchConnection(cursor))
    return cursor


def _batch_row(
    name: str,
    row_count: int,
    used: int,
    allocated: int,
    skew: float | None,
) -> dict[str, object]:
    return {
        "TABLE_NAME": name,
        "ROW_COUNT": row_count,
        "SIZE_BYTES_USED": used,
        "SIZE_BYTES_ALLOCATED": allocated,
        "SKEW": skew,
        "TABLE_CREATED": None,
    }


def test_parse_table_stats_batch_row_tuple() -> None:
    parsed = _parse_table_stats_batch_row(("T", 10, 1024, 2048, 2.5, None))
    assert parsed["name"] == "T"
    assert parsed["row_count"] == 10
    assert parsed["size_bytes_used"] == 1024
    assert parsed["size_bytes_allocated"] == 2048
    assert parsed["skew"] == 2.5
    assert parsed["table_created"] is None


def test_parse_table_stats_batch_row_dict() -> None:
    parsed = _parse_table_stats_batch_row(
        _batch_row("T", 10, 1024, 2048, None),
    )
    assert parsed["name"] == "T"
    assert parsed["row_count"] == 10
    assert parsed["skew"] is None


def test_parse_table_stats_batch_row_dict_requires_table_name() -> None:
    with pytest.raises(NetezzaError):
        _parse_table_stats_batch_row({"ROW_COUNT": 1, "SIZE_BYTES_USED": 1})


def test_parse_table_stats_batch_row_unexpected_shape_raises() -> None:
    with pytest.raises(NetezzaError):
        _parse_table_stats_batch_row((1, 2))


def test_get_table_stats_batch_orders_by_size_with_name_tiebreak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[object] = [
        _batch_row("B", 500, 1024, 2048, 0.4),
        _batch_row("C", 100, 2048, 2048, None),
        _batch_row("A", 100, 2048, 4096, 0.05),
    ]
    cursor = _patch_batch_driver(monkeypatch, rows)

    out = get_table_stats_batch(_profile_dev(), database="DEV", schema="PUBLIC", order_by="size")

    assert [r["name"] for r in out] == ["A", "C", "B"]
    assert out[0]["size_used_human"] == format_bytes_iec(2048)
    assert out[0]["skew_class"] == "balanced"
    assert out[2]["skew_class"] == "severe"
    assert cursor.params == ("PUBLIC",)
    assert "ORDER BY t.TABLENAME" in cursor.sql


def test_get_table_stats_batch_orders_by_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows: list[object] = [
        _batch_row("A", 100, 2048, 2048, None),
        _batch_row("B", 500, 1024, 2048, None),
        _batch_row("C", 100, 512, 512, None),
    ]
    _patch_batch_driver(monkeypatch, rows)

    out = get_table_stats_batch(_profile_dev(), database="DEV", schema="PUBLIC", order_by="rows")

    assert [r["name"] for r in out] == ["B", "A", "C"]


def test_get_table_stats_batch_empty_schema_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_batch_driver(monkeypatch, [])

    out = get_table_stats_batch(_profile_dev(), database="DEV", schema="PUBLIC", order_by="size")

    assert out == []


def test_get_table_stats_batch_driver_error_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_batch_driver(monkeypatch, [], error=RuntimeError("driver exploded"))

    with pytest.raises(NetezzaError):
        get_table_stats_batch(_profile_dev(), database="DEV", schema="PUBLIC", order_by="size")
