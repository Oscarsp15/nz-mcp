"""Tests for nz_describe_view and nz_object_dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nz_mcp.errors import ObjectNotFoundError
from nz_mcp.tools.views import (
    DescribeViewInput,
    ObjectDependenciesInput,
    nz_describe_view,
    nz_object_dependencies,
)


def test_describe_view_input_accepts_wire_schema_key() -> None:
    parsed = DescribeViewInput.model_validate(
        {"database": "DEV", "schema": "DBO", "view": "V_CASCADAS"},
    )
    assert parsed.view_schema == "DBO"
    assert parsed.view == "V_CASCADAS"


def test_describe_view_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_describe_view(
        _profile: object,
        database: str,
        schema: str,
        view: str,
    ) -> dict[str, object]:
        assert (database, schema, view) == ("DEV", "DBO", "V_CASCADAS")
        return {
            "name": "V_CASCADAS",
            "kind": "VIEW",
            "columns": [
                {
                    "name": "KEYBD",
                    "type": "CHARACTER VARYING(10)",
                    "nullable": True,
                    "default": None,
                }
            ],
            "depends_on": [{"schema": "DBO", "name": "V_CASCADASUNIVERSO", "kind": "VIEW"}],
        }

    monkeypatch.setattr("nz_mcp.tools.views.describe_view", _fake_describe_view)
    out = nz_describe_view(
        DescribeViewInput(database="DEV", view_schema="DBO", view="V_CASCADAS"),
        config_path=two_profiles,
    )
    assert out.name == "V_CASCADAS"
    assert out.kind == "VIEW"
    assert out.columns[0].name == "KEYBD"
    assert out.columns[0].sql_type == "CHARACTER VARYING(10)"
    assert out.depends_on[0].name == "V_CASCADASUNIVERSO"
    assert out.depends_on[0].ref_schema == "DBO"
    assert out.duration_ms >= 0


def test_describe_view_propagates_object_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_describe_view(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ObjectNotFoundError(code="OBJECT_NOT_FOUND", obj="NOPE")

    monkeypatch.setattr("nz_mcp.tools.views.describe_view", _fake_describe_view)
    with pytest.raises(ObjectNotFoundError):
        nz_describe_view(
            DescribeViewInput(database="DEV", view_schema="DBO", view="NOPE"),
            config_path=two_profiles,
        )


def test_object_dependencies_input_defaults() -> None:
    parsed = ObjectDependenciesInput.model_validate(
        {"database": "DEV", "schema": "DBO", "object": "V_CASCADAS"},
    )
    assert parsed.object_schema == "DBO"
    assert parsed.direction == "up"
    assert parsed.depth == 1


def test_object_dependencies_rejects_unknown_direction() -> None:
    with pytest.raises(ValidationError):
        ObjectDependenciesInput.model_validate(
            {"database": "DEV", "schema": "DBO", "object": "X", "direction": "sideways"},
        )


def test_object_dependencies_rejects_depth_over_cap() -> None:
    with pytest.raises(ValidationError):
        ObjectDependenciesInput.model_validate(
            {"database": "DEV", "schema": "DBO", "object": "X", "depth": 99},
        )


def test_object_dependencies_happy_path(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_object_dependencies(
        _profile: object,
        database: str,
        schema: str,
        obj: str,
        *,
        direction: str,
        depth: int,
    ) -> dict[str, object]:
        assert (database, schema, obj, direction, depth) == (
            "DEV",
            "DBO",
            "V_CASCADAS",
            "up",
            2,
        )
        return {
            "name": "V_CASCADAS",
            "kind": "VIEW",
            "direction": "up",
            "depth": 2,
            "nodes": [
                {"schema": "DBO", "name": "V_CASCADASUNIVERSO", "kind": "VIEW", "level": 1},
                {"schema": "DBO", "name": "T_BASE", "kind": "TABLE", "level": 2},
            ],
            "truncated": False,
        }

    monkeypatch.setattr("nz_mcp.tools.views.object_dependencies", _fake_object_dependencies)
    out = nz_object_dependencies(
        ObjectDependenciesInput(
            database="DEV",
            object_schema="DBO",
            object="V_CASCADAS",
            direction="up",
            depth=2,
        ),
        config_path=two_profiles,
    )
    assert out.direction == "up"
    assert out.depth == 2
    assert [node.level for node in out.nodes] == [1, 2]
    assert out.nodes[1].name == "T_BASE"
    assert out.nodes[1].kind == "TABLE"
    assert out.truncated is False


def test_object_dependencies_propagates_object_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_object_dependencies(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ObjectNotFoundError(code="OBJECT_NOT_FOUND", obj="NOPE")

    monkeypatch.setattr("nz_mcp.tools.views.object_dependencies", _fake_object_dependencies)
    with pytest.raises(ObjectNotFoundError):
        nz_object_dependencies(
            ObjectDependenciesInput(database="DEV", object_schema="DBO", object="NOPE"),
            config_path=two_profiles,
        )
