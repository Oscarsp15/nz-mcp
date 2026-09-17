"""Tests for the ``nz_list_constraints`` tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import NetezzaError, ObjectNotFoundError
from nz_mcp.tools.list_constraints import ListConstraintsInput, nz_list_constraints


def test_nz_list_constraints_happy_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_list_constraints(
        _profile: object,
        database: str,
        schema: str,
        table: str | None = None,
    ) -> list[dict[str, object]]:
        assert database == "DEV"
        assert schema == "DBO"
        assert table is None
        return [
            {"table": "EFE_MC_CREDITOS", "name": "PK_X", "type": "p", "columns": ["CODCREDITO"]},
        ]

    monkeypatch.setattr("nz_mcp.tools.list_constraints.list_constraints", _fake_list_constraints)
    out = nz_list_constraints(
        ListConstraintsInput(database="DEV", table_schema="DBO"),
        config_path=two_profiles,
    )

    assert len(out.constraints) == 1
    item = out.constraints[0]
    assert item.model_dump() == {
        "table": "EFE_MC_CREDITOS",
        "name": "PK_X",
        "type": "p",
        "columns": ["CODCREDITO"],
    }
    assert out.truncated is False
    assert out.hint is None
    assert out.duration_ms >= 0


def test_nz_list_constraints_input_accepts_wire_schema_key() -> None:
    parsed = ListConstraintsInput.model_validate({"database": "DEV", "schema": "PUBLIC"})
    assert parsed.table_schema == "PUBLIC"


def test_nz_list_constraints_no_constraints_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr("nz_mcp.tools.list_constraints.list_constraints", lambda *_a, **_k: [])
    out = nz_list_constraints(
        ListConstraintsInput(database="DEV", table_schema="DBO", table="BAMURE_CLIENTE"),
        config_path=two_profiles,
    )
    assert out.constraints == []
    assert out.truncated is False


def test_nz_list_constraints_propagates_object_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise_not_found(*_a: object, **_k: object) -> list[dict[str, object]]:
        raise ObjectNotFoundError(detail="nope", object_type="table")

    monkeypatch.setattr("nz_mcp.tools.list_constraints.list_constraints", _raise_not_found)

    with pytest.raises(ObjectNotFoundError) as exc:
        nz_list_constraints(
            ListConstraintsInput(database="DEV", table_schema="DBO", table="NOPE"),
            config_path=two_profiles,
        )
    assert exc.value.code == "OBJECT_NOT_FOUND"


def test_nz_list_constraints_propagates_typed_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise_netezza_error(*_a: object, **_k: object) -> list[dict[str, object]]:
        raise NetezzaError(operation="list_constraints", detail="denied")

    monkeypatch.setattr("nz_mcp.tools.list_constraints.list_constraints", _raise_netezza_error)

    with pytest.raises(NetezzaError) as exc:
        nz_list_constraints(
            ListConstraintsInput(database="DEV", table_schema="DBO"),
            config_path=two_profiles,
        )
    assert exc.value.code == "NETEZZA_ERROR"


def _fake_rows(count: int) -> list[dict[str, object]]:
    return [
        {"table": f"T{i}", "name": f"PK_T{i}", "type": "p", "columns": ["ID"]} for i in range(count)
    ]


def test_nz_list_constraints_under_cap_is_not_truncated(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.list_constraints.list_constraints", lambda *_a, **_k: _fake_rows(3)
    )
    out = nz_list_constraints(
        ListConstraintsInput(database="DEV", table_schema="DBO", max_rows=10),
        config_path=two_profiles,
    )
    assert len(out.constraints) == 3
    assert out.truncated is False
    assert out.hint is None


def test_nz_list_constraints_truncates_and_hints(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setattr(
        "nz_mcp.tools.list_constraints.list_constraints", lambda *_a, **_k: _fake_rows(5)
    )
    out = nz_list_constraints(
        ListConstraintsInput(database="DEV", table_schema="DBO", max_rows=2),
        config_path=two_profiles,
    )
    assert len(out.constraints) == 2
    assert out.truncated is True
    assert out.hint is not None
