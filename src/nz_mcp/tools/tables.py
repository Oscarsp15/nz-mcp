"""Table catalog tools."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import get_table_ddl, get_table_sample, get_table_stats, list_tables
from nz_mcp.config import get_active_profile
from nz_mcp.i18n import resolve_locale, t
from nz_mcp.tools.query import ColumnMeta, QuerySelectOutput, hint_from_execute_payload
from nz_mcp.tools.registry import tool

_TABLE_SAMPLE_ROWS_CAP: int = 50


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


class TableSampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    table: str = Field(min_length=1, max_length=128)
    rows: int = Field(default=10, ge=1, le=_TABLE_SAMPLE_ROWS_CAP)


class TableStatsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    table: str = Field(min_length=1, max_length=128)


class TableStatsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_count: int
    size_bytes_used: int
    size_used_human: str
    size_bytes_allocated: int
    size_allocated_human: str
    skew: float | None
    table_created: str | None


class GetTableDdlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    table: str = Field(min_length=1, max_length=128)
    include_constraints: bool = True


class GetTableDdlOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ddl: str
    reconstructed: bool = True
    notes: list[str]


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


@tool(
    name="nz_table_sample",
    description=(
        "Return a small row sample from a base table (SELECT with a row cap). "
        "Use after nz_list_tables / nz_describe_table. "
        "Database must match the active profile database."
    ),
    mode="read",
    input_model=TableSampleInput,
    output_model=QuerySelectOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_table_sample(
    params: TableSampleInput,
    *,
    config_path: Path | None = None,
) -> QuerySelectOutput:
    profile = get_active_profile(path=config_path)
    raw = get_table_sample(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        rows=params.rows,
        timeout_s=profile.timeout_s_default,
    )
    hint = hint_from_execute_payload(raw)
    columns = [
        ColumnMeta.model_validate({"name": c["name"], "type": c["type"]}) for c in raw["columns"]
    ]
    return QuerySelectOutput(
        columns=columns,
        rows=raw["rows"],
        row_count=int(raw["row_count"]),
        truncated=bool(raw["truncated"]),
        duration_ms=int(raw["duration_ms"]),
        hint=hint,
    )


@tool(
    name="nz_table_stats",
    description=(
        "Return estimated row count and on-disk storage metrics for a base table "
        "from catalog statistics. Use for capacity planning."
    ),
    mode="read",
    input_model=TableStatsInput,
    output_model=TableStatsOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_table_stats(
    params: TableStatsInput,
    *,
    config_path: Path | None = None,
) -> TableStatsOutput:
    profile = get_active_profile(path=config_path)
    payload = get_table_stats(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
    )
    return TableStatsOutput.model_validate(payload)


@tool(
    name="nz_get_table_ddl",
    description=(
        "Return a reconstructed CREATE TABLE DDL string from system catalogs "
        "(SHOW TABLE is not used). Optionally omit constraints."
    ),
    mode="read",
    input_model=GetTableDdlInput,
    output_model=GetTableDdlOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_get_table_ddl(
    params: GetTableDdlInput,
    *,
    config_path: Path | None = None,
) -> GetTableDdlOutput:
    profile = get_active_profile(path=config_path)
    payload = get_table_ddl(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        include_constraints=params.include_constraints,
    )
    loc = resolve_locale()
    note = t("NOTE.DDL_RECONSTRUCTED", loc)
    return GetTableDdlOutput(
        ddl=payload["ddl"],
        reconstructed=bool(payload["reconstructed"]),
        notes=[note],
    )
