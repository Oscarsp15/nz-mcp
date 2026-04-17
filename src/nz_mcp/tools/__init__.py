"""MCP tools — registered via ``registry.tool`` decorator.

Importing this package registers every tool side-effect-free.
"""

from __future__ import annotations

from nz_mcp.tools import (
    databases,  # noqa: F401  (registers database tools)
    schemas,  # noqa: F401  (registers schema tools)
    session,  # noqa: F401  (registers session tools)
    tables,  # noqa: F401  (registers table tools)
)
from nz_mcp.tools.registry import TOOLS, ToolSpec

__all__ = ["TOOLS", "ToolSpec"]
