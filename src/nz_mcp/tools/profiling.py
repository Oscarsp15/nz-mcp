"""Column profiling tool."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.profiling import TOP_N_CAP, TOP_N_DEFAULT, profile_column
from nz_mcp.config import get_active_profile
from nz_mcp.i18n import resolve_locale, t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class TopValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    count: int = Field(ge=0)


class ProfileColumnInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    table: str = Field(min_length=1, max_length=128)
    column: str = Field(min_length=1, max_length=128)
    top_n: int = Field(default=TOP_N_DEFAULT, ge=1, le=TOP_N_CAP)


class ProfileColumnOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int = Field(ge=0)
    nulls: int = Field(ge=0)
    null_pct: float = Field(ge=0.0, le=100.0)
    distinct: int = Field(ge=0)
    min: str | None
    max: str | None
    top_values: list[TopValue]
    hint: str | None = None
    duration_ms: int = Field(ge=0, description="Wall time to profile the column (milliseconds).")


@tool(
    name="nz_profile_column",
    description=(
        "Profile one column: total, nulls, null %, distinct, min/max and top-N values in "
        "one read-only pass. Use before analyzing a new table. "
        "Database must match the active profile database."
    ),
    mode="read",
    input_model=ProfileColumnInput,
    output_model=ProfileColumnOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_profile_column(
    params: ProfileColumnInput,
    *,
    config_path: Path | None = None,
) -> ProfileColumnOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    payload = profile_column(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        column=params.column,
        top_n=params.top_n,
        timeout_s=profile.timeout_s_default,
    )
    distinct = int(payload["distinct"])
    hint: str | None = None
    if distinct > params.top_n:
        hint = t(
            "HINT.PROFILE_TOP_VALUES_LIMITED",
            resolve_locale(),
            shown=params.top_n,
            distinct=distinct,
            cap=TOP_N_CAP,
        )
    return ProfileColumnOutput(
        total=int(payload["total"]),
        nulls=int(payload["nulls"]),
        null_pct=float(payload["null_pct"]),
        distinct=distinct,
        min=payload["min"],
        max=payload["max"],
        top_values=[TopValue.model_validate(v) for v in payload["top_values"]],
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )
