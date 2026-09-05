"""Error payload the AI receives: localized detail plus actionable hint (#141, #142)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from nz_mcp.error_hints import (
    hints_for_error,
    hints_for_validation_error,
    summarize_validation_error,
)
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.errors import NetezzaError, ObjectNotFoundError
from nz_mcp.server import call_tool


class _Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: int


def _validation_error(payload: dict[str, Any]) -> ValidationError:
    with pytest.raises(ValidationError) as exc:
        _Sample.model_validate(payload)
    return exc.value


# --- pydantic summary ---------------------------------------------------------


def test_summary_is_one_compact_pair_per_field() -> None:
    detail = summarize_validation_error(_validation_error({}))
    assert detail == "a: Field required; b: Field required"


def test_summary_drops_the_docs_url_and_the_echoed_input() -> None:
    """The URL and the echoed value are the bulk of ``str(exc)`` and fix nothing."""
    detail = summarize_validation_error(_validation_error({"a": "secret-value", "b": "x"}))
    assert "https://" not in detail
    assert "secret-value" not in detail
    assert "b: Input should be a valid integer" in detail


def test_summary_caps_the_list_and_says_how_many_are_left() -> None:
    class _Wide(BaseModel):
        model_config = ConfigDict(extra="forbid")
        f1: str
        f2: str
        f3: str
        f4: str
        f5: str
        f6: str
        f7: str

    with pytest.raises(ValidationError) as exc:
        _Wide.model_validate({})
    detail = summarize_validation_error(exc.value)
    assert detail.endswith("(+2 more)")


def test_summary_renders_nested_locations() -> None:
    class _Row(BaseModel):
        model_config = ConfigDict(extra="forbid")
        id: int

    class _Batch(BaseModel):
        model_config = ConfigDict(extra="forbid")
        rows: list[_Row]

    with pytest.raises(ValidationError) as exc:
        _Batch.model_validate({"rows": [{"id": "nope"}]})
    assert summarize_validation_error(exc.value).startswith("rows.0.id: ")


# --- pydantic hints -----------------------------------------------------------


def test_hint_names_the_missing_arguments() -> None:
    hints = hints_for_validation_error(_validation_error({"a": "x"}))
    assert hints is not None
    assert "b" in hints["en"] and "b" in hints["es"]
    assert "nz_" not in hints["en"]


def test_missing_arguments_win_over_unknown_ones() -> None:
    """Dropping the unknown argument alone would not make the call succeed."""
    hints = hints_for_validation_error(_validation_error({"a": "x", "tabla": "T"}))
    assert hints is not None
    assert "b" in hints["en"]
    assert "tabla" not in hints["en"]


def test_hint_names_the_unknown_arguments_when_nothing_is_missing() -> None:
    hints = hints_for_validation_error(_validation_error({"a": "x", "b": 1, "tabla": "T"}))
    assert hints is not None
    assert "tabla" in hints["en"] and "tabla" in hints["es"]


def test_no_hint_when_the_fix_is_not_a_field_list() -> None:
    """A wrong type is already explained by the detail; a filler hint would be noise."""
    assert hints_for_validation_error(_validation_error({"a": "x", "b": "nope"})) is None


# --- code plus context hints --------------------------------------------------


def test_object_not_found_hint_points_at_the_listing_tool() -> None:
    hints = hints_for_error(
        "OBJECT_NOT_FOUND",
        {"object_type": "procedure", "database": "DEV", "schema": "PUBLIC"},
    )
    assert hints is not None
    assert "nz_list_procedures" in hints["en"]
    assert "DEV" in hints["es"] and "PUBLIC" in hints["es"]


def test_object_not_found_without_scope_gets_no_hint() -> None:
    assert hints_for_error("OBJECT_NOT_FOUND", {"object_type": "table"}) is None
    assert hints_for_error("OBJECT_NOT_FOUND", {"detail": "no such table"}) is None


def test_object_kind_without_a_listing_tool_gets_no_hint() -> None:
    """nz_switch_database already returns the visible databases in its own detail."""
    assert (
        hints_for_error(
            "OBJECT_NOT_FOUND",
            {"object_type": "database", "database": "DEV", "schema": "PUBLIC"},
        )
        is None
    )


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("ERROR: Multiple-row VALUES lists are not supported", "nz_insert_select"),
        ("ERROR: relation does not exist CLIENTES", "nz_list_tables"),
        ("ERROR: Attribute 'NOMBRE' not found", "nz_describe_table"),
        ("ERROR: permission denied on table CLIENTES", "nz_current_profile"),
    ],
)
def test_known_netezza_errors_get_their_own_hint(detail: str, expected: str) -> None:
    hints = hints_for_error("NETEZZA_ERROR", {"operation": "x", "detail": detail})
    assert hints is not None
    assert expected in hints["en"]
    assert hints["es"] != hints["en"]


def test_unclassified_netezza_error_gets_no_hint() -> None:
    assert hints_for_error("NETEZZA_ERROR", {"detail": "ERROR: something new"}) is None


def test_codes_without_rules_get_no_hint() -> None:
    assert hints_for_error("QUERY_TIMEOUT", {"detail": "timed out"}) is None


# --- end-to-end payload -------------------------------------------------------


def test_invalid_input_payload_carries_the_reason_not_the_code(two_profiles: Path) -> None:
    """Issue #142: ``message_*`` used to be the literal string ``INVALID_INPUT``."""
    out = call_tool(
        "nz_describe_table",
        {"database": "DEV", "tabla": "CLIENTES"},
        config_path=two_profiles,
    )
    error = out["error"]
    assert error["code"] == "INVALID_INPUT"
    for key in ("message_es", "message_en"):
        assert error[key] != "INVALID_INPUT"
        assert "schema: Field required" in error[key]
        assert "tabla" in error[key]
    assert "schema" in error["hint_en"] and "table" in error["hint_en"]
    assert "schema" in error["hint_es"] and "table" in error["hint_es"]


