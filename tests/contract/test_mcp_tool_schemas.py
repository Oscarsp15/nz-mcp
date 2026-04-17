"""Contract tests — registry shape and call_tool error paths.

v0.1.0a0: only session tools are registered. As more arrive, EXPECTED grows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import ObjectNotFoundError
from nz_mcp.server import call_tool, list_tools
from nz_mcp.tools.registry import TOOLS

EXPECTED_V010A0: set[str] = {
    "nz_create_table",
    "nz_current_profile",
    "nz_delete",
    "nz_describe_procedure",
    "nz_describe_table",
    "nz_drop_table",
    "nz_explain",
    "nz_get_procedure_ddl",
    "nz_get_procedure_section",
    "nz_get_table_ddl",
    "nz_get_view_ddl",
    "nz_insert",
    "nz_list_databases",
    "nz_list_procedures",
    "nz_list_schemas",
    "nz_list_tables",
    "nz_list_views",
    "nz_query_select",
    "nz_switch_profile",
    "nz_table_sample",
    "nz_table_stats",
    "nz_truncate",
    "nz_update",
}


@pytest.mark.contract
def test_registry_contains_expected_for_v010a0() -> None:
    assert set(TOOLS) >= EXPECTED_V010A0


@pytest.mark.contract
def test_each_tool_has_required_metadata() -> None:
    for spec in TOOLS.values():
        assert spec.name and spec.name.startswith("nz_")
        assert spec.description
        assert len(spec.description) <= 500
        assert spec.mode in ("read", "write", "admin")
        assert spec.input_model is not None
        assert spec.output_model is not None
        assert "openWorldHint" in spec.annotations
        assert spec.annotations["openWorldHint"] is False


@pytest.mark.contract
def test_listings_have_json_schemas() -> None:
    listings = list_tools()
    assert len(listings) >= len(EXPECTED_V010A0)
    for listing in listings:
        assert listing.input_schema.get("type") == "object"
        assert listing.output_schema.get("type") == "object"


@pytest.mark.contract
def test_call_tool_unknown_returns_structured_error(two_profiles: Path) -> None:
    out = call_tool("nz_does_not_exist", {}, config_path=two_profiles)
    assert "error" in out
    assert out["error"]["code"] == "UNKNOWN_TOOL"


@pytest.mark.contract
def test_call_tool_invalid_input_returns_structured_error(two_profiles: Path) -> None:
    out = call_tool("nz_switch_profile", {"profile": ""}, config_path=two_profiles)
    assert "error" in out
    assert out["error"]["code"] == "INVALID_INPUT"


@pytest.mark.contract
def test_call_tool_happy_path(two_profiles: Path) -> None:
    out = call_tool("nz_current_profile", {}, config_path=two_profiles)
    assert "result" in out
    assert out["result"]["profile"] == "dev"


@pytest.mark.contract
def test_call_tool_describe_table_object_not_found(
    two_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(_profile: object, **_kwargs: object) -> dict[str, object]:
        raise ObjectNotFoundError(detail="no such table")

    monkeypatch.setattr("nz_mcp.tools.describe_table.describe_table", _raise)

    out = call_tool(
        "nz_describe_table",
        {"database": "DEV", "schema": "PUBLIC", "table": "__missing__"},
        config_path=two_profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "OBJECT_NOT_FOUND"


@pytest.mark.contract
def test_call_tool_permission_denied_when_mode_too_low(tmp_profiles: Path) -> None:
    """Simulate a tool registered as admin against a read-only profile."""
    from pydantic import BaseModel, ConfigDict

    from nz_mcp.tools.registry import tool

    class _In(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class _Out(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ok: bool = True

    @tool(
        name="nz_test_admin_only",
        description="test-only",
        mode="admin",
        input_model=_In,
        output_model=_Out,
        annotations={"readOnlyHint": False, "openWorldHint": False},
    )
    def _h(_p: _In) -> _Out:  # pragma: no cover - never reached
        return _Out()

    tmp_profiles.write_text(
        'active = "low"\n'
        "[profiles.low]\n"
        'host = "h"\nport = 5480\ndatabase = "DB"\nuser = "u"\nmode = "read"\n',
        encoding="utf-8",
    )
    out = call_tool("nz_test_admin_only", {}, config_path=tmp_profiles)

    # Cleanup so the rogue test tool does not leak across tests.
    TOOLS.pop("nz_test_admin_only", None)

    assert "error" in out
    assert out["error"]["code"] == "PERMISSION_DENIED"
