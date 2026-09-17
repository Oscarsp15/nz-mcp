"""View catalog tools."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.ddl import execute_drop_view
from nz_mcp.catalog.views import describe_view, get_view_ddl, list_views, object_dependencies
from nz_mcp.config import MAX_ROWS_CAP, get_active_profile
from nz_mcp.errors import InvalidInputError
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class ListViewsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    view_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    pattern: str | None = Field(default=None, min_length=1, max_length=128)
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ROWS_CAP,
        description=(
            "Maximum number of views to return. Defaults to the active profile's "
            "max_rows_default; always capped at MAX_ROWS_CAP."
        ),
    )


class ViewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str


class ListViewsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    views: list[ViewItem]
    truncated: bool = Field(
        default=False,
        description="True when the schema holds more views than max_rows.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to reach the views left out.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


class GetViewDdlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    view_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    view: str = Field(min_length=1, max_length=128)


class GetViewDdlOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ddl: str
    duration_ms: int = Field(ge=0, description="Wall time to fetch DDL (milliseconds).")


class DropViewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    view_schema: str = Field(alias="schema", min_length=1, max_length=128)
    view: str = Field(min_length=1, max_length=128)
    confirm: bool
    if_exists: bool = True


class DropViewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dropped: bool
    duration_ms: int = Field(ge=0, description="Wall time to run the DROP (milliseconds).")


@tool(
    name="nz_list_views",
    description=(
        "List Netezza views in a schema. "
        "Use to discover view names before fetching DDL. "
        "The result is capped by max_rows (profile default); when truncated, "
        "narrow the search with pattern instead of raising max_rows blindly. "
        "Do not use for tables, materialized views, or procedures."
    ),
    mode="read",
    input_model=ListViewsInput,
    output_model=ListViewsOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_list_views(
    params: ListViewsInput,
    *,
    config_path: Path | None = None,
) -> ListViewsOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    requested = params.max_rows if params.max_rows is not None else profile.max_rows_default
    max_rows = min(requested, MAX_ROWS_CAP)
    rows = list_views(
        profile,
        database=params.database,
        schema=params.view_schema,
        pattern=params.pattern,
    )
    total = len(rows)
    truncated = total > max_rows
    hint = (
        t("HINT.VIEW_LIST_TRUNCATED", None, n=max_rows, total=total, cap=MAX_ROWS_CAP)
        if truncated
        else None
    )
    return ListViewsOutput(
        views=[ViewItem(name=r["name"], owner=r["owner"]) for r in rows[:max_rows]],
        truncated=truncated,
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )


@tool(
    name="nz_get_view_ddl",
    description=(
        "Return CREATE VIEW DDL text for one view from the system catalog. "
        "Call after resolving the view name (e.g. via nz_list_views). "
        "Do not use for tables or procedures."
    ),
    mode="read",
    input_model=GetViewDdlInput,
    output_model=GetViewDdlOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_get_view_ddl(
    params: GetViewDdlInput,
    *,
    config_path: Path | None = None,
) -> GetViewDdlOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    ddl = get_view_ddl(
        profile,
        database=params.database,
        schema=params.view_schema,
        view=params.view,
    )
    return GetViewDdlOutput(ddl=ddl, duration_ms=monotonic_duration_ms(start))


@tool(
    name="nz_drop_view",
    description=(
        "Drop a view via DROP VIEW schema.view. Requires profile mode admin and "
        "confirm=true. Database must match the active profile. With if_exists=true "
        "(default) a missing view is a no-op instead of an error, checked against the "
        "catalog because NPS does not parse an IF EXISTS clause on DROP VIEW in any form. "
        "Destructive — use only when intended. Do not use for tables (nz_drop_table) or "
        "procedures (nz_drop_procedure)."
    ),
    mode="admin",
    input_model=DropViewInput,
    output_model=DropViewOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_drop_view(
    params: DropViewInput,
    *,
    config_path: Path | None = None,
) -> DropViewOutput:
    if params.confirm is not True:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required for nz_drop_view.",
        )
    profile = get_active_profile(path=config_path)
    raw = execute_drop_view(
        profile,
        database=params.database,
        schema=params.view_schema,
        view=params.view,
        if_exists=params.if_exists,
    )
    return DropViewOutput(
        dropped=bool(raw["dropped"]),
        duration_ms=int(raw["duration_ms"]),
    )


class DescribeViewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    view_schema: str = Field(alias="schema", min_length=1, max_length=128)
    view: str = Field(min_length=1, max_length=128)


class ViewColumnDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name: str
    sql_type: str = Field(alias="type")
    nullable: bool
    default: str | None


class DependencyItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str | None = Field(
        default=None,
        description="Database the reference lives in (set when the definition qualifies it).",
    )
    ref_schema: str = Field(alias="schema")
    name: str
    kind: str


class DescribeViewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: Literal["VIEW"]
    columns: list[ViewColumnDescriptor]
    depends_on: list[DependencyItem]
    duration_ms: int = Field(ge=0, description="Wall time to query catalogs (milliseconds).")


class ObjectDependenciesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    object_schema: str = Field(alias="schema", min_length=1, max_length=128)
    object: str = Field(min_length=1, max_length=128)
    direction: Literal["up", "down"] = Field(
        default="up",
        description="'up' walks what the object reads; 'down' walks what reads the object.",
    )
    depth: int = Field(default=1, ge=1, le=5, description="Maximum levels to walk.")


class ObjectDependencyNode(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str | None = Field(
        default=None,
        description="Database the node lives in; set when it differs from the walk root.",
    )
    node_schema: str = Field(alias="schema")
    name: str
    kind: str
    level: int


class ObjectDependenciesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str
    direction: Literal["up", "down"]
    depth: int
    nodes: list[ObjectDependencyNode]
    truncated: bool = Field(
        default=False,
        description="True when the node cap was reached before the walk finished.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to walk dependencies (milliseconds).")


@tool(
    name="nz_describe_view",
    description=(
        "Describe a view's columns and the objects it reads (depends_on). Use before "
        "changing a table or view to see what a view depends on. "
        "Do not use for tables or procedures."
    ),
    mode="read",
    input_model=DescribeViewInput,
    output_model=DescribeViewOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_describe_view(
    params: DescribeViewInput,
    *,
    config_path: Path | None = None,
) -> DescribeViewOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    payload = describe_view(
        profile,
        database=params.database,
        schema=params.view_schema,
        view=params.view,
    )
    return DescribeViewOutput.model_validate(
        {**payload, "duration_ms": monotonic_duration_ms(start)},
    )


@tool(
    name="nz_object_dependencies",
    description=(
        "Walk object dependencies (views/tables) up (what it reads) or down (what reads "
        "it) for impact analysis before changing an object. "
        "Do not use for column-level lineage or stored procedures."
    ),
    mode="read",
    input_model=ObjectDependenciesInput,
    output_model=ObjectDependenciesOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_object_dependencies(
    params: ObjectDependenciesInput,
    *,
    config_path: Path | None = None,
) -> ObjectDependenciesOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    payload = object_dependencies(
        profile,
        database=params.database,
        schema=params.object_schema,
        obj=params.object,
        direction=params.direction,
        depth=params.depth,
    )
    return ObjectDependenciesOutput.model_validate(
        {**payload, "duration_ms": monotonic_duration_ms(start)},
    )
