"""Netezza driver layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import nzpy

from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.logging_utils import sanitize

if TYPE_CHECKING:
    from nz_mcp.config import Profile

APPLICATION_NAME: Final[str] = "nz-mcp"

# nzpy's per-Connection logger gets explicit setLevel in its __init__, bypassing
# parent-logger filtering. ``logLevel=2`` maps to WARNING (0=DEBUG, 1=INFO, 2=WARNING
# in nzpy's convention); anything lower floods stderr with per-packet traffic and
# breaks client UIs that render on stderr.
_NZPY_LOG_LEVEL_WARNING: Final[int] = 2


def open_connection(profile: Profile, password: str) -> object:
    """Open a Netezza connection with bounded timeout and fixed app name."""
    try:
        return nzpy.connect(
            user=profile.user,
            host=profile.host,
            port=profile.port,
            database=profile.database,
            password=password,
            timeout=profile.timeout_s_default,
            application_name=APPLICATION_NAME,
            securityLevel=1,
            logLevel=_NZPY_LOG_LEVEL_WARNING,
        )
    except Exception as exc:  # noqa: BLE001, RUF100
        # nzpy may raise unchecked driver errors; we surface them as typed ConnectionError for MCP.
        raise NzConnectionError(
            host=profile.host,
            port=profile.port,
            database=profile.database,
            user=profile.user,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
