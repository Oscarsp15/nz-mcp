"""Database catalog tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.databases import list_databases
from nz_mcp.config import MAX_ROWS_CAP, get_active_profile
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class ListDatabasesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str | None = Field(default=None, min_length=1, max_length=128)
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ROWS_CAP,
        description=(
            "Maximum number of databases to return. Defaults to the active profile's "
            "max_rows_default; always capped at MAX_ROWS_CAP."
        ),
    )


class DatabaseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str


class ListDatabasesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    databases: list[DatabaseItem]
    truncated: bool = Field(
        default=False,
        description="True when the profile can see more databases than max_rows.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to reach the databases left out.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


@tool(
    name="nz_list_databases",
    description=(
        "List visible Netezza databases for the active profile. "
        "Use to discover available database names before exploring schemas or tables. "
        "The result is capped by max_rows (profile default); when truncated, "
        "narrow the search with pattern instead of raising max_rows blindly. "
        "Do not use for schema or table metadata."
    ),
    mode="read",
    input_model=ListDatabasesInput,
    output_model=ListDatabasesOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_list_databases(
    params: ListDatabasesInput,
    *,
    config_path: Path | None = None,
) -> ListDatabasesOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    requested = params.max_rows if params.max_rows is not None else profile.max_rows_default
    max_rows = min(requested, MAX_ROWS_CAP)
    rows = list_databases(profile, pattern=params.pattern)
    total = len(rows)
    truncated = total > max_rows
    hint = (
        t("HINT.DATABASE_LIST_TRUNCATED", None, n=max_rows, total=total, cap=MAX_ROWS_CAP)
        if truncated
        else None
    )
    return ListDatabasesOutput(
        databases=[DatabaseItem(**row) for row in rows[:max_rows]],
        truncated=truncated,
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )
