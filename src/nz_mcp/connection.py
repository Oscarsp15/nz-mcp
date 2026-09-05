"""Netezza driver layer."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Final

import nzpy

from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.i18n import both
from nz_mcp.logging_utils import sanitize

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from nz_mcp.config import Profile

APPLICATION_NAME: Final[str] = "nz-mcp"

# nzpy's per-Connection logger gets explicit setLevel in its __init__, bypassing
# parent-logger filtering. ``logLevel=2`` maps to WARNING (0=DEBUG, 1=INFO, 2=WARNING
# in nzpy's convention); anything lower floods stderr with per-packet traffic and
# breaks client UIs that render on stderr.
_NZPY_LOG_LEVEL_WARNING: Final[int] = 2

# nzpy names its per-connection logger ``nzpy.Connection[<database>}]`` and lets records
# propagate, so a handler on the ``nzpy`` ancestor receives everything it emits. The real
# failure reason ("authentication failed", "Database X does not exist") only travels in
# those records: the exception nzpy raises is always the generic "Error in handshake".
_NZPY_LOGGER_NAME: Final[str] = "nzpy"

# Stable cause codes carried in ``ConnectionError.context["cause"]``. Each one has an
# actionable hint in the i18n catalog under ``CONNECTION_FAILED.HINT.<cause>``.
CAUSE_AUTH_REJECTED: Final[str] = "AUTH_REJECTED"
CAUSE_DATABASE_UNAVAILABLE: Final[str] = "DATABASE_UNAVAILABLE"
CAUSE_HOST_UNREACHABLE: Final[str] = "HOST_UNREACHABLE"
CAUSE_TLS_FAILED: Final[str] = "TLS_FAILED"
CAUSE_UNKNOWN: Final[str] = "UNKNOWN"

# Ordered classification rules, first match wins. Needles are matched lowercase against
# the driver diagnostics joined with the exception text. Kept as data (not nested ifs) so
# that a newly observed message costs one tuple entry, not a new branch.
# Note: nzpy clips the leading bytes of the server response, so the observed text is
# "hentication failed for user 'X'" - needles must tolerate that truncation.
_CAUSE_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        CAUSE_TLS_FAILED,
        (
            "problem establishing secured session",
            "ca certificate",
            "certificate verify",
            "ssl",
            "tls",
        ),
    ),
    (
        CAUSE_AUTH_REJECTED,
        (
            "entication failed",
            "invalid username",
            "invalid password",
            "password authentication",
        ),
    ),
    (
        CAUSE_DATABASE_UNAVAILABLE,
        (
            "does not exist",
            "no such database",
            "invalid database",
            "permission denied",
            "not authorized",
        ),
    ),
    (
        CAUSE_HOST_UNREACHABLE,
        (
            "communication error",
            "timed out",
            "timeout",
            "refused",
            "getaddrinfo",
            "unreachable",
            "name or service not known",
            "no route to host",
            "reset by peer",
        ),
    ),
)

# nzpy prefixes the server payload with this; dropping it keeps the detail readable.
_SERVER_RESPONSE_PREFIX: Final[str] = "Error occured, server response:"
# Control-flow breadcrumbs ("Error in conn_connection_complete"): they name the nzpy step
# that failed but carry no diagnostic value for the user.
_CONTROL_FLOW_MARKER: Final[re.Pattern[str]] = re.compile(r"^Error in conn_\w+$")


class _DriverDiagnosticsHandler(logging.Handler):
    """Collect the messages nzpy logs while a connection is being opened."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        # A broken log record must never turn into a connection failure.
        with suppress(Exception):
            self.messages.append(record.getMessage())


@contextmanager
def _capture_driver_diagnostics() -> Iterator[_DriverDiagnosticsHandler]:
    """Attach a private handler to the ``nzpy`` logger for the duration of the block.

    Scoped on purpose: it neither reconfigures global logging nor touches levels or
    propagation, and it is always detached again. While attached it also keeps nzpy
    warnings away from ``logging.lastResort`` (stderr), which client UIs render.
    """
    handler = _DriverDiagnosticsHandler()
    logger = logging.getLogger(_NZPY_LOGGER_NAME)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        handler.close()


def classify_connection_failure(text: str) -> str:
    """Map raw driver text to a stable cause code; ``UNKNOWN`` when no rule matches."""
    lowered = text.lower()
    for cause, needles in _CAUSE_RULES:
        if any(needle in lowered for needle in needles):
            return cause
    return CAUSE_UNKNOWN


def _readable_diagnostics(messages: Sequence[str]) -> list[str]:
    """Normalize nzpy log messages: strip its prefix, drop breadcrumbs, de-duplicate."""
    out: list[str] = []
    for message in messages:
        # The server payload is NUL-terminated and nzpy hands it over verbatim.
        text = message.replace("\x00", " ").strip()
        if text.startswith(_SERVER_RESPONSE_PREFIX):
            text = text[len(_SERVER_RESPONSE_PREFIX) :].strip()
        text = " ".join(text.split())
        if not text or _CONTROL_FLOW_MARKER.match(text) or text in out:
            continue
        out.append(text)
    return out


def _build_failure_detail(exc: BaseException, messages: Sequence[str]) -> str:
    """Join the driver exception with the diagnostics it only ever logged."""
    exc_text = " ".join(str(exc).split())
    diagnostics = _readable_diagnostics(messages)
    if not diagnostics:
        return exc_text
    joined = "; ".join(diagnostics)
    return f"{exc_text}: {joined}" if exc_text else joined


def _connection_failure(
    profile: Profile,
    password: str,
    exc: BaseException,
    messages: Sequence[str],
) -> NzConnectionError:
    """Build the typed error: sanitized detail, stable cause, actionable ES/EN hints."""
    # Sanitize once, before the captured text reaches any message, log or hint.
    detail = sanitize(_build_failure_detail(exc, messages), known_secrets={password})
    cause = classify_connection_failure(detail)
    hints = both(
        f"CONNECTION_FAILED.HINT.{cause}",
        host=profile.host,
        port=profile.port,
        database=profile.database,
        user=profile.user,
    )
    return NzConnectionError(
        host=profile.host,
        port=profile.port,
        database=profile.database,
        user=profile.user,
        detail=detail,
        cause=cause,
        # Hints are built from profile fields only, but sanitize them too: a password
        # that happens to equal a profile value must not leak through this path.
        hint_es=sanitize(hints["es"], known_secrets={password}),
        hint_en=sanitize(hints["en"], known_secrets={password}),
    )


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
    with _capture_driver_diagnostics() as diagnostics:
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
            # nzpy may raise unchecked driver errors; we surface them as typed
            # ConnectionError for MCP, enriched with what it only logged.
            raise _connection_failure(profile, password, exc, diagnostics.messages) from exc
