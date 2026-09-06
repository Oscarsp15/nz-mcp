"""Tests for CLI internal helpers (profile writing, Claude Desktop snippet)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import cast

import pytest

from nz_mcp import cli
from nz_mcp.cli import _claude_desktop_snippet, _ensure_config_dir, _ProfileDraft, _write_profile
from nz_mcp.config import PermissionMode, get_profile, list_profile_names, load_profiles_file
from nz_mcp.i18n import Locale
from nz_mcp.secret import Secret


def _draft(
    *,
    host: str = "h",
    port: int = 5480,
    database: str = "DB",
    user: str = "u",
    mode: PermissionMode = "read",
    security_level: int = 2,
    ca_certs: str | None = None,
) -> _ProfileDraft:
    return _ProfileDraft(
        host=host,
        port=port,
        database=database,
        user=user,
        password=Secret("pw123456"),
        mode=mode,
        security_level=security_level,
        ca_certs=ca_certs,
    )


def test_ensure_config_dir_idempotent(tmp_profiles: Path) -> None:
    _ensure_config_dir()
    _ensure_config_dir()  # second call must not raise


@pytest.mark.parametrize("set_active", [True, False])
def test_write_profile_creates_block(tmp_profiles: Path, set_active: bool) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=set_active)
    file = load_profiles_file(tmp_profiles)
    assert list(file.profiles) == ["dev"]
    assert get_profile("dev", path=tmp_profiles).host == "h"
    assert file.active == ("dev" if set_active else None)


def test_write_profile_never_persists_the_password(tmp_profiles: Path) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=True)
    assert "pw123456" not in tmp_profiles.read_text(encoding="utf-8")


def test_write_profile_appends_second(tmp_profiles: Path) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=True)
    _write_profile(name="prod", draft=_draft(host="h2", mode="write"), set_active=False)
    file = load_profiles_file(tmp_profiles)
    assert list_profile_names(tmp_profiles) == ["dev", "prod"]
    # active stays as dev (already present)
    assert file.active == "dev"


def test_write_profile_same_name_replaces_section(tmp_profiles: Path) -> None:
    _write_profile(name="dev", draft=_draft(), set_active=True)
    _write_profile(
        name="dev",
        draft=_draft(host="h2", port=5481, database="DB2", user="u2", mode="write"),
        set_active=True,
    )
    content = tmp_profiles.read_text(encoding="utf-8")
    assert content.count("[profiles.dev]") == 1
    # The file must still load: a duplicated section made tomllib reject the whole file.
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == "h2"
    assert profile.port == 5481
    assert profile.database == "DB2"
    assert profile.mode == "write"


def test_write_profile_persists_security_fields(tmp_profiles: Path) -> None:
    _write_profile(
        name="dev",
        draft=_draft(security_level=3, ca_certs="/etc/ssl/nz.pem"),
        set_active=True,
    )
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.security_level == 3
    assert profile.ca_certs == "/etc/ssl/nz.pem"


def test_write_profile_overwrite_keeps_unmanaged_fields(tmp_profiles: Path) -> None:
    """Overwriting must not drop config the wizard never asks for (issue #167)."""
    _write_profile(name="dev", draft=_draft(), set_active=True)
    raw = tmp_profiles.read_text(encoding="utf-8")
    extra = '[profiles.dev.catalog_overrides]\nlist_databases = "SELECT 1"\n'
    tmp_profiles.write_text(raw + extra, encoding="utf-8")

    _write_profile(name="dev", draft=_draft(host="h2", port=5481), set_active=True)

    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == "h2"
    assert profile.catalog_overrides == {"list_databases": "SELECT 1"}


def test_write_profile_overwrite_clears_ca_certs_when_dropped(tmp_profiles: Path) -> None:
    """An empty answer to the CA prompt must not resurrect the previous path."""
    _write_profile(name="dev", draft=_draft(ca_certs="/etc/ssl/nz.pem"), set_active=True)
    _write_profile(name="dev", draft=_draft(ca_certs=None), set_active=True)
    assert get_profile("dev", path=tmp_profiles).ca_certs is None


def test_claude_desktop_snippet_substitutes_the_profile_name_and_command() -> None:
    block = json.loads(_claude_desktop_snippet("dev", "/opt/pipx/venvs/nz-mcp/bin/nz-mcp"))
    server = block["mcpServers"]["netezza"]
    assert server["command"] == "/opt/pipx/venvs/nz-mcp/bin/nz-mcp"
    assert server["args"] == ["serve"]
    assert server["env"]["NZ_MCP_PROFILE"] == "dev"


# --- issue #207: the snippet must carry the real absolute path -----------------

_WINDOWS_PATH = "C:\\Users\\ana\\AppData\\Roaming\\Python\\Python311\\Scripts\\nz-mcp.exe"


def test_windows_backslashes_are_escaped_and_the_block_still_parses() -> None:
    """The block is pasted verbatim into JSON, so backslashes must survive a round trip."""
    rendered = _claude_desktop_snippet("prod", _WINDOWS_PATH)
    assert "\\\\" in rendered, "backslashes are not escaped; the pasted JSON would be invalid"
    assert json.loads(rendered)["mcpServers"]["netezza"]["command"] == _WINDOWS_PATH


def _fake_scripts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every lookup at an empty directory, so each test declares its own answer."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(sysconfig, "get_path", lambda *_args, **_kwargs: str(empty))
    monkeypatch.setattr(sys, "executable", str(empty / "python"))
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    return empty


def test_executable_is_resolved_next_to_the_running_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The venv or pipx install that is running wins: its scripts dir is checked first."""
    scripts = _fake_scripts_dir(tmp_path, monkeypatch)
    installed = scripts / cli._executable_file_name()
    installed.write_text("#!/bin/sh\n", encoding="utf-8")

    resolved = cli.resolve_executable_path()

    assert resolved == str(installed)
    assert Path(resolved or "").is_absolute()


def test_executable_falls_back_to_path_when_no_console_script_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running as ``python -m nz_mcp`` leaves no script next to the interpreter."""
    _fake_scripts_dir(tmp_path, monkeypatch)
    on_path = tmp_path / "bin" / cli._executable_file_name()
    on_path.parent.mkdir()
    on_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: str(on_path))

    assert cli.resolve_executable_path() == str(on_path.resolve())


