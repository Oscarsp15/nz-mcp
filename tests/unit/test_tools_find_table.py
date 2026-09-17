"""Tests for nz_find_table."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import ObjectNotFoundError
from nz_mcp.tools.find_table import FindTableInput, nz_find_table


def _rows() -> list[dict[str, str]]:
    return [
        {"database": "DESA_MODELOS", "schema": "DBO", "name": "EFE_MC_CREDITOS", "kind": "TABLE"},
        {"database": "DESA_BI", "schema": "DBO", "name": "EFE_MC_CREDITOS", "kind": "TABLE"},
    ]


def test_nz_find_table_wire_schema_key(two_profiles: Path) -> None:
    parsed = FindTableInput.model_validate({"table_pattern": "EFE_%", "schema_pattern": "DBO"})
    assert parsed.schema_pattern == "DBO"
    assert parsed.object_type == "TABLE"
    assert parsed.database is None


def test_nz_find_table_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    captured: dict[str, object] = {}

    def _find(_profile: object, **kwargs: object) -> tuple[list[dict[str, str]], bool]:
        captured.update(kwargs)
        return _rows(), False

    monkeypatch.setattr("nz_mcp.tools.find_table.find_tables", _find)

    out = nz_find_table(
        FindTableInput(table_pattern="EFE_%"),
        config_path=two_profiles,
    )

    assert captured["table_pattern"] == "EFE_%"
    assert captured["object_type"] == "TABLE"
    assert [o.database for o in out.objects] == ["DESA_MODELOS", "DESA_BI"]
    assert out.objects[0].schema_name == "DBO"
    assert out.objects[0].name == "EFE_MC_CREDITOS"
    assert out.truncated is False
    assert out.hint is None
    assert out.duration_ms >= 0


def test_nz_find_table_truncation_hint(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.find_table.find_tables",
        lambda _p, **_kw: (_rows(), True),
    )

    out = nz_find_table(
        FindTableInput(table_pattern="EFE_%", max_rows=1),
        config_path=two_profiles,
    )

    assert out.truncated is True
    assert len(out.objects) == 1
    assert out.hint is not None
    assert "max_rows" in out.hint


def test_nz_find_table_invisible_database(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(_profile: object, **_kwargs: object) -> tuple[list[dict[str, str]], bool]:
        raise ObjectNotFoundError(detail="not visible", database="NOPE")

    monkeypatch.setattr("nz_mcp.tools.find_table.find_tables", _raise)

    with pytest.raises(ObjectNotFoundError) as exc:
        nz_find_table(
            FindTableInput(table_pattern="T%", database="NOPE"),
            config_path=two_profiles,
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"
