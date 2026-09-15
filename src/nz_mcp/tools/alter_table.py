"""``nz_alter_table`` — additive ALTER TABLE (admin) with dry-run default."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.alter_table import execute_alter_table
from nz_mcp.config import get_active_profile
from nz_mcp.tools.ddl import ColumnDef
from nz_mcp.tools.registry import tool


class SetDefaultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(min_length=1, max_length=128)
    default: Any


class RenameColumnInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from", min_length=1, max_length=128)
    to: str = Field(min_length=1, max_length=128)


class AlterTableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    add_columns: list[ColumnDef] = Field(default_factory=list)
    set_defaults: list[SetDefaultInput] = Field(default_factory=list)
    drop_defaults: list[str] = Field(default_factory=list)
    rename_columns: list[RenameColumnInput] = Field(default_factory=list)
    dry_run: bool = True
    confirm: bool = False


class AlterTableOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    statements_to_execute: list[str] | None = None
    executed: bool
    statements_executed: int
    duration_ms: int


@tool(
    name="nz_alter_table",
    description=(
        "Use for additive ALTER TABLE on an existing table: ADD COLUMN, SET/DROP DEFAULT, "
        "RENAME COLUMN. Admin mode. dry_run=true (default) returns the SQL without executing; "
        "dry_run=false + confirm=true executes. Do not use for DROP COLUMN or ALTER VIEW "
        "(rejected), nor for CREATE (nz_create_table)."
    ),
    mode="admin",
    input_model=AlterTableInput,
    output_model=AlterTableOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_alter_table(
    params: AlterTableInput,
    *,
    config_path: Path | None = None,
) -> AlterTableOutput:
    profile = get_active_profile(path=config_path)
    raw = execute_alter_table(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        add_columns=[c.model_dump() for c in params.add_columns],
        set_defaults=[s.model_dump() for s in params.set_defaults],
        drop_defaults=list(params.drop_defaults),
        rename_columns=[r.model_dump(by_alias=True) for r in params.rename_columns],
        dry_run=params.dry_run,
        confirm=params.confirm,
    )
    return AlterTableOutput(
        dry_run=bool(raw["dry_run"]),
        statements_to_execute=raw["statements_to_execute"],
        executed=bool(raw["executed"]),
        statements_executed=int(raw["statements_executed"]),
        duration_ms=int(raw["duration_ms"]),
    )
