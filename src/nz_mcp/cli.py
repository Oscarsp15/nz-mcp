"""Command-line interface — typer.

Commands are **defined in the order they are used**, not in the order they were written,
because typer lists them in registration order and that list is the first screen of the
product: install, prove it works, then live with it, then diagnose, then the parts you
rarely type by hand.

- ``init``               first-time wizard: creates the first profile.
- ``test-connection``    verify the active profile against Netezza.
- ``list-profiles``      show the profiles and where each one points.
- ``switch-profile``     make an existing profile the active one.
- ``add-profile``        add another profile.
- ``edit-profile``       update an existing profile (mode, database, limits).
- ``remove-profile``     delete a profile and its keyring password.
- ``doctor``             print local diagnostics (no Netezza connection).
- ``probe-catalog``      execute every catalog query with dummy parameters (validates overrides).
- ``version``            print the package version.
- ``serve``              run the MCP server over stdio.

Every user-facing string here — help texts included — comes from the i18n catalog. Help is
resolved once at import time into ``_HELP_LOCALE``: typer reads ``help=`` while the module is
being imported, so there is no later moment at which to pick a language.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

import typer

from nz_mcp import __version__
from nz_mcp import cli_output as out
from nz_mcp.auth import delete_password, get_password, store_password
from nz_mcp.catalog.probe import (
    ProbeResult,
    ProbeRun,
    probe_has_hard_failure,
    probe_run_to_json_dict,
    run_probe_catalog,
)
from nz_mcp.catalog.queries import ALL_QUERIES
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
    active_profile_name,
    config_dir,
    get_active_profile,
    get_profile,
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
from nz_mcp.profile_check import (
    CHECK_LEVELS,
    CheckLevel,
    CheckOutcome,
    ValidationReport,
    iter_checks,
    run_checks,
)
from nz_mcp.secret import Secret
from nz_mcp.server import run_stdio_server
from nz_mcp.tools.session import SwitchProfileInput, nz_switch_profile

#: Language of ``--help``. Resolved once, at import time, because typer captures the ``help=``
#: strings while the decorators run: by the time a command executes, the help screen has
#: already been built. Everything else in this module resolves the locale per call.
_HELP_LOCALE: Final[Locale] = resolve_locale()


def _help(key: str) -> str:
    """Localized help text for a command, an argument or an option."""
    return t(key, _HELP_LOCALE)


app = typer.Typer(
    name="nz-mcp",
    help=_help("CLI.HELP.APP"),
    no_args_is_help=True,
    add_completion=False,
)

#: Title of the panel typer draws around the command list. Set on every command so the list
#: stays a single block: several panels would group the commands, and grouping eleven
#: commands into boxes buys structure the ordering already provides.
_COMMANDS_PANEL: Final[str] = _help("CLI.HELP.COMMANDS_PANEL")


@app.command("init", help=_help("CLI.HELP.INIT"), rich_help_panel=_COMMANDS_PANEL)
def init_cmd() -> None:
    """Interactive wizard: create the first profile."""
    locale = resolve_locale()
    out.heading("nz-mcp init")
    out.note(t("CLI.INIT_INTRO", locale))
    name = out.ask(t("CLI.INIT_NAME_PROMPT", locale), default="default")
    _add_profile_interactive(name=name, set_active=True)


@app.command(
    "test-connection",
    help=_help("CLI.HELP.TEST_CONNECTION"),
    rich_help_panel=_COMMANDS_PANEL,
)
def test_connection_cmd(
    profile: str | None = typer.Option(None, "--profile", "-p", help=_help("CLI.HELP.OPT.PROFILE")),
) -> None:
    """Verify connectivity: open Netezza, run a version query, report OK or FAIL (exit 0/1)."""
    locale = resolve_locale()
    try:
        prof = get_profile(profile) if profile is not None else get_active_profile()
    except ProfileNotFoundError as exc:
        out.fail(_format_profile_not_found_cli(locale, exc))
        raise typer.Exit(code=1) from exc
    except InvalidProfileError as exc:
        out.fail(t("INVALID_CONFIG", locale, detail=str(exc)))
        raise typer.Exit(code=1) from exc

    try:
        password = get_password(prof.name)
    except (CredentialNotFoundError, KeyringUnavailableError) as exc:
        detail = sanitize(str(exc), known_secrets=())
        out.fail(t("CLI.TEST_CONNECTION_FAIL", locale, detail=detail))
        raise typer.Exit(code=1) from exc

    # Level 1 of the validation ladder the wizard also runs (profile_check.run_checks).
    # The wait is a TCP session over a VPN and can last until the driver times out, so it
    # is announced while it happens instead of after: naming host, port and user is what
    # tells someone with the VPN down where to look. Never the password.
    waiting = t(
        "CLI.TEST_CONNECTION_RUNNING", locale, host=prof.host, port=prof.port, user=prof.user
    )
    with out.progress(waiting):
        outcome = run_checks(prof, password, levels=1).outcomes[0]
    if outcome.status != "ok":
        out.fail(t("CLI.TEST_CONNECTION_FAIL", locale, detail=outcome.detail))
        hint = outcome.hint_es if locale == "es" else outcome.hint_en
        if hint:
            out.warn(t("CLI.TEST_CONNECTION_HINT", locale, hint=hint))
        raise typer.Exit(code=1)
    out.success(t("CLI.TEST_CONNECTION_OK", locale, detail=outcome.detail, user=prof.user))
    raise typer.Exit(code=0)


@app.command(
    "list-profiles",
    help=_help("CLI.HELP.LIST_PROFILES"),
    rich_help_panel=_COMMANDS_PANEL,
)
def list_profiles_cmd() -> None:
    """Show every configured profile, where it points, and which one is active.

    A bare list of names does not answer the question people actually ask before letting an
    assistant loose on a database: *which* profile is in use and *what* is it pointing at.
    """
    locale = resolve_locale()
    file = _load_profiles_or_exit(locale)
    if not file.profiles:
        out.note(t("CLI.PROFILES_EMPTY", locale))
        raise typer.Exit(code=0)
    active = active_profile_name(file)
    out.emit(_render_profiles(file, active, locale))
    out.note(
        t("CLI.PROFILES_SINGLE_NEXT_STEP", locale)
        if len(file.profiles) == 1
        else t("CLI.PROFILES_NEXT_STEP", locale)
    )
    raise typer.Exit(code=0)


@app.command(
    "switch-profile",
    help=_help("CLI.HELP.SWITCH_PROFILE"),
    rich_help_panel=_COMMANDS_PANEL,
)
def switch_profile_cmd(
    name: str = typer.Argument(..., help=_help("CLI.HELP.OPT.EXISTING_PROFILE_NAME")),
) -> None:
    """Make an existing profile the active one."""
    locale = resolve_locale()
    try:
        # Single source of truth: the CLI delegates to the MCP tool instead of
        # re-implementing "validate the name, then persist active=..." on its own.
        result = nz_switch_profile(SwitchProfileInput(profile=name))
    except ProfileNotFoundError as exc:
        out.fail(_format_profile_not_found_cli(locale, exc))
        raise typer.Exit(code=1) from exc
    except InvalidProfileError as exc:
        out.fail(t("INVALID_CONFIG", locale, detail=str(exc)))
        raise typer.Exit(code=1) from exc
    out.success(t("CLI.PROFILE_SWITCHED", locale, profile=result.switched_to, mode=result.mode))
    raise typer.Exit(code=0)


@app.command("add-profile", help=_help("CLI.HELP.ADD_PROFILE"), rich_help_panel=_COMMANDS_PANEL)
def add_profile_cmd(
    name: str = typer.Argument(..., help=_help("CLI.HELP.OPT.NEW_PROFILE_NAME")),
    set_active: bool = typer.Option(
        False,
        "--active/--no-active",
        help=_help("CLI.HELP.OPT.SET_ACTIVE"),
    ),
) -> None:
    """Add a new profile (interactive)."""
    _add_profile_interactive(name=name, set_active=set_active)


@app.command("edit-profile", help=_help("CLI.HELP.EDIT_PROFILE"), rich_help_panel=_COMMANDS_PANEL)
def edit_profile_cmd(
    name: str = typer.Argument(..., help=_help("CLI.HELP.OPT.EXISTING_PROFILE_NAME")),
    mode: str | None = typer.Option(None, "--mode", help=_help("CLI.HELP.OPT.MODE")),
    database: str | None = typer.Option(None, "--database", help=_help("CLI.HELP.OPT.DATABASE")),
    max_rows_default: int | None = typer.Option(
        None, "--max-rows-default", help=_help("CLI.HELP.OPT.MAX_ROWS_DEFAULT")
    ),
    timeout_s_default: int | None = typer.Option(
        None, "--timeout-s-default", help=_help("CLI.HELP.OPT.TIMEOUT_S_DEFAULT")
    ),
) -> None:
    """Update fields of an existing profile (password stays in the OS keyring)."""
    locale = resolve_locale()
    if mode is not None and mode.strip().lower() not in ("read", "write", "admin"):
        out.fail(t("CLI.EDIT_PROFILE_INVALID_MODE", locale, value=mode))
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
        out.fail(_format_profile_not_found_cli(locale, exc))
        raise typer.Exit(code=1) from exc
    if result is None:
        out.note(t("CLI.EDIT_PROFILE_NO_CHANGES", locale))
        raise typer.Exit(code=0)
    out.success(t("CLI.EDIT_PROFILE_UPDATED", locale, profile=result.name, mode=result.mode))
    raise typer.Exit(code=0)


@app.command(
    "remove-profile",
    help=_help("CLI.HELP.REMOVE_PROFILE"),
    rich_help_panel=_COMMANDS_PANEL,
)
def remove_profile_cmd(
    name: str = typer.Argument(..., help=_help("CLI.HELP.OPT.PROFILE_TO_DELETE")),
) -> None:
    """Delete a profile from profiles.toml and its password from the OS keyring."""
    locale = resolve_locale()
    file = _load_profiles_or_exit(locale)
    if name not in file.profiles:
        exc = _profile_not_found(name, list(file.profiles))
        out.fail(_format_profile_not_found_cli(locale, exc))
        raise typer.Exit(code=1)
    prompt = t("CLI.PROFILE_REMOVE_CONFIRM", locale, profile=name, path=profiles_path())
    if not out.confirm(prompt, default=False):
        out.warn(t("CLI.PROFILE_REMOVE_CANCELLED", locale, profile=name))
        raise typer.Exit(code=1)
    _delete_password_or_warn(name, locale)
    was_active = remove_profile(name)
    out.success(t("CLI.PROFILE_REMOVED", locale, profile=name, path=profiles_path()))
    if was_active:
        out.warn(t("CLI.ACTIVE_PROFILE_CLEARED", locale, path=profiles_path()))
    raise typer.Exit(code=0)


@app.command("doctor", help=_help("CLI.HELP.DOCTOR"), rich_help_panel=_COMMANDS_PANEL)
def doctor_cmd() -> None:
    """Print local diagnostics (package, Python, profiles metadata, keyring) — no Netezza."""
    report = collect_diagnostic()
    locale = resolve_locale()
    out.emit(format_diagnostic_report(report, locale=locale))
    raise typer.Exit(code=0 if report.is_healthy else 1)


@app.command(
    "probe-catalog",
    help=_help("CLI.HELP.PROBE_CATALOG"),
    rich_help_panel=_COMMANDS_PANEL,
)
def probe_catalog_cmd(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help=_help("CLI.HELP.OPT.PROFILE"),
    ),
    as_json: bool = typer.Option(False, "--json", help=_help("CLI.HELP.OPT.JSON")),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show every query in a table, not just the ones worth acting on"
    ),
) -> None:
    """Run every registered catalog query with dummy parameters against Netezza.

    Fourteen queries in a row, so this is the longest wait the CLI has. Two channels, and each
    carries one thing: the progress indicator is transient and goes to stderr, the report is
    the whole report and goes to stderr as one block. ``--json`` is the machine surface and
    owns stdout by itself, unchanged.
    """
    locale = resolve_locale()
    try:
        prof = get_profile(profile) if profile is not None else get_active_profile()
    except ProfileNotFoundError as exc:
        out.fail(_format_profile_not_found_cli(locale, exc))
        raise typer.Exit(code=1) from exc
    except InvalidProfileError as exc:
        out.fail(t("INVALID_CONFIG", locale, detail=str(exc)))
        raise typer.Exit(code=1) from exc

    run = _run_probe_showing_progress(prof, locale)
    if as_json:
        out.emit(json.dumps(probe_run_to_json_dict(run), indent=2, ensure_ascii=False))
    else:
        _report_probe_run(run, locale, verbose=verbose)

    code = 0 if not probe_has_hard_failure(run) else 1
    raise typer.Exit(code=code)


@app.command("version", help=_help("CLI.HELP.VERSION"), rich_help_panel=_COMMANDS_PANEL)
def version_cmd() -> None:
    """Print the installed nz-mcp version."""
    out.emit(__version__)


@app.command("serve", help=_help("CLI.HELP.SERVE"), rich_help_panel=_COMMANDS_PANEL)
def serve_cmd() -> None:
    """Run the MCP server over stdio."""
    # Logging is configured first so structlog binds the real stderr; only then is
    # descriptor 1 handed over to the protocol.
    configure_logging_for_stdio()
    with out.stdout_reserved_for_protocol() as protocol_stdout:
        run_stdio_server(protocol_stdout=protocol_stdout)


# --- list-profiles rendering --------------------------------------------------

#: Shown for a field a profile does not define. Profiles are read as raw sections here, not
#: validated, so that one hand-edited profile missing its host does not stop the command that
#: would let someone notice it.
_PROFILE_FIELD_UNSET: Final[str] = "-"

#: Marks the active row. Text, not colour, and ASCII: it has to survive a redirect to a file,
#: a terminal without colour, and a Windows console on a legacy code page.
_ACTIVE_MARK: Final[str] = "*"

#: The four fields that answer "where does this point", in reading order.
_PROFILE_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("CLI.PROFILES_COLUMN_NAME", "name"),
    ("CLI.PROFILES_COLUMN_HOST", "host"),
    ("CLI.PROFILES_COLUMN_DATABASE", "database"),
    ("CLI.PROFILES_COLUMN_MODE", "mode"),
)


def _profile_field(section: dict[str, object], field: str, name: str) -> str:
    """One cell: the raw value as text, or a placeholder when the profile does not set it."""
    if field == "name":
        return name
    value = section.get(field)
    return str(value) if value not in (None, "") else _PROFILE_FIELD_UNSET


def _render_profiles(file: ProfilesFile, active: str | None, locale: Locale) -> str:
    """Render the profiles as a table, or as ``key: value`` when there is only one.

    A table earns its borders when there are rows to compare and one to choose. With a
    single profile there is nothing to compare it against and the active column is noise:
    that profile is the active one by definition.
    """
    names = sorted(file.profiles)
    labels = [t(key, locale) for key, _ in _PROFILE_COLUMNS]
    if len(names) == 1:
        section = file.profiles[names[0]]
        cells = [_profile_field(section, field, names[0]) for _, field in _PROFILE_COLUMNS]
        return "\n".join(f"{label}: {cell}" for label, cell in zip(labels, cells, strict=True))
    rows = [
        [
            *(_profile_field(file.profiles[name], field, name) for _, field in _PROFILE_COLUMNS),
            _ACTIVE_MARK if name == active else "",
        ]
        for name in names
    ]
    return out.table([*labels, t("CLI.PROFILES_COLUMN_ACTIVE", locale)], rows)


# --- probe-catalog: progress while it runs, one report when it ends -----------

#: ASCII status markers, deliberately untranslated: they are identifiers the README, the JSON
#: output and the line messages already share, and a person greps for them.
_PROBE_STATUS_MARK: Final[dict[str, str]] = {
    "ok": "OK",
    "structural_warning": "WARN",
    "failure": "FAIL",
}


def _run_probe_showing_progress(profile: Profile, locale: Locale) -> ProbeRun:
    """Run the probe with a determinate indicator naming the query in flight.

    This is the only place in the CLI where a counter is honest: the query list is known in
    advance, so ``7/14`` is counted rather than invented. The point is less the animation than
    the name next to it — when a run stops responding, that name is the answer to "on which
    one?", which fourteen queries of silence used to hide.

    Nothing is written when there is no terminal: the indicator disappears entirely and a
    redirected run leaves exactly the report behind.
    """
    with out.steps(len(ALL_QUERIES)) as step:

        def announce(query_id: str, position: int, _total: int) -> None:
            step(position, t("PROBE_CATALOG.RUNNING", locale, query_id=query_id))

        return run_probe_catalog(profile, on_query=announce)


def _probe_failure_detail(row: ProbeResult) -> str:
    """The human part of a failure first, the driver text after it."""
    parts = [part for part in (row.detail, row.error_detail) if part]
    return " — ".join(parts) if parts else "error"


def _probe_verbose_table(run: ProbeRun, locale: Locale) -> str:
    """All fourteen rows, aligned: with ``--verbose`` the point is to compare them."""
    headers = [
        t("PROBE_CATALOG.COLUMN_QUERY", locale),
        t("PROBE_CATALOG.COLUMN_STATUS", locale),
        t("PROBE_CATALOG.COLUMN_MS", locale),
        t("PROBE_CATALOG.COLUMN_ROWS", locale),
    ]
    rows = [
        [
            row.query_id,
            _PROBE_STATUS_MARK[row.status],
            f"{row.duration_ms:.1f}" if row.duration_ms is not None else "-",
            str(row.row_count) if row.row_count is not None else "-",
        ]
        for row in run.results
    ]
    return out.table(headers, rows)


def _report_probe_run(run: ProbeRun, locale: Locale, *, verbose: bool) -> None:
    """Print the whole report on stderr: what needs acting on first, one conclusion last.

    The default view stays quiet about the queries that worked. Printing all fourteen lines,
    eleven of them ``[OK]``, is how a failure ends up buried in the middle of good news; the
    successes are worth exactly one closing sentence, and ``--verbose`` is there for whoever
    wants the matrix.
    """
    out.heading(t("PROBE_CATALOG.HEADER", locale, profile=run.profile_name))
    if run.config_error is not None:
        out.fail(t("PROBE_CATALOG.CONFIG_ERROR", locale, detail=run.config_error))
        out.note(t("PROBE_CATALOG.NEXT_STEP_FAILED", locale))
        return
    for row in run.results:
        if row.status == "failure":
            detail = _probe_failure_detail(row)
            out.fail(t("PROBE_CATALOG.LINE_FAIL", locale, query_id=row.query_id, detail=detail))
    for row in run.results:
        if row.status == "structural_warning":
            detail = row.error_detail or ""
            out.warn(t("PROBE_CATALOG.LINE_WARN", locale, query_id=row.query_id, detail=detail))
    if verbose:
        out.note(_probe_verbose_table(run, locale))
    _report_probe_summary(run, locale)


def _report_probe_summary(run: ProbeRun, locale: Locale) -> None:
    """One sentence for the outcome, one line for what to do next. One of each."""
    total = len(run.results)
    failed = sum(1 for row in run.results if row.status == "failure")
    warned = sum(1 for row in run.results if row.status == "structural_warning")
    if failed or warned:
        out.status(
            t(
                "PROBE_CATALOG.SUMMARY",
                locale,
                ok=total - failed - warned,
                total=total,
                failed=failed,
                warned=warned,
            ),
            style="warning" if not failed else "error",
        )
    else:
        out.success(t("PROBE_CATALOG.SUMMARY_ALL_OK", locale, total=total))
    key = "PROBE_CATALOG.NEXT_STEP_FAILED" if failed else "PROBE_CATALOG.NEXT_STEP_OK"
    out.note(t(key, locale, total=total))


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
        out.fail(t("INVALID_CONFIG", locale, detail=str(exc)))
        raise typer.Exit(code=1) from exc


def _confirm_overwrite_or_exit(name: str, locale: Locale) -> None:
    """Ask before replacing an existing profile; abort (exit 1) unless confirmed."""
    out.warn(t("CLI.PROFILE_ALREADY_EXISTS", locale, profile=name, path=profiles_path()))
    if not out.confirm(t("CLI.PROFILE_OVERWRITE_CONFIRM", locale), default=False):
        out.warn(t("CLI.PROFILE_OVERWRITE_CANCELLED", locale, profile=name))
        raise typer.Exit(code=1)


def _delete_password_or_warn(name: str, locale: Locale) -> None:
    """Drop the keyring entry; a broken keyring must not block removing the profile."""
    try:
        delete_password(name)
    except KeyringUnavailableError as exc:
        detail = sanitize(str(exc), known_secrets=())
        out.warn(t("CLI.PROFILE_PASSWORD_DELETE_FAILED", locale, profile=name, detail=detail))
        return
    out.note(t("CLI.PROFILE_PASSWORD_DELETED", locale, profile=name))


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
    out.note(t("CLI.WIZARD_INTRO", locale, profile=name))
    draft = _prompt_draft(locale, previous)

    if not _validate_before_saving(name, draft, previous, locale):
        out.warn(t("CLI.WIZARD_CANCELLED", locale, path=profiles_path()))
        raise typer.Exit(code=1)

    _ensure_config_dir()
    _write_profile(name=name, draft=draft, set_active=set_active)
    store_password(name, draft.password)
    out.success(t("CLI.PROFILE_SAVED", locale, profile=name, path=profiles_path()))
    out.note(t("CLI.PROFILE_NEXT_STEP", locale, profile=name))
    _print_claude_desktop_block(name, locale)
    out.note(t("CLI.PROBE_SUGGESTION", locale, profile=name))


# --- wizard prompts (one explanation per non-obvious concept) ------------------


def _prompt_draft(locale: Locale, previous: dict[str, object]) -> _ProfileDraft:
    """Ask for every field, defaulting to the current value when overwriting a profile."""
    return _ProfileDraft(
        host=out.ask(t("CLI.WIZARD_HOST_PROMPT", locale), default=_text(previous, "host")),
        port=_prompt_port(locale, _number(previous, "port", DEFAULT_PORT)),
        database=_prompt_database(locale, _text(previous, "database")),
        user=out.ask(t("CLI.WIZARD_USER_PROMPT", locale), default=_text(previous, "user")),
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
    return out.ask_int(t("CLI.WIZARD_PORT_PROMPT", locale), default=default)


def _prompt_database(locale: Locale, default: str | None) -> str:
    out.note(t("CLI.WIZARD_DATABASE_EXPLAIN", locale))
    return out.ask(t("CLI.WIZARD_DATABASE_PROMPT", locale), default=default)


def _prompt_password(locale: Locale) -> Secret:
    out.note(t("CLI.WIZARD_PASSWORD_EXPLAIN", locale))
    return Secret(out.ask_secret(t("CLI.WIZARD_PASSWORD_PROMPT", locale)))


def _prompt_mode(locale: Locale, default: str) -> PermissionMode:
    out.note(t("CLI.WIZARD_MODE_EXPLAIN", locale))
    while True:
        raw = out.ask(t("CLI.WIZARD_MODE_PROMPT", locale), default=default)
        value = raw.strip().lower()
        if value in _MODES:
            return cast(PermissionMode, value)
        out.fail(t("CLI.WIZARD_MODE_INVALID", locale, value=raw))


def _prompt_security_level(locale: Locale, default: int) -> int:
    out.note(t("CLI.WIZARD_SECURITY_EXPLAIN", locale))
    while True:
        raw = out.ask(t("CLI.WIZARD_SECURITY_PROMPT", locale), default=str(default))
        value = raw.strip()
        if value.isdigit() and MIN_SECURITY_LEVEL <= int(value) <= MAX_SECURITY_LEVEL:
            return int(value)
        out.fail(t("CLI.WIZARD_SECURITY_INVALID", locale, value=raw))


def _prompt_ca_certs(locale: Locale, default: str | None) -> str | None:
    out.note(t("CLI.WIZARD_CA_CERTS_EXPLAIN", locale))
    raw = out.ask(
        t("CLI.WIZARD_CA_CERTS_PROMPT", locale),
        default=default or "",
        show_default=bool(default),
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
    if not out.confirm(t("CLI.VALIDATE_ASK", locale), default=True):
        out.note(t("CLI.VALIDATE_NOT_RUN", locale))
        return True
    while True:
        out.heading(t("CLI.VALIDATE_HEADER", locale))
        report = _run_ladder(_draft_profile(name, draft, previous), draft.password, locale)
        if report.ok:
            out.success(t("CLI.VALIDATE_ALL_OK", locale))
            return True
        out.note(t("CLI.VALIDATE_MENU", locale))
        choice = _prompt_failure_choice(locale)
        if choice == "g":
            out.warn(t("CLI.VALIDATE_SAVED_ANYWAY", locale, profile=name))
            return True
        if choice == "x":
            return False
        if choice == "c":
            _fix_one_field(draft, locale)


def _draft_profile(name: str, draft: _ProfileDraft, previous: dict[str, object]) -> Profile:
    """Shape the draft as a ``Profile`` so it can be validated without being persisted."""
    overrides = previous.get("catalog_overrides")
    return Profile(
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


def _run_ladder(profile: Profile, password: Secret, locale: Locale) -> ValidationReport:
    """Run the ladder level by level, saying what is running and printing each result.

    This is the longest silence of the whole install path: level 1 opens a TCP session,
    usually over a VPN, and used to show nothing until the driver gave up — at which point
    all three lines appeared at once. Someone with the VPN down could not tell "still
    trying" from "hung", and the natural reaction, Ctrl+C, threw away eight answers.

    So each level announces itself before it runs and its result line replaces the
    indicator when it ends. The indicator is indeterminate because Netezza does not report
    how far a query has got; a percentage here would be invented. Without a terminal
    nothing is announced at all and the output is exactly the three result lines, as before.
    """
    outcomes: list[CheckOutcome] = []
    with contextlib.closing(iter_checks(profile, password)) as ladder:
        for level in CHECK_LEVELS:
            with out.progress(_render_running(level, profile, locale)):
                outcome = next(ladder, None)
            if outcome is None:
                break
            outcomes.append(outcome)
            out.status(
                _render_outcome(outcome, profile.database, locale),
                style=_outcome_style(outcome),
            )
    return ValidationReport(tuple(outcomes))


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


#: What the indicator says while each level is in flight. Same numbering as the result
#: lines, so the line that replaces it reads as the answer to the same question.
_RUNNING_MESSAGE_KEYS: Final[dict[CheckLevel, str]] = {
    "connect": "CLI.VALIDATE_CONNECT_RUNNING",
    "catalog_read": "CLI.VALIDATE_CATALOG_RUNNING",
    "default_database": "CLI.VALIDATE_DATABASE_RUNNING",
}


def _render_running(level: CheckLevel, profile: Profile, locale: Locale) -> str:
    """Name the level in flight. Host, port and database only: never the credential."""
    return t(
        _RUNNING_MESSAGE_KEYS[level],
        locale,
        host=profile.host,
        port=profile.port,
        database=profile.database,
    )


def _render_outcome(outcome: CheckOutcome, database: str, locale: Locale) -> str:
    key = _OUTCOME_MESSAGE_KEYS[(outcome.level, outcome.status)]
    return t(key, locale, detail=outcome.detail, count=outcome.count, database=database)


def _outcome_style(outcome: CheckOutcome) -> out.Style:
    if outcome.status == "ok":
        return "success"
    if outcome.status == "skipped":
        return "warning"
    return "error"


def _prompt_failure_choice(locale: Locale) -> str:
    while True:
        raw = out.ask(t("CLI.VALIDATE_MENU_PROMPT", locale), default="r")
        choice = raw.strip().lower()
        if choice in ("r", "c", "g", "x"):
            return choice
        out.fail(t("CLI.VALIDATE_MENU_INVALID", locale, value=raw))


def _fix_one_field(draft: _ProfileDraft, locale: Locale) -> None:
    """Re-ask a single field, keeping every other value already typed."""
    fields = ", ".join(_DRAFT_FIELDS)
    while True:
        raw = out.ask(t("CLI.VALIDATE_FIELD_PROMPT", locale, fields=fields), default="host")
        field = raw.strip().lower()
        if field in _DRAFT_FIELDS:
            _reprompt_field(draft, field, locale)
            return
        out.fail(t("CLI.VALIDATE_FIELD_INVALID", locale, value=raw, fields=fields))


def _reprompt_field(draft: _ProfileDraft, field: str, locale: Locale) -> None:
    if field == "host":
        draft.host = out.ask(t("CLI.WIZARD_HOST_PROMPT", locale), default=draft.host)
    elif field == "port":
        draft.port = _prompt_port(locale, draft.port)
    elif field == "database":
        draft.database = _prompt_database(locale, draft.database)
    elif field == "user":
        draft.user = out.ask(t("CLI.WIZARD_USER_PROMPT", locale), default=draft.user)
    elif field == "password":
        draft.password = _prompt_password(locale)
    elif field == "mode":
        draft.mode = _prompt_mode(locale, draft.mode)
    elif field == "security_level":
        draft.security_level = _prompt_security_level(locale, draft.security_level)
    else:
        draft.ca_certs = _prompt_ca_certs(locale, draft.ca_certs)


#: Name of the console script declared in ``pyproject.toml`` (``[project.scripts]``).
_EXECUTABLE_NAME: Final[str] = "nz-mcp"


def _executable_file_name() -> str:
    return f"{_EXECUTABLE_NAME}.exe" if os.name == "nt" else _EXECUTABLE_NAME


def _executable_candidates() -> list[Path]:
    """Where the console script of the *running* installation may live, best guess first.

    Covers the two documented install methods on the three platforms: a virtual environment
    (``<venv>/Scripts`` or ``<venv>/bin``, which is what ``sysconfig`` reports from inside it)
    and pipx (each app gets its own venv, so the same lookup applies). The user scheme is
    checked too, because ``pip install --user`` lands scripts outside the interpreter prefix.
    """
    name = _executable_file_name()
    user_scheme = "nt_user" if os.name == "nt" else "posix_user"
    directories = [
        sysconfig.get_path("scripts"),
        sysconfig.get_path("scripts", user_scheme),
        str(Path(sys.executable).parent),
    ]
    seen: list[Path] = []
    for directory in directories:
        candidate = Path(directory) / name
        if directory and candidate not in seen:
            seen.append(candidate)
    return seen


def resolve_executable_path() -> str | None:
    """Absolute path of the ``nz-mcp`` executable, or ``None`` when it cannot be determined.

    The installation that is running wins over whatever sits on ``PATH``: a globally installed
    ``nz-mcp`` may be a different one (see ``docs/guides/claude-desktop-setup.md``). ``PATH`` is
    only consulted as a fallback, for the case where the CLI runs as ``python -m nz_mcp`` and no
    console script exists next to the interpreter.
    """
    for candidate in _executable_candidates():
        if candidate.is_file():
            return str(candidate)
    on_path = shutil.which(_EXECUTABLE_NAME)
    return str(Path(on_path).resolve()) if on_path else None


def _how_to_find_executable() -> str:
    """The command that prints the absolute path, per platform."""
    return "where.exe nz-mcp" if os.name == "nt" else "which nz-mcp"


def _claude_desktop_snippet(profile: str, command: str) -> str:
    """Render the claude_desktop_config.json block for ``profile`` and ``command``.

    ``json.dumps`` escapes the Windows backslashes, so the result is valid JSON and can be
    pasted as it is printed.
    """
    block = {
        "mcpServers": {
            "netezza": {
                "command": command,
                "args": ["serve"],
                "env": {"NZ_MCP_PROFILE": profile},
            }
        }
    }
    return json.dumps(block, indent=2, ensure_ascii=False)


def _print_claude_desktop_block(profile: str, locale: Locale) -> None:
    """Print the block to paste, with the real executable path resolved at runtime.

    Claude Desktop does not start with the terminal ``PATH``, so a bare ``nz-mcp`` in
    ``command`` fails silently and much later, inside the client log. When the path cannot be
    determined the block carries an obvious placeholder instead of a value that would probably
    not work, plus the command that prints the right one.

    The two channels of the output layer split this cleanly: the JSON block is payload — it is
    literally copied, and ``nz-mcp init > block.json`` has to yield a parsable file — so it goes
    to stdout through ``emit``. The heading and the warning are text for a person and go to
    stderr, which is also what keeps them out of that redirected file.
    """
    executable = resolve_executable_path()
    placeholder = t("CLI.CLAUDE_CONFIG_PATH_PLACEHOLDER", locale)
    out.note(t("CLI.CLAUDE_CONFIG_HEADER", locale))
    out.emit(_claude_desktop_snippet(profile, executable or placeholder))
    if executable is None:
        out.note(t("CLI.CLAUDE_CONFIG_PATH_UNKNOWN", locale, command=_how_to_find_executable()))


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
