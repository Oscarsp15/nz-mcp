"""A slow synchronous tool must not park the event loop (issue #360).

The dispatcher is synchronous on purpose (every handler is sync and nzpy is blocking), so
``server._dispatch_tool_call_offloaded`` is what keeps the loop free. These tests drive it
directly: they register throwaway tools in the shared registry and remove them afterwards.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import anyio
import pytest
from pydantic import BaseModel, ConfigDict

from nz_mcp.server import _dispatch_tool_call_offloaded
from nz_mcp.tools.registry import TOOLS, tool


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True


def _register_slow(name: str, handler: object) -> None:
    tool(
        name=name,
        description="test-only",
        mode="read",
        input_model=_In,
        output_model=_Out,
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )(handler)  # type: ignore[arg-type]


@pytest.mark.contract
def test_slow_tool_does_not_block_the_event_loop(two_profiles: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def _slow(_params: _In) -> _Out:
        started.set()
        assert release.wait(timeout=10)
        order.append("slow")
        return _Out()

    _register_slow("nz_test_slow_offload", _slow)
    try:

        async def _run() -> None:
            limiter = anyio.CapacityLimiter(4)

            async def _slow_call() -> None:
                await _dispatch_tool_call_offloaded(
                    "nz_test_slow_offload", {}, config_path=two_profiles, limiter=limiter
                )

            async def _fast_call() -> None:
                # Only once the slow handler is inside its worker thread: if the loop were
                # blocked, this coroutine would never get to run at all.
                while not started.is_set():
                    await anyio.sleep(0.005)
                await _dispatch_tool_call_offloaded(
                    "nz_current_profile", {}, config_path=two_profiles, limiter=limiter
                )
                order.append("fast")

            async with anyio.create_task_group() as tg:
                tg.start_soon(_slow_call)
                tg.start_soon(_fast_call)
                while "fast" not in order:
                    await anyio.sleep(0.005)
                assert order == ["fast"], "the fast call must win while the slow one is parked"
                release.set()

        anyio.run(_run)
        assert order == ["fast", "slow"]
    finally:
        release.set()
        TOOLS.pop("nz_test_slow_offload", None)


@pytest.mark.contract
def test_limiter_caps_concurrent_tools(two_profiles: Path) -> None:
    lock = threading.Lock()
    active = 0
    peak = 0

    def _slow(_params: _In) -> _Out:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _Out()

    _register_slow("nz_test_slow_capped", _slow)
    try:

        async def _run() -> None:
            limiter = anyio.CapacityLimiter(2)

            async def _call() -> None:
                await _dispatch_tool_call_offloaded(
                    "nz_test_slow_capped", {}, config_path=two_profiles, limiter=limiter
                )

            async with anyio.create_task_group() as tg:
                for _ in range(6):
                    tg.start_soon(_call)

        anyio.run(_run)
        assert peak == 2
    finally:
        TOOLS.pop("nz_test_slow_capped", None)
