"""``nz_drop_procedure`` — drop a stored procedure overload (admin, confirm-gated)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.ddl import execute_drop_procedure
from nz_mcp.config import get_active_profile
from nz_mcp.errors import InvalidInputError
from nz_mcp.tools.registry import tool


class DropProcedureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(alias="schema", min_length=1, max_length=128)
    procedure: str = Field(min_length=1, max_length=128)
    signature: str = Field(
        min_length=1,
        max_length=2048,
        description="Argument-type list of the overload, e.g. '(DATE, VARCHAR(20))' or 'INT4'.",
    )
    confirm: bool
    if_exists: bool = True


class DropProcedureOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dropped: bool
    duration_ms: int


@tool(
    name="nz_drop_procedure",
    description=(
        "Drop a stored procedure overload via DROP PROCEDURE schema.proc(types). Requires "
        "profile mode admin and confirm=true. The argument-type signature is mandatory "
        "(Netezza disambiguates overloads by it). With if_exists=true a missing procedure is "
        "a no-op. Database must match the active profile. Destructive — use only when intended."
    ),
    mode="admin",
    input_model=DropProcedureInput,
    output_model=DropProcedureOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_drop_procedure(
    params: DropProcedureInput,
    *,
    config_path: Path | None = None,
) -> DropProcedureOutput:
    if params.confirm is not True:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required for nz_drop_procedure.",
        )
    profile = get_active_profile(path=config_path)
    raw = execute_drop_procedure(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        signature=params.signature,
        if_exists=params.if_exists,
    )
    return DropProcedureOutput(
        dropped=bool(raw["dropped"]),
        duration_ms=int(raw["duration_ms"]),
    )
