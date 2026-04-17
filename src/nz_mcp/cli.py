"""Command-line interface — typer.

Commands:
- ``init``               first-time wizard: creates the first profile.
- ``add-profile``        add another profile.
- ``list-profiles``      list configured profiles.
- ``test-connection``    verify the active profile (stubbed in v0.1.0a0).
- ``serve``              run the MCP server over stdio (stubbed in v0.1.0a0).
- ``version``            print the package version.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import cast

import typer

from nz_mcp import __version__
from nz_mcp.auth import store_password
from nz_mcp.config import (
    DEFAULT_MAX_ROWS,
    DEFAULT_TIMEOUT_S,
    PermissionMode,
    config_dir,
    list_profile_names,
    profiles_path,
)

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
    name: str = typer.Argument(..., help="Nombre del perfil"),
    set_active: bool = typer.Option(False, "--active/--no-active", help="Marcar como activo"),
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


@app.command("test-connection")
def test_connection_cmd(
    profile: str | None = typer.Option(None, "--profile", "-p", help="Perfil a probar"),
) -> None:
    """Verify connectivity to Netezza (stubbed in v0.1.0a0)."""
    target = profile or "<active>"
    typer.secho(
        f"[stub] test-connection({target}) — no implementado aún. Issue #1.",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=0)


@app.command("serve")
def serve_cmd() -> None:
    """Run the MCP server over stdio (stubbed in v0.1.0a0)."""
    typer.secho(
        "[stub] serve — la integración con el SDK 'mcp' llega en issue #2.\n"
        "Mientras tanto el registro de tools es funcional y testeado.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(code=0)


# --- helpers ------------------------------------------------------------------


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
