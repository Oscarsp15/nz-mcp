"""Netezza driver layer.

Stubbed in v0.1.0a0. Real ``nzpy`` integration arrives with the first read tool.
See docs/roles/data-engineer.md for the streaming/timeout contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nz_mcp.errors import ConnectionError as NzConnectionError

if TYPE_CHECKING:
    from nz_mcp.config import Profile

APPLICATION_NAME: Final[str] = "nz-mcp"


def open_connection(profile: Profile, password: str) -> object:  # noqa: ARG001
    """Open a Netezza connection.

    Not implemented in v0.1.0a0. Tracked by issue #4.
    """
    raise NzConnectionError(
        code="NOT_IMPLEMENTED",
        detail="connection.open_connection arrives with the first read tool (issue #4).",
    )
