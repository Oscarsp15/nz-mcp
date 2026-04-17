"""Schema catalog tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.schemas import list_schemas
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool


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
    profile = get_active_profile(path=config_path)
    rows = list_schemas(profile, database=params.database, pattern=params.pattern)
    return ListSchemasOutput(schemas=[SchemaItem(**row) for row in rows])
