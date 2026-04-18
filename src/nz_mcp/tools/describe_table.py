"""Describe base table metadata (columns, distribution, PK, FK) from Netezza catalogs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import describe_table
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class DescribeTableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    table: str = Field(min_length=1, max_length=128)


class ColumnDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    sql_type: str = Field(alias="type")
    nullable: bool
    default: str | None


class DistributionBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dist_type: Literal["HASH", "RANDOM"] = Field(alias="type")
    columns: list[str]


class ForeignKeyReferences(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str | None = None
    ref_schema: str = Field(alias="schema")
    ref_table: str = Field(alias="table")
    columns: list[str]


class ForeignKeyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    columns: list[str]
    references: ForeignKeyReferences


class DescribeTableOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: Literal["TABLE"] = "TABLE"
    columns: list[ColumnDescriptor]
    distribution: DistributionBlock
    organized_on: list[str] = Field(default_factory=list)
    primary_key: list[str]
    foreign_keys: list[ForeignKeyItem]
    duration_ms: int = Field(ge=0, description="Wall time to query catalogs (milliseconds).")


@tool(
    name="nz_describe_table",
    description=(
        "Describe Netezza table columns, primary key, foreign keys, and distribution "
        "from system catalogs. Use before querying or sampling data. "
        "Do not use for views or procedures."
    ),
    mode="read",
    input_model=DescribeTableInput,
    output_model=DescribeTableOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_describe_table(
    params: DescribeTableInput,
    *,
    config_path: Path | None = None,
) -> DescribeTableOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    payload = describe_table(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
    )
    return DescribeTableOutput.model_validate(
        {**payload, "duration_ms": monotonic_duration_ms(start)},
    )
