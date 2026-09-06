"""Three-level validation ladder for a connection profile.

Used by ``nz-mcp test-connection`` (level 1 only) and by the ``init`` / ``add-profile``
wizard, which runs the whole ladder **before** writing anything to ``profiles.toml`` or
to the keyring. The password is always passed in, never read from the keyring: the
wizard validates a draft profile that does not exist on disk yet.

Levels, reported one by one so the user knows which one failed and what it means:

1. ``connect``          — open the session and read ``VERSION()``: credentials, network
   reachability and ``security_level`` negotiation.
2. ``catalog_read``     — list databases: the account can really read the catalog, not
   just authenticate.
3. ``default_database`` — list the schemas of the profile default database: the account
   sees at least one object there. Catches the silent failure of connecting fine while
   holding no grant on anything.

Every level reuses the registered catalog SQL (``resolve_query``), so profile-level
``catalog_overrides`` are honoured here exactly as they are by the MCP tools.

Two entry points, same ladder: :func:`run_checks` returns the finished report, and
:func:`iter_checks` hands the outcomes over one at a time so a caller can say what it is
waiting on before each level runs. Neither of them prints anything: this module grades,
the CLI decides how that looks.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass
from typing import Any, Final, Literal

from nz_mcp.catalog.identifier import render_cross_db
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.errors import NzMcpError
from nz_mcp.logging_utils import sanitize
from nz_mcp.secret import Secret

CheckLevel = Literal["connect", "catalog_read", "default_database"]
CheckStatus = Literal["ok", "failed", "empty", "skipped"]

CHECK_LEVELS: Final[tuple[CheckLevel, ...]] = ("connect", "catalog_read", "default_database")

VERSION_SQL: Final[str] = "SELECT CAST(VERSION() AS VARCHAR(200)) AS v"

_NO_PATTERN: Final[tuple[str | None, str | None]] = (None, None)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """Result of a single validation level.

    ``detail`` carries the technical reason (driver message, already sanitized); the
    caller wraps it in a localized explanation of what that level means.
    """

    level: CheckLevel
    status: CheckStatus
    detail: str = ""
    count: int = 0
    # Localized "what to do next" for a connect failure, straight from ConnectionError.
    # Empty for every other level and for successful checks.
    hint_es: str = ""
    hint_en: str = ""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    outcomes: tuple[CheckOutcome, ...]

    @property
    def ok(self) -> bool:
        return bool(self.outcomes) and all(o.status == "ok" for o in self.outcomes)

    @property
    def failure(self) -> CheckOutcome | None:
        """First level that did not pass, or ``None`` when every level passed."""
        return next((o for o in self.outcomes if o.status in ("failed", "empty")), None)


def run_checks(
    profile: Profile,
    password: str,
    *,
    levels: int = len(CHECK_LEVELS),
) -> ValidationReport:
    """Run the first ``levels`` checks over a single connection and report each one.

    Eager: every level runs before anything comes back. Callers that need to show what is
    happening *while* it happens use :func:`iter_checks` instead.

    The wizard passes a draft password that never reached the keyring, so it is re-bound
    to a ``Secret`` here for the same reason as in ``open_connection``: this function and
    every helper below it carries the credential as a frame argument (ADR 0026).
    """
    password = Secret(password)
    with contextlib.closing(iter_checks(profile, password, levels=levels)) as stream:
        return ValidationReport(tuple(stream))


def iter_checks(
    profile: Profile,
    password: str,
    *,
    levels: int = len(CHECK_LEVELS),
) -> Generator[CheckOutcome, None, None]:
    """Yield one outcome per level, resolving each level only when it is asked for.

    Laziness is the whole point. The connection level opens a TCP session, usually over a
    VPN, and can sit there until the driver times out; a caller that only gets the finished
    report has no moment at which to say "this is what I am waiting on". Pulling one outcome
    at a time gives it that moment, on the terminal or anywhere else, without this module
    knowing what a terminal is.

    Levels after a failure still come back, marked ``skipped``, and they resolve instantly:
    the sequence always has one entry per requested level.

    The connection is opened on the first ``next()`` and closed when the generator is
    exhausted or closed. Callers that may stop early should wrap it in
    ``contextlib.closing`` so the session does not wait for the garbage collector.
    """
    password = Secret(password)
    try:
        connection: Any = open_connection(profile, password)
    except NzConnectionError as exc:
        detail = str(exc.context.get("detail", "")) or str(exc)
        yield from _report_of_connect_failure(
            detail,
            levels,
            hint_es=str(exc.context.get("hint_es", "")),
            hint_en=str(exc.context.get("hint_en", "")),
        ).outcomes
        return
    try:
        yield from _iter_levels(connection, profile, password, levels)
    finally:
        with contextlib.suppress(Exception):  # pragma: no cover - driver-specific close
            connection.close()


def _iter_levels(
    connection: Any, profile: Profile, password: str, levels: int
) -> Iterator[CheckOutcome]:
    runners: tuple[Callable[[], CheckOutcome], ...] = (
        lambda: _check_connect(connection, password),
        lambda: _check_catalog_read(connection, profile, password),
        lambda: _check_default_database(connection, profile, password),
    )
    stopped = False
    for level, run in zip(CHECK_LEVELS[:levels], runners[:levels], strict=True):
        if stopped:
            yield CheckOutcome(level=level, status="skipped")
            continue
        try:
            outcome = run()
        except NzMcpError as exc:
            # Typed failures raised while building the SQL (unknown catalog override,
            # database name that cannot be interpolated) belong to the level that hit them.
            outcome = CheckOutcome(level=level, status="failed", detail=str(exc))
        yield outcome
        stopped = outcome.status != "ok"


def _report_of_connect_failure(
    detail: str, levels: int, *, hint_es: str = "", hint_en: str = ""
) -> ValidationReport:
    """Build a report where ``connect`` failed and the remaining levels are skipped."""
    head = CheckOutcome(
        level="connect", status="failed", detail=detail, hint_es=hint_es, hint_en=hint_en
    )
    tail = [CheckOutcome(level=level, status="skipped") for level in CHECK_LEVELS[1:levels]]
    return ValidationReport((head, *tail))


def _check_connect(connection: Any, password: str) -> CheckOutcome:
    try:
        with contextlib.closing(connection.cursor()) as cursor:
            cursor.execute(VERSION_SQL)
            row = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001, RUF100
        # Driver failures are not guaranteed to use a stable exception type.
        return CheckOutcome(level="connect", status="failed", detail=_safe(exc, password))
    version = str(row[0] or "").strip() if row is not None else ""
    return CheckOutcome(level="connect", status="ok", detail=version or "unknown")


def _check_catalog_read(connection: Any, profile: Profile, password: str) -> CheckOutcome:
    sql = render_cross_db(resolve_query("list_databases", profile), database=profile.database)
    return _count_rows(connection, sql, password, level="catalog_read")


def _check_default_database(connection: Any, profile: Profile, password: str) -> CheckOutcome:
    sql = render_cross_db(resolve_query("list_schemas", profile), database=profile.database)
    return _count_rows(connection, sql, password, level="default_database")


def _count_rows(connection: Any, sql: str, password: str, *, level: CheckLevel) -> CheckOutcome:
    """Run a catalog query and grade it: rows -> ok, no rows -> empty, error -> failed."""
    try:
        with contextlib.closing(connection.cursor()) as cursor:
            cursor.execute(sql, _NO_PATTERN)
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        # Catalog failures are not guaranteed to use a stable exception type.
        return CheckOutcome(level=level, status="failed", detail=_safe(exc, password))
    count = len(list(rows))
    if count == 0:
        return CheckOutcome(level=level, status="empty")
    return CheckOutcome(level=level, status="ok", count=count)


def _safe(exc: Exception, password: str) -> str:
    return sanitize(str(exc), known_secrets={password})
