"""Tests for view catalog MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.tools.views import (
    DropViewInput,
    GetViewDdlInput,
    ListViewsInput,
    nz_drop_view,
    nz_get_view_ddl,
    nz_list_views,
)


def test_list_views_input_accepts_wire_schema_key() -> None:
    parsed = ListViewsInput.model_validate({"database": "DEV", "schema": "PUBLIC"})
    assert parsed.view_schema == "PUBLIC"


def test_get_view_ddl_input_accepts_wire_keys() -> None:
    parsed = GetViewDdlInput.model_validate(
        {"database": "DEV", "schema": "PUBLIC", "view": "V_X"},
    )
    assert parsed.view_schema == "PUBLIC"
    assert parsed.view == "V_X"


def test_drop_view_input_accepts_wire_schema_key() -> None:
    parsed = DropViewInput.model_validate(
        {"database": "DEV", "schema": "PUBLIC", "view": "V_X", "confirm": True},
    )
    assert parsed.view_schema == "PUBLIC"
    assert parsed.if_exists is True


def test_nz_list_views_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_list_views(
        _profile: object,
        database: str,
        schema: str,
        pattern: str | None = None,
    ) -> list[dict[str, str]]:
        assert database == "DEV"
        assert schema == "PUBLIC"
        assert pattern == "V%"
        return [{"name": "V1", "owner": "ADMIN"}]

    monkeypatch.setattr("nz_mcp.tools.views.list_views", _fake_list_views)
    out = nz_list_views(
        ListViewsInput(database="DEV", view_schema="PUBLIC", pattern="V%"),
        config_path=two_profiles,
    )
    assert len(out.views) == 1
    assert out.views[0].name == "V1"
    assert out.views[0].owner == "ADMIN"


def test_nz_list_views_propagates_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(*_a: object, **_k: object) -> list[dict[str, str]]:
        raise NetezzaError(operation="list_views", detail="denied")

    monkeypatch.setattr("nz_mcp.tools.views.list_views", _raise)

    with pytest.raises(NetezzaError):
        nz_list_views(
            ListViewsInput(database="DEV", view_schema="PUBLIC"), config_path=two_profiles
        )


def test_nz_get_view_ddl_happy_path(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_get_view_ddl(
        _profile: object,
        database: str,
        schema: str,
        view: str,
    ) -> str:
        assert database == "DEV"
        assert schema == "PUBLIC"
        assert view == "VW_A"
        return "CREATE VIEW PUBLIC.VW_A AS SELECT 1"

    monkeypatch.setattr("nz_mcp.tools.views.get_view_ddl", _fake_get_view_ddl)
    out = nz_get_view_ddl(
        GetViewDdlInput(database="DEV", view_schema="PUBLIC", view="VW_A"),
        config_path=two_profiles,
    )
    assert out.ddl.startswith("CREATE VIEW")


def test_nz_get_view_ddl_propagates_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(*_a: object, **_k: object) -> str:
        raise NetezzaError(operation="get_view_ddl", detail="missing")

    monkeypatch.setattr("nz_mcp.tools.views.get_view_ddl", _raise)

    with pytest.raises(NetezzaError):
        nz_get_view_ddl(
            GetViewDdlInput(database="DEV", view_schema="PUBLIC", view="X"),
            config_path=two_profiles,
        )


def test_nz_drop_view_requires_confirm(two_profiles: Path) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        nz_drop_view(
            DropViewInput(database="DEV", view_schema="PUBLIC", view="V_X", confirm=False),
            config_path=two_profiles,
        )
    assert excinfo.value.code == "CONFIRM_REQUIRED"


def test_nz_drop_view_handler_drops(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_execute_drop_view(
        _profile: object,
        database: str,
        schema: str,
        view: str,
        *,
        if_exists: bool,
    ) -> dict[str, object]:
        assert database == "DEV"
        assert schema == "PUBLIC"
        assert view == "V_X"
        assert if_exists is True
        return {"dropped": True, "duration_ms": 5}

    monkeypatch.setattr("nz_mcp.tools.views.execute_drop_view", _fake_execute_drop_view)
    out = nz_drop_view(
        DropViewInput(database="DEV", view_schema="PUBLIC", view="V_X", confirm=True),
        config_path=two_profiles,
    )
    assert out.dropped is True
    assert out.duration_ms == 5


def test_nz_drop_view_propagates_errors(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _raise(*_a: object, **_k: object) -> dict[str, object]:
        raise NetezzaError(operation="execute_drop_view", detail="denied")

    monkeypatch.setattr("nz_mcp.tools.views.execute_drop_view", _raise)
    with pytest.raises(NetezzaError):
        nz_drop_view(
            DropViewInput(database="DEV", view_schema="PUBLIC", view="V_X", confirm=True),
            config_path=two_profiles,
        )
