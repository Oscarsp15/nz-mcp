"""Unit tests for the CLI output layer (issue #203): channel, colour and terminal detection."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from nz_mcp import cli_output

_ESC: Final[str] = "\x1b["


class _FakeStream:
    """Minimal stand-in for a stream whose ``isatty`` answer we control."""

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _clear_color_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")


def test_emit_writes_payload_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    cli_output.emit("0.1.0")
    captured = capsys.readouterr()
    assert captured.out == "0.1.0\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    "writer",
    [cli_output.note, cli_output.heading, cli_output.success, cli_output.warn, cli_output.fail],
)
def test_every_status_writer_uses_stderr(
    writer: object, capsys: pytest.CaptureFixture[str]
) -> None:
    assert callable(writer)
    writer("hola")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hola" in captured.err


def test_color_is_enabled_only_on_a_real_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_color_env(monkeypatch)
    assert cli_output.color_enabled(_FakeStream(tty=True)) is True
    assert cli_output.color_enabled(_FakeStream(tty=False)) is False


def test_no_color_env_disables_color_even_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli_output.color_enabled(_FakeStream(tty=True)) is False


def test_dumb_terminal_disables_color(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_color_env(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    assert cli_output.color_enabled(_FakeStream(tty=True)) is False


def test_status_is_plain_text_when_color_is_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_output, "color_enabled", lambda *_args: False)
    cli_output.fail("algo ha fallado")
    assert _ESC not in capsys.readouterr().err


def test_status_is_styled_when_color_is_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_output, "color_enabled", lambda *_args: True)
    cli_output.fail("algo ha fallado")
    assert _ESC in capsys.readouterr().err


def test_reserving_stdout_turns_a_stray_payload_write_into_a_loud_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In serve mode a payload write is a corrupted protocol; it must raise, not print."""
    monkeypatch.setitem(cli_output._STATE, "stdout_reserved", False)
    assert cli_output.stdout_is_reserved() is False
    cli_output.reserve_stdout_for_protocol()
    assert cli_output.stdout_is_reserved() is True
    with pytest.raises(RuntimeError, match="reserved for MCP JSON-RPC"):
        cli_output.emit("this would break Claude Desktop")


def test_status_still_works_after_stdout_is_reserved(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(cli_output._STATE, "stdout_reserved", False)
    cli_output.reserve_stdout_for_protocol()
    cli_output.warn("stderr sigue disponible")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "stderr sigue disponible" in captured.err


def _run_cli(args: list[str], home: Path, *, force_color: bool) -> subprocess.CompletedProcess[str]:
    """Run a CLI command with both streams piped — i.e. redirected, never a terminal."""
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["NZ_MCP_HOME"] = str(home)
    env["NZ_MCP_LANG"] = "es"
    # Spanish messages carry non-ASCII; without this the child would use the legacy
    # Windows code page and the parent could not decode what it wrote.
    env["PYTHONIOENCODING"] = "utf-8"
    env["TERM"] = "xterm-256color"
    env.pop("NO_COLOR", None)
    if force_color:
        env["FORCE_COLOR"] = "1"
    else:
        env.pop("FORCE_COLOR", None)
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


@pytest.mark.parametrize("args", [["version"], ["doctor"], ["list-profiles"]])
def test_redirected_output_never_contains_ansi(args: list[str], tmp_path: Path) -> None:
    """Piped output is plain text even with FORCE_COLOR and a colour-capable TERM set.

    The output layer decides colour from the terminal, ``NO_COLOR`` and ``TERM`` only: an
    environment that begs for colour cannot put escape sequences in a redirected file.
    """
    proc = _run_cli(args, tmp_path, force_color=True)
    assert _ESC not in proc.stdout, f"ANSI on stdout of {args}"
    assert _ESC not in proc.stderr, f"ANSI on stderr of {args}"


# ``--help`` is deliberately absent from the list above: typer renders it with its own
# machinery, which forces terminal mode on CI regardless of redirection, so asserting on it
# would test typer instead of this layer. Rewriting the help text is issue #208.
