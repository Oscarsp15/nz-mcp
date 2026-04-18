"""DDL tools (CREATE TABLE / TRUNCATE / DROP) — ``mode: admin`` only."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nz_mcp.catalog.ddl import (
    execute_create_table,
    execute_create_table_as,
    execute_drop_table,
    execute_truncate,
)
from nz_mcp.config import get_active_profile
from nz_mcp.errors import InvalidInputError
from nz_mcp.tools.registry import tool


class ColumnDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=200)
    nullable: bool = True
    default: Any | None = None


class DistributionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["HASH", "RANDOM"] = "RANDOM"
    columns: list[str] = Field(default_factory=list)


class CreateTableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    columns: list[ColumnDef] = Field(min_length=1)
    distribution: DistributionInput | None = None
    organized_on: list[str] | None = None
    if_not_exists: bool = True
    dry_run: bool = True
    confirm: bool = False


class CreateTableOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    ddl_to_execute: str
    executed: bool
    duration_ms: int


class CreateTableAsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(min_length=1, max_length=128)
    target_schema: str = Field(min_length=1, max_length=128)
    target_table: str = Field(min_length=1, max_length=128)
    select_sql: str = Field(min_length=1, max_length=65536)
    distribution: DistributionInput | None = None
    organized_on: list[str] | None = None
    dry_run: bool = True
    confirm: bool = False
    estimate_rows: bool = False

    @field_validator("select_sql")
    @classmethod
    def strip_select_sql(cls, v: str) -> str:
        s = v.strip()
        if not s:
            msg = "select_sql must be non-empty"
            raise ValueError(msg)
        return s


class CreateTableAsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    ddl_to_execute: str
    would_create_rows: int | None = None
    executed: bool
    duration_ms: int


class TruncateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    confirm: bool


class TruncateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    truncated: bool
    duration_ms: int


class DropTableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    confirm: bool
    if_exists: bool = True


class DropTableOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dropped: bool


def _require_confirm_true(confirm: bool, *, tool: str) -> None:
    if confirm is not True:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail=f"confirm=true is required for {tool}.",
        )


@tool(
    name="nz_create_table",
    description=(
        "Create a base table with validated identifiers and Netezza distribution. "
        "Requires profile mode admin. Default dry_run=true returns DDL only; set "
        "dry_run=false and confirm=true to execute. Use for new tables only — not for ALTER."
    ),
    mode="admin",
    input_model=CreateTableInput,
    output_model=CreateTableOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_create_table(
    params: CreateTableInput,
    *,
    config_path: Path | None = None,
) -> CreateTableOutput:
    profile = get_active_profile(path=config_path)
    dist_dict = params.distribution.model_dump() if params.distribution is not None else None
    if params.dry_run:
        raw = execute_create_table(
            profile,
            database=params.database,
            schema=params.table_schema,
            table=params.table,
            columns=[c.model_dump() for c in params.columns],
            distribution=dist_dict,
            organized_on=params.organized_on,
            if_not_exists=params.if_not_exists,
            dry_run=True,
        )
        return CreateTableOutput(
            dry_run=True,
            ddl_to_execute=str(raw["ddl_to_execute"]),
            executed=False,
            duration_ms=int(raw["duration_ms"]),
        )
    if params.confirm is not True:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_create_table.",
        )
    raw = execute_create_table(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        columns=[c.model_dump() for c in params.columns],
        distribution=dist_dict,
        organized_on=params.organized_on,
        if_not_exists=params.if_not_exists,
        dry_run=False,
    )
    return CreateTableOutput(
        dry_run=False,
        ddl_to_execute=str(raw["ddl_to_execute"]),
        executed=bool(raw["executed"]),
        duration_ms=int(raw["duration_ms"]),
    )


@tool(
    name="nz_create_table_as",
    description=(
        "Create a base table from a validated SELECT (CTAS) with Netezza distribution. "
        "Requires profile mode admin. Default dry_run=true returns DDL only; set "
        "estimate_rows=true to run a COUNT preview (can be expensive). "
        "Rejects if the target table already exists."
    ),
    mode="admin",
    input_model=CreateTableAsInput,
    output_model=CreateTableAsOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_create_table_as(
    params: CreateTableAsInput,
    *,
    config_path: Path | None = None,
) -> CreateTableAsOutput:
    profile = get_active_profile(path=config_path)
    dist_dict = params.distribution.model_dump() if params.distribution is not None else None
    raw = execute_create_table_as(
        profile,
        database=params.database,
        schema=params.target_schema,
        table=params.target_table,
        select_sql=params.select_sql,
        distribution=dist_dict,
        organized_on=params.organized_on,
        dry_run=params.dry_run,
        confirm=params.confirm,
        estimate_rows=params.estimate_rows,
    )
    return CreateTableAsOutput(
        dry_run=bool(raw["dry_run"]),
        ddl_to_execute=str(raw["ddl_to_execute"]),
        would_create_rows=raw["would_create_rows"],
        executed=bool(raw["executed"]),
        duration_ms=int(raw["duration_ms"]),
    )


@tool(
    name="nz_truncate",
    description=(
        "Truncate a base table (removes all rows). Requires profile mode admin and "
        "confirm=true. Irreversible — use only when intended."
    ),
    mode="admin",
    input_model=TruncateInput,
    output_model=TruncateOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_truncate(
    params: TruncateInput,
    *,
    config_path: Path | None = None,
) -> TruncateOutput:
    _require_confirm_true(params.confirm, tool="nz_truncate")
    profile = get_active_profile(path=config_path)
    raw = execute_truncate(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
    )
    return TruncateOutput(truncated=bool(raw["truncated"]), duration_ms=int(raw["duration_ms"]))


@tool(
    name="nz_drop_table",
    description=(
        "Drop a base table. Requires profile mode admin and confirm=true. "
        "Destructive — prefer if_exists when unsure the table is present."
    ),
    mode="admin",
    input_model=DropTableInput,
    output_model=DropTableOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_drop_table(
    params: DropTableInput,
    *,
    config_path: Path | None = None,
) -> DropTableOutput:
    _require_confirm_true(params.confirm, tool="nz_drop_table")
    profile = get_active_profile(path=config_path)
    raw = execute_drop_table(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        if_exists=params.if_exists,
    )
    return DropTableOutput(dropped=bool(raw["dropped"]))
