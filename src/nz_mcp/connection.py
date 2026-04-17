"""Netezza driver layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import nzpy

from nz_mcp.errors import ConnectionError as NzConnectionError

if TYPE_CHECKING:
    from nz_mcp.config import Profile

APPLICATION_NAME: Final[str] = "nz-mcp"


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
        )
    except Exception as exc:
        raise NzConnectionError(
            host=profile.host,
            port=profile.port,
            database=profile.database,
            user=profile.user,
            detail=str(exc),
        ) from exc
