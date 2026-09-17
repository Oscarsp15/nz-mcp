"""Tests for nz_profile_column."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import ObjectNotFoundError
from nz_mcp.tools.profiling import ProfileColumnInput, nz_profile_column


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "total": 100,
        "nulls": 5,
        "null_pct": 5.0,
        "distinct": 3,
        "min": "2026-04-01",
        "max": "2026-06-30",
        "top_values": [{"value": "A", "count": 60}, {"value": "B", "count": 35}],
    }
    payload.update(overrides)
    return payload


def test_nz_profile_column_wire_schema_key() -> None:
    parsed = ProfileColumnInput.model_validate(
        {"database": "DEV", "schema": "PUBLIC", "table": "T", "column": "C"},
    )
    assert parsed.table_schema == "PUBLIC"
    assert parsed.top_n == 10


def test_nz_profile_column_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _profile(_profile: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["database"] == "DEV"
        assert kwargs["schema"] == "PUBLIC"
        assert kwargs["table"] == "T"
        assert kwargs["column"] == "C"
        assert kwargs["top_n"] == 10
        return _payload()

    monkeypatch.setattr("nz_mcp.tools.profiling.profile_column", _profile)

    out = nz_profile_column(
        ProfileColumnInput(database="DEV", table_schema="PUBLIC", table="T", column="C"),
        config_path=two_profiles,
    )
    assert out.total == 100
    assert out.nulls == 5
    assert out.null_pct == 5.0
    assert out.distinct == 3
    assert out.min == "2026-04-01"
    assert out.top_values[0].value == "A"
    assert out.top_values[0].count == 60
    assert out.hint is None
    assert out.duration_ms >= 0


def test_nz_profile_column_hint_when_more_distinct_than_top_n(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.profiling.profile_column",
        lambda _p, **_kw: _payload(distinct=99),
    )

    out = nz_profile_column(
        ProfileColumnInput(database="DEV", table_schema="PUBLIC", table="T", column="C", top_n=10),
        config_path=two_profiles,
    )
    assert out.hint is not None
    assert "99" in out.hint


def test_nz_profile_column_object_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(_profile: object, **_kwargs: object) -> dict[str, object]:
        raise ObjectNotFoundError(detail="no such column", object_type="column")

    monkeypatch.setattr("nz_mcp.tools.profiling.profile_column", _raise)

    with pytest.raises(ObjectNotFoundError) as exc:
        nz_profile_column(
            ProfileColumnInput(database="DEV", table_schema="PUBLIC", table="T", column="NOPE"),
            config_path=two_profiles,
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"
