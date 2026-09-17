"""View catalog tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.ddl import execute_drop_view
from nz_mcp.catalog.views import get_view_ddl, list_views
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
