"""Tests for ``nz_summarize_partitions`` (issue #338)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nz_mcp.catalog import tables as cat
from nz_mcp.config import get_active_profile
from nz_mcp.errors import InputTooBroadError, InvalidInputError
from nz_mcp.tools.tables import SummarizePartitionsInput, nz_summarize_partitions


def _raw(partitions: list[dict[str, Any]], *, duration_ms: int = 7) -> dict[str, Any]:
    return {
        "partitions": partitions,
        "partition_count": len(partitions),
        "latest": partitions[0]["value"] if partitions else None,
        "earliest": partitions[-1]["value"] if partitions else None,
        "duration_ms": duration_ms,
    }


def _patch_summary(monkeypatch: pytest.MonkeyPatch, raw: dict[str, Any]) -> None:
    monkeypatch.setattr("nz_mcp.tools.tables.summarize_partitions", lambda *_a, **_k: raw)


# ── tool layer ───────────────────────────────────────────────────────────────


def test_happy_path_returns_counts_and_bounds(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    _patch_summary(
        monkeypatch,
        _raw(
            [
                {"value": "2026-07-06", "rows": 34},
                {"value": "2026-06-30", "rows": 12318},
                {"value": "2026-05-30", "rows": 12249},
                {"value": "2026-04-30", "rows": 12865},
            ]
        ),
    )

    out = nz_summarize_partitions(
        SummarizePartitionsInput(
            database="DEV", table_schema="DBO", table="EFE_MC_CREDITOS", partition_column="FECCORTE"
        ),
        config_path=two_profiles,
    )
    assert out.partition_count == 4
    assert out.latest == "2026-07-06"
    assert out.earliest == "2026-04-30"
    assert out.partitions[0].value == "2026-07-06"
    assert out.partitions[0].rows == 34
    assert out.truncated is False
    assert out.hint is None
    assert out.duration_ms >= 0


def test_truncation_keeps_full_bounds_and_sets_hint(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    partitions = [{"value": f"2026-0{i}", "rows": i} for i in range(1, 6)]
    _patch_summary(monkeypatch, _raw(partitions))

    out = nz_summarize_partitions(
        SummarizePartitionsInput(
            database="DEV",
            table_schema="DBO",
            table="T",
            partition_column="FECCORTE",
            max_rows=2,
        ),
        config_path=two_profiles,
    )
    assert len(out.partitions) == 2
    assert out.partition_count == 5
    assert out.truncated is True
    assert out.hint is not None
    assert "5" in out.hint
    # latest/earliest come from the full set, not from the truncated slice.
    assert out.latest == "2026-01"
    assert out.earliest == "2026-05"


def test_empty_table_yields_no_partitions(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    _patch_summary(monkeypatch, _raw([]))

    out = nz_summarize_partitions(
        SummarizePartitionsInput(
            database="DEV", table_schema="DBO", table="T", partition_column="F"
        ),
        config_path=two_profiles,
    )
    assert out.partitions == []
    assert out.partition_count == 0
    assert out.latest is None
    assert out.earliest is None
    assert out.truncated is False


def test_input_rejects_extra_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SummarizePartitionsInput.model_validate(
            {
                "database": "DEV",
                "schema": "DBO",
                "table": "T",
                "partition_column": "F",
                "column": "X",  # not part of this tool
            }
        )


@pytest.mark.parametrize("value", [0, -1, 1001])
def test_input_rejects_out_of_range_max_rows(value: int) -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        SummarizePartitionsInput.model_validate(
            {
                "database": "DEV",
                "schema": "DBO",
                "table": "T",
                "partition_column": "F",
                "max_rows": value,
            }
        )


# ── catalog layer ────────────────────────────────────────────────────────────


def _capture_execute(
    monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake(_profile: object, sql: str, *, max_rows: int, timeout_s: int) -> dict[str, Any]:
        calls.append({"sql": sql, "max_rows": max_rows, "timeout_s": timeout_s})
        return result

    monkeypatch.setattr(cat, "execute_select", _fake)
    return calls


def test_catalog_builds_group_by_and_maps_rows(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    profile = get_active_profile(path=two_profiles)
    calls = _capture_execute(
        monkeypatch,
        {
            "columns": [
                {"name": "PARTITION_VALUE", "type": "VARCHAR"},
                {"name": "PARTITION_ROWS", "type": "INT"},
            ],
            "rows": [["2026-07-06", 34], [None, 2], ["2026-06-30", 12318]],
            "row_count": 3,
            "truncated": False,
            "duration_ms": 11,
            "hint_key": None,
            "hint_fmt": {},
        },
    )

    raw = cat.summarize_partitions(
        profile, "DEV", "dbo", "efe_mc_creditos", "feccorte", timeout_s=30
    )
    sql = calls[0]["sql"]
    assert "FROM DBO.EFE_MC_CREDITOS" in sql
    assert "GROUP BY FECCORTE" in sql
    assert "ORDER BY FECCORTE DESC" in sql
    assert calls[0]["timeout_s"] == 30
    assert raw["partition_count"] == 3
    assert raw["latest"] == "2026-07-06"
    assert raw["earliest"] == "2026-06-30"
    # A SQL NULL group is surfaced as None, not as the string "None".
    assert raw["partitions"][1]["value"] is None
    assert raw["partitions"][1]["rows"] == 2


def test_catalog_rejects_high_cardinality_column(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    profile = get_active_profile(path=two_profiles)
    _capture_execute(
        monkeypatch,
        {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": True,
            "duration_ms": 5,
            "hint_key": "HINT.RESULT_TRUNCATED_BY_ROWS",
            "hint_fmt": {"n": 1000},
        },
    )

    with pytest.raises(InputTooBroadError) as exc:
        cat.summarize_partitions(profile, "DEV", "DBO", "T", "NUMDOCUMENTO", timeout_s=30)
    assert exc.value.code == "INPUT_TOO_BROAD"
    assert exc.value.context.get("column") == "NUMDOCUMENTO"
    assert "nz_describe_table" in str(exc.value.context.get("hint_en"))


def test_catalog_requires_profile_database(two_profiles: Path) -> None:
    profile = get_active_profile(path=two_profiles)

    with pytest.raises(InvalidInputError):
        cat.summarize_partitions(profile, "OTRA_BD", "DBO", "T", "FECCORTE", timeout_s=30)


def test_catalog_rejects_invalid_identifier(two_profiles: Path) -> None:
    profile = get_active_profile(path=two_profiles)

    with pytest.raises(InvalidInputError):
        cat.summarize_partitions(profile, "DEV", "DBO", "T", "FEC CORTE", timeout_s=30)