def test_executable_is_none_when_it_cannot_be_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_scripts_dir(tmp_path, monkeypatch)
    assert cli.resolve_executable_path() is None


def test_block_carries_the_resolved_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole of stdout is the block: that is what makes redirecting it to a file work."""
    monkeypatch.setattr(cli, "resolve_executable_path", lambda: _WINDOWS_PATH)

    cli._print_claude_desktop_block("prod", "es")

    captured = capsys.readouterr()
    block = json.loads(captured.out)
    assert block["mcpServers"]["netezza"]["command"] == _WINDOWS_PATH
    # The heading is for the person, not for the file being pasted.
    assert "claude_desktop_config.json" in captured.err
    assert "no se ha podido determinar" not in captured.err.lower()


@pytest.mark.parametrize(
    ("locale", "placeholder"),
    [("es", "<ruta absoluta de nz-mcp>"), ("en", "<absolute path to nz-mcp>")],
)
def test_block_degrades_honestly_when_the_path_is_unknown(
    locale: str,
    placeholder: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No invented value: an obvious placeholder plus the command that prints the real path."""
    monkeypatch.setattr(cli, "resolve_executable_path", lambda: None)

    cli._print_claude_desktop_block("prod", cast(Locale, locale))

    captured = capsys.readouterr()
    block = json.loads(captured.out)
    assert block["mcpServers"]["netezza"]["command"] == placeholder
    # Even in the degraded branch the redirected file stays parsable: the explanation of how
    # to get the real path is a message to the person, so it goes to stderr.
    assert cli._how_to_find_executable() in captured.err


def test_the_redirected_block_is_a_parsable_file(tmp_path: Path) -> None:
    """Redirect the block to a file in a real process: it must be JSON and nothing else.

    This is the reason the block stays on stdout while its heading moves to stderr. Run in a
    subprocess rather than in-process so the split is exercised at the operating-system level,
    the way ``nz-mcp init > block.json`` does it.
    """
    root = Path(__file__).resolve().parents[2]
    target = tmp_path / "block.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["NZ_MCP_LANG"] = "es"
    with target.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from nz_mcp.cli import _print_claude_desktop_block as p; p('prod', 'es')",
            ],
            check=False,
            stdout=handle,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=60,
            cwd=root,
            env=env,
        )

    assert proc.returncode == 0, proc.stderr
    block = json.loads(target.read_text(encoding="utf-8"))
    assert block["mcpServers"]["netezza"]["env"]["NZ_MCP_PROFILE"] == "prod"
    assert "claude_desktop_config.json" in proc.stderr, "the heading did not go to stderr"
    assert "claude_desktop_config.json" not in target.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("os_name", "expected"), [("nt", "where.exe nz-mcp"), ("posix", "which nz-mcp")]
)
def test_the_command_to_find_the_path_matches_the_platform(
    os_name: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "name", os_name)
    assert cli._how_to_find_executable() == expected
