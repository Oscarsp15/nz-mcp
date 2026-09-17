"""Cross-table/view column search tool."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import find_columns
from nz_mcp.config import MAX_ROWS_CAP, get_active_profile
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class FindColumnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(min_length=1, max_length=128)
    column_pattern: str = Field(min_length=1, max_length=128)
    schema_pattern: str | None = Field(default=None, min_length=1, max_length=128)
    table_pattern: str | None = Field(default=None, min_length=1, max_length=128)
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ROWS_CAP,
        description=(
            "Maximum number of column matches to return. Defaults to the active profile's "
            "max_rows_default; always capped at MAX_ROWS_CAP."
        ),
    )


class ColumnMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_name: str = Field(alias="schema")
    table: str
    column: str
    type: str


class FindColumnOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[ColumnMatch]
    truncated: bool = Field(
        default=False,
        description="True when more columns matched than max_rows.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to reach the matches left out.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


@tool(
    name="nz_find_column",
    description=(
        "Find columns by name pattern across a database; returns schema, table, column and "
        "type. Use to locate where a field lives before renaming or tracing it."
    ),
    mode="read",
    input_model=FindColumnInput,
    output_model=FindColumnOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_find_column(
    params: FindColumnInput,
    *,
    config_path: Path | None = None,
) -> FindColumnOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    requested = params.max_rows if params.max_rows is not None else profile.max_rows_default
    max_rows = min(requested, MAX_ROWS_CAP)
    rows = find_columns(
        profile,
        database=params.database,
        column_pattern=params.column_pattern,
        schema_pattern=params.schema_pattern,
        table_pattern=params.table_pattern,
    )
    total = len(rows)
    truncated = total > max_rows
    hint = (
        t("HINT.COLUMN_SEARCH_TRUNCATED", None, n=max_rows, total=total, cap=MAX_ROWS_CAP)
        if truncated
        else None
    )
    return FindColumnOutput(
        columns=[
            ColumnMatch(
                schema_name=r["schema"], table=r["table"], column=r["column"], type=r["type"]
            )
            for r in rows[:max_rows]
        ],
        truncated=truncated,
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )
