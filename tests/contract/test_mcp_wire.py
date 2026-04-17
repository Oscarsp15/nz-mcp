"""Contract tests for MCP wire handlers (initialize/list/call)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.message import SessionMessage
from mcp.types import CallToolResult, ListToolsResult

from nz_mcp import __version__
from nz_mcp.server import build_mcp_server


@asynccontextmanager
async def _inprocess_client(config_path: Path) -> AsyncIterator[ClientSession]:
    server_to_client_send, server_to_client_recv = anyio.create_memory_object_stream[
        SessionMessage
    ](20)
    client_to_server_send, client_to_server_recv = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](20)
    server = build_mcp_server(config_path=config_path)
    init_options = server.create_initialization_options()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            server.run,
            client_to_server_recv,
            server_to_client_send,
            init_options,
            True,
        )
        async with ClientSession(server_to_client_recv, client_to_server_send) as client:
            yield client
        tg.cancel_scope.cancel()


@pytest.mark.contract
def test_mcp_initialize_reports_name_and_version(two_profiles: Path) -> None:
    async def _run() -> None:
        async with _inprocess_client(two_profiles) as client:
            init = await client.initialize()
            assert init.serverInfo.name == "nz-mcp"
            assert init.serverInfo.version == __version__

    anyio.run(_run)


@pytest.mark.contract
def test_mcp_tools_list_and_call(two_profiles: Path) -> None:
    async def _run() -> None:
        async with _inprocess_client(two_profiles) as client:
            await client.initialize()

            listing: ListToolsResult = await client.list_tools()
            by_name = {tool.name: tool for tool in listing.tools}
            assert "nz_current_profile" in by_name
            assert "nz_switch_profile" in by_name

            current = by_name["nz_current_profile"]
            assert current.description
            assert current.inputSchema.get("type") == "object"
            assert current.outputSchema is not None
            assert current.annotations is not None
            assert current.annotations.readOnlyHint is True

            call_ok: CallToolResult = await client.call_tool("nz_current_profile", {})
            assert call_ok.structuredContent is not None
            assert call_ok.structuredContent["result"]["profile"] == "dev"

            call_bad: CallToolResult = await client.call_tool("nz_switch_profile", {"profile": ""})
            assert call_bad.structuredContent is not None
            error = call_bad.structuredContent["error"]
            assert error["code"] == "INVALID_INPUT"
            assert "message_es" in error
            assert "message_en" in error
            assert isinstance(error["context"], dict)

    anyio.run(_run)
