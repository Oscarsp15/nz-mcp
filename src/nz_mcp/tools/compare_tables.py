"""Compare schemas of two tables or views."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import compare_tables
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class CompareTablesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(
        min_length=1,
        max_length=128,
        description="Database of table_a (and default for table_b).",
    )
    schema_a: str = Field(min_length=1, max_length=128, description="Schema of table_a.")
    table_a: str = Field(min_length=1, max_length=128, description="Name of table_a.")
    database_b: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Database of table_b (defaults to database).",
    )
    schema_b: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Schema of table_b (defaults to schema_a).",
    )
    table_b: str = Field(min_length=1, max_length=128, description="Name of table_b.")


class ColumnSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    type: str
    nullable: bool
    position: int


class TypeMismatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    type_a: str
    type_b: str
    nullable_a: bool
    nullable_b: bool


class PositionMismatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    position_a: int
    position_b: int


class CompareTablesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identical: bool = Field(
        description="True if both tables have identical columns, types, nullability, and positions."
    )
    columns_in_a: int = Field(ge=0, description="Total column count in table A.")
    columns_in_b: int = Field(ge=0, description="Total column count in table B.")
    columns_in_common: int = Field(ge=0, description="Number of columns present in both tables.")
    only_in_a: list[ColumnSummary] = Field(
        description="Columns present in table A but missing in table B."
    )
    only_in_b: list[ColumnSummary] = Field(
        description="Columns present in table B but missing in table A."
    )
    type_mismatches: list[TypeMismatch] = Field(
        description="Columns present in both tables with differing data types or nullability."
    )
    position_mismatches: list[PositionMismatch] = Field(
        description="Columns present in both tables with differing ordinal positions."
    )
    duration_ms: int = Field(
        ge=0, description="Wall time to query catalogs and compare (milliseconds)."
    )


@tool(
    name="nz_compare_tables",
    description=(
        "Compare the schema of two tables: columns only in A, only in B, and type/position "
        "mismatches. Use before migrations or to reconcile layers."
    ),
    mode="read",
    input_model=CompareTablesInput,
    output_model=CompareTablesOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_compare_tables(
    params: CompareTablesInput,
    *,
    config_path: Path | None = None,
) -> CompareTablesOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    database_b = params.database_b if params.database_b is not None else params.database
    schema_b = params.schema_b if params.schema_b is not None else params.schema_a
    result = compare_tables(
        profile,
        database_a=params.database,
        schema_a=params.schema_a,
        table_a=params.table_a,
        database_b=database_b,
        schema_b=schema_b,
        table_b=params.table_b,
    )
    return CompareTablesOutput.model_validate(
        {**result, "duration_ms": monotonic_duration_ms(start)}
    )
