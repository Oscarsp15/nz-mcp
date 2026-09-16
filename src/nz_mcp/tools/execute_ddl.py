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
    echo_sql: bool = True
    validate_compile: bool = False


class ExecuteDdlOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    sql_to_execute: str | None = None
    executed: bool
    duration_ms: int
    compile_warning: str | None = None
    compile_error: str | None = None
    compiled: bool | None = None


@tool(
    name="nz_execute_ddl",
    description=(
        "Compile a CREATE PROCEDURE (NZPLSQL) or VIEW from sql or input_path. "
        "Admin mode. dry_run=true previews; dry_run=false+confirm=true compiles. "
        "NZPLSQL bodies compile lazily: executed=true means DDL accepted, not body valid; "
        "compile_warning is always set for procedures. "
        "validate_compile=true forces a compile check after CREATE. "
        "Rejects PROD_ refs unless allow_prod_reads=true. echo_sql=false omits DDL. "
        "Procedures/views only — not tables nor CALL."
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
        echo_sql=params.echo_sql,
        validate_compile=params.validate_compile,
    )
    return ExecuteDdlOutput(
        dry_run=bool(raw["dry_run"]),
        sql_to_execute=raw["sql_to_execute"],
        executed=bool(raw["executed"]),
        duration_ms=int(raw["duration_ms"]),
        compile_warning=raw.get("compile_warning"),
        compile_error=raw.get("compile_error"),
        compiled=raw.get("compiled"),
    )
