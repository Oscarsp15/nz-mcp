"""Constraint metadata tool (primary/foreign/unique keys)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import list_constraints
from nz_mcp.config import MAX_ROWS_CAP, get_active_profile
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class ListConstraintsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str | None = Field(default=None, min_length=1, max_length=128)
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ROWS_CAP,
        description=(
            "Maximum number of constraints to return. Defaults to the active profile's "
            "max_rows_default; always capped at MAX_ROWS_CAP."
        ),
    )


class ConstraintItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    name: str
    type: str
    columns: list[str]


class ListConstraintsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraints: list[ConstraintItem]
    truncated: bool = Field(
        default=False,
        description="True when more constraints matched than max_rows.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to reach the constraints left out.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


@tool(
    name="nz_list_constraints",
    description=(
        "List primary/foreign/unique constraints for a table or a whole schema. Use to "
        "understand keys before joins or to audit integrity."
    ),
    mode="read",
    input_model=ListConstraintsInput,
    output_model=ListConstraintsOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_list_constraints(
    params: ListConstraintsInput,
    *,
    config_path: Path | None = None,
) -> ListConstraintsOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    requested = params.max_rows if params.max_rows is not None else profile.max_rows_default
    max_rows = min(requested, MAX_ROWS_CAP)
    rows = list_constraints(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
    )
    total = len(rows)
    truncated = total > max_rows
    hint = (
        t("HINT.CONSTRAINT_LIST_TRUNCATED", None, n=max_rows, total=total, cap=MAX_ROWS_CAP)
        if truncated
        else None
    )
    return ListConstraintsOutput(
        constraints=[
            ConstraintItem(table=r["table"], name=r["name"], type=r["type"], columns=r["columns"])
            for r in rows[:max_rows]
        ],
        truncated=truncated,
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )
