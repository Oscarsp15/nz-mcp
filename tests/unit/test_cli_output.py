"""Unit tests for the CLI output layer (issue #203): channel, colour and terminal detection.

Also home of the level-0 contract of ADR 0031 (issue #236): the tests at the bottom pin
what the floor draws, character by character. No later PR may "adapt" them - if one of them
fails, a higher level has leaked into the floor.
"""

from __future__ import annotations

import atexit
import contextlib
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
    """``status`` is gated by :func:`terminal_level` now (ADR 0031, point 8, trap 2), which is
    the strict superset of what :func:`color_enabled` checks - see
    ``test_a_ci_terminal_with_a_pty_still_draws_the_floor`` for the case that made the switch
    necessary. Forcing the level to 0 is what this test now has to do to keep meaning what its
    name says.
    """
    monkeypatch.setattr(cli_output, "terminal_level", lambda *_args: 0)
    cli_output.fail("algo ha fallado")
    assert _ESC not in capsys.readouterr().err


def test_status_is_styled_when_color_is_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_output, "terminal_level", lambda *_args: 1)
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


# --- prepare_windows_console: ADR 0033, issue #255 ------------------------------


class _FakeKernel32:
    """A stand-in for ``kernel32`` with just enough state to prove what changed and back.

    ``GetStdHandle`` hands back the ``nStdHandle`` constant itself as the "handle" - there
    is nothing in this test that needs it to look like a real pointer, only that the same
    value threads through ``GetConsoleMode``/``SetConsoleMode`` for the same stream.

    Each Win32 name is a **plain function** assigned in ``__init__``, not a bound method:
    ``_prepare_windows_console`` sets ``.restype``/``.argtypes`` on what it looks up, which
    is exactly what a real ``ctypes`` function pointer allows and a bound method does not.
    """

    def __init__(self, *, output_cp: int = 850) -> None:
        self.output_cp = output_cp
        self.set_output_cp_calls: list[int] = []
        self.set_mode_calls: list[tuple[int, int]] = []
        self._modes: dict[int, int] = {
            cli_output._STD_OUTPUT_HANDLE: 0x1,
            cli_output._STD_ERROR_HANDLE: 0x1,
        }

        def get_console_output_cp() -> int:
            return self.output_cp

        def set_console_output_cp(code_page: int) -> int:
            self.set_output_cp_calls.append(code_page)
            self.output_cp = code_page
            return 1

        def get_std_handle(std_handle: int) -> int:
            return std_handle

        def get_console_mode(handle: int, mode_ptr: ctypes._Pointer[ctypes.c_uint32]) -> int:
            mode_ptr.contents.value = self._modes[handle]
            return 1

        def set_console_mode(handle: int, mode: int) -> int:
            self.set_mode_calls.append((handle, mode))
            self._modes[handle] = mode
            return 1

        self.GetConsoleOutputCP = get_console_output_cp
        self.SetConsoleOutputCP = set_console_output_cp
        self.GetStdHandle = get_std_handle
        self.GetConsoleMode = get_console_mode
        self.SetConsoleMode = set_console_mode


class _Windll:
    def __init__(self, kernel32: object) -> None:
        self.kernel32 = kernel32


class _FakeReconfigurableStream:
    """A stream whose ``isatty`` is controlled and whose ``reconfigure`` calls are recorded."""

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty
        self.reconfigure_calls: list[dict[str, object]] = []

    def isatty(self) -> bool:
        return self._tty

    def reconfigure(self, **kwargs: object) -> None:
        self.reconfigure_calls.append(kwargs)


def _windows_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_FakeKernel32, _FakeReconfigurableStream, _FakeReconfigurableStream]:
    """A Windows process with a real console attached on both standard streams."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv(cli_output.NO_CONSOLE_PREP_ENV, raising=False)
    kernel32 = _FakeKernel32()
    monkeypatch.setattr(ctypes, "windll", _Windll(kernel32), raising=False)
    stdout = _FakeReconfigurableStream(tty=True)
    stderr = _FakeReconfigurableStream(tty=True)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    return kernel32, stdout, stderr


def test_prepare_windows_console_is_a_noop_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    """POSIX never asks ``_prepare_windows_console`` anything - and never imports ``ctypes``."""

    def explode() -> Callable[[], None] | None:
        raise AssertionError("the Windows console API was consulted on POSIX")

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(cli_output, "_prepare_windows_console", explode)
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()
    assert registered == []


def test_prepare_windows_console_skips_a_redirected_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows, but neither stream is a real console: nothing is touched."""
    kernel32, _, _ = _windows_terminal(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _FakeReconfigurableStream(tty=False))
    monkeypatch.setattr(sys, "stderr", _FakeReconfigurableStream(tty=False))
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()
    assert kernel32.set_output_cp_calls == []
    assert registered == []


