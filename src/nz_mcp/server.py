"""MCP server entry and MCP SDK adapter (stdio transport)."""

from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import anyio
from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ValidationError

import nz_mcp.tools  # noqa: F401  (side effect: register tools)
from nz_mcp import __version__
from nz_mcp.config import Profile, get_active_profile
from nz_mcp.errors import InvalidInputError, NzMcpError, PermissionDeniedError
from nz_mcp.i18n import MESSAGES, both
from nz_mcp.logging_config import configure_logging_for_stdio
from nz_mcp.tools.registry import TOOLS, OutputKind, ToolSpec

_MODE_RANK = {"read": 0, "write": 1, "admin": 2}


@dataclass(frozen=True, slots=True)
class ToolListing:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    output_kind: OutputKind
    annotations: dict[str, Any]


def list_tools() -> list[ToolListing]:
    return [
        ToolListing(
            name=spec.name,
            description=spec.description,
            input_schema=spec.input_model.model_json_schema(),
            output_schema=spec.output_model.model_json_schema(),
            output_kind=spec.output_kind,
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
        return _error_response("INVALID_INPUT", detail=str(exc))

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
    if key == "PROFILE_NOT_FOUND":
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
    elif key:
        messages = both(key, **context)
    else:
        messages = {"es": code, "en": code}
    return {
        "error": {
            "code": code,
            "message_en": messages["en"],
            "message_es": messages["es"],
            "context": context,
        }
    }


def _i18n_key_for(code: str) -> str | None:
    """Map a stable error code to its primary i18n key, when one exists."""
    mapping = {
        "PERMISSION_DENIED": "PERMISSION_DENIED.MODE_TOO_LOW",
        "PROFILE_NOT_FOUND": "PROFILE_NOT_FOUND",
        "INVALID_CONFIG": "INVALID_CONFIG",
        "INVALID_DATABASE_NAME": "INVALID_DATABASE_NAME",
        "CONNECTION_FAILED": "CONNECTION_FAILED",
        "NETEZZA_ERROR": "NETEZZA_ERROR",
        # sql_guard / tool-specific rejection codes → GUARD_REJECTED.* catalog keys
        "STACKED_NOT_ALLOWED": "GUARD_REJECTED.STACKED_NOT_ALLOWED",
        "STATEMENT_NOT_ALLOWED": "GUARD_REJECTED.STATEMENT_NOT_ALLOWED",
        "UPDATE_REQUIRES_WHERE": "GUARD_REJECTED.UPDATE_REQUIRES_WHERE",
        "DELETE_REQUIRES_WHERE": "GUARD_REJECTED.DELETE_REQUIRES_WHERE",
        "UNKNOWN_STATEMENT": "GUARD_REJECTED.UNKNOWN_STATEMENT",
        "EMPTY_STATEMENT": "GUARD_REJECTED.EMPTY_STATEMENT",
        "WRONG_STATEMENT_FOR_TOOL": "GUARD_REJECTED.WRONG_STATEMENT_FOR_TOOL",
        "SECTION_NOT_FOUND": "SECTION_NOT_FOUND",
        "OVERLOAD_AMBIGUOUS": "OVERLOAD_AMBIGUOUS",
        "PROCEDURE_ALREADY_EXISTS": "PROCEDURE_ALREADY_EXISTS",
        "CONFIRM_REQUIRED": "CONFIRM_REQUIRED",
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
            structured = {
                "content": [_serialize_content_block(b) for b in blocks],
                "meta": meta.model_dump(mode="json", by_alias=True),
            }
            return types.CallToolResult(
                content=blocks,
                structuredContent=structured,
                isError=False,
            )
        return {"result": out.model_dump(mode="json", by_alias=True)}

    return server


def run_stdio_server(*, config_path: Path | None = None) -> None:
    """Run the MCP server on stdio using the official MCP SDK transport."""
    configure_logging_for_stdio()
    anyio.run(_run_stdio_server_async, config_path)


async def _run_stdio_server_async(config_path: Path | None) -> None:
    server = build_mcp_server(config_path=config_path)
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


def _to_mcp_tool(listing: ToolListing) -> types.Tool:
    return types.Tool(
        name=listing.name,
        description=listing.description,
        inputSchema=_inline_refs(listing.input_schema),
        outputSchema=_tool_output_schema(listing.output_schema, output_kind=listing.output_kind),
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


def _tool_output_schema(
    result_schema: dict[str, Any],
    *,
    output_kind: OutputKind = "model",
) -> dict[str, Any]:
    err_block: dict[str, Any] = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "code": {"type": "string"},
            "message_en": {"type": "string"},
            "message_es": {"type": "string"},
            "context": {"type": "object"},
        },
        "required": ["code", "message_en", "message_es", "context"],
    }
    if output_kind == "content_blocks":
        inlined = _inline_refs(result_schema)
        props = inlined.get("properties") or {}
        content_s = props.get("content")
        meta_s = props.get("meta")
        if content_s is None or meta_s is None:
            raise ValueError("content_blocks tools require output_model with content and meta")
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "content": content_s,
                "meta": meta_s,
                "error": err_block,
            },
            "oneOf": [
                {"required": ["content", "meta"]},
                {"required": ["error"]},
            ],
        }

    inlined = _inline_refs(result_schema)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "result": inlined,
            "error": err_block,
        },
        "oneOf": [
            {"required": ["result"]},
            {"required": ["error"]},
        ],
    }


__all__ = [
    "InvalidInputError",
    "Profile",
    "ToolListing",
    "build_mcp_server",
    "call_tool",
    "list_tools",
    "run_stdio_server",
]
