"""nz-mcp — MCP server for IBM Netezza Performance Server."""

from __future__ import annotations

from importlib import metadata

#: Fallback for running from a source checkout, where no distribution is installed. Keep it
#: in sync with ``pyproject.toml``; ``tests/unit/test_version.py`` fails if it drifts.
_FALLBACK_VERSION = "0.1.0a5"


def current_version() -> str:
    """Version of the installed ``nz-mcp`` distribution, or the source fallback.

    Single source of truth for anything user-visible (``nz-mcp version``, ``doctor``, the
    MCP handshake, the update check): reading the installed metadata means the number can
    never drift from the package that is actually installed.
    """
    try:
        return metadata.version("nz-mcp")
    except metadata.PackageNotFoundError:
        return _FALLBACK_VERSION


#: Resolved from the installed distribution, so it can never drift from the package; the
#: fallback above only matters when running from a source checkout.
__version__ = current_version()
__all__ = ["__version__", "current_version"]
