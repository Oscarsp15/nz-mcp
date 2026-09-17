"""Schema catalog tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.schemas import list_schemas
from nz_mcp.config import MAX_ROWS_CAP, get_active_profile
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class ListSchemasInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(min_length=1, max_length=128)
    pattern: str | None = Field(default=None, min_length=1, max_length=128)
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ROWS_CAP,
        description=(
            "Maximum number of schemas to return. Defaults to the active profile's "
            "max_rows_default; always capped at MAX_ROWS_CAP."
        ),
    )


class SchemaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str


class ListSchemasOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemas: list[SchemaItem]
    truncated: bool = Field(
        default=False,
        description="True when the database holds more schemas than max_rows.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to reach the schemas left out.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


@tool(
    name="nz_list_schemas",
    description=(
        "List Netezza schemas in a database. "
        "Use for discovering schema names before listing tables. "
        "The result is capped by max_rows (profile default); when truncated, "
        "narrow the search with pattern instead of raising max_rows blindly. "
        "Do not use for databases or table metadata."
    ),
    mode="read",
    input_model=ListSchemasInput,
    output_model=ListSchemasOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_list_schemas(
    params: ListSchemasInput,
    *,
    config_path: Path | None = None,
) -> ListSchemasOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    requested = params.max_rows if params.max_rows is not None else profile.max_rows_default
    max_rows = min(requested, MAX_ROWS_CAP)
    rows = list_schemas(profile, database=params.database, pattern=params.pattern)
    total = len(rows)
    truncated = total > max_rows
    hint = (
        t("HINT.SCHEMA_LIST_TRUNCATED", None, n=max_rows, total=total, cap=MAX_ROWS_CAP)
        if truncated
        else None
    )
    return ListSchemasOutput(
        schemas=[SchemaItem(**row) for row in rows[:max_rows]],
        truncated=truncated,
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )
