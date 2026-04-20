"""Logging setup for MCP stdio transport: JSON-RPC must own stdout; logs go to stderr."""

from __future__ import annotations

import logging
import sys
import warnings
from typing import Final

import structlog

_state: dict[str, bool] = {"configured": False}

# Third-party loggers that flood stderr with per-packet or per-request
# DEBUG/INFO noise when left at default levels. Clients that wrap nz-mcp
# (e.g. nz-workbench) render UI on stderr, so this noise breaks their output.
# ``mcp`` covers ``mcp.server.lowlevel.server`` (one INFO line per tool call)
# and any other SDK children.
_NOISY_LOGGERS: Final[tuple[str, ...]] = ("nzpy", "mcp")


def configure_logging_for_stdio() -> None:
    """Route stdlib logging and structlog to stderr so stdout stays JSON-RPC only.

    Call once when entering stdio server mode (``run_stdio_server`` / ``serve`` CLI).
    Idempotent: repeated calls are no-ops.
    """
    if _state["configured"]:
        return
    _state["configured"] = True

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            stream=sys.stderr,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    logging.captureWarnings(True)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    warnings.filterwarnings(
        "ignore",
        category=UserWarning,
        module=r"sqlglot\..*",
    )

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


__all__: Final[tuple[str, ...]] = ("configure_logging_for_stdio",)
