"""Cross-database table/view name search tool."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import find_tables
from nz_mcp.config import MAX_ROWS_CAP, get_active_profile
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start

ObjectType = Literal["TABLE", "VIEW", "ALL"]


class FindTableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    table_pattern: str = Field(min_length=1, max_length=128)
    database: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Limit the search to one database. Omit to search every visible database, which "
            "is only allowed when the pattern narrows (at least one literal character)."
        ),
    )
    schema_pattern: str | None = Field(default=None, min_length=1, max_length=128)
    object_type: ObjectType = Field(
        default="TABLE",
        description="TABLE (base tables), VIEW, or ALL (base tables, external tables and views).",
    )
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ROWS_CAP,
        description=(
            "Maximum number of matches to return. Defaults to the active profile's "
            "max_rows_default; always capped at MAX_ROWS_CAP."
        ),
    )


class TableMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str
    schema_name: str = Field(alias="schema")
    name: str
    kind: str


class FindTableOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objects: list[TableMatch]
    truncated: bool = Field(
        default=False,
        description="True when more objects matched than max_rows.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to reach the matches left out.",
    )
    duration_ms: int = Field(
        ge=0, description="Wall time to run the catalog queries (milliseconds)."
    )


@tool(
    name="nz_find_table",
    description=(
        "Find tables and views by name pattern across visible databases, optionally limited "
        "by database or schema. Use to locate an object before describing or querying it. "
        "Without a database, a pattern of wildcards only is refused with INPUT_TOO_BROAD "
        "and a hint to pass database or a narrower pattern."
    ),
    mode="read",
    input_model=FindTableInput,
    output_model=FindTableOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_find_table(
    params: FindTableInput,
    *,
    config_path: Path | None = None,
) -> FindTableOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    requested = params.max_rows if params.max_rows is not None else profile.max_rows_default
    max_rows = min(requested, MAX_ROWS_CAP)
    rows, truncated = find_tables(
        profile,
        table_pattern=params.table_pattern,
        database=params.database,
        schema_pattern=params.schema_pattern,
        object_type=params.object_type,
        max_rows=max_rows,
    )
    hint = (
        t("HINT.TABLE_SEARCH_TRUNCATED", None, n=max_rows, cap=MAX_ROWS_CAP) if truncated else None
    )
    return FindTableOutput(
        objects=[TableMatch.model_validate(r) for r in rows[:max_rows]],
        truncated=truncated,
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )
