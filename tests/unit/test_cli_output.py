"""Unit tests for the CLI output layer (issue #203): channel, colour and terminal detection.

Also home of the level-0 contract of ADR 0031 (issue #236): the tests at the bottom pin
what the floor draws, character by character. No later PR may "adapt" them - if one of them
fails, a higher level has leaked into the floor.
"""

from __future__ import annotations

import ctypes
import io
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from nz_mcp import cli_output

_ESC: Final[str] = "\x1b["

#: Highest code point the floor may emit: printable ASCII. Structural on purpose - this
#: project has watched two barriers fail on the same day for banning things by name.
_LAST_ASCII: Final[int] = 126


class _FakeStream:
    """Minimal stand-in for a stream whose ``isatty`` answer we control."""

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class _FakeTerminal(io.StringIO):
    """A stream that answers ``isatty`` as told and keeps whatever is written to it."""

    def __init__(self, *, tty: bool) -> None:
        super().__init__()
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


def test_table_returns_text_and_writes_to_neither_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The renderer hands the text back; the caller decides the channel.

    That is what keeps condition 1 of ADR 0027 — precised by its addendum 1 to *no console
    writes to stdout* — true by construction: the only ``rich`` console this project builds
    targets a memory buffer and owns no file descriptor, so it cannot put a byte on the
    stdout that ``serve`` speaks JSON-RPC over.
    """
    # No dotted host name in the cells: CodeQL reads ``"a.b.com" in text`` as a URL check
    # done by substring, and a false alarm in a test is still a blocked pipeline.
    rendered = cli_output.table(["Perfil", "Host"], [["prod", "nz-prod-01"]])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "prod" in rendered
    assert "nz-prod-01" in rendered


def test_table_aligns_its_columns() -> None:
    """Alignment is the whole point: a column you cannot scan is a list with extra bars."""
    rendered = cli_output.table(["A", "B"], [["short", "1"], ["much-longer-value", "2"]])
    bar_positions = {line.index("|") for line in rendered.splitlines() if "|" in line}
    assert len(bar_positions) == 1


@pytest.mark.parametrize("code_page", ["cp437", "cp850"])
def test_table_frame_is_drawable_on_a_legacy_windows_console(code_page: str) -> None:
    """``rich`` would pick Unicode box characters, which print as "?" on those code pages."""
    rendered = cli_output.table(["Modo"], [["read"]])
    rendered.encode(code_page)


def test_table_carries_no_colour_and_no_trailing_blanks() -> None:
    """Colour would be the only carrier of meaning for whoever sees it, and padding is noise.

    Trailing spaces matter because this text is payload: it ends up in redirected files and
    in issue reports, where invisible characters are pure cost.
    """
    rendered = cli_output.table(["A", "B"], [["x", "y"], ["longer", ""]])
    assert _ESC not in rendered
    assert all(line == line.rstrip() for line in rendered.splitlines())


def test_reserving_stdout_turns_a_stray_payload_write_into_a_loud_error() -> None:
    """In serve mode a payload write is a corrupted protocol; it must raise, not print."""
    assert cli_output.stdout_is_reserved() is False
    with cli_output.stdout_reserved_for_protocol():
        assert cli_output.stdout_is_reserved() is True
        with pytest.raises(RuntimeError, match="reserved for MCP JSON-RPC"):
            cli_output.emit("this would break Claude Desktop")


def test_the_reservation_gives_the_descriptors_back_on_exit() -> None:
    """It is a context manager on purpose: a test suite must not lose its stdout."""
    before = os.dup(1)
    try:
        with cli_output.stdout_reserved_for_protocol():
            pass
        assert cli_output.stdout_is_reserved() is False
        assert os.fstat(1).st_ino == os.fstat(before).st_ino
    finally:
        os.close(before)


def test_status_still_works_after_stdout_is_reserved(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with cli_output.stdout_reserved_for_protocol():
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


# --- terminal_level(): the capability question of ADR 0031 ---------------------


def a_modern_terminal(monkeypatch: pytest.MonkeyPatch) -> _FakeStream:
    """Set every signal to the value that gives level 1, and return a terminal stream.

    Each level-0 test below starts from here and flips exactly one signal, so that none of
    them passes because a different signal fired. The terminfo lookup is stubbed, as in the
    gate tests, so this answers the same on every runner; ``CI`` is cleared because every
    runner sets it, and ``WT_SESSION`` is set because a Windows runner is not Windows
    Terminal.
    """
    monkeypatch.delenv(cli_output.UI_LEVEL_ENV, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("WT_SESSION", "1")
    monkeypatch.setattr(cli_output, "_terminfo_declares_full_screen", lambda _term: True)
    return _FakeStream(tty=True)


def test_a_modern_terminal_is_level_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline. Without it every level-0 test below could pass for the wrong reason."""
    stream = a_modern_terminal(monkeypatch)
    assert cli_output.terminal_level(stream) == 1


def test_the_default_stream_is_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Level is asked of the channel this layer draws on, like ``color_enabled``."""
    a_modern_terminal(monkeypatch)
    monkeypatch.setattr(sys, "stderr", _FakeStream(tty=True))
    assert cli_output.terminal_level() == 1
    monkeypatch.setattr(sys, "stderr", _FakeStream(tty=False))
    assert cli_output.terminal_level() == 0


def _no_color_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")


def _no_color_present_but_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "")


def _term_dumb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "dumb")


def _ci_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")


def _posix_term_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("TERM", "")


def _posix_term_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.delenv("TERM")


def _posix_term_unknown_to_terminfo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("TERM", "banana-9000")
    monkeypatch.setattr(cli_output, "_terminfo_declares_full_screen", lambda _term: False)


def _windows_console_on_a_legacy_code_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("WT_SESSION")
    monkeypatch.setattr(cli_output, "_console_output_code_page", lambda: 850)


def _windows_console_without_a_code_page_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("WT_SESSION")
    monkeypatch.setattr(cli_output, "_console_output_code_page", lambda: None)


@pytest.mark.parametrize(
    "signal",
    [
        pytest.param(_no_color_set, id="no-color"),
        pytest.param(_no_color_present_but_empty, id="no-color-empty"),
        pytest.param(_term_dumb, id="term-dumb"),
        pytest.param(_ci_present, id="ci"),
        pytest.param(_posix_term_empty, id="posix-term-empty"),
        pytest.param(_posix_term_unset, id="posix-term-unset"),
        pytest.param(_posix_term_unknown_to_terminfo, id="posix-term-unknown"),
        pytest.param(_windows_console_on_a_legacy_code_page, id="windows-cp850"),
        pytest.param(_windows_console_without_a_code_page_answer, id="windows-no-answer"),
    ],
)
def test_each_signal_alone_brings_a_modern_terminal_down_to_level_0(
    monkeypatch: pytest.MonkeyPatch, signal: Callable[[pytest.MonkeyPatch], None]
) -> None:
    """One test per signal of ADR 0031, point 2, each from an environment that gives 1."""
    stream = a_modern_terminal(monkeypatch)
    signal(monkeypatch)
    assert cli_output.terminal_level(stream) == 0


def test_a_stream_that_is_not_a_terminal_is_level_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Signal 5: redirection, pipe, CI without ``CI``. The case ADR 0027 protected."""
    a_modern_terminal(monkeypatch)
    assert cli_output.terminal_level(_FakeStream(tty=False)) == 0
    assert cli_output.terminal_level(object()) == 0  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("hosted_by_windows_terminal", "code_page"),
    [
        pytest.param(False, 65001, id="utf-8-console"),
        pytest.param(True, 850, id="windows-terminal-on-cp850"),
    ],
)
def test_either_windows_fact_is_enough_for_level_1(
    monkeypatch: pytest.MonkeyPatch, hosted_by_windows_terminal: bool, code_page: int
) -> None:
    """Windows Terminal or code page 65001: one of the two says Unicode arrives whole."""
    stream = a_modern_terminal(monkeypatch)
    monkeypatch.setattr(os, "name", "nt")
    if not hosted_by_windows_terminal:
        monkeypatch.delenv("WT_SESSION")
    monkeypatch.setattr(cli_output, "_console_output_code_page", lambda: code_page)
    assert cli_output.terminal_level(stream) == 1


def test_posix_never_asks_the_windows_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """The code page lookup is off the common path: on POSIX there is nothing to ask."""

    def explode() -> int:
        raise AssertionError("the Windows console API was consulted on POSIX")

    stream = a_modern_terminal(monkeypatch)
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.delenv("WT_SESSION")
    monkeypatch.setattr(cli_output, "_console_output_code_page", explode)
    assert cli_output.terminal_level(stream) == 1


class _Kernel32:
    def __init__(self, answer: Callable[[], int]) -> None:
        self.GetConsoleOutputCP = answer


class _WindowsLibraries:
    def __init__(self, answer: Callable[[], int]) -> None:
        self.kernel32 = _Kernel32(answer)


def test_the_code_page_lookup_reads_the_console_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real helper, against a stand-in of ``ctypes.windll``, on every platform."""
    monkeypatch.setattr(ctypes, "windll", _WindowsLibraries(lambda: 65001), raising=False)
    assert cli_output._console_output_code_page() == 65001


def test_the_code_page_lookup_answers_none_without_a_console_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``windll`` at all - POSIX - or an API call that fails: ``None``, never a crash."""
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert cli_output._console_output_code_page() is None

    def refuse() -> int:
        raise OSError("no console attached")

    monkeypatch.setattr(ctypes, "windll", _WindowsLibraries(refuse), raising=False)
    assert cli_output._console_output_code_page() is None


@pytest.mark.skipif(os.name != "nt", reason="the console API only exists on Windows")
def test_the_code_page_lookup_answers_about_the_real_console() -> None:
    """The stand-in above has to stand for something real: on Windows, an integer or None."""
    answer = cli_output._console_output_code_page()
    assert answer is None or isinstance(answer, int)


# --- NZ_MCP_UI_LEVEL: the escape hatch, in both directions ---------------------


def test_the_override_forces_the_floor_on_a_modern_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = a_modern_terminal(monkeypatch)
    monkeypatch.setenv(cli_output.UI_LEVEL_ENV, "0")
    assert cli_output.terminal_level(stream) == 0


def test_the_override_raises_the_level_where_detection_gave_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half an escape hatch is none: ``1`` has to work on a terminal the heuristics reject."""
    a_modern_terminal(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv(cli_output.UI_LEVEL_ENV, " 1 ")
    assert cli_output.terminal_level(_FakeStream(tty=False)) == 1


def test_the_override_wins_over_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0031, point 3: a variable that names this program beats a global convention."""
    stream = a_modern_terminal(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv(cli_output.UI_LEVEL_ENV, "1")
    assert cli_output.terminal_level(stream) == 1


@pytest.mark.parametrize("value", ["2", "si", "true", "", "  ", "01", "1.0", "-1"])
def test_an_invalid_override_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """No exception, no invented level: the detection runs as if nothing had been set.

    ``2`` is on the list on purpose - level 2 has its own gate and this function cannot
    grant it - and so is a value that would parse as an integer but is not a spelling.
    """
    stream = a_modern_terminal(monkeypatch)
    monkeypatch.setenv(cli_output.UI_LEVEL_ENV, value)
    assert cli_output.terminal_level(stream) == 1
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli_output.terminal_level(stream) == 0


# --- colour and motion keep their own truth --------------------------------------


def test_colour_and_motion_are_not_the_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """``color_enabled`` and ``animation_enabled`` answer exactly what they answered before.

    Neither is re-expressed on ``terminal_level``, and this pins why that would have changed
    their truth: on a real terminal ``CI`` is not a reason to drop colour or motion, and
    ``NO_COLOR`` is not a reason to freeze the indicator - yet both give level 0.
    """
    stream = a_modern_terminal(monkeypatch)

    monkeypatch.setenv("CI", "true")
    assert cli_output.terminal_level(stream) == 0
    assert cli_output.color_enabled(stream) is True
    assert cli_output.animation_enabled(stream) is True

    monkeypatch.delenv("CI")
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli_output.terminal_level(stream) == 0
    assert cli_output.color_enabled(stream) is False
    assert cli_output.animation_enabled(stream) is True


# --- level 0 is a contract: what the floor draws, character by character ----------
#
# Reference text captured from ``main`` before ``terminal_level()`` existed. If one of these
# assertions fails, a higher level has leaked into the floor; the fix is in the code that
# leaked, never in the strings below.


def _assert_is_floor_output(text: str) -> None:
    """The structural half of the contract: no escape sequence, nothing outside ASCII."""
    assert "\x1b" not in text
    assert all(ord(char) <= _LAST_ASCII for char in text), text


def _the_floor(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> _FakeTerminal:
    """Level 0 the way a person meets it: a pipe, or a terminal with ``NO_COLOR``."""
    monkeypatch.delenv(cli_output.UI_LEVEL_ENV, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    if tty:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    stream = _FakeTerminal(tty=tty)
    monkeypatch.setattr(sys, "stderr", stream)
    assert cli_output.terminal_level() == 0
    return stream


def test_level_0_table_is_exactly_what_main_drew() -> None:
    """The three shapes of ``table()``: columns, a middle cut, and ``key: value`` blocks."""
    rows = [["prod", "nz-prod-01", "read", "OK"], ["dev", "nz-dev-01", "write", ""]]
    wide = cli_output.table(["Perfil", "Host", "Modo", "Activo"], rows, width=80)
    assert wide == (
        "Perfil | Host       | Modo  | Activo\n"
        "-------+------------+-------+-------\n"
        "prod   | nz-prod-01 | read  | OK\n"
        "dev    | nz-dev-01  | write |"
    )
    squeezed = cli_output.table(
        ["Perfil", "Host"], [["prod", "nz-prod-01-with-a-very-long-name"]], width=24
    )
    assert squeezed == "Perfil | Host\n-------+----------------\nprod   | nz-pro...g-name"
    records = cli_output.table(["Perfil", "Host"], [["prod", "nz-prod-01"]], width=10)
    assert records == "Perfil: prod\nHost: nz-prod-01"
    for rendered in (wide, squeezed, records):
        _assert_is_floor_output(rendered)


def test_level_0_status_lines_are_exactly_what_main_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``heading`` and every ``status`` style: the words, a newline, and nothing else.

    Bold is an escape sequence too (ADR 0031, point 8): a heading on the floor is the word.
    """
    stream = _the_floor(monkeypatch, tty=False)
    cli_output.heading("Perfiles")
    cli_output.status("linea")
    cli_output.success("bien")
    cli_output.warn("ojo")
    cli_output.fail("mal")
    assert stream.getvalue() == "Perfiles\nlinea\nbien\nojo\nmal\n"
    _assert_is_floor_output(stream.getvalue())

    stream = _the_floor(monkeypatch, tty=True)
    cli_output.heading("Perfiles")
    cli_output.fail("mal")
    assert stream.getvalue() == "Perfiles\nmal\n"
    _assert_is_floor_output(stream.getvalue())


def test_level_0_indicators_write_nothing_without_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``progress`` and ``steps`` into a pipe: not one byte, exactly as before."""
    stream = _the_floor(monkeypatch, tty=False)
    with cli_output.progress("esperando"):
        pass
    with cli_output.steps(3) as advance:
        advance(1, "uno")
    assert stream.getvalue() == ""


def test_level_0_steps_frames_are_exactly_what_main_drew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a terminal without colour the bar is ``#`` and ``-`` over a carriage return."""
    stream = _the_floor(monkeypatch, tty=True)
    with cli_output.steps(3) as advance:
        advance(1, "uno")
        advance(2, "dos largo")
    assert stream.getvalue() == (
        "\r[#######-------------] 1/3 uno"
        "\r[#############-------] 2/3 dos largo"
        "\r                                    \r"
    )
    _assert_is_floor_output(stream.getvalue())


def test_level_0_spinner_frames_are_ascii() -> None:
    """The one surface whose timing a unit test cannot pin: its frames, then, are."""
    for frame in cli_output._SPINNER_FRAMES:
        _assert_is_floor_output(frame)
