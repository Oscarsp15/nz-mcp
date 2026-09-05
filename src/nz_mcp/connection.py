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
    # nzpy >=1.17.7 aborts the SSL handshake unless a CA bundle is given via
    # ``ssl={"ca_certs": ...}`` or ``skipCertVerification=True`` is passed (a top-level
    # connect kwarg, not an ``ssl`` key). Verification is opt-in per profile; see
    # docs/adr/0017-connection-security-level.md (#160).
    ssl_kwargs: dict[str, object] = (
        {"ssl": {"ca_certs": profile.ca_certs}, "skipCertVerification": False}
        if profile.ca_certs
        else {"skipCertVerification": True}
    )
    try:
        return nzpy.connect(
            user=profile.user,
            host=profile.host,
            port=profile.port,
            database=profile.database,
            password=password,
            timeout=profile.timeout_s_default,
            application_name=APPLICATION_NAME,
            # SSL negotiation per profile (default 2 = preferred-secured). See config.Profile
            # and docs/adr/0017-connection-security-level.md.
            securityLevel=profile.security_level,
            logLevel=_NZPY_LOG_LEVEL_WARNING,
            **ssl_kwargs,
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
