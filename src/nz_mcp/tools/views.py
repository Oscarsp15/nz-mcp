"""View catalog tools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.views import get_view_ddl, list_views
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool


class ListViewsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    view_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    pattern: str | None = Field(default=None, min_length=1, max_length=128)


class ViewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str


class ListViewsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    views: list[ViewItem]


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


@tool(
    name="nz_list_views",
    description=(
        "List Netezza views in a schema. "
        "Use to discover view names before fetching DDL. "
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
    profile = get_active_profile(path=config_path)
    rows = list_views(
        profile,
        database=params.database,
        schema=params.view_schema,
        pattern=params.pattern,
    )
    return ListViewsOutput(views=[ViewItem(name=r["name"], owner=r["owner"]) for r in rows])


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
    profile = get_active_profile(path=config_path)
    ddl = get_view_ddl(
        profile,
        database=params.database,
        schema=params.view_schema,
        view=params.view,
    )
    return GetViewDdlOutput(ddl=ddl)
