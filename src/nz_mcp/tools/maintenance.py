"""``nz_maintenance`` — table maintenance DDL (admin) with dry-run default."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.maintenance import MaintenanceAction, execute_maintenance
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool


class MaintenanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    action: MaintenanceAction
    dry_run: bool = True
    confirm: bool = False
    echo_sql: bool = True


class MaintenanceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    dry_run: bool
    statements_to_execute: list[str] | None = None
    executed: bool
    statements_executed: int
    duration_ms: int


@tool(
    name="nz_maintenance",
    description=(
        "Use to maintain one existing table: refresh statistics (generate_statistics) "
        "or reclaim space (groom, vacuum). Admin mode. dry_run=true (default) returns the "
        "SQL without executing; dry_run=false + confirm=true runs it. Do not use for "
        "structure changes (nz_alter_table) nor raw SQL (nz_execute_ddl)."
    ),
    mode="admin",
    input_model=MaintenanceInput,
    output_model=MaintenanceOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_maintenance(
    params: MaintenanceInput,
    *,
    config_path: Path | None = None,
) -> MaintenanceOutput:
    profile = get_active_profile(path=config_path)
    raw = execute_maintenance(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        action=params.action,
        dry_run=params.dry_run,
        confirm=params.confirm,
        echo_sql=params.echo_sql,
    )
    return MaintenanceOutput(
        action=str(raw["action"]),
        dry_run=bool(raw["dry_run"]),
        statements_to_execute=raw["statements_to_execute"],
        executed=bool(raw["executed"]),
        statements_executed=int(raw["statements_executed"]),
        duration_ms=int(raw["duration_ms"]),
    )
