"""``nz-mcp list-profiles`` (issue #169): where each profile points, and which one is used.

The command used to print names and nothing else, so with two profiles configured there was
no way to tell which one an assistant would use, or what it pointed at — which is exactly the
question worth answering before letting a model write to a database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from nz_mcp.cli import app

runner = CliRunner()

_ESC: Final[str] = "\x1b["

_THREE_PROFILES: Final[str] = (
    'active = "prod"\n'
    "\n[profiles.prod]\n"
    'host = "nz-prod.example.com"\nport = 5480\n'
    'database = "RETAIL"\nuser = "svc_prod"\nmode = "read"\n'
    "\n[profiles.lab]\n"
    'host = "10.0.0.5"\nport = 5480\n'
    'database = "SANDBOX"\nuser = "dev"\nmode = "write"\n'
    "\n[profiles.broken]\n"
    'host = "half-configured.example.com"\nport = 5480\n'
    'database = "X"\nuser = "u"\nmode = "read"\n'
)

_ONE_PROFILE: Final[str] = (
    "[profiles.solo]\n"
    'host = "nz-solo.example.com"\nport = 5480\n'
    'database = "ONLY"\nuser = "svc"\nmode = "admin"\n'
)


def _rows(body: str) -> dict[str, list[str]]:
    """Split the rendered table into cells, keyed by the value of its first column."""
    rows: dict[str, list[str]] = {}
    for line in body.splitlines():
        if "|" not in line or set(line) <= set("-+"):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        rows[cells[0]] = cells
    return rows


def test_with_no_profiles_it_says_how_to_create_one(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """An empty list is a dead end unless it names the command that fills it."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    assert "nz-mcp init" in result.stderr
    assert result.stdout == ""


def test_a_single_profile_is_shown_as_key_and_value(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """One row has nothing to compare itself against, so a table would be all borders."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    tmp_profiles.write_text(_ONE_PROFILE, encoding="utf-8")
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    # Whole lines, not substrings: it says more, and it keeps the host out of the kind of
    # ``"a.b.com" in text`` expression CodeQL reads as a URL check done by substring.
    assert result.stdout.splitlines() == [
        "Perfil: solo",
        "Host: nz-solo.example.com",
        "Base de datos: ONLY",
        "Modo: admin",
    ]
    # With one profile there is nothing to switch to: the next step is to prove it works.
    assert "nz-mcp test-connection" in result.stderr


def test_several_profiles_are_shown_as_a_table_marking_the_active_one(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    tmp_profiles.write_text(_THREE_PROFILES, encoding="utf-8")
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0

    rows = _rows(result.stdout)
    assert {"Perfil", "prod", "lab", "broken"} <= set(rows)
    # Cell by cell rather than "is this substring in the line": the assertion is sharper, and
    # CodeQL reads ``"a.b.com" in text`` as a URL check done by substring and blocks the merge.
    assert rows["prod"] == ["prod", "nz-prod.example.com", "RETAIL", "read", "*"]
    # The marker is text, so it survives a redirect and a terminal without colour.
    assert rows["lab"][-1] == ""


def test_the_active_profile_marked_is_the_one_the_server_would_use(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """``NZ_MCP_PROFILE`` beats no ``active`` field, and the mark has to agree.

    Two answers to "which profile is in use" would be one too many, so the command asks the
    same helper ``get_active_profile`` asks instead of re-deriving the rule.
    """
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    monkeypatch.setenv("NZ_MCP_PROFILE", "lab")
    tmp_profiles.write_text(_THREE_PROFILES.replace('active = "prod"\n', ""), encoding="utf-8")
    result = runner.invoke(app, ["list-profiles"])
    rows = _rows(result.stdout)
    assert rows["lab"][-1] == "*"
    assert rows["prod"][-1] == ""


def test_a_profile_missing_a_field_still_gets_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """Sections are read raw, not validated: this command is how you notice a broken one.

    Validating here would mean a single hand-edited profile without a host aborts the listing,
    hiding the other profiles and the very problem the person is looking for.
    """
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    tmp_profiles.write_text(_THREE_PROFILES.replace('host = "10.0.0.5"\n', ""), encoding="utf-8")
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    rows = _rows(result.stdout)
    assert rows["lab"] == ["lab", "-", "SANDBOX", "write", ""]


def _run_cli(args: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    """Run the real CLI with both streams piped: no terminal, whatever the environment begs for."""
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["NZ_MCP_HOME"] = str(home)
    env["NZ_MCP_LANG"] = "es"
    env["PYTHONIOENCODING"] = "utf-8"
    env["TERM"] = "xterm-256color"
    env["FORCE_COLOR"] = "1"
    env.pop("NO_COLOR", None)
    env.pop("NZ_MCP_PROFILE", None)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "nz_mcp", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=root,
        env=env,
    )


def test_the_table_is_plain_text_when_redirected(tmp_path: Path) -> None:
    """In a subprocess, not with an in-memory capture: only a real pipe proves this.

    ``FORCE_COLOR`` and a colour-capable ``TERM`` are set on purpose. An environment begging
    for colour must not put a single escape sequence in a redirected file.
    """
    home = tmp_path / "nz-mcp"
    home.mkdir()
    (home / "profiles.toml").write_text(_THREE_PROFILES, encoding="utf-8")
    proc = _run_cli(["list-profiles"], home)
    assert proc.returncode == 0, proc.stderr
    assert _ESC not in proc.stdout
    assert _ESC not in proc.stderr
    assert "RETAIL" in proc.stdout


def test_the_table_uses_only_characters_a_legacy_console_can_draw(tmp_path: Path) -> None:
    """A Windows console on cp437 or cp850 turns the fancy box characters into "?"."""
    home = tmp_path / "nz-mcp"
    home.mkdir()
    (home / "profiles.toml").write_text(_THREE_PROFILES, encoding="utf-8")
    body = _run_cli(["list-profiles"], home).stdout
    frame = "".join(character for character in body if character in "|-+")
    assert frame, "the table lost its frame"
    for code_page in ("cp437", "cp850"):
        body.encode(code_page)
