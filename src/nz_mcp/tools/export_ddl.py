"""Export DDL as MCP content blocks (embedded resource + summary text).

Accepts an optional ``output_path``: when provided, the DDL is also persisted
to disk on the MCP server via :func:`nz_mcp.io.write_export_ddl`.

Two parameters refine the on-disk and over-the-wire shape (issue #129):

* ``include_resource_in_response`` (default ``False``): when ``output_path``
  is set, the resource block is omitted from the MCP response by default to
  avoid the response cap collision with very large DDLs. Setting it to
  ``True`` restores the previous behaviour (resource + path), at the caller's
  own risk of truncation.
* ``include_header`` (default ``True``): when ``output_path`` is set, a small
  SQL-comment header with database / schema / object / timestamp / profile /
  ``nz-mcp`` version is prepended to the file, followed by ``SET CATALOG
  <database>;``. This makes the file self-contained and re-executable. When
  ``False`` the file is byte-identical to the resource text (preserves the
  ADR 0013 invariant for callers that need it).

The SHA-256 reported in ``meta`` is always the digest of the bytes actually
on disk — when ``include_header=True`` this differs from the resource text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from mcp import types
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from nz_mcp import __version__ as _nz_mcp_version
from nz_mcp.catalog.procedures import get_procedure_ddl
from nz_mcp.catalog.tables import get_table_ddl
from nz_mcp.catalog.views import get_view_ddl
from nz_mcp.config import Profile, get_active_profile
from nz_mcp.errors import InvalidInputError
from nz_mcp.i18n import resolve_locale, t
from nz_mcp.io import WriteResult, validate_output_path, write_export_ddl
from nz_mcp.tools.procedures import PROC_DDL_LARGE_WARNING, PROC_DDL_WARN_BYTES
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start

# Number of leading lines included in the optional preview when the resource
# block is omitted from the response. Kept small and constant so the preview
# never approaches the response cap on its own.
_PREVIEW_LINES: int = 10


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
    output_path: str | None = Field(
        default=None,
        max_length=4096,
        description=(
            "Optional absolute path on the MCP server filesystem. If set, the DDL is also "
            "written to disk; '..', '~' and relative paths are rejected. The parent directory "
            "must exist and the file must not exist unless overwrite=True."
        ),
    )
    overwrite: bool = Field(
        default=False,
        description="If true and output_path points to an existing file, replace it.",
    )
    include_resource_in_response: bool = Field(
        default=False,
        description=(
            "Only meaningful when output_path is set. Default False: the resource block is "
            "omitted from the response (only summary + meta) to avoid response-cap collisions "
            "for large DDLs; the file on disk holds the full content. Set True to restore the "
            "previous behaviour (resource + path), assuming caller-side cap risk."
        ),
    )
    include_header: bool = Field(
        default=True,
        description=(
            "Only meaningful when output_path is set. Default True: prepend a SQL-comment "
            "header with database/schema/object/timestamp/profile/version followed by "
            "'SET CATALOG <database>;' so the file is self-contained and re-executable. "
            "Set False to write the DDL byte-identically to the resource text."
        ),
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
    output_path: str | None = Field(
        default=None,
        description="Absolute path of the file written, when output_path was provided.",
    )
    bytes_written: int | None = Field(
        default=None,
        description="Bytes written to disk (UTF-8 length of the DDL).",
    )
    sha256: str | None = Field(
        default=None,
        description=(
            "SHA-256 hex digest of the bytes actually on disk (header + DDL when "
            "include_header=True; equal to the resource text digest when "
            "include_header=False). The file is the source of truth (issue #129)."
        ),
    )
    preview: str | None = Field(
        default=None,
        description=(
            "First few lines of the file written to disk. Populated only when output_path "
            "is set and the resource block is omitted from the response (default), so the "
            "LLM has a small, bounded indicator of the on-disk content without re-reading "
            "the file."
        ),
    )
    resource_in_response: bool | None = Field(
        default=None,
        description=(
            "True when the response includes the EmbeddedResource block; False when only "
            "the on-disk file holds the full DDL. None when output_path was not provided."
        ),
    )
    header_included: bool | None = Field(
        default=None,
        description=(
            "True when the file on disk was prefixed with the SET CATALOG header. "
            "None when output_path was not provided."
        ),
    )


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
    path = "/".join(quote(part, safe="") for part in (database, schema, object_type, name))
    base = f"nz-mcp://ddl/{path}"
    if signature:
        return f"{base}?signature={quote(signature, safe='')}"
    return base


def build_header_block(
    *,
    database: str,
    schema: str,
    name: str,
    object_type: Literal["table", "view", "procedure"],
    profile_name: str,
    timestamp_utc: datetime,
    nz_mcp_version: str,
) -> str:
    """Build the SQL-comment + ``SET CATALOG`` preamble for the exported file.

    The preamble is composed of pure SQL ``--`` comments plus a ``SET CATALOG``
    statement, so the resulting file is still valid SQL and can be replayed
    against Netezza without preprocessing. The function is deliberately pure:
    no I/O, no clock access, no profile lookup — every input is supplied by
    the caller. This makes it trivial to unit-test and free of accidental
    leakage of credential-shaped data (only the *profile name* is included,
    never host/user/password/connection-string).

    The timestamp is normalised to UTC and serialised as ISO-8601 with the
    ``Z`` suffix (no microseconds) so two exports issued the same day from
    different machines are directly comparable.
    """
    iso = timestamp_utc.astimezone(UTC).replace(microsecond=0).isoformat()
    if iso.endswith("+00:00"):
        iso = iso[: -len("+00:00")] + "Z"
    return (
        f"-- Database: {database}\n"
        f"-- Schema:   {schema}\n"
        f"-- Object:   {object_type} {schema}.{name}\n"
        f"-- Exported: {iso} by {profile_name} (nz-mcp v{nz_mcp_version})\n"
        f"SET CATALOG {database};\n"
        "\n"
    )


def _build_header_for(
    *,
    profile: Profile,
    object_type: Literal["table", "view", "procedure"],
    database: str,
    schema: str,
    name: str,
) -> str:
    """Bridge between the tool inputs and :func:`build_header_block`.

    Captures ``datetime.now(UTC)`` and ``__version__`` in a single place so
    the pure builder remains time- and import-independent (and thus
    deterministic in tests).
    """
    return build_header_block(
        database=database,
        schema=schema,
        name=name,
        object_type=object_type,
        profile_name=profile.name,
        timestamp_utc=datetime.now(UTC),
        nz_mcp_version=_nz_mcp_version,
    )


def _ddl_preview(text: str, max_lines: int = _PREVIEW_LINES) -> str:
    """Return the first ``max_lines`` of ``text`` joined by ``\\n``.

    Used as a small, bounded indicator for the LLM when the full resource
    block is intentionally omitted from the response. Never grows with the
    DDL size, so it cannot trigger a cap collision on its own.
    """
    return "\n".join(text.splitlines()[:max_lines])


def _validate_output_path_eager(output_path: str | None) -> None:
    """Reject malformed ``output_path`` *before* hitting the catalog.

    The acceptance criteria for this feature require that a path with
    ``..``, ``~`` or any other policy violation is rejected before any
    Netezza query runs. Filesystem-state checks (parent existence,
    overwrite collision) still happen later inside :func:`write_export_ddl`
    because they require knowing the actual bytes (and we want the same
    error envelope regardless of whether the path or the filesystem state
    is the offender).
    """
    if output_path is None:
        return
    try:
        validate_output_path(output_path)
    except ValueError as exc:
        raise InvalidInputError(detail=str(exc)) from exc


def _maybe_persist_ddl(
    *,
    ddl: str,
    output_path: str | None,
    overwrite: bool,
    header: str | None,
) -> WriteResult | None:
    """Persist ``ddl`` to disk when ``output_path`` is set.

    When ``header`` is not ``None`` it is prepended to ``ddl`` before bytes
    are written; the SHA-256 in the returned :class:`WriteResult` then
    reflects the full file on disk (header + DDL), which is the source of
    truth for callers verifying integrity.

    Stdlib filesystem errors raised by :func:`write_export_ddl` are translated
    into :class:`InvalidInputError` with code ``INVALID_INPUT`` so the caller
    receives the standard MCP error envelope (i18n-aware) rather than a
    bare Python traceback. The original detail text is preserved in
    ``error.context.detail`` for debugging.
    """
    if output_path is None:
        return None
    try:
        return write_export_ddl(ddl, output_path, overwrite, header=header)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        raise InvalidInputError(detail=str(exc)) from exc


def _build_blocks_and_meta(
    *,
    ddl: str,
    file_text: str,
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
    write_result: WriteResult | None,
    include_resource_in_response: bool,
    header_included: bool | None,
) -> tuple[list[types.EmbeddedResource | types.TextContent], ExportDdlMeta]:
    """Compose the MCP content blocks and the structured meta for the response.

    The resource block is only emitted when the call did not write to disk
    *or* when the caller explicitly asked for it via
    ``include_resource_in_response=True``. Default-to-disk callers receive
    summary + meta only, which keeps the response well below the MCP cap
    even for very large DDLs (issue #129).
    """
    persisted_to_disk = write_result is not None
    emit_resource = (not persisted_to_disk) or include_resource_in_response

    blocks: list[types.EmbeddedResource | types.TextContent] = []
    if emit_resource:
        blocks.append(
            types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(
                    uri=AnyUrl(uri),
                    mimeType="text/sql",
                    text=ddl,
                ),
            )
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
    if write_result is not None:
        lines.append(
            t("EXPORT_DDL.WROTE_FILE", loc).format(
                path=write_result.path,
                bytes_written=write_result.bytes_written,
                sha256=write_result.sha256,
            )
        )
    if warning:
        lines.append(warning)
    if notes:
        lines.extend(notes)
    summary = "\n".join(lines)
    blocks.append(types.TextContent(type="text", text=summary))

    preview = _ddl_preview(file_text) if (persisted_to_disk and not emit_resource) else None
    resource_in_response = emit_resource if persisted_to_disk else None

    meta = ExportDdlMeta(
        object_type=object_type,
        database=database,
        object_schema=schema,
        name=name,
        duration_ms=duration_ms,
        resource_uri=uri,
        signature=signature,
        include_constraints=include_constraints,
        reconstructed=reconstructed,
        notes=notes,
        size_bytes=size_bytes,
        warning=warning,
        output_path=write_result.path if write_result is not None else None,
        bytes_written=write_result.bytes_written if write_result is not None else None,
        sha256=write_result.sha256 if write_result is not None else None,
        preview=preview,
        resource_in_response=resource_in_response,
        header_included=header_included if persisted_to_disk else None,
    )
    return blocks, meta


@tool(
    name="nz_export_ddl",
    description=(
        "Return Netezza DDL as MCP content blocks: embedded text/sql resource (native copy in "
        "Claude Desktop) plus a short text summary. Pass output_path to also persist the DDL "
        "to disk; by default the response then omits the resource block (file is the source "
        "of truth) and the file is prefixed with a self-contained 'SET CATALOG <db>;' header. "
        "Resolve names with list/describe tools first."
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
    _validate_output_path_eager(params.output_path)
    profile = get_active_profile(path=config_path)
    uri = _ddl_resource_uri(
        database=params.database,
        schema=params.object_schema,
        object_type=params.object_type,
        name=params.name,
        signature=params.signature,
    )

    persist_to_disk = params.output_path is not None
    use_header = persist_to_disk and params.include_header

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
        header = (
            _build_header_for(
                profile=profile,
                object_type="table",
                database=params.database,
                schema=params.object_schema,
                name=params.name,
            )
            if use_header
            else None
        )
        write_result = _maybe_persist_ddl(
            ddl=ddl,
            output_path=params.output_path,
            overwrite=params.overwrite,
            header=header,
        )
        return _build_blocks_and_meta(
            ddl=ddl,
            file_text=(header + ddl) if header is not None else ddl,
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
            write_result=write_result,
            include_resource_in_response=params.include_resource_in_response,
            header_included=(header is not None) if persist_to_disk else None,
        )

    if params.object_type == "view":
        ddl = get_view_ddl(
            profile,
            database=params.database,
            schema=params.object_schema,
            view=params.name,
        )
        header = (
            _build_header_for(
                profile=profile,
                object_type="view",
                database=params.database,
                schema=params.object_schema,
                name=params.name,
            )
            if use_header
            else None
        )
        write_result = _maybe_persist_ddl(
            ddl=ddl,
            output_path=params.output_path,
            overwrite=params.overwrite,
            header=header,
        )
        return _build_blocks_and_meta(
            ddl=ddl,
            file_text=(header + ddl) if header is not None else ddl,
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
            write_result=write_result,
            include_resource_in_response=params.include_resource_in_response,
            header_included=(header is not None) if persist_to_disk else None,
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
    header = (
        _build_header_for(
            profile=profile,
            object_type="procedure",
            database=params.database,
            schema=params.object_schema,
            name=params.name,
        )
        if use_header
        else None
    )
    write_result = _maybe_persist_ddl(
        ddl=ddl,
        output_path=params.output_path,
        overwrite=params.overwrite,
        header=header,
    )
    return _build_blocks_and_meta(
        ddl=ddl,
        file_text=(header + ddl) if header is not None else ddl,
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
        write_result=write_result,
        include_resource_in_response=params.include_resource_in_response,
        header_included=(header is not None) if persist_to_disk else None,
    )
