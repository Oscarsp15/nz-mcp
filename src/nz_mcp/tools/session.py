"""Session tools: introspect and switch the active profile.

Spec: docs/architecture/tools-contract.md (#23, #24).
Security: switching profile NEVER elevates the granted mode beyond what's
configured in profiles.toml. The AI cannot grant itself more permissions.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.config import (
    PermissionMode,
    Profile,
    get_active_profile,
    get_profile,
    list_profile_names,
    set_active_profile,
)
from nz_mcp.errors import ProfileNotFoundError
from nz_mcp.tools.registry import tool

# --- nz_current_profile -------------------------------------------------------


class CurrentProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CurrentProfileOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str
    mode: PermissionMode
    host: str
    port: int
    database_default: str
    user: str
    available_profiles: list[str]


@tool(
    name="nz_current_profile",
    description=(
        "Return the active Netezza profile metadata (name, mode, host, port, db, user) "
        "and the list of available profiles. Use to know what context the AI is operating in. "
        "Never reveals passwords."
    ),
    mode="read",
    input_model=CurrentProfileInput,
    output_model=CurrentProfileOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_current_profile(
    _input: CurrentProfileInput,
    *,
    config_path: Path | None = None,
) -> CurrentProfileOutput:
    profile = get_active_profile(path=config_path)
    return CurrentProfileOutput(
        profile=profile.name,
        mode=profile.mode,
        host=profile.host,
        port=profile.port,
        database_default=profile.database,
        user=profile.user,
        available_profiles=list_profile_names(path=config_path),
    )


# --- nz_switch_profile --------------------------------------------------------


class SwitchProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = Field(min_length=1, max_length=64)


class SwitchProfileOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    switched_to: str
    mode: PermissionMode


@tool(
    name="nz_switch_profile",
    description=(
        "Switch the active session to a different pre-configured profile. "
        "This updates profiles.toml (active=...) and affects new nz-mcp processes; the running "
        "MCP session uses the switched profile immediately. "
        "Cannot elevate permissions: the new mode is always what profiles.toml declares. "
        "Call nz_current_profile first if you need to see available profiles."
    ),
    mode="read",
    input_model=SwitchProfileInput,
    output_model=SwitchProfileOutput,
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": False},
)
def nz_switch_profile(
    params: SwitchProfileInput,
    *,
    config_path: Path | None = None,
    on_switch: Callable[[Profile], None] | None = None,
) -> SwitchProfileOutput:
    try:
        target = get_profile(params.profile, path=config_path)
    except ProfileNotFoundError:
        names = list_profile_names(path=config_path)
        joined = ", ".join(names)
        hint_es = f" Perfiles existentes: {joined}." if joined else ""
        hint_en = f" Existing profiles: {joined}." if joined else ""
        raise ProfileNotFoundError(
            profile=params.profile,
            hint_es=hint_es,
            hint_en=hint_en,
            available_profiles=names,
        ) from None
    set_active_profile(target.name, path=config_path)
    if on_switch is not None:
        on_switch(target)
    return SwitchProfileOutput(switched_to=target.name, mode=target.mode)