@pytest.mark.parametrize("value", ["1", "true", "yes", "anything"])
def test_prepare_windows_console_respects_the_escape_hatch(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    kernel32, _, _ = _windows_terminal(monkeypatch)
    monkeypatch.setenv(cli_output.NO_CONSOLE_PREP_ENV, value)
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()
    assert kernel32.set_output_cp_calls == []
    assert registered == []


@pytest.mark.parametrize("value", ["0", "false", "False", " "])
def test_the_escape_hatch_spellings_that_do_not_opt_out(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Same convention as ``NZ_MCP_NO_TUI``: only these two spellings mean "no"."""
    kernel32, _, _ = _windows_terminal(monkeypatch)
    monkeypatch.setenv(cli_output.NO_CONSOLE_PREP_ENV, value)
    cli_output.prepare_windows_console()
    assert kernel32.set_output_cp_calls == [cli_output._UTF8_CODE_PAGE]


def test_prepare_windows_console_swallows_a_console_api_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permissions, a console that vanished mid-call: caught, never raised, level 0 stands."""
    kernel32, stdout, stderr = _windows_terminal(monkeypatch)

    def refuse(_code_page: int) -> int:
        raise OSError("no console attached")

    kernel32.SetConsoleOutputCP = refuse  # type: ignore[assignment]
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()  # must not raise
    assert registered == []
    assert stdout.reconfigure_calls == []
    assert stderr.reconfigure_calls == []


def test_prepare_windows_console_tolerates_a_missing_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older ``kernel32`` build without one of the five calls: nothing raises either."""
    kernel32, _, _ = _windows_terminal(monkeypatch)
    kernel32.SetConsoleMode = None  # type: ignore[assignment]
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()
    assert registered == []


def test_prepare_windows_console_tolerates_a_missing_kernel32(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``ctypes.windll`` with no ``kernel32`` at all - nothing raises."""
    _windows_terminal(monkeypatch)
    monkeypatch.setattr(ctypes, "windll", object(), raising=False)
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()
    assert registered == []


def test_prepare_windows_console_returns_none_when_the_code_page_write_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SetConsoleOutputCP`` can fail by returning falsy, not only by raising."""
    kernel32, _, _ = _windows_terminal(monkeypatch)
    kernel32.SetConsoleOutputCP = lambda code_page: 0
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()
    assert registered == []


def test_prepare_windows_console_continues_past_a_mode_read_failure_on_one_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One handle refuses ``GetConsoleMode``: the other is still prepared, nothing raises."""
    kernel32, _, _ = _windows_terminal(monkeypatch)
    real_get_mode = kernel32.GetConsoleMode

    def flaky_get_mode(handle: int, mode_ptr: ctypes._Pointer[ctypes.c_uint32]) -> int:
        if handle == cli_output._STD_ERROR_HANDLE:
            return 0
        return real_get_mode(handle, mode_ptr)

    kernel32.GetConsoleMode = flaky_get_mode
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)

    cli_output.prepare_windows_console()

    touched_handles = {handle for handle, _mode in kernel32.set_mode_calls}
    assert touched_handles == {cli_output._STD_OUTPUT_HANDLE}
    assert len(registered) == 1


def test_prepare_windows_console_does_not_restore_a_mode_it_never_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SetConsoleMode`` refusing one handle is not remembered as "changed"."""
    kernel32, _, _ = _windows_terminal(monkeypatch)
    real_set_mode = kernel32.SetConsoleMode

    def flaky_set_mode(handle: int, mode: int) -> int:
        if handle == cli_output._STD_ERROR_HANDLE:
            return 0
        return real_set_mode(handle, mode)

    kernel32.SetConsoleMode = flaky_set_mode
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)

    cli_output.prepare_windows_console()
    (restore,) = registered
    calls_before_restore = len(kernel32.set_mode_calls)
    restore()

    # Only the handle that was actually changed gets a restoring ``SetConsoleMode`` call.
    assert len(kernel32.set_mode_calls) == calls_before_restore + 1


def test_prepare_windows_console_enables_vt_and_utf8_and_reconfigures_the_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32, stdout, stderr = _windows_terminal(monkeypatch)
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)

    cli_output.prepare_windows_console()

    assert kernel32.set_output_cp_calls == [cli_output._UTF8_CODE_PAGE]
    touched_handles = {handle for handle, _mode in kernel32.set_mode_calls}
    assert touched_handles == {cli_output._STD_OUTPUT_HANDLE, cli_output._STD_ERROR_HANDLE}
    for _handle, mode in kernel32.set_mode_calls:
        assert mode & cli_output._ENABLE_VIRTUAL_TERMINAL_PROCESSING
    assert stdout.reconfigure_calls == [{"encoding": "utf-8"}]
    assert stderr.reconfigure_calls == [{"encoding": "utf-8"}]
    assert len(registered) == 1


def test_prepare_windows_console_restore_undoes_exactly_what_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callable handed to ``atexit`` puts the code page and both modes back.

    Called directly, standing in for the interpreter shutdown that would otherwise call
    it - the same technique the rest of this suite uses to test a callback without
    opening a real terminal or a real process exit.
    """
    kernel32, _, _ = _windows_terminal(monkeypatch)
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)

    cli_output.prepare_windows_console()
    assert kernel32.output_cp == cli_output._UTF8_CODE_PAGE
    (restore,) = registered

    restore()

    assert kernel32.output_cp == 850
    assert kernel32.set_mode_calls[-2:] == [
        (cli_output._STD_OUTPUT_HANDLE, 0x1),
        (cli_output._STD_ERROR_HANDLE, 0x1),
    ]


