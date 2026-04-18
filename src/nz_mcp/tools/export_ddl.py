"""Export DDL as MCP content blocks (embedded resource + summary text)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from mcp import types
from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.procedures import get_procedure_ddl
from nz_mcp.catalog.tables import get_table_ddl
from nz_mcp.catalog.views import get_view_ddl
from nz_mcp.config import get_active_profile
from nz_mcp.i18n import resolve_locale, t
from nz_mcp.tools.procedures import PROC_DDL_LARGE_WARNING, PROC_DDL_WARN_BYTES
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class ExportDdlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    object_type: Literal["table", "view", "procedure"]
    database: str = Field(min_length=1, max_length=128)
    object_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    name: str = Field(min_length=1, max_length=128)
    signature: str | None = Field(
        default=None,
        max_length=2048,
        description="Procedure overload signature when multiple overloads exist.",
    )
    include_constraints: bool = Field(
        default=True,
        description="For tables only: include constraints in reconstructed DDL.",
    )


class ExportDdlMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    object_type: Literal["table", "view", "procedure"]
    database: str
    object_schema: str = Field(alias="schema", min_length=1, max_length=128)
    name: str
    duration_ms: int = Field(ge=0)
    resource_uri: str
    signature: str | None = None
    include_constraints: bool | None = None
    reconstructed: bool | None = None
    notes: list[str] | None = None
    size_bytes: int | None = None
    warning: str | None = None


class ExportDdlToolOutput(BaseModel):
    """Wire shape for ``structuredContent`` on success (matches ``call_tool``)."""

    model_config = ConfigDict(extra="forbid")
    content: list[dict[str, object]] = Field(
        description="MCP content blocks: EmbeddedResource (DDL) + TextContent (summary).",
    )
    meta: ExportDdlMeta


def _ddl_resource_uri(
    *,
    database: str,
    schema: str,
    object_type: str,
    name: str,
    signature: str | None,
) -> str:
    path = "/".join(
        quote(part, safe="")
        for part in (database, schema, object_type, name)
    )
    base = f"nz-mcp://ddl/{path}"
    if signature:
        return f"{base}?signature={quote(signature, safe='')}"
    return base


def _build_blocks_and_meta(
    *,
    ddl: str,
    uri: str,
    object_type: Literal["table", "view", "procedure"],
    database: str,
    schema: str,
    name: str,
    duration_ms: int,
    signature: str | None,
    include_constraints: bool | None,
    reconstructed: bool | None,
    notes: list[str] | None,
    size_bytes: int | None,
    warning: str | None,
) -> tuple[list[types.EmbeddedResource | types.TextContent], ExportDdlMeta]:
    embedded = types.EmbeddedResource(
        type="resource",
        resource=types.TextResourceContents(
            uri=uri,
            mimeType="text/sql",
            text=ddl,
        ),
    )
    loc = resolve_locale()
    lines = [
        t("EXPORT_DDL.SUMMARY_LINE", loc).format(
            object_type=object_type,
            schema=schema,
            name=name,
            duration_ms=duration_ms,
        )
    ]
    if warning:
        lines.append(warning)
    if notes:
        lines.extend(notes)
    summary = "\n".join(lines)
    text = types.TextContent(type="text", text=summary)
    meta = ExportDdlMeta(
        object_type=object_type,
        database=database,
        schema=schema,
        name=name,
        duration_ms=duration_ms,
        resource_uri=uri,
        signature=signature,
        include_constraints=include_constraints,
        reconstructed=reconstructed,
        notes=notes,
        size_bytes=size_bytes,
        warning=warning,
    )
    return [embedded, text], meta


@tool(
    name="nz_export_ddl",
    description=(
        "Return Netezza DDL as MCP content blocks: embedded text/sql resource (native copy in "
        "Claude Desktop) plus a short text summary. Resolve names with list/describe tools first. "
        "Not a substitute for nz_query_select."
    ),
    mode="read",
    input_model=ExportDdlInput,
    output_model=ExportDdlToolOutput,
    output_kind="content_blocks",
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_export_ddl(
    params: ExportDdlInput,
    *,
    config_path: Path | None = None,
) -> tuple[list[types.EmbeddedResource | types.TextContent], ExportDdlMeta]:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    uri = _ddl_resource_uri(
        database=params.database,
        schema=params.object_schema,
        object_type=params.object_type,
        name=params.name,
        signature=params.signature,
    )

    if params.object_type == "table":
        payload = get_table_ddl(
            profile,
            database=params.database,
            schema=params.object_schema,
            table=params.name,
            include_constraints=params.include_constraints,
        )
        ddl = str(payload["ddl"])
        loc = resolve_locale()
        notes = [
            t("NOTE.DDL_RECONSTRUCTED", loc),
            t("NOTE.DDL_RECONSTRUCTED_DETAIL", loc),
            t("NOTE.DDL_WITH_DATA_CAVEAT", loc),
        ]
        return _build_blocks_and_meta(
            ddl=ddl,
            uri=uri,
            object_type="table",
            database=params.database,
            schema=params.object_schema,
            name=params.name,
            duration_ms=monotonic_duration_ms(start),
            signature=None,
            include_constraints=params.include_constraints,
            reconstructed=bool(payload["reconstructed"]),
            notes=notes,
            size_bytes=None,
            warning=None,
        )

    if params.object_type == "view":
        ddl = get_view_ddl(
            profile,
            database=params.database,
            schema=params.object_schema,
            view=params.name,
        )
        return _build_blocks_and_meta(
            ddl=ddl,
            uri=uri,
            object_type="view",
            database=params.database,
            schema=params.object_schema,
            name=params.name,
            duration_ms=monotonic_duration_ms(start),
            signature=None,
            include_constraints=None,
            reconstructed=None,
            notes=None,
            size_bytes=None,
            warning=None,
        )

    ddl = get_procedure_ddl(
        profile,
        database=params.database,
        schema=params.object_schema,
        procedure=params.name,
        signature=params.signature,
    )
    size_b = len(ddl.encode("utf-8"))
    warn = PROC_DDL_LARGE_WARNING if size_b > PROC_DDL_WARN_BYTES else None
    return _build_blocks_and_meta(
        ddl=ddl,
        uri=uri,
        object_type="procedure",
        database=params.database,
        schema=params.object_schema,
        name=params.name,
        duration_ms=monotonic_duration_ms(start),
        signature=params.signature,
        include_constraints=None,
        reconstructed=None,
        notes=None,
        size_bytes=size_b,
        warning=warn,
    )
