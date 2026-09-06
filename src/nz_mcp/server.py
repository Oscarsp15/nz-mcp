"""MCP server entry and MCP SDK adapter (stdio transport)."""

from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, cast

import anyio
from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ValidationError

import nz_mcp.tools  # noqa: F401  (side effect: register tools)
from nz_mcp import __version__
from nz_mcp.config import Profile, get_active_profile
from nz_mcp.error_hints import (
    hints_for_error,
    hints_for_validation_error,
    summarize_validation_error,
)
from nz_mcp.errors import InvalidInputError, NzMcpError, PermissionDeniedError
from nz_mcp.i18n import MESSAGES, both
from nz_mcp.logging_config import configure_logging_for_stdio
from nz_mcp.tools.registry import TOOLS, ToolSpec

_MODE_RANK = {"read": 0, "write": 1, "admin": 2}


@dataclass(frozen=True, slots=True)
class ToolListing:
    """What ``tools/list`` advertises for a single tool.

    No output schema is advertised on purpose: see ``docs/adr/0019-sin-output-schema.md``.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any]


def list_tools() -> list[ToolListing]:
    return [
        ToolListing(
            name=spec.name,
            description=spec.description,
            input_schema=spec.input_model.model_json_schema(),
            annotations=dict(spec.annotations),
        )
        for spec in TOOLS.values()
    ]


def _serialize_content_block(block: Any) -> dict[str, Any]:
    dump = getattr(block, "model_dump", None)
    if callable(dump):
        return cast(dict[str, Any], dump(mode="json", by_alias=True))
    raise TypeError(f"unexpected content block type: {type(block).__name__}")


def _invoke(spec: ToolSpec, params: Any, *, config_path: Path | None) -> Any:
    if "config_path" in inspect.signature(spec.handler).parameters:
        return spec.handler(params, config_path=config_path)
    return spec.handler(params)


def _dispatch_tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    config_path: Path | None,
) -> dict[str, Any] | tuple[list[Any], Any] | BaseModel:
    """Error dict, or ``(blocks, meta)`` for content-block tools, or a Pydantic output model."""
    spec = TOOLS.get(name)
    if spec is None:
        return _error_response("UNKNOWN_TOOL", tool=name)

    profile = get_active_profile(path=config_path)
    if not _mode_allows(profile.mode, spec.mode):
        err = PermissionDeniedError(required=spec.mode, actual=profile.mode)
        return _error_response(err.code, **err.context)

    try:
        params = spec.input_model.model_validate(arguments)
    except ValidationError as exc:
        # Bad arguments are the single most frequent failure, so the payload carries the
        # compact reason per field plus, when derivable, the fields to add or drop.
        context: dict[str, Any] = {"detail": summarize_validation_error(exc)}
        hints = hints_for_validation_error(exc)
        if hints is not None:
            context["hint_es"] = hints["es"]
            context["hint_en"] = hints["en"]
        return _error_response("INVALID_INPUT", **context)

    try:
        raw = _invoke(spec, params, config_path=config_path)
    except NzMcpError as exc:
        return _error_response(exc.code, **exc.context)

    if spec.output_kind == "content_blocks":
        blocks, meta = raw
        return blocks, meta
    return cast(BaseModel, raw)


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    out = _dispatch_tool_call(name, arguments, config_path=config_path)
    if isinstance(out, dict):
        return out
    if isinstance(out, tuple):
        blocks, meta = out
        return {
            "content": [_serialize_content_block(b) for b in blocks],
            "meta": meta.model_dump(mode="json", by_alias=True),
        }
    return {"result": out.model_dump(mode="json", by_alias=True)}


def _mode_allows(profile_mode: str, required: str) -> bool:
    return _MODE_RANK[profile_mode] >= _MODE_RANK[required]


def _error_response(code: str, **context: Any) -> dict[str, Any]:
    key = _i18n_key_for(code)
    hints: dict[str, str] | None = None
    if key == "PROFILE_NOT_FOUND":
        # This one interpolates its hint into the message itself, so it is not promoted.
        pnf = MESSAGES["PROFILE_NOT_FOUND"]
        messages = {
            "es": pnf["es"].format(
                profile=context.get("profile", ""),
                hint_es=str(context.get("hint_es", "")),
            ),
            "en": pnf["en"].format(
                profile=context.get("profile", ""),
                hint_en=str(context.get("hint_en", "")),
            ),
        }
    else:
        hints = _resolve_hints(code, context)
        messages = both(key, **context) if key else {"es": code, "en": code}
    return {
        "error": {
            "code": code,
            "message_en": messages["en"],
            "message_es": messages["es"],
            # Always present, ``None`` when no rule is specific enough: a field that
            # appears and disappears is harder for a model to branch on than a null.
            "hint_en": hints["en"] if hints else None,
            "hint_es": hints["es"] if hints else None,
            "context": context,
        }
    }


def _resolve_hints(code: str, context: dict[str, Any]) -> dict[str, str] | None:
    """Hints built at the raise site win; otherwise derive one from code plus context.

    Promoted out of ``context`` on purpose: the pair travels once, at the top level,
    where every client reads it, instead of twice in the same payload.
    """
    at_raise_site = {loc: context.pop(f"hint_{loc}", None) for loc in ("es", "en")}
    if at_raise_site["es"] and at_raise_site["en"]:
        return {"es": str(at_raise_site["es"]), "en": str(at_raise_site["en"])}
    return hints_for_error(code, context)


def _i18n_key_for(code: str) -> str | None:
    """Map a stable error code to its primary i18n key, when one exists."""
    mapping = {
        "PERMISSION_DENIED": "PERMISSION_DENIED.MODE_TOO_LOW",
        "PROFILE_NOT_FOUND": "PROFILE_NOT_FOUND",
        "INVALID_CONFIG": "INVALID_CONFIG",
        "INVALID_DATABASE_NAME": "INVALID_DATABASE_NAME",
        "CONNECTION_FAILED": "CONNECTION_FAILED",
        "NETEZZA_ERROR": "NETEZZA_ERROR",
        # Without these two the payload said literally "INVALID_INPUT" and the reason
        # only survived inside ``context`` (issue #142).
        "INVALID_INPUT": "INVALID_INPUT",
        "OBJECT_NOT_FOUND": "OBJECT_NOT_FOUND",
        # sql_guard / tool-specific rejection codes → GUARD_REJECTED.* catalog keys
        "STACKED_NOT_ALLOWED": "GUARD_REJECTED.STACKED_NOT_ALLOWED",
        "STATEMENT_NOT_ALLOWED": "GUARD_REJECTED.STATEMENT_NOT_ALLOWED",
        "UPDATE_REQUIRES_WHERE": "GUARD_REJECTED.UPDATE_REQUIRES_WHERE",
        "DELETE_REQUIRES_WHERE": "GUARD_REJECTED.DELETE_REQUIRES_WHERE",
        "WHERE_ALWAYS_TRUE": "GUARD_REJECTED.WHERE_ALWAYS_TRUE",
        "UNKNOWN_STATEMENT": "GUARD_REJECTED.UNKNOWN_STATEMENT",
        "EMPTY_STATEMENT": "GUARD_REJECTED.EMPTY_STATEMENT",
        "WRONG_STATEMENT_FOR_TOOL": "GUARD_REJECTED.WRONG_STATEMENT_FOR_TOOL",
        "LIMIT_NOT_A_LITERAL": "GUARD_REJECTED.LIMIT_NOT_A_LITERAL",
        "PROD_REF_IN_NONPROD": "GUARD_REJECTED.PROD_REF_IN_NONPROD",
        "CATALOG_OVERRIDE_REJECTED": "GUARD_REJECTED.CATALOG_OVERRIDE_REJECTED",
        "SECTION_NOT_FOUND": "SECTION_NOT_FOUND",
        "OVERLOAD_AMBIGUOUS": "OVERLOAD_AMBIGUOUS",
        "PROCEDURE_ALREADY_EXISTS": "PROCEDURE_ALREADY_EXISTS",
        "CONFIRM_REQUIRED": "CONFIRM_REQUIRED",
        "RESPONSE_TOO_LARGE": "RESPONSE_TOO_LARGE",
        "INPUT_TOO_BROAD": "INPUT_TOO_BROAD",
    }
    return mapping.get(code)


def build_mcp_server(*, config_path: Path | None = None) -> Server[Any, Any]:
    """Build a low-level MCP server that delegates to the internal dispatcher."""
    server: Server[Any, Any] = Server(name="nz-mcp", version=__version__)

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _handle_list_tools() -> list[types.Tool]:
        return [_to_mcp_tool(listing) for listing in list_tools()]

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def _handle_call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | types.CallToolResult:
        out = _dispatch_tool_call(name, arguments, config_path=config_path)
        if isinstance(out, dict):
            return out
        if isinstance(out, tuple):
            blocks, meta = out
            # The blocks themselves are the payload; only the small metadata envelope is
            # mirrored into structuredContent so it is not re-sent as serialized blocks.
            return types.CallToolResult(
                content=blocks,
                structuredContent={"meta": meta.model_dump(mode="json", by_alias=True)},
                isError=False,
            )
        return {"result": out.model_dump(mode="json", by_alias=True)}

    return server


def run_stdio_server(
    *,
    config_path: Path | None = None,
    protocol_stdout: TextIO | None = None,
) -> None:
    """Run the MCP server on stdio using the official MCP SDK transport.

    Args:
        config_path: Optional profiles file to use instead of the default one.
        protocol_stdout: Stream the JSON-RPC answers are written to. The CLI passes the
            private duplicate of descriptor 1 built by
            ``nz_mcp.cli_output.stdout_reserved_for_protocol``, so the protocol does not
            travel through ``sys.stdout`` and a stray write cannot reach it. When ``None``
            the SDK falls back to ``sys.stdout``, which is the right default for a caller
            that has not moved the descriptor.
    """
    configure_logging_for_stdio()
    anyio.run(_run_stdio_server_async, config_path, protocol_stdout)


async def _run_stdio_server_async(
    config_path: Path | None,
    protocol_stdout: TextIO | None,
) -> None:
    server = build_mcp_server(config_path=config_path)
    options = server.create_initialization_options()
    stdout = anyio.wrap_file(protocol_stdout) if protocol_stdout is not None else None
    async with stdio_server(stdout=stdout) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


def _to_mcp_tool(listing: ToolListing) -> types.Tool:
    """Adapt a listing to the MCP ``Tool`` shape.

    ``outputSchema`` is optional in MCP (2025-06-18) and is deliberately omitted: it was
    the single largest part of the catalog injected into every session, and declaring it
    also forces a conforming ``structuredContent`` on every reply.
    """
    return types.Tool(
        name=listing.name,
        description=listing.description,
        inputSchema=_inline_refs(listing.input_schema),
        annotations=types.ToolAnnotations.model_validate(listing.annotations),
    )


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline ``$ref`` to ``#/$defs`` / ``#/definitions`` so nested MCP schemas stay valid.

    Pydantic puts reusable models under ``$defs`` with ``$ref`` at ``#/$defs/Name``. Wrapping the
    result model under ``properties.result`` breaks root-based resolvers (e.g. Claude Desktop).
    Inlining yields a self-contained subtree.
    """
    defs: dict[str, Any] = {}
    defs.update(schema.get("$defs") or {})
    defs.update(schema.get("definitions") or {})

    out = deepcopy(schema)
    out.pop("$defs", None)
    out.pop("definitions", None)

    if not defs:
        return out

    def _walk(node: Any, visited: frozenset[str]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith(("#/$defs/", "#/definitions/")):
                name = ref.rsplit("/", 1)[-1]
                if name in visited:
                    return dict(node)
                target = defs.get(name)
                if target is None:
                    return {k: _walk(v, visited) for k, v in node.items()}
                merged: dict[str, Any] = deepcopy(target)
                for k, v in node.items():
                    if k != "$ref":
                        merged[k] = v
                return _walk(merged, visited | {name})
            return {k: _walk(v, visited) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(x, visited) for x in node]
        return node

    return cast(dict[str, Any], _walk(out, frozenset()))


__all__ = [
    "InvalidInputError",
    "Profile",
    "ToolListing",
    "build_mcp_server",
    "call_tool",
    "list_tools",
    "run_stdio_server",
]
