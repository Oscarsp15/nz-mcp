"""Database catalog tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.databases import list_databases
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class ListDatabasesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str | None = Field(default=None, min_length=1, max_length=128)


class DatabaseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str


class ListDatabasesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    databases: list[DatabaseItem]
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


@tool(
    name="nz_list_databases",
    description=(
        "List visible Netezza databases for the active profile. "
        "Use to discover available database names before exploring schemas or tables. "
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
    rows = list_databases(profile, pattern=params.pattern)
    return ListDatabasesOutput(
        databases=[DatabaseItem(**row) for row in rows],
        duration_ms=monotonic_duration_ms(start),
    )
