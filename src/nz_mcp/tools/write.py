"""Write tools (INSERT / UPDATE / DELETE) with ``sql_guard`` and dry-run defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nz_mcp.catalog.write import (
    execute_delete,
    execute_insert,
    execute_insert_select,
    execute_update,
)
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool


class InsertInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    rows: list[dict[str, Any]]
    on_conflict: Literal["error", "skip"] = "error"
    dry_run: bool = True
    confirm: bool = False


class InsertOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inserted: int
    duration_ms: int
    dry_run: bool
    would_insert: int | None = None
    confirm_required: bool | None = None


class UpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    set: dict[str, Any] = Field(min_length=1)
    where: str = Field(min_length=1, max_length=8192)
    dry_run: bool = True
    confirm: bool = False

    @field_validator("where")
    @classmethod
    def strip_where(cls, v: str) -> str:
        s = v.strip()
        if not s:
            msg = "where must be a non-empty predicate"
            raise ValueError(msg)
        return s


class UpdateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    updated: int
    duration_ms: int
    dry_run: bool
    would_update: int | None = None
    confirm_required: bool | None = None


class DeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    where: str = Field(min_length=1, max_length=8192)
    dry_run: bool = True
    confirm: bool = False

    @field_validator("where")
    @classmethod
    def strip_where(cls, v: str) -> str:
        s = v.strip()
        if not s:
            msg = "where must be a non-empty predicate"
            raise ValueError(msg)
        return s


class DeleteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted: int
    duration_ms: int
    dry_run: bool
    would_delete: int | None = None
    confirm_required: bool | None = None


class InsertSelectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(min_length=1, max_length=128)
    target_schema: str = Field(min_length=1, max_length=128)
    target_table: str = Field(min_length=1, max_length=128)
    target_columns: list[str] | None = None
    select_sql: str = Field(min_length=1, max_length=65536)
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


class InsertSelectOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool
    sql_to_execute: str
    would_insert: int | None = None
    executed: bool
    inserted: int | None = None
    duration_ms: int
    warnings: list[str] = Field(default_factory=list)
    confirm_required: bool | None = None


@tool(
    name="nz_insert",
    description=(
        "Insert rows into a base table using parameterized INSERT. "
        "Default dry_run=true validates the INSERT without executing; set dry_run=false and "
        "confirm=true to apply. Requires profile mode write or admin. Database must match "
        "the active profile database."
    ),
    mode="write",
    input_model=InsertInput,
    output_model=InsertOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_insert(
    params: InsertInput,
    *,
    config_path: Path | None = None,
) -> InsertOutput:
    profile = get_active_profile(path=config_path)
    raw = execute_insert(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        rows=list(params.rows),
        on_conflict=params.on_conflict,
        dry_run=params.dry_run,
        confirm=params.confirm,
    )
    if raw.get("dry_run"):
        return InsertOutput(
            inserted=0,
            duration_ms=int(raw["duration_ms"]),
            dry_run=True,
            would_insert=int(raw["would_insert"]),
            confirm_required=bool(raw["confirm_required"]),
        )
    return InsertOutput(
        inserted=int(raw["inserted"]),
        duration_ms=int(raw["duration_ms"]),
        dry_run=False,
    )


@tool(
    name="nz_update",
    description=(
        "Update rows in a base table; WHERE is mandatory. Default dry_run=true runs COUNT only; "
        "set dry_run=false and confirm=true to apply."
    ),
    mode="write",
    input_model=UpdateInput,
    output_model=UpdateOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_update(
    params: UpdateInput,
    *,
    config_path: Path | None = None,
) -> UpdateOutput:
    profile = get_active_profile(path=config_path)
    raw = execute_update(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        set_cols=dict(params.set),
        where=params.where,
        dry_run=params.dry_run,
        confirm=params.confirm,
    )
    if raw.get("dry_run"):
        return UpdateOutput(
            updated=0,
            duration_ms=int(raw["duration_ms"]),
            dry_run=True,
            would_update=int(raw["would_update"]),
            confirm_required=bool(raw["confirm_required"]),
        )
    return UpdateOutput(
        updated=int(raw["updated"]),
        duration_ms=int(raw["duration_ms"]),
        dry_run=False,
    )


@tool(
    name="nz_delete",
    description=(
        "Delete rows from a base table; WHERE is mandatory. Default dry_run=true counts matches; "
        "set dry_run=false and confirm=true to execute DELETE."
    ),
    mode="write",
    input_model=DeleteInput,
    output_model=DeleteOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_delete(
    params: DeleteInput,
    *,
    config_path: Path | None = None,
) -> DeleteOutput:
    profile = get_active_profile(path=config_path)
    raw = execute_delete(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        where=params.where,
        dry_run=params.dry_run,
        confirm=params.confirm,
    )
    if raw.get("dry_run"):
        return DeleteOutput(
            deleted=0,
            duration_ms=int(raw["duration_ms"]),
            dry_run=True,
            would_delete=int(raw["would_delete"]),
            confirm_required=bool(raw["confirm_required"]),
        )
    return DeleteOutput(
        deleted=int(raw["deleted"]),
        duration_ms=int(raw["duration_ms"]),
        dry_run=False,
    )


@tool(
    name="nz_insert_select",
    description=(
        "Insert into a base table from a validated SELECT (bulk copy, UNION ALL multi-row). "
        "Default dry_run=true returns generated SQL only; set estimate_rows=true to run a COUNT "
        "preview (can be expensive). Execute with dry_run=false and confirm=true. "
        "Literal values in select_sql are caller-controlled — not parameterized."
    ),
    mode="write",
    input_model=InsertSelectInput,
    output_model=InsertSelectOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_insert_select(
    params: InsertSelectInput,
    *,
    config_path: Path | None = None,
) -> InsertSelectOutput:
    profile = get_active_profile(path=config_path)
    raw = execute_insert_select(
        profile,
        database=params.database,
        schema=params.target_schema,
        table=params.target_table,
        select_sql=params.select_sql,
        target_columns=params.target_columns,
        dry_run=params.dry_run,
        confirm=params.confirm,
        estimate_rows=params.estimate_rows,
    )
    if raw.get("dry_run"):
        return InsertSelectOutput(
            dry_run=True,
            sql_to_execute=str(raw["sql_to_execute"]),
            would_insert=raw["would_insert"],
            executed=False,
            inserted=None,
            duration_ms=int(raw["duration_ms"]),
            warnings=list(raw["warnings"]),
            confirm_required=True,
        )
    return InsertSelectOutput(
        dry_run=False,
        sql_to_execute=str(raw["sql_to_execute"]),
        would_insert=None,
        executed=True,
        inserted=raw["inserted"],
        duration_ms=int(raw["duration_ms"]),
        warnings=list(raw["warnings"]),
    )
