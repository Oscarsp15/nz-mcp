"""Command-line interface — typer.

Commands:
- ``init``               first-time wizard: creates the first profile.
- ``add-profile``        add another profile.
- ``list-profiles``      list configured profiles.
- ``edit-profile``       update an existing profile (mode, database, limits).
- ``doctor``             print local diagnostics (no Netezza connection).
- ``probe-catalog``      execute every catalog query with dummy parameters (validates overrides).
- ``test-connection``    verify the active profile (opens Netezza, runs ``VERSION()``).
- ``serve``              run the MCP server over stdio.
- ``version``            print the package version.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, cast

import typer

from nz_mcp import __version__
from nz_mcp.auth import get_password, store_password
from nz_mcp.catalog.probe import probe_has_hard_failure, probe_run_to_json_dict, run_probe_catalog
from nz_mcp.config import (
    DEFAULT_MAX_ROWS,
    DEFAULT_TIMEOUT_S,
    PermissionMode,
    config_dir,
    get_active_profile,
    get_profile,
    list_profile_names,
    profiles_path,
    update_profile_fields,
)
from nz_mcp.connection import open_connection
from nz_mcp.diagnostic import collect_diagnostic, format_diagnostic_report
from nz_mcp.errors import (
    ConnectionError,
    CredentialNotFoundError,
    InvalidProfileError,
    KeyringUnavailableError,
    ProfileNotFoundError,
)
from nz_mcp.i18n import MESSAGES, resolve_locale, t
from nz_mcp.logging_config import configure_logging_for_stdio
from nz_mcp.logging_utils import sanitize
from nz_mcp.server import run_stdio_server

app = typer.Typer(
    name="nz-mcp",
    help="MCP server for IBM Netezza Performance Server.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("version")
def version_cmd() -> None:
    """Print the installed nz-mcp version."""
    typer.echo(__version__)


@app.command("init")
def init_cmd() -> None:
    """Interactive wizard: create the first profile."""
    typer.secho("nz-mcp init", bold=True)
    typer.echo("Esto crea el primer perfil. Las credenciales irán a tu keyring del SO.")
    name = typer.prompt("Nombre del perfil", default="default")
    _add_profile_interactive(name=name, set_active=True)


@app.command("add-profile")
def add_profile_cmd(
    name: str = typer.Argument(..., help="Profile name"),
    set_active: bool = typer.Option(
        False,
        "--active/--no-active",
        help="Mark the new profile as active",
    ),
) -> None:
    """Add a new profile (interactive)."""
    _add_profile_interactive(name=name, set_active=set_active)


@app.command("list-profiles")
def list_profiles_cmd() -> None:
    """List configured profile names."""
    names = list_profile_names()
    if not names:
        typer.echo("(sin perfiles configurados — usa: nz-mcp init)")
        raise typer.Exit(code=0)
    for n in names:
        typer.echo(n)


@app.command("edit-profile")
def edit_profile_cmd(
    name: str = typer.Argument(..., help="Existing profile name"),
    mode: str | None = typer.Option(None, "--mode", help="read | write | admin"),
    database: str | None = typer.Option(None, "--database", help="Default database"),
    max_rows_default: int | None = typer.Option(None, "--max-rows-default"),
    timeout_s_default: int | None = typer.Option(None, "--timeout-s-default"),
) -> None:
    """Update fields of an existing profile (password stays in the OS keyring)."""
    locale = resolve_locale()
    if mode is not None and mode.strip().lower() not in ("read", "write", "admin"):
        typer.secho("Invalid --mode: use read | write | admin.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    pm: PermissionMode | None = cast(PermissionMode, mode.strip().lower()) if mode else None
    try:
        result = update_profile_fields(
            name,
            mode=pm,
            database=database,
            max_rows_default=max_rows_default,
            timeout_s_default=timeout_s_default,
        )
    except ProfileNotFoundError as exc:
        typer.secho(_format_profile_not_found_cli(locale, exc), err=True)
        raise typer.Exit(code=1) from exc
    if result is None:
        typer.echo(
            "No changes: pass at least one of --mode, --database, "
            "--max-rows-default, --timeout-s-default.",
        )
        raise typer.Exit(code=0)
    typer.secho(f"Updated profile '{result.name}' (mode={result.mode}).", fg=typer.colors.GREEN)
    raise typer.Exit(code=0)


@app.command("doctor")
def doctor_cmd() -> None:
    """Print local diagnostics (package, Python, profiles metadata, keyring) — no Netezza."""
    report = collect_diagnostic()
    locale = resolve_locale()
    typer.echo(format_diagnostic_report(report, locale=locale))
    raise typer.Exit(code=0 if report.is_healthy else 1)


@app.command("probe-catalog")
def probe_catalog_cmd(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile name (default: active)",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    """Run every registered catalog query with dummy parameters against Netezza."""
    locale = resolve_locale()
    try:
        prof = get_profile(profile) if profile is not None else get_active_profile()
    except ProfileNotFoundError as exc:
        typer.secho(_format_profile_not_found_cli(locale, exc), err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProfileError as exc:
        typer.secho(t("INVALID_CONFIG", locale, detail=str(exc)), err=True)
        raise typer.Exit(code=1) from exc

    run = run_probe_catalog(prof)
    if as_json:
        typer.echo(json.dumps(probe_run_to_json_dict(run), indent=2, ensure_ascii=False))
    else:
        typer.secho(t("PROBE_CATALOG.HEADER", locale, profile=run.profile_name), bold=True)
        if run.config_error is not None:
            typer.secho(
                t("PROBE_CATALOG.CONFIG_ERROR", locale, detail=run.config_error),
                fg=typer.colors.RED,
                err=True,
            )
        for row in run.results:
            if row.status == "ok":
                ms = row.duration_ms if row.duration_ms is not None else 0.0
                rc = row.row_count if row.row_count is not None else 0
                typer.echo(
                    t("PROBE_CATALOG.LINE_OK", locale, query_id=row.query_id, ms=ms, rows=rc),
                )
            elif row.status == "structural_warning":
                detail = row.error_detail or ""
                typer.secho(
                    t("PROBE_CATALOG.LINE_WARN", locale, query_id=row.query_id, detail=detail),
                    fg=typer.colors.YELLOW,
                )
            else:
                parts = []
                if row.detail:
                    parts.append(row.detail)
                if row.error_detail:
                    parts.append(row.error_detail)
                detail = " — ".join(parts) if parts else "error"
                typer.secho(
                    t("PROBE_CATALOG.LINE_FAIL", locale, query_id=row.query_id, detail=detail),
                    fg=typer.colors.RED,
                    err=True,
                )

    code = 0 if not probe_has_hard_failure(run) else 1
    raise typer.Exit(code=code)


_VERSION_SQL = "SELECT CAST(VERSION() AS VARCHAR(200)) AS v"


@app.command("test-connection")
def test_connection_cmd(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Profile to test (defaults to active profile)"
    ),
) -> None:
    """Verify connectivity: open Netezza, run ``VERSION()``, report OK or FAIL (exit 0/1)."""
    locale = resolve_locale()
    try:
        prof = get_profile(profile) if profile is not None else get_active_profile()
    except ProfileNotFoundError as exc:
        typer.secho(_format_profile_not_found_cli(locale, exc), err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProfileError as exc:
        typer.secho(t("INVALID_CONFIG", locale, detail=str(exc)), err=True)
        raise typer.Exit(code=1) from exc

    try:
        password = get_password(prof.name)
    except (CredentialNotFoundError, KeyringUnavailableError) as exc:
        detail = sanitize(str(exc), known_secrets=())
        typer.secho(f"FAIL: {detail}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    try:
        conn: Any = open_connection(prof, password)
    except ConnectionError as exc:
        detail = str(exc.context.get("detail", "")) or str(exc)
        typer.secho(f"FAIL: {detail}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    try:
        with contextlib.closing(conn.cursor()) as cur:
            cur.execute(_VERSION_SQL)
            row = cur.fetchone()
    except Exception as exc:
        detail = sanitize(str(exc), known_secrets={password})
        typer.secho(f"FAIL: {detail}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    finally:
        with contextlib.suppress(Exception):  # pragma: no cover - driver-specific close
            conn.close()

    version_text = "unknown"
    if row is not None:
        version_text = str(row[0] or "").strip()
    typer.secho(f"OK: connected to {version_text} as {prof.user}", fg=typer.colors.GREEN)
    raise typer.Exit(code=0)


@app.command("serve")
def serve_cmd() -> None:
    """Run the MCP server over stdio."""
    configure_logging_for_stdio()
    run_stdio_server()


# --- helpers ------------------------------------------------------------------


def _format_profile_not_found_cli(locale: str, exc: ProfileNotFoundError) -> str:
    pnf = MESSAGES["PROFILE_NOT_FOUND"]
    if locale == "es":
        return pnf["es"].format(
            profile=exc.context["profile"],
            hint_es=str(exc.context.get("hint_es", "")),
        )
    return pnf["en"].format(
        profile=exc.context["profile"],
        hint_en=str(exc.context.get("hint_en", "")),
    )


def _add_profile_interactive(*, name: str, set_active: bool) -> None:
    host = typer.prompt("Host Netezza")
    port = typer.prompt("Puerto", default=5480, type=int)
    database = typer.prompt("Base de datos por defecto")
    user = typer.prompt("Usuario")
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    mode = cast(
        PermissionMode,
        typer.prompt(
            "Modo (read|write|admin)",
            default="read",
            show_choices=False,
        )
        .strip()
        .lower(),
    )
    if mode not in ("read", "write", "admin"):
        typer.secho(
            f"Modo inválido: {mode!r}. Use read|write|admin.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    _ensure_config_dir()
    _write_profile(
        name=name,
        host=host,
        port=int(port),
        database=database,
        user=user,
        mode=mode,
        set_active=set_active,
    )
    store_password(name, password)
    typer.secho(f"Perfil '{name}' guardado en {profiles_path()}", fg=typer.colors.GREEN)


def _ensure_config_dir() -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):  # pragma: no cover - Windows ACLs differ
        cfg.chmod(0o700)


def _write_profile(
    *,
    name: str,
    host: str,
    port: int,
    database: str,
    user: str,
    mode: PermissionMode,
    set_active: bool,
) -> None:
    target = profiles_path()
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    block = (
        f"\n[profiles.{name}]\n"
        f'host = "{host}"\n'
        f"port = {port}\n"
        f'database = "{database}"\n'
        f'user = "{user}"\n'
        f'mode = "{mode}"\n'
        f"max_rows_default = {DEFAULT_MAX_ROWS}\n"
        f"timeout_s_default = {DEFAULT_TIMEOUT_S}\n"
    )
    new_content = existing + block
    if set_active:
        active_line = f'active = "{name}"\n'
        new_content = active_line + new_content if "active = " not in new_content else new_content
    _atomic_write(target, new_content)
    with contextlib.suppress(OSError):  # pragma: no cover - Windows ACLs differ
        target.chmod(0o600)


def _atomic_write(target: Path, content: str) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)
