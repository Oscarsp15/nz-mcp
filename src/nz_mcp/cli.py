"""Command-line interface — typer.

Commands:
- ``init``               first-time wizard: creates the first profile.
- ``add-profile``        add another profile.
- ``remove-profile``     delete a profile and its keyring password.
- ``list-profiles``      list configured profiles.
- ``switch-profile``     make an existing profile the active one.
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
from dataclasses import dataclass
from typing import Any, Final, cast

import typer

from nz_mcp import __version__
from nz_mcp.auth import delete_password, get_password, store_password
from nz_mcp.catalog.probe import probe_has_hard_failure, probe_run_to_json_dict, run_probe_catalog
from nz_mcp.config import (
    DEFAULT_MAX_ROWS,
    DEFAULT_PORT,
    DEFAULT_SECURITY_LEVEL,
    DEFAULT_TIMEOUT_S,
    MAX_SECURITY_LEVEL,
    MIN_SECURITY_LEVEL,
    PermissionMode,
    Profile,
    ProfilesFile,
    config_dir,
    get_active_profile,
    get_profile,
    list_profile_names,
    load_profiles_file,
    profiles_path,
    remove_profile,
    update_profile_fields,
    upsert_profile,
)
from nz_mcp.diagnostic import collect_diagnostic, format_diagnostic_report
from nz_mcp.errors import (
    CredentialNotFoundError,
    InvalidProfileError,
    KeyringUnavailableError,
    ProfileNotFoundError,
)
from nz_mcp.i18n import MESSAGES, Locale, resolve_locale, t
from nz_mcp.logging_config import configure_logging_for_stdio
from nz_mcp.logging_utils import sanitize
from nz_mcp.profile_check import CheckOutcome, ValidationReport, run_checks
from nz_mcp.secret import Secret
from nz_mcp.server import run_stdio_server
from nz_mcp.tools.session import SwitchProfileInput, nz_switch_profile

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
    locale = resolve_locale()
    typer.secho("nz-mcp init", bold=True)
    typer.echo(t("CLI.INIT_INTRO", locale))
    name = str(typer.prompt(t("CLI.INIT_NAME_PROMPT", locale), default="default"))
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


@app.command("remove-profile")
def remove_profile_cmd(
    name: str = typer.Argument(..., help="Profile name to delete"),
) -> None:
    """Delete a profile from profiles.toml and its password from the OS keyring."""
    locale = resolve_locale()
    file = _load_profiles_or_exit(locale)
    if name not in file.profiles:
        exc = _profile_not_found(name, list(file.profiles))
        typer.secho(_format_profile_not_found_cli(locale, exc), err=True)
        raise typer.Exit(code=1)
    prompt = t("CLI.PROFILE_REMOVE_CONFIRM", locale, profile=name, path=profiles_path())
    if not typer.confirm(prompt, default=False):
        typer.secho(t("CLI.PROFILE_REMOVE_CANCELLED", locale, profile=name), fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)
    _delete_password_or_warn(name, locale)
    was_active = remove_profile(name)
    typer.secho(
        t("CLI.PROFILE_REMOVED", locale, profile=name, path=profiles_path()),
        fg=typer.colors.GREEN,
    )
    if was_active:
        typer.secho(
            t("CLI.ACTIVE_PROFILE_CLEARED", locale, path=profiles_path()),
            fg=typer.colors.YELLOW,
        )
    raise typer.Exit(code=0)


@app.command("list-profiles")
def list_profiles_cmd() -> None:
    """List configured profile names."""
    names = list_profile_names()
    if not names:
        typer.echo("(sin perfiles configurados — usa: nz-mcp init)")
        raise typer.Exit(code=0)
    for n in names:
        typer.echo(n)


@app.command("switch-profile")
def switch_profile_cmd(
    name: str = typer.Argument(..., help="Existing profile name to activate"),
) -> None:
    """Make an existing profile the active one (same logic as the nz_switch_profile tool)."""
    locale = resolve_locale()
    try:
        # Single source of truth: the CLI delegates to the MCP tool instead of
        # re-implementing "validate the name, then persist active=..." on its own.
        result = nz_switch_profile(SwitchProfileInput(profile=name))
    except ProfileNotFoundError as exc:
        typer.secho(_format_profile_not_found_cli(locale, exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProfileError as exc:
        typer.secho(t("INVALID_CONFIG", locale, detail=str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.secho(
        t("CLI.PROFILE_SWITCHED", locale, profile=result.switched_to, mode=result.mode),
        fg=typer.colors.GREEN,
    )
    raise typer.Exit(code=0)


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

    # Level 1 of the validation ladder the wizard also runs (profile_check.run_checks).
    outcome = run_checks(prof, password, levels=1).outcomes[0]
    if outcome.status != "ok":
        typer.secho(f"FAIL: {outcome.detail}", fg=typer.colors.RED, err=True)
        hint = outcome.hint_es if locale == "es" else outcome.hint_en
        if hint:
            typer.secho(f"HINT: {hint}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"OK: connected to {outcome.detail} as {prof.user}", fg=typer.colors.GREEN)
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


def _profile_not_found(name: str, available: list[str]) -> ProfileNotFoundError:
    """Build a ProfileNotFoundError whose hint lists the profiles that do exist."""
    joined = ", ".join(sorted(available))
    return ProfileNotFoundError(
        profile=name,
        hint_es=f" Perfiles existentes: {joined}." if joined else "",
        hint_en=f" Existing profiles: {joined}." if joined else "",
    )


def _load_profiles_or_exit(locale: Locale) -> ProfilesFile:
    """Load profiles.toml, exiting with an actionable message when it cannot be parsed."""
    try:
        return load_profiles_file()
    except InvalidProfileError as exc:
        typer.secho(t("INVALID_CONFIG", locale, detail=str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def _confirm_overwrite_or_exit(name: str, locale: Locale) -> None:
    """Ask before replacing an existing profile; abort (exit 1) unless confirmed."""
    typer.secho(
        t("CLI.PROFILE_ALREADY_EXISTS", locale, profile=name, path=profiles_path()),
        fg=typer.colors.YELLOW,
    )
    if not typer.confirm(t("CLI.PROFILE_OVERWRITE_CONFIRM", locale), default=False):
        typer.secho(
            t("CLI.PROFILE_OVERWRITE_CANCELLED", locale, profile=name),
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)


def _delete_password_or_warn(name: str, locale: Locale) -> None:
    """Drop the keyring entry; a broken keyring must not block removing the profile."""
    try:
        delete_password(name)
    except KeyringUnavailableError as exc:
        detail = sanitize(str(exc), known_secrets=())
        typer.secho(
            t("CLI.PROFILE_PASSWORD_DELETE_FAILED", locale, profile=name, detail=detail),
            fg=typer.colors.YELLOW,
            err=True,
        )
        return
    typer.echo(t("CLI.PROFILE_PASSWORD_DELETED", locale, profile=name))


@dataclass
class _ProfileDraft:
    """Everything the wizard collected, held in memory until validation is settled.

    A failed validation must never discard what the user already typed: the draft is
    what makes "retry", "fix one field" and "save anyway" possible without asking for
    the rest again. ``password`` is part of the draft so it can be corrected too, but
    it is never written to profiles.toml — it goes to the OS keyring.

    ``password`` is a ``Secret`` so that the draft, which is a frame argument of half the
    wizard, cannot print the credential in a traceback or in a dataclass repr (ADR 0026).
    """

    host: str
    port: int
    database: str
    user: str
    password: Secret
    mode: PermissionMode
    security_level: int
    ca_certs: str | None


_MODES: Final[tuple[str, ...]] = ("read", "write", "admin")
_DRAFT_FIELDS: Final[tuple[str, ...]] = (
    "host",
    "port",
    "database",
    "user",
    "password",
    "mode",
    "security_level",
    "ca_certs",
)


def _add_profile_interactive(*, name: str, set_active: bool) -> None:
    locale = resolve_locale()
    file = _load_profiles_or_exit(locale)
    if name in file.profiles:
        _confirm_overwrite_or_exit(name, locale)
    previous = file.profiles.get(name, {})
    typer.echo(t("CLI.WIZARD_INTRO", locale, profile=name))
    draft = _prompt_draft(locale, previous)

    if not _validate_before_saving(name, draft, previous, locale):
        typer.secho(
            t("CLI.WIZARD_CANCELLED", locale, path=profiles_path()),
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    _ensure_config_dir()
    _write_profile(name=name, draft=draft, set_active=set_active)
    store_password(name, draft.password)
    typer.secho(
        t("CLI.PROFILE_SAVED", locale, profile=name, path=profiles_path()),
        fg=typer.colors.GREEN,
    )
    typer.echo(t("CLI.PROFILE_NEXT_STEP", locale, profile=name))
    typer.echo(t("CLI.CLAUDE_CONFIG_HEADER", locale))
    typer.echo(_claude_desktop_snippet(name))
    typer.echo(t("CLI.PROBE_SUGGESTION", locale, profile=name))


# --- wizard prompts (one explanation per non-obvious concept) ------------------


def _prompt_draft(locale: Locale, previous: dict[str, object]) -> _ProfileDraft:
    """Ask for every field, defaulting to the current value when overwriting a profile."""
    return _ProfileDraft(
        host=typer.prompt(t("CLI.WIZARD_HOST_PROMPT", locale), default=_text(previous, "host")),
        port=_prompt_port(locale, _number(previous, "port", DEFAULT_PORT)),
        database=_prompt_database(locale, _text(previous, "database")),
        user=typer.prompt(t("CLI.WIZARD_USER_PROMPT", locale), default=_text(previous, "user")),
        password=_prompt_password(locale),
        mode=_prompt_mode(locale, str(previous.get("mode") or "read")),
        security_level=_prompt_security_level(
            locale, _number(previous, "security_level", DEFAULT_SECURITY_LEVEL)
        ),
        ca_certs=_prompt_ca_certs(locale, _text(previous, "ca_certs")),
    )


def _text(previous: dict[str, object], key: str) -> str | None:
    value = previous.get(key)
    return str(value) if isinstance(value, str) and value else None


def _number(previous: dict[str, object], key: str, fallback: int) -> int:
    value = previous.get(key)
    return value if isinstance(value, int) else fallback


def _prompt_port(locale: Locale, default: int) -> int:
    return int(typer.prompt(t("CLI.WIZARD_PORT_PROMPT", locale), default=default, type=int))


def _prompt_database(locale: Locale, default: str | None) -> str:
    typer.echo(t("CLI.WIZARD_DATABASE_EXPLAIN", locale))
    return str(typer.prompt(t("CLI.WIZARD_DATABASE_PROMPT", locale), default=default))


def _prompt_password(locale: Locale) -> Secret:
    typer.echo(t("CLI.WIZARD_PASSWORD_EXPLAIN", locale))
    return Secret(
        typer.prompt(
            t("CLI.WIZARD_PASSWORD_PROMPT", locale),
            hide_input=True,
            confirmation_prompt=True,
        )
    )


def _prompt_mode(locale: Locale, default: str) -> PermissionMode:
    typer.echo(t("CLI.WIZARD_MODE_EXPLAIN", locale))
    while True:
        raw = str(
            typer.prompt(t("CLI.WIZARD_MODE_PROMPT", locale), default=default, show_choices=False)
        )
        value = raw.strip().lower()
        if value in _MODES:
            return cast(PermissionMode, value)
        typer.secho(t("CLI.WIZARD_MODE_INVALID", locale, value=raw), fg=typer.colors.RED, err=True)


def _prompt_security_level(locale: Locale, default: int) -> int:
    typer.echo(t("CLI.WIZARD_SECURITY_EXPLAIN", locale))
    while True:
        raw = str(typer.prompt(t("CLI.WIZARD_SECURITY_PROMPT", locale), default=str(default)))
        value = raw.strip()
        if value.isdigit() and MIN_SECURITY_LEVEL <= int(value) <= MAX_SECURITY_LEVEL:
            return int(value)
        typer.secho(
            t("CLI.WIZARD_SECURITY_INVALID", locale, value=raw), fg=typer.colors.RED, err=True
        )


def _prompt_ca_certs(locale: Locale, default: str | None) -> str | None:
    typer.echo(t("CLI.WIZARD_CA_CERTS_EXPLAIN", locale))
    raw = str(
        typer.prompt(
            t("CLI.WIZARD_CA_CERTS_PROMPT", locale),
            default=default or "",
            show_default=bool(default),
        )
    )
    return raw.strip() or None


# --- validation before persisting ---------------------------------------------


def _validate_before_saving(
    name: str,
    draft: _ProfileDraft,
    previous: dict[str, object],
    locale: Locale,
) -> bool:
    """Run the ladder before writing anything. Return ``True`` when the profile must be saved.

    No branch loses the collected data: on failure the user retries, fixes a single
    field, saves anyway (legitimate: configuring a profile without the VPN up), or cancels.
    """
    if not typer.confirm(t("CLI.VALIDATE_ASK", locale), default=True):
        typer.echo(t("CLI.VALIDATE_NOT_RUN", locale))
        return True
    while True:
        typer.secho(t("CLI.VALIDATE_HEADER", locale), bold=True)
        report = _run_ladder(name, draft, previous)
        _print_report(report, draft.database, locale)
        if report.ok:
            typer.secho(t("CLI.VALIDATE_ALL_OK", locale), fg=typer.colors.GREEN)
            return True
        typer.echo(t("CLI.VALIDATE_MENU", locale))
        choice = _prompt_failure_choice(locale)
        if choice == "g":
            typer.secho(
                t("CLI.VALIDATE_SAVED_ANYWAY", locale, profile=name), fg=typer.colors.YELLOW
            )
            return True
        if choice == "x":
            return False
        if choice == "c":
            _fix_one_field(draft, locale)


def _run_ladder(name: str, draft: _ProfileDraft, previous: dict[str, object]) -> ValidationReport:
    """Validate the draft as if it were already a profile, without persisting it."""
    overrides = previous.get("catalog_overrides")
    profile = Profile(
        name=name,
        host=draft.host,
        port=draft.port,
        database=draft.database,
        user=draft.user,
        mode=draft.mode,
        security_level=draft.security_level,
        ca_certs=draft.ca_certs,
        catalog_overrides=cast(dict[str, str], overrides) if isinstance(overrides, dict) else {},
    )
    return run_checks(profile, draft.password)


_OUTCOME_MESSAGE_KEYS: Final[dict[tuple[str, str], str]] = {
    ("connect", "ok"): "CLI.VALIDATE_CONNECT_OK",
    ("connect", "failed"): "CLI.VALIDATE_CONNECT_FAIL",
    ("connect", "empty"): "CLI.VALIDATE_CONNECT_FAIL",
    ("catalog_read", "ok"): "CLI.VALIDATE_CATALOG_OK",
    ("catalog_read", "failed"): "CLI.VALIDATE_CATALOG_FAIL",
    ("catalog_read", "empty"): "CLI.VALIDATE_CATALOG_EMPTY",
    ("catalog_read", "skipped"): "CLI.VALIDATE_CATALOG_SKIPPED",
    ("default_database", "ok"): "CLI.VALIDATE_DATABASE_OK",
    ("default_database", "failed"): "CLI.VALIDATE_DATABASE_FAIL",
    ("default_database", "empty"): "CLI.VALIDATE_DATABASE_EMPTY",
    ("default_database", "skipped"): "CLI.VALIDATE_DATABASE_SKIPPED",
}


def _print_report(report: ValidationReport, database: str, locale: Locale) -> None:
    """Report every level on its own line: what failed and what that means."""
    for outcome in report.outcomes:
        typer.secho(_render_outcome(outcome, database, locale), fg=_outcome_color(outcome))


def _render_outcome(outcome: CheckOutcome, database: str, locale: Locale) -> str:
    key = _OUTCOME_MESSAGE_KEYS[(outcome.level, outcome.status)]
    return t(key, locale, detail=outcome.detail, count=outcome.count, database=database)


def _outcome_color(outcome: CheckOutcome) -> str:
    if outcome.status == "ok":
        return typer.colors.GREEN
    if outcome.status == "skipped":
        return typer.colors.YELLOW
    return typer.colors.RED


def _prompt_failure_choice(locale: Locale) -> str:
    while True:
        raw = str(typer.prompt(t("CLI.VALIDATE_MENU_PROMPT", locale), default="r"))
        choice = raw.strip().lower()
        if choice in ("r", "c", "g", "x"):
            return choice
        typer.secho(
            t("CLI.VALIDATE_MENU_INVALID", locale, value=raw), fg=typer.colors.RED, err=True
        )


def _fix_one_field(draft: _ProfileDraft, locale: Locale) -> None:
    """Re-ask a single field, keeping every other value already typed."""
    fields = ", ".join(_DRAFT_FIELDS)
    while True:
        raw = str(
            typer.prompt(t("CLI.VALIDATE_FIELD_PROMPT", locale, fields=fields), default="host")
        )
        field = raw.strip().lower()
        if field in _DRAFT_FIELDS:
            _reprompt_field(draft, field, locale)
            return
        typer.secho(
            t("CLI.VALIDATE_FIELD_INVALID", locale, value=raw, fields=fields),
            fg=typer.colors.RED,
            err=True,
        )


def _reprompt_field(draft: _ProfileDraft, field: str, locale: Locale) -> None:
    if field == "host":
        draft.host = str(typer.prompt(t("CLI.WIZARD_HOST_PROMPT", locale), default=draft.host))
    elif field == "port":
        draft.port = _prompt_port(locale, draft.port)
    elif field == "database":
        draft.database = _prompt_database(locale, draft.database)
    elif field == "user":
        draft.user = str(typer.prompt(t("CLI.WIZARD_USER_PROMPT", locale), default=draft.user))
    elif field == "password":
        draft.password = _prompt_password(locale)
    elif field == "mode":
        draft.mode = _prompt_mode(locale, draft.mode)
    elif field == "security_level":
        draft.security_level = _prompt_security_level(locale, draft.security_level)
    else:
        draft.ca_certs = _prompt_ca_certs(locale, draft.ca_certs)


def _claude_desktop_snippet(profile: str) -> str:
    """Render the claude_desktop_config.json block with the profile name substituted."""
    block = {
        "mcpServers": {
            "netezza": {
                "command": "nz-mcp",
                "args": ["serve"],
                "env": {"NZ_MCP_PROFILE": profile},
            }
        }
    }
    return json.dumps(block, indent=2, ensure_ascii=False)


def _ensure_config_dir() -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):  # pragma: no cover - Windows ACLs differ
        cfg.chmod(0o700)


# Keys the wizard asks for and therefore owns on overwrite. ``ca_certs`` is listed even
# though it is only written when set: leaving it out would resurrect a stale path after
# the user cleared it with an empty answer.
_WIZARD_OWNED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "host",
        "port",
        "database",
        "user",
        "mode",
        "security_level",
        "ca_certs",
        "max_rows_default",
        "timeout_s_default",
    }
)


def _write_profile(*, name: str, draft: _ProfileDraft, set_active: bool) -> None:
    """Persist the draft. The password is not part of the block: it goes to the keyring."""
    block: dict[str, Any] = {
        "host": draft.host,
        "port": draft.port,
        "database": draft.database,
        "user": draft.user,
        "mode": draft.mode,
        "security_level": draft.security_level,
        "max_rows_default": DEFAULT_MAX_ROWS,
        "timeout_s_default": DEFAULT_TIMEOUT_S,
    }
    if draft.ca_certs:
        block["ca_certs"] = draft.ca_certs
    current = load_profiles_file()
    # ``--active`` only elects a profile when none is declared yet: switching the active
    # profile of an existing setup is an explicit action, not a side effect of add-profile.
    elect_active = set_active and current.active is None
    # Overwriting must not silently drop hand-edited configuration the wizard does not ask
    # for (catalog_overrides and any field added later): carry every key the wizard does
    # not own over to the replacement section.
    previous = current.profiles.get(name, {})
    preserved = {k: v for k, v in previous.items() if k not in _WIZARD_OWNED_KEYS and k != "name"}
    upsert_profile(name, {**preserved, **block}, set_active=elect_active)
