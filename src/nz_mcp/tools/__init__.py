"""MCP tools — registered via ``registry.tool`` decorator.

Importing this package registers every tool side-effect-free.
"""

from __future__ import annotations

from nz_mcp.tools import (
    clone_procedure,  # noqa: F401  (registers nz_clone_procedure)
    databases,  # noqa: F401  (registers database tools)
    ddl,  # noqa: F401  (registers DDL tools)
    export_ddl,  # noqa: F401  (registers nz_export_ddl)
    describe_table,  # noqa: F401  (registers nz_describe_table)
    procedures,  # noqa: F401  (registers procedure tools)
    query,  # noqa: F401  (registers nz_query_select, nz_explain)
    schemas,  # noqa: F401  (registers schema tools)
    session,  # noqa: F401  (registers session tools)
    tables,  # noqa: F401  (registers table tools)
    views,  # noqa: F401  (registers view tools)
    write,  # noqa: F401  (registers nz_insert, nz_update, nz_delete)
)
from nz_mcp.tools.registry import TOOLS, ToolSpec

__all__ = ["TOOLS", "ToolSpec"]