def test_restoration_does_not_depend_on_the_command_finishing_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The restore callback is captured before the command runs, so a raised exception -
    or a ``Ctrl+C`` that becomes an uncaught ``KeyboardInterrupt`` - cannot prevent it from
    existing. This does not open a real interpreter shutdown; it proves the callback was
    registered *before* the command had a chance to fail, and that calling it afterwards
    still restores everything.
    """
    kernel32, _, _ = _windows_terminal(monkeypatch)
    registered: list[Callable[[], None]] = []
    monkeypatch.setattr(atexit, "register", registered.append)
    cli_output.prepare_windows_console()
    (restore,) = registered

    with contextlib.suppress(RuntimeError):
        try:
            raise RuntimeError("the command blew up")
        finally:
            pass  # the command's own cleanup, not this function's - restore is atexit's job

    restore()
    assert kernel32.output_cp == 850


# Deliberately no test here calls ``prepare_windows_console()`` against the real console.
# Unlike ``_console_output_code_page()``, which only reads, a successful real call writes
# process-wide state - the console code page, both console modes, and ``sys.stdout`` /
# ``sys.stderr`` themselves - and registers a real ``atexit`` callback nothing in this test
# session would trigger. On a Windows runner whose own stdout is a real console, doing that
# from inside the suite corrupts every test that runs afterwards in the same process; this
# was caught by the pre-merge full-suite run, not by the file in isolation, which is exactly
# why it is written down here instead of tried again differently.


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


# --- level 1 draws colour, a rounded frame and a fluid indicator (issue #237) --------
#
# The level-0 contract above is never touched by any of this: every test here either passes
# ``level=1`` explicitly or forces ``terminal_level`` to 1, so none of it can pass for the
# wrong reason - the same discipline ``a_modern_terminal`` uses above for the detector itself.


def test_table_level_1_uses_a_rounded_frame_and_an_accented_header() -> None:
    """ADR 0031, point 5: rounded border, accent on the header and the frame."""
    rendered = cli_output.table(["Perfil", "Modo"], [["prod", "read"]], width=40, level=1)
    assert _ESC in rendered, "level 1 must colour the header and the frame"
    assert "\N{BOX DRAWINGS LIGHT ARC DOWN AND RIGHT}" in rendered  # "╭"
    assert "prod" in rendered
    assert "read" in rendered


def test_table_level_0_is_unaffected_by_the_new_parameter() -> None:
    """The default is 0, and passing it explicitly draws exactly what omitting it always drew."""
    without_level = cli_output.table(["Perfil"], [["prod"]], width=20)
    with_level_0 = cli_output.table(["Perfil"], [["prod"]], width=20, level=0)
    assert without_level == with_level_0
    assert _ESC not in with_level_0


#: Every box-drawing character either box style can produce, ASCII and rounded alike - stripped
#: out so the two renders can be compared on data alone.
_FRAME_CHARS: Final[str] = (
    "|+-"
    "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
    "\N{BOX DRAWINGS LIGHT VERTICAL}"
    "\N{BOX DRAWINGS LIGHT ARC DOWN AND RIGHT}"
    "\N{BOX DRAWINGS LIGHT ARC DOWN AND LEFT}"
    "\N{BOX DRAWINGS LIGHT ARC UP AND RIGHT}"
    "\N{BOX DRAWINGS LIGHT ARC UP AND LEFT}"
    "\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}"
    "\N{BOX DRAWINGS LIGHT VERTICAL AND LEFT}"
    "\N{BOX DRAWINGS LIGHT DOWN AND HORIZONTAL}"
    "\N{BOX DRAWINGS LIGHT UP AND HORIZONTAL}"
    "\N{BOX DRAWINGS LIGHT VERTICAL AND HORIZONTAL}"
)


def _data_tokens(rendered: str) -> set[str]:
    """Every word left once ANSI and every box-drawing character are gone."""
    plain = cli_output._ANSI_SGR_RE.sub("", rendered)
    plain = plain.translate({ord(char): " " for char in _FRAME_CHARS})
    return set(plain.split())


def test_table_level_1_carries_the_same_data_as_level_0() -> None:
    """ADR 0031, point 5: level 1 adds style, never information - same rows, same columns."""
    headers = ["Perfil", "Host", "Modo"]
    rows = [["prod", "nz-prod-01", "read"], ["lab", "nz-lab-07", "write"]]
    level_0 = cli_output.table(headers, rows, width=60, level=0)
    level_1 = cli_output.table(headers, rows, width=60, level=1)
    assert _data_tokens(level_0) == _data_tokens(level_1)


def test_a_ci_terminal_with_a_real_pty_still_draws_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0031, point 8, trap 2. ``color_enabled`` alone would miss this: it never asks about
    ``CI``, so a runner with a real pty attached can pass it while ``terminal_level`` - which
    does ask - still answers 0. What gates every escape sequence, bold included, has to be the
    level, not the narrower check.
    """
    stream = _FakeTerminal(tty=True)
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.delenv(cli_output.UI_LEVEL_ENV, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("CI", "true")
    assert cli_output.color_enabled(stream) is True, "the gap this trap closes"
    assert cli_output.terminal_level(stream) == 0
    cli_output.heading("Perfiles")
    cli_output.success("bien")
    _assert_is_floor_output(stream.getvalue())


@pytest.mark.parametrize(
    ("writer", "glyph"),
    [
        (cli_output.success, "\N{BLACK CIRCLE}"),
        (cli_output.warn, "\N{BLACK UP-POINTING TRIANGLE}"),
        (cli_output.fail, "\N{MULTIPLICATION X}"),
    ],
)
def test_states_carry_shape_word_and_colour_at_level_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    writer: Callable[[str], None],
    glyph: str,
) -> None:
    """ADR 0031, point 7, rule 1: colour never carries the meaning alone."""
    monkeypatch.setattr(cli_output, "terminal_level", lambda *_args: 1)
    writer("mensaje")
    err = capsys.readouterr().err
    assert glyph in err
    assert "mensaje" in err
    assert _ESC in err


def test_heading_is_accented_and_bold_at_level_1_with_no_state_glyph(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A heading is a title, not a state: it gets the accent, not one of the three glyphs."""
    monkeypatch.setattr(cli_output, "terminal_level", lambda *_args: 1)
    cli_output.heading("Perfiles")
    err = capsys.readouterr().err
    assert "Perfiles" in err
    assert _ESC in err
    for glyph in ("\N{BLACK CIRCLE}", "\N{BLACK UP-POINTING TRIANGLE}", "\N{MULTIPLICATION X}"):
        assert glyph not in err
