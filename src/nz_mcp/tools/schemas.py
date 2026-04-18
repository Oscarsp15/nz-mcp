"""Schema catalog tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.schemas import list_schemas
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class ListSchemasInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(min_length=1, max_length=128)
    pattern: str | None = Field(default=None, min_length=1, max_length=128)


class SchemaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str


class ListSchemasOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemas: list[SchemaItem]
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


@tool(
    name="nz_list_schemas",
    description=(
        "List Netezza schemas in a database. "
        "Use for discovering schema names before listing tables. "
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
    rows = list_schemas(profile, database=params.database, pattern=params.pattern)
    return ListSchemasOutput(
        schemas=[SchemaItem(**row) for row in rows],
        duration_ms=monotonic_duration_ms(start),
    )
