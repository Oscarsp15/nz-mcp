"""Tool registry — extension via decorator.

Adding a tool: only this file + the tool's own module are touched.
``server.py`` does NOT need to know about specific tools.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, ParamSpec, TypeVar

from pydantic import BaseModel

from nz_mcp.config import PermissionMode

ToolHandler = Callable[..., BaseModel]

P = ParamSpec("P")
R = TypeVar("R", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    mode: PermissionMode
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    annotations: dict[str, Any] = field(default_factory=dict)


TOOLS: dict[str, ToolSpec] = {}


def tool(
    *,
    name: str,
    description: str,
    mode: PermissionMode,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    annotations: dict[str, Any] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Register a tool. Idempotent fail: re-registering the same name raises."""

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        if name in TOOLS:
            raise RuntimeError(f"tool already registered: {name}")
        TOOLS[name] = ToolSpec(
            name=name,
            description=description,
            mode=mode,
            input_model=input_model,
            output_model=output_model,
            handler=fn,
            annotations=annotations or {},
        )
        return fn

    return decorator


def reset_for_tests() -> None:
    """Clear the registry. Tests only — never call from production code."""
    TOOLS.clear()


# Re-export for convenience.
ReadOnlyHint = Literal[True, False]
