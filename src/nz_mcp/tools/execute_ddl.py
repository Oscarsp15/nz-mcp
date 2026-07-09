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
    allow_prod_reads: bool = False


class ExecuteDdlOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    sql_to_execute: str
    executed: bool
    duration_ms: int


@tool(
    name="nz_execute_ddl",
    description=(
        "Compile a full CREATE [OR REPLACE] PROCEDURE (NZPLSQL) or VIEW from sql or input_path "
        "against the active profile database. Requires mode admin. dry_run=true (default) "
        "returns the SQL without executing; dry_run=false + confirm=true compiles. Rejects "
        "PROD_ refs from a non-production database; allow_prod_reads=true skips that check when "
        "you certify all writes were flipped to the active DB and remaining PROD_ refs are "
        "read-only. Procedures/views only — not tables nor CALL (nz_call_procedure)."
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
        allow_prod_reads=params.allow_prod_reads,
    )
    return ExecuteDdlOutput(
        dry_run=bool(raw["dry_run"]),
        sql_to_execute=str(raw["sql_to_execute"]),
        executed=bool(raw["executed"]),
        duration_ms=int(raw["duration_ms"]),
    )
