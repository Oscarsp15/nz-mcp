"""Table catalog tools."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import list_tables
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool


class ListTablesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    pattern: str | None = Field(default=None, min_length=1, max_length=128)


class TableItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: Literal["TABLE"] = "TABLE"


class ListTablesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tables: list[TableItem]


@tool(
    name="nz_list_tables",
    description=(
        "List Netezza base tables in a schema (not views). "
        "Use before describing columns or sampling. "
        "Do not use for views, procedures, or stats."
    ),
    mode="read",
    input_model=ListTablesInput,
    output_model=ListTablesOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_list_tables(
    params: ListTablesInput,
    *,
    config_path: Path | None = None,
) -> ListTablesOutput:
    profile = get_active_profile(path=config_path)
    rows = list_tables(
        profile,
        database=params.database,
        schema=params.table_schema,
        pattern=params.pattern,
    )
    return ListTablesOutput(
        tables=[TableItem(name=row["name"], kind="TABLE") for row in rows],
    )
