"""Clone a stored procedure to another database/schema (admin)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.clone import clone_procedure
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool


class TransformationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from", min_length=1, max_length=8192)
    to: str = Field(min_length=0, max_length=8192)
    regex: bool = False


class CloneProcedureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    source_database: str = Field(min_length=1, max_length=128)
    source_schema: str = Field(min_length=1, max_length=128)
    source_procedure: str = Field(min_length=1, max_length=128)
    source_signature: str | None = Field(default=None, max_length=2048)
    target_database: str = Field(min_length=1, max_length=128)
    target_schema: str = Field(min_length=1, max_length=128)
    target_procedure: str | None = Field(default=None, max_length=128)
    replace_if_exists: bool = False
    transformations: list[TransformationInput] | None = None
    dry_run: bool = True
    confirm: bool = False


class CloneProcedureOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    ddl_to_execute: str
    executed: bool
    warnings: list[str]
    duration_ms: int | None = None


@tool(
    name="nz_clone_procedure",
    description=(
        "Clone a Netezza stored procedure to another database/schema with optional "
        "body transformations. Requires profile mode admin. Use dry_run first; destructive "
        "when dry_run=false with confirm=true."
    ),
    mode="admin",
    input_model=CloneProcedureInput,
    output_model=CloneProcedureOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_clone_procedure(
    params: CloneProcedureInput,
    *,
    config_path: Path | None = None,
) -> CloneProcedureOutput:
    profile = get_active_profile(path=config_path)
    trans = (
        [t.model_dump(by_alias=True) for t in params.transformations]
        if params.transformations
        else None
    )
    raw = clone_procedure(
        profile,
        source_database=params.source_database,
        source_schema=params.source_schema,
        source_procedure=params.source_procedure,
        source_signature=params.source_signature,
        target_database=params.target_database,
        target_schema=params.target_schema,
        target_procedure=params.target_procedure,
        replace_if_exists=params.replace_if_exists,
        transformations=trans,
        dry_run=params.dry_run,
        confirm=params.confirm,
    )
    return CloneProcedureOutput(
        dry_run=bool(raw["dry_run"]),
        ddl_to_execute=str(raw["ddl_to_execute"]),
        executed=bool(raw["executed"]),
        warnings=list(raw["warnings"]),
        duration_ms=raw.get("duration_ms"),
    )
