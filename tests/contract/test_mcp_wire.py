"""Contract tests for MCP wire handlers (initialize/list/call)."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.message import SessionMessage
from mcp.types import CallToolResult, ListToolsResult
from pydantic import BaseModel, ConfigDict

from nz_mcp import __version__
from nz_mcp.server import build_mcp_server
from nz_mcp.tools.registry import TOOLS, tool


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
            assert current.annotations is not None
            assert current.annotations.readOnlyHint is True

            # ADR 0019: no tool advertises an output schema.
            assert all(tool.outputSchema is None for tool in listing.tools)

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


@pytest.mark.contract
def test_concurrent_tool_calls_do_not_serialize(two_profiles: Path) -> None:
    """A parked slow tool must not delay an unrelated call over the real wire (issue #360)."""
    started = threading.Event()
    release = threading.Event()

    class _In(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class _Out(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ok: bool = True

    @tool(
        name="nz_test_slow_wire",
        description="test-only",
        mode="read",
        input_model=_In,
        output_model=_Out,
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def _slow(_params: _In) -> _Out:
        started.set()
        release.wait(timeout=10)
        return _Out()

    try:

        async def _run() -> None:
            async with _inprocess_client(two_profiles) as client:
                await client.initialize()
                order: list[str] = []

                async def _slow_call() -> None:
                    await client.call_tool("nz_test_slow_wire", {})
                    order.append("slow")

                async def _fast_call() -> None:
                    while not started.is_set():
                        await anyio.sleep(0.005)
                    await client.call_tool("nz_current_profile", {})
                    order.append("fast")

                async with anyio.create_task_group() as tg:
                    tg.start_soon(_slow_call)
                    tg.start_soon(_fast_call)
                    while "fast" not in order:
                        await anyio.sleep(0.005)
                    assert order == ["fast"]
                    release.set()
                assert order == ["fast", "slow"]

        anyio.run(_run)
    finally:
        release.set()
        TOOLS.pop("nz_test_slow_wire", None)


@pytest.mark.contract
def test_mcp_nz_export_ddl_embedded_resource(
    two_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_get_table_ddl(_profile: object, **_kwargs: object) -> dict[str, object]:
        return {"ddl": "CREATE TABLE t(i int);", "reconstructed": True}

    monkeypatch.setattr("nz_mcp.tools.export_ddl.get_table_ddl", _fake_get_table_ddl)

    async def _run() -> None:
        async with _inprocess_client(two_profiles) as client:
            await client.initialize()
            res: CallToolResult = await client.call_tool(
                "nz_export_ddl",
                {
                    "object_type": "table",
                    "database": "DB",
                    "schema": "PUB",
                    "name": "T1",
                },
            )
            assert res.structuredContent is not None
            assert res.structuredContent["meta"]["schema"] == "PUB"
            assert len(res.content) == 2
            assert res.content[0].type == "resource"

            # ADR 0019: the blocks are not mirrored back into structuredContent.
            assert set(res.structuredContent) == {"meta"}

    anyio.run(_run)
