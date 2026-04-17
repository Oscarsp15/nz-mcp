"""MCP tools — registered via ``registry.tool`` decorator.

Importing this package registers every tool side-effect-free.
"""

from __future__ import annotations

from nz_mcp.tools import session  # noqa: F401  (registers session tools)
from nz_mcp.tools.registry import TOOLS, ToolSpec

__all__ = ["TOOLS", "ToolSpec"]
