"""Best-effort notice when a newer ``nz-mcp`` release is published on PyPI.

The check runs once at server startup, in a daemon thread, with a short timeout, so it
never delays or blocks the MCP handshake. It writes at most one line, on **stderr**,
through :mod:`nz_mcp.cli_output`: stdout is the JSON-RPC channel of ``serve`` and a single
byte there breaks the protocol (ADR 0027, addendum 1; ADR 0037).

Failure is silence by design. Offline, a timeout, a proxy error or an unexpected payload
must produce no output, no traceback and no log line: the alternative would turn "PyPI is
down" into "the MCP server misbehaves". The result is cached for :data:`_CACHE_TTL_S` in
the config directory so several restarts a day do not hit PyPI every time.

This module is not part of the tool catalog: it registers no tool, touches no SQL and is
never reachable through ``tools/call``.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Final
from urllib.request import urlopen

from packaging.version import InvalidVersion, Version

from nz_mcp import __version__
from nz_mcp import cli_output as out
from nz_mcp.config import config_dir
from nz_mcp.i18n import Locale, resolve_locale, t

#: Opt-out. Any value counts as *yes* except the two that conventionally mean "no", so
#: ``NZ_MCP_NO_UPDATE_CHECK=1`` does the obvious thing and ``=0`` does not (ADR 0037,
#: same spelling rule as ``NZ_MCP_NO_CONSOLE_PREP``).
NO_UPDATE_CHECK_ENV: Final[str] = "NZ_MCP_NO_UPDATE_CHECK"

_PACKAGE_NAME: Final[str] = "nz-mcp"
_PYPI_JSON_URL: Final[str] = f"https://pypi.org/pypi/{_PACKAGE_NAME}/json"
_CACHE_FILE_NAME: Final[str] = "update-check.json"

#: One day. The check is a courtesy, not a security control, so asking PyPI more often
#: buys nothing and costs a network round trip on every server start.
_CACHE_TTL_S: Final[float] = 24 * 60 * 60

#: Short on purpose: this must never be felt at startup. A VPN-less or offline machine
#: gives up here and says nothing.
_TIMEOUT_S: Final[float] = 1.5

_FALSE_SPELLINGS: Final[frozenset[str]] = frozenset({"", "0", "false", "no"})


def _disabled() -> bool:
    value = os.environ.get(NO_UPDATE_CHECK_ENV, "").strip().lower()
    return value not in _FALSE_SPELLINGS


def installed_version() -> str:
    """Version of the running distribution, or the packaged constant when not installed.

    ``importlib.metadata`` is what ``uv tool`` / ``pip`` actually installed; running from a
    source checkout there is no distribution metadata, so the constant in the package wins.
    """
    try:
        return metadata.version(_PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return __version__


def _parse_latest(payload: object) -> str | None:
    """Highest published version in a PyPI JSON document, or ``None``.

    Reads ``releases`` **and** ``info.version``: the first lists every upload (pre-releases
    included, which is what an alpha project needs), the second is what PyPI calls latest.
    ``packaging`` orders the candidates, so ``0.1.0a10`` beats ``0.1.0a4``.
    """
    if not isinstance(payload, dict):
        return None
    candidates: list[str] = []
    releases = payload.get("releases")
    if isinstance(releases, dict):
        candidates.extend(key for key in releases if isinstance(key, str))
    info = payload.get("info")
    if isinstance(info, dict):
        version = info.get("version")
        if isinstance(version, str):
            candidates.append(version)
    parsed: list[Version] = []
    for candidate in candidates:
        with contextlib.suppress(InvalidVersion):
            parsed.append(Version(candidate))
    return str(max(parsed)) if parsed else None


def _fetch_latest(url: str = _PYPI_JSON_URL, *, timeout: float = _TIMEOUT_S) -> str | None:
    """Ask PyPI for the latest version, or return ``None`` on any failure.

    ``OSError`` covers the whole connection family (``URLError``, DNS, timeout, TLS);
    ``ValueError`` covers a body that is not JSON or not UTF-8. Both mean the same thing
    here: not knowing, which is never worth a message.
    """
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - constant https URL
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return _parse_latest(payload)


def _cache_path() -> Path:
    return config_dir() / _CACHE_FILE_NAME


def _read_cache(path: Path) -> tuple[float, str | None] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    checked_at = raw.get("checked_at")
    latest = raw.get("latest")
    if not isinstance(checked_at, int | float) or isinstance(checked_at, bool):
        return None
    if latest is not None and not isinstance(latest, str):
        return None
    return float(checked_at), latest


def _write_cache(path: Path, *, checked_at: float, latest: str | None) -> None:
    """Persist the result. A read-only or missing config directory is not an error."""
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"checked_at": checked_at, "latest": latest}),
            encoding="utf-8",
        )


def latest_version(
    *,
    now: float | None = None,
    cache_path: Path | None = None,
    fetch: Callable[[], str | None] | None = None,
) -> str | None:
    """Latest known version, from the cache when it is fresh and from PyPI otherwise.

    ``now`` and ``fetch`` are injected so the TTL and the network can be tested without
    sleeping and without a socket.
    """
    moment = time.time() if now is None else now
    path = _cache_path() if cache_path is None else cache_path
    cached = _read_cache(path)
    if cached is not None:
        checked_at, latest = cached
        if moment - checked_at < _CACHE_TTL_S:
            return latest
    fetched = (fetch or _fetch_latest)()
    _write_cache(path, checked_at=moment, latest=fetched)
    return fetched


def update_notice(installed: str, latest: str | None, locale: Locale) -> str | None:
    """The one-line notice when ``latest`` is newer than ``installed``, else ``None``.

    Equal versions and an unparseable one are silence: this exists to announce an upgrade,
    not to grade what is installed.
    """
    if latest is None:
        return None
    try:
        newer = Version(latest) > Version(installed)
    except InvalidVersion:
        return None
    if not newer:
        return None
    return t("CLI.UPDATE_AVAILABLE", locale, installed=installed, latest=latest)


def run_update_check(*, locale: Locale | None = None) -> None:
    """Check, and write the notice on stderr if there is one. Never raises.

    Every failure mode of a network call in a program whose stdout is a protocol channel
    has to end in silence, so the exceptions that can still escape the helpers are caught
    here explicitly instead of with a blanket ``except Exception`` (coding.md).
    """
    if _disabled():
        return
    try:
        notice = update_notice(installed_version(), latest_version(), resolve_locale(locale))
    except (OSError, ValueError, KeyError, TypeError):
        return
    if notice is not None:
        out.warn(notice)


def start_update_check() -> None:
    """Run :func:`run_update_check` in a daemon thread, off the startup path.

    Daemon so a slow or hanging lookup can never keep the interpreter alive at shutdown;
    the MCP handshake proceeds while this happens and does not wait for it.
    """
    if _disabled():
        return
    threading.Thread(
        target=run_update_check,
        name="nz-mcp-update-check",
        daemon=True,
    ).start()


__all__: Final[tuple[str, ...]] = (
    "NO_UPDATE_CHECK_ENV",
    "installed_version",
    "latest_version",
    "run_update_check",
    "start_update_check",
    "update_notice",
)
