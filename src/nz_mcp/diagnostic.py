"""Local environment diagnostics for ``nz-mcp doctor`` (no network, no Netezza).

Collects non-sensitive metadata only: never hostnames, usernames, passwords, or keyring secrets.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

import keyring
from keyring.backends.fail import Keyring as FailKeyring
from pydantic import BaseModel, ConfigDict

from nz_mcp import __version__
from nz_mcp.config import (
    config_dir,
    load_profiles_file,
    profiles_path,
    single_profile_name_or_none,
)
from nz_mcp.errors import InvalidProfileError
from nz_mcp.i18n import Locale, resolve_locale, t


class DiagnosticReport(BaseModel):
    """Structured diagnostic data (safe to JSON-serialize; no credentials)."""

    model_config = ConfigDict(frozen=True)

    nz_mcp_version: str
    python_version: str
    platform: str
    config_dir: str
    config_dir_exists: bool
    config_dir_writable: bool
    profiles_path: str
    profiles_path_exists: bool
    profiles_load_ok: bool
    profiles_count: int
    profiles_names: tuple[str, ...]
    active_profile: str | None
    keyring_backend: str
    keyring_available: bool
    locale: Locale

    @property
    def is_healthy(self) -> bool:
        """False when a critical local setup issue is detected."""
        return self.config_dir_writable and self.keyring_available


def _writable_dir(path: Path) -> bool:
    """Return whether ``path`` can be used as a writable config directory."""
    try:
        target = path.expanduser().resolve()
    except OSError:
        return False
    cur: Path = target
    while True:
        if cur.exists():
            return cur.is_dir() and os.access(cur, os.W_OK)
        if cur.parent == cur:
            return False
        cur = cur.parent


def _probe_keyring() -> tuple[str, bool]:
    """Return ``(backend_class_name, available)`` using a non-destructive probe."""
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001, RUF100
        # Keyring backends may raise vendor/runtime-specific errors while being resolved.
        # The diagnostic command must degrade gracefully and never crash on local probing.
        return ("<unavailable>", False)
    name = backend.__class__.__name__
    if isinstance(backend, FailKeyring):
        return (name, False)
    return (name, True)


def collect_diagnostic(
    *,
    profiles_file: Path | None = None,
    config_dir_override: Path | None = None,
) -> DiagnosticReport:
    """Gather diagnostic fields without printing or touching Netezza.

    Parameters are for tests; production uses ``config_dir()`` / ``profiles_path()``.
    """
    cfg = (config_dir_override or config_dir()).expanduser().resolve()
    pp = profiles_file if profiles_file is not None else profiles_path()
    pp = pp.expanduser().resolve()

    loc = resolve_locale()
    py_ver = ".".join(str(x) for x in sys.version_info[:3])
    plat = platform.platform()

    profiles_load_ok = True
    profiles_count = 0
    profiles_names: tuple[str, ...] = ()
    active_profile: str | None = None

    if pp.exists():
        try:
            data = load_profiles_file(pp)
        except InvalidProfileError:
            profiles_load_ok = False
        else:
            profiles_count = len(data.profiles)
            profiles_names = tuple(sorted(data.profiles.keys()))
            active_profile = (
                data.active or os.environ.get("NZ_MCP_PROFILE") or single_profile_name_or_none(data)
            )

    kr_name, kr_ok = _probe_keyring()

    return DiagnosticReport(
        nz_mcp_version=__version__,
        python_version=py_ver,
        platform=plat,
        config_dir=str(cfg),
        config_dir_exists=cfg.exists(),
        config_dir_writable=_writable_dir(cfg),
        profiles_path=str(pp),
        profiles_path_exists=pp.exists(),
        profiles_load_ok=profiles_load_ok,
        profiles_count=profiles_count,
        profiles_names=profiles_names,
        active_profile=active_profile,
        keyring_backend=kr_name,
        keyring_available=kr_ok,
        locale=loc,
    )


def format_diagnostic_report(report: DiagnosticReport, *, locale: Locale | None = None) -> str:
    """Render a human-readable, localized table (no secrets)."""
    loc = resolve_locale(locale)

    def lbl(key: str) -> str:
        return t(key, loc)

    yes = lbl("DOCTOR.BOOL_YES")
    no = lbl("DOCTOR.BOOL_NO")

    def yn(b: bool) -> str:
        return yes if b else no

    lines = [
        lbl("DOCTOR.HEADER"),
        "",
        f"{lbl('DOCTOR.LABEL.NZ_MCP_VERSION')}: {report.nz_mcp_version}",
        f"{lbl('DOCTOR.LABEL.PYTHON_VERSION')}: {report.python_version}",
        f"{lbl('DOCTOR.LABEL.PLATFORM')}: {report.platform}",
        f"{lbl('DOCTOR.LABEL.CONFIG_DIR')}: {report.config_dir}",
        f"  {lbl('DOCTOR.LABEL.EXISTS')}: {yn(report.config_dir_exists)}",
        f"  {lbl('DOCTOR.LABEL.WRITABLE')}: {yn(report.config_dir_writable)}",
        f"{lbl('DOCTOR.LABEL.PROFILES_PATH')}: {report.profiles_path}",
        f"  {lbl('DOCTOR.LABEL.EXISTS')}: {yn(report.profiles_path_exists)}",
        f"{lbl('DOCTOR.LABEL.PROFILES_LOAD_OK')}: {yn(report.profiles_load_ok)}",
        f"{lbl('DOCTOR.LABEL.PROFILES_COUNT')}: {report.profiles_count}",
        (
            f"{lbl('DOCTOR.LABEL.PROFILES_NAMES')}: "
            f"{', '.join(report.profiles_names) or lbl('DOCTOR.NONE')}"
        ),
        f"{lbl('DOCTOR.LABEL.ACTIVE_PROFILE')}: {report.active_profile or lbl('DOCTOR.NONE')}",
        f"{lbl('DOCTOR.LABEL.KEYRING_BACKEND')}: {report.keyring_backend}",
        f"  {lbl('DOCTOR.LABEL.AVAILABLE')}: {yn(report.keyring_available)}",
        f"{lbl('DOCTOR.LABEL.LOCALE')}: {report.locale}",
    ]

    if not report.is_healthy:
        lines.extend(["", lbl("DOCTOR.CRITICAL_HEADER")])
        if not report.config_dir_writable:
            lines.append(f"- {lbl('DOCTOR.CRITICAL.CONFIG_DIR_NOT_WRITABLE')}")
        if not report.keyring_available:
            lines.append(f"- {lbl('DOCTOR.CRITICAL.KEYRING_UNAVAILABLE')}")

    return "\n".join(lines)


def report_json_for_audit(report: DiagnosticReport) -> str:
    """JSON snapshot for tests (ensures no accidental sensitive fields)."""
    return json.dumps(report.model_dump(mode="json"), sort_keys=True)
