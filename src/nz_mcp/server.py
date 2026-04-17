"""MCP server entry and MCP SDK adapter (stdio transport)."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

import nz_mcp.tools  # noqa: F401  (side effect: register tools)
from nz_mcp import __version__
from nz_mcp.config import Profile, get_active_profile
from nz_mcp.errors import InvalidInputError, NzMcpError, PermissionDeniedError
from nz_mcp.i18n import both
from nz_mcp.tools.registry import TOOLS, ToolSpec

_MODE_RANK = {"read": 0, "write": 1, "admin": 2}


@dataclass(frozen=True, slots=True)
class ToolListing:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    annotations: dict[str, Any]


def list_tools() -> list[ToolListing]:
    return [
        ToolListing(
            name=spec.name,
            description=spec.description,
            input_schema=spec.input_model.model_json_schema(),
            output_schema=spec.output_model.model_json_schema(),
            annotations=dict(spec.annotations),
        )
        for spec in TOOLS.values()
    ]


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
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
        result = _invoke(spec, params, config_path=config_path)
    except NzMcpError as exc:
        return _error_response(exc.code, **exc.context)

    return {"result": result.model_dump(mode="json", by_alias=True)}


def _invoke(spec: ToolSpec, params: Any, *, config_path: Path | None) -> Any:
    if "config_path" in inspect.signature(spec.handler).parameters:
        return spec.handler(params, config_path=config_path)
    return spec.handler(params)


def _mode_allows(profile_mode: str, required: str) -> bool:
    return _MODE_RANK[profile_mode] >= _MODE_RANK[required]


def _error_response(code: str, **context: Any) -> dict[str, Any]:
    key = _i18n_key_for(code)
    messages = both(key, **context) if key else {"es": code, "en": code}
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
    }
    return mapping.get(code)


def build_mcp_server(*, config_path: Path | None = None) -> Server[Any, Any]:
    """Build a low-level MCP server that delegates to the internal dispatcher."""
    server: Server[Any, Any] = Server(name="nz-mcp", version=__version__)

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _handle_list_tools() -> list[types.Tool]:
        return [_to_mcp_tool(listing) for listing in list_tools()]

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def _handle_call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return call_tool(name, arguments, config_path=config_path)

    return server


def run_stdio_server(*, config_path: Path | None = None) -> None:
    """Run the MCP server on stdio using the official MCP SDK transport."""
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
        inputSchema=listing.input_schema,
        outputSchema=_tool_output_schema(listing.output_schema),
        annotations=types.ToolAnnotations.model_validate(listing.annotations),
    )


def _tool_output_schema(result_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "result": result_schema,
            "error": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "code": {"type": "string"},
                    "message_en": {"type": "string"},
                    "message_es": {"type": "string"},
                    "context": {"type": "object"},
                },
                "required": ["code", "message_en", "message_es", "context"],
            },
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
