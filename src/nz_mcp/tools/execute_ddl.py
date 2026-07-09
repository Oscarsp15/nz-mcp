"""``nz_execute_ddl`` — compile a full procedure/view DDL (admin) with dry-run default."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.execute_ddl import execute_ddl
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool

_MAX_INLINE_DDL: int = 1024 * 1024


class ExecuteDdlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str | None = Field(default=None, min_length=1, max_length=_MAX_INLINE_DDL)
    input_path: str | None = Field(default=None, max_length=4096)
    statement_type: Literal["procedure", "view"]
    dry_run: bool = True
    confirm: bool = False


class ExecuteDdlOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    sql_to_execute: str
    executed: bool
    duration_ms: int


@tool(
    name="nz_execute_ddl",
    description=(
        "Compile a full CREATE [OR REPLACE] PROCEDURE (NZPLSQL) or CREATE [OR REPLACE] VIEW "
        "from inline sql or input_path against the active profile database. Requires profile "
        "mode admin. Default dry_run=true validates and returns the SQL without executing; set "
        "dry_run=false and confirm=true to compile. Rejects PROD_ references when the active "
        "database is not a production one. Use for procedures/views only — not for tables (use "
        "nz_create_table) nor for running a procedure (use nz_call_procedure)."
    ),
    mode="admin",
    input_model=ExecuteDdlInput,
    output_model=ExecuteDdlOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_execute_ddl(
    params: ExecuteDdlInput,
    *,
    config_path: Path | None = None,
) -> ExecuteDdlOutput:
    profile = get_active_profile(path=config_path)
    raw = execute_ddl(
        profile,
        sql=params.sql,
        input_path=params.input_path,
        statement_type=params.statement_type,
        dry_run=params.dry_run,
        confirm=params.confirm,
    )
    return ExecuteDdlOutput(
        dry_run=bool(raw["dry_run"]),
        sql_to_execute=str(raw["sql_to_execute"]),
        executed=bool(raw["executed"]),
        duration_ms=int(raw["duration_ms"]),
    )