def test_invalid_input_payload_has_null_hints_when_none_applies(two_profiles: Path) -> None:
    out = call_tool("nz_switch_profile", {"profile": ""}, config_path=two_profiles)
    error = out["error"]
    assert error["code"] == "INVALID_INPUT"
    assert "profile: String should have at least 1 character" in error["message_en"]
    assert error["hint_en"] is None
    assert error["hint_es"] is None


def test_object_not_found_payload_localizes_the_detail_and_hints(
    two_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(_profile: object, **_kwargs: object) -> dict[str, object]:
        raise ObjectNotFoundError(
            detail="Table 'CLIENTES' does not exist in DEV.PUBLIC or is not visible.",
            object_type="table",
            database="DEV",
            schema="PUBLIC",
            table="CLIENTES",
        )

    monkeypatch.setattr("nz_mcp.tools.describe_table.describe_table", _raise)
    out = call_tool(
        "nz_describe_table",
        {"database": "DEV", "schema": "PUBLIC", "table": "CLIENTES"},
        config_path=two_profiles,
    )
    error = out["error"]
    assert error["code"] == "OBJECT_NOT_FOUND"
    assert "CLIENTES" in error["message_es"] and "CLIENTES" in error["message_en"]
    assert error["message_en"] != "OBJECT_NOT_FOUND"
    assert "nz_list_tables" in error["hint_en"]
    assert "nz_list_tables" in error["hint_es"]


def test_netezza_error_payload_gets_the_pattern_hint(
    two_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(_profile: object, **_kwargs: object) -> dict[str, object]:
        raise NetezzaError(
            operation="describe_table",
            database="DEV",
            detail="ERROR: Attribute 'NOMBRE' not found",
        )

    monkeypatch.setattr("nz_mcp.tools.describe_table.describe_table", _raise)
    out = call_tool(
        "nz_describe_table",
        {"database": "DEV", "schema": "PUBLIC", "table": "CLIENTES"},
        config_path=two_profiles,
    )
    assert "nz_describe_table" in out["error"]["hint_en"]


def test_hint_built_at_the_raise_site_is_promoted_once(
    two_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connection failures already build their hint; it must not travel twice."""

    def _raise(_profile: object, **_kwargs: object) -> dict[str, object]:
        raise NzConnectionError(
            host="nz-dev.example.com",
            port=5480,
            database="DEV",
            detail="Error in handshake",
            cause="AUTH_REJECTED",
            hint_es="Vuelve a guardar la contraseña.",
            hint_en="Store the password again.",
        )

    monkeypatch.setattr("nz_mcp.tools.describe_table.describe_table", _raise)
    out = call_tool(
        "nz_describe_table",
        {"database": "DEV", "schema": "PUBLIC", "table": "CLIENTES"},
        config_path=two_profiles,
    )
    error = out["error"]
    assert error["hint_en"] == "Store the password again."
    assert error["hint_es"] == "Vuelve a guardar la contraseña."
    assert "hint_en" not in error["context"]
    assert "hint_es" not in error["context"]


def test_profile_not_found_keeps_its_hint_inside_the_message(two_profiles: Path) -> None:
    """Its hint is a message fragment, so promoting it would duplicate the text."""
    out = call_tool("nz_switch_profile", {"profile": "ghost"}, config_path=two_profiles)
    error = out["error"]
    assert error["code"] == "PROFILE_NOT_FOUND"
    assert "nz-mcp add-profile" in error["message_es"]
    assert "dev" in error["message_en"]
    assert error["hint_es"] is None
    assert error["hint_en"] is None


# --- catalog_overrides rejection (issue #139, ADR 0022) -----------------------


def test_override_hint_names_the_profiles_toml_key_and_the_statement_kind() -> None:
    """A rejected override is config, not a retryable call: the hint must name the key."""
    hints = hints_for_error(
        "CATALOG_OVERRIDE_REJECTED",
        {
            "query_id": "list_tables",
            "profile": "prod",
            "reason": "NOT_A_SELECT",
            "statement_kind": "SHOW",
        },
    )
    assert hints is not None
    for text in hints.values():
        assert "catalog_overrides.list_tables" in text
        assert "profiles.prod" in text
        assert "SHOW" in text


def test_override_hint_falls_back_to_quoting_the_guard_code() -> None:
    """Reasons without a dedicated way out still say which guard rule fired."""
    hints = hints_for_error(
        "CATALOG_OVERRIDE_REJECTED",
        {"query_id": "list_databases", "profile": "dev", "reason": "STACKED_NOT_ALLOWED"},
    )
    assert hints is not None
    for text in hints.values():
        assert "STACKED_NOT_ALLOWED" in text
        assert "catalog_overrides.list_databases" in text


@pytest.mark.parametrize(
    ("reason", "needle"),
    [("SELECT_INTO", "INTO"), ("UNRESOLVED_BD_MARKER", "<BD>..")],
)
def test_override_hint_is_specific_per_reason(reason: str, needle: str) -> None:
    hints = hints_for_error(
        "CATALOG_OVERRIDE_REJECTED",
        {"query_id": "list_schemas", "profile": "dev", "reason": reason},
    )
    assert hints is not None
    assert all(needle in text for text in hints.values())


def test_no_override_hint_without_a_key_to_point_at() -> None:
    """Rule of ADR 0023: a hint is specific or absent, never filler."""
    assert hints_for_error("CATALOG_OVERRIDE_REJECTED", {"reason": "NOT_A_SELECT"}) is None
