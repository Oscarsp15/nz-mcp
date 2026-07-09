"""``nz_call_procedure`` — CALL a stored procedure (admin), returning messages/return code."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.call import call_procedure
from nz_mcp.config import TIMEOUT_S_CAP, get_active_profile
from nz_mcp.tools.registry import tool

ScalarArg = str | int | float | bool | None


class CallProcedureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(alias="schema", min_length=1, max_length=128)
    procedure: str = Field(min_length=1, max_length=128)
    args: list[ScalarArg] | None = None
    signature: str | None = Field(default=None, max_length=2048)
    dry_run: bool = True
    confirm: bool = False
    timeout_s: int | None = Field(default=None, ge=1, le=TIMEOUT_S_CAP)


class CallProcedureOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    call_sql: str
    executed: bool
    return_value: str | None = None
    messages: list[str] = Field(default_factory=list)
    duration_ms: int


@tool(
    name="nz_call_procedure",
    description=(
        "Execute a stored procedure via CALL and return its return value plus NOTICE/RAISE "
        "messages. Requires profile mode admin and database matching the active profile. "
        "Arguments are parameterized. Default dry_run=true returns the CALL SQL without "
        "executing; set dry_run=false and confirm=true to run. Use to run a procedure — "
        "not to create one (use nz_execute_ddl) nor to read its DDL (use nz_get_procedure_ddl)."
    ),
    mode="admin",
    input_model=CallProcedureInput,
    output_model=CallProcedureOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_call_procedure(
    params: CallProcedureInput,
    *,
    config_path: Path | None = None,
) -> CallProcedureOutput:
    profile = get_active_profile(path=config_path)
    raw = call_procedure(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        args=list(params.args) if params.args is not None else None,
        signature=params.signature,
        dry_run=params.dry_run,
        confirm=params.confirm,
        timeout_s=params.timeout_s,
    )
    return CallProcedureOutput(
        dry_run=bool(raw["dry_run"]),
        call_sql=str(raw["call_sql"]),
        executed=bool(raw["executed"]),
        return_value=raw["return_value"],
        messages=list(raw["messages"]),
        duration_ms=int(raw["duration_ms"]),
    )
