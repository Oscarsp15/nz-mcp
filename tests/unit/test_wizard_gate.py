"""The gate that decides whether a full-screen wizard may start (ADR 0028, condition 1).

Degradation is the condition that can sink the whole feature: **nobody may end up unable
to configure nz-mcp because an interface would not start.** So each of the seven start-up
triggers gets a test of its own, starting from a helper that opens the gate completely -
otherwise a test would pass because a *different* trigger fired, which is how a broken
gate stays green.

The eighth - shrinking the window below the minimum mid-session - cannot be seen from
this side and lives in ``tests/unit/test_wizard_app.py``.
"""

from __future__ import annotations

import os
from typing import Final

import pytest

from nz_mcp import cli_output as out
from nz_mcp.wizard import MIN_HEIGHT, MIN_WIDTH

#: A window that clears the minimum with room to spare.
_ROOMY: Final[tuple[int, int]] = (MIN_WIDTH + 20, MIN_HEIGHT + 4)


class _FakeStream:
    """A stand-in for a standard stream that knows whether it is a terminal."""

    def __init__(self, *, terminal: bool) -> None:
        self._terminal = terminal

    def isatty(self) -> bool:
        return self._terminal


def _set_size(monkeypatch: pytest.MonkeyPatch, columns: int, lines: int) -> None:
    """``shutil.get_terminal_size`` reads these before asking the operating system."""
    monkeypatch.setenv("COLUMNS", str(columns))
    monkeypatch.setenv("LINES", str(lines))


def open_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set everything the gate looks at to the value that lets a wizard through.

    Called from the body of each test rather than from a fixture on purpose: pytest
    reinstates its own capture objects on ``sys.stdout`` and ``sys.stderr`` when the call
    phase begins, which is *after* fixture setup, so a fixture that replaced them would be
    quietly undone and every test here would pass for the wrong reason.

    The terminfo lookup is stubbed so these tests answer the same on every platform: the
    real one is exercised separately, against the real database, in
    :func:`test_the_terminfo_lookup_answers_about_the_real_database`. So is the foreground
    check, for the same reason and one more: the streams here are stand-ins with no file
    descriptor, and asking a terminal that does not exist which process group it is
    listening to would close the gate in every single test.
    """
    monkeypatch.delenv(out.NO_TUI_ENV, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    for stream in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(f"sys.{stream}", _FakeStream(terminal=True))
    monkeypatch.setattr(out, "_terminfo_declares_full_screen", lambda _term: True)
    monkeypatch.setattr(out, "detect_legacy_windows", lambda: False)
    monkeypatch.setattr(out, "_owns_the_terminal", lambda: True)
    _set_size(monkeypatch, *_ROOMY)


def _blocker(**overrides: int) -> out.InteractiveBlocker | None:
    return out.interactive_ui_blocker(
        min_width=overrides.get("min_width", MIN_WIDTH),
        min_height=overrides.get("min_height", MIN_HEIGHT),
    )


def test_a_capable_terminal_opens_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline. Without it, every test below could be passing for the wrong reason."""
    open_the_gate(monkeypatch)
    assert _blocker() is None
    assert out.interactive_ui_enabled(min_width=MIN_WIDTH, min_height=MIN_HEIGHT)


def test_the_escape_hatch_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 1. Someone on a bad SSH session sets this once and forgets about it."""
    open_the_gate(monkeypatch)
    monkeypatch.setenv(out.NO_TUI_ENV, "1")
    assert _blocker() == "opted_out"


@pytest.mark.parametrize("value", ["1", "true", "yes", "please"])
def test_any_affirmative_value_of_the_escape_hatch_works(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """An escape hatch that only understands one spelling is a trap."""
    open_the_gate(monkeypatch)
    monkeypatch.setenv(out.NO_TUI_ENV, value)
    assert _blocker() == "opted_out"


@pytest.mark.parametrize("value", ["0", "false", ""])
def test_a_negative_escape_hatch_leaves_the_gate_open(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """``NZ_MCP_NO_TUI=0`` must not disable the very thing it spells out."""
    open_the_gate(monkeypatch)
    monkeypatch.setenv(out.NO_TUI_ENV, value)
    assert _blocker() is None


def test_a_dumb_terminal_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 2, and the one the library will not check for us.

    Measured on ``textual`` 8.2.8: the word ``dumb`` does not appear in the package. A TUI
    library tries to paint wherever it is allowed to, so the door is ours.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    assert _blocker() == "term_dumb"


@pytest.mark.parametrize("stream", ["stdin", "stdout", "stderr"])
def test_a_redirected_stream_closes_it(monkeypatch: pytest.MonkeyPatch, stream: str) -> None:
    """Trigger 3, once per stream: piped, redirected, in CI, or driven by another process.

    ``stdout`` is on the list on purpose. ``nz-mcp init > block.json`` is a documented
    flow - the Claude Desktop snippet is payload - and it has to keep producing a file
    with the snippet in it, not a screen drawn into a text file.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setattr(f"sys.{stream}", _FakeStream(terminal=False))
    assert _blocker() == "no_terminal"


def test_a_stream_that_cannot_answer_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrapper that replaced the stream with something incomplete degrades, not crashes."""
    open_the_gate(monkeypatch)
    monkeypatch.setattr("sys.stdin", object())
    assert _blocker() == "no_terminal"


@pytest.mark.parametrize("term", ["", "   ", "banana-9000", "unknown"])
def test_a_posix_terminal_without_guarantees_closes_it(
    monkeypatch: pytest.MonkeyPatch, term: str
) -> None:
    """Trigger 5, one of the two the first round of this work missed.

    ``TERM=dumb`` is not the only way to have no guarantees. An empty or unset ``TERM`` is
    routine inside containers and in some multiplexed SSH sessions, and a value the host's
    terminfo database cannot use is routine when the client's terminal type is not
    installed on the server. In both cases the three streams *are* terminals and the window
    *is* a good size, so not one of the other seven triggers fires - and a full-screen
    application would start with no guarantee that any escape sequence or key it uses means
    anything. Because the size is fine, the live-resize net would not catch it either.

    The lookup is stubbed here, and whether a real ncurses rejects an invented name is not
    something this asserts - see
    :func:`test_the_terminfo_lookup_answers_about_the_real_database`. What is asserted is
    the wiring: when the lookup says no, the gate closes with this reason.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("TERM", term)
    # An unknown type reaches the lookup; an empty one never gets that far.
    monkeypatch.setattr(out, "_terminfo_declares_full_screen", lambda _term: False)
    assert _blocker() == "terminal_without_capabilities"


def test_a_posix_terminal_the_database_knows_opens_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The trigger has to let a normal terminal through, or it is just a switch that is off."""
    open_the_gate(monkeypatch)
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert _blocker() is None


def test_windows_does_not_ask_terminfo_because_there_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows ``TERM`` is normally unset and says nothing about the console.

    The equivalent question there is whether the console speaks VT, which is the trigger
    right after this one. Asking terminfo on Windows would close the gate on every single
    Windows user, which is the platform this product mostly runs on.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(out, "_terminfo_declares_full_screen", lambda _term: False)
    assert _blocker() is None


@pytest.mark.skipif(os.name != "posix", reason="terminfo is a POSIX database")
def test_the_terminfo_lookup_answers_about_the_real_database() -> None:
    """The stub above has to stand for something real, so here it is unstubbed.

    Only the positive direction is asserted, and that is a finding rather than laziness:
    the first version of this test also asserted that an invented terminal name comes back
    unknown, and **ncurses on the CI runners answered it with a usable fallback entry
    instead of an error**. Which way a given build goes is not portable, so asserting it
    would be asserting the runner rather than the code.

    What that leaves is honest and is what the docstring of the lookup now says: the
    portable half of this trigger is ``TERM`` being set at all, tested just below against
    the real function, and the lookup is what catches a system whose terminfo database is
    missing or unusable.
    """
    assert out._terminfo_declares_full_screen("xterm")


@pytest.mark.skipif(os.name != "posix", reason="terminfo is a POSIX database")
def test_an_unset_term_closes_the_gate_without_consulting_any_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The container case, against the real function rather than a stub.

    No ``TERM`` at all is the common way to end up here, and it is decided before terminfo
    is asked anything - so this half of the trigger holds on every POSIX system, whatever
    its ncurses does with names it does not recognise.
    """
    monkeypatch.delenv("TERM", raising=False)
    assert not out._terminal_type_is_capable()


def test_a_console_without_vt_sequences_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 6: the legacy Windows console, which is the destination of this product.

    A console on a legacy code page renders anything outside ASCII as ``?``, and one
    without VT cannot position a cursor at all. The detection is the one the output layer
    already uses for everything else it draws.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setattr(out, "detect_legacy_windows", lambda: True)
    assert _blocker() == "console_without_vt"


@pytest.mark.parametrize(
    ("columns", "lines"),
    [
        pytest.param(MIN_WIDTH - 1, MIN_HEIGHT + 4, id="too-narrow"),
        pytest.param(MIN_WIDTH + 20, MIN_HEIGHT - 1, id="too-short"),
        pytest.param(40, 12, id="a-small-ssh-window"),
    ],
)
def test_a_window_below_the_minimum_closes_it(
    monkeypatch: pytest.MonkeyPatch, columns: int, lines: int
) -> None:
    """Trigger 7, on both axes. Small remote windows are the routine case, not the edge."""
    open_the_gate(monkeypatch)
    _set_size(monkeypatch, columns, lines)
    assert _blocker() == "window_too_small"


def test_exactly_the_minimum_is_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    """The boundary is inclusive: the layout is measured to fit in exactly this."""
    open_the_gate(monkeypatch)
    _set_size(monkeypatch, MIN_WIDTH, MIN_HEIGHT)
    assert _blocker() is None


def test_the_declared_minimum_fits_in_the_oldest_default_terminal() -> None:
    """80x24 has been the default for forty years; asking for more would exclude people."""
    assert MIN_WIDTH <= 80
    assert MIN_HEIGHT <= 24


def test_the_gate_does_not_import_textual() -> None:
    """Condition 1 of ADR 0029: the gate decides a value, it does not build anything.

    Read from the source rather than from the loaded module, because by the time this test
    runs the wizard has already imported ``textual`` for its own tests. The contract test
    ``test_serve_stdout_protocol_only.py`` enforces this across the whole package; it is
    stated again here because it is the reason the gate is allowed to live in this module.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(str(out.__file__)).read_text(encoding="utf-8"))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert [name for name in imported if name.split(".")[0] == "textual"] == []


# --- trigger 4: the process does not own the terminal it would paint on -------


class _DescriptorStream:
    """A terminal stand-in that also has a file descriptor, like a real stdin."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return self._descriptor


def test_a_background_process_closes_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 4, and the one with the worst failure of the eight.

    ``nz-mcp &``, or a process that inherited the descriptors through ``nohup`` or
    ``setsid``, has three valid terminals, a real ``TERM`` and a good window, so **not one
    of the other seven fires**. Start a full-screen application there and reading the
    keyboard raises ``SIGTTIN``: the process stops with the alternate screen open and
    whoever was sitting at that terminal is left with an unusable one.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setattr(out, "_owns_the_terminal", lambda: False)
    assert _blocker() == "background_process"


def _with_process_groups(monkeypatch: pytest.MonkeyPatch, listening_to: int) -> None:
    """Give ``os`` the two POSIX calls, with the terminal listening to ``listening_to``.

    ``raising=False`` because neither exists on a Windows build - which is exactly what the
    implementation looks for. Setting them here means these tests exercise the real logic on
    every runner instead of being skipped on half of them.
    """
    monkeypatch.setattr(os, "getpgrp", lambda: 4321, raising=False)
    monkeypatch.setattr(os, "tcgetpgrp", lambda _fd: listening_to, raising=False)


def test_the_foreground_check_compares_the_two_process_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The terminal's listener has to be our own group, or we are in the background."""
    monkeypatch.setattr("sys.stdin", _DescriptorStream(7))

    _with_process_groups(monkeypatch, listening_to=4321)
    assert out._owns_the_terminal()

    _with_process_groups(monkeypatch, listening_to=999)
    assert not out._owns_the_terminal()


def test_a_terminal_that_cannot_be_asked_counts_as_not_ours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degrading costs a help screen; guessing wrong costs someone their terminal.

    Two ways of not being able to ask, both real: a stream a wrapper replaced with an
    object that has no descriptor, and a descriptor the terminal refuses to answer about
    (``ENOTTY``, ``EBADF``).
    """
    _with_process_groups(monkeypatch, listening_to=4321)

    monkeypatch.setattr("sys.stdin", _FakeStream(terminal=True))
    assert not out._owns_the_terminal()

    def refuse(_fd: int) -> int:
        raise OSError(25, "Inappropriate ioctl for device")

    monkeypatch.setattr("sys.stdin", _DescriptorStream(7))
    monkeypatch.setattr(os, "tcgetpgrp", refuse, raising=False)
    assert not out._owns_the_terminal()


@pytest.mark.parametrize("missing", ["tcgetpgrp", "getpgrp"])
def test_an_operating_system_without_process_groups_owns_nothing_to_check(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """Said out loud rather than left implicit: on Windows this trigger does not apply.

    There are no POSIX process groups, no controlling terminal to own and no ``SIGTTIN``. A
    detached process there has no console at all, which is trigger 3, and one started with a
    shared console is not stopped for reading it. So the answer is yes.

    And it is decided by whether the two calls **exist**, not by comparing ``sys.platform``:
    the question is *"does this operating system have process groups?"*, the honest way to
    ask it is to look them up, and doing it that way keeps this testable on both platforms.
    The stub that is left blows up if it is ever consulted.
    """

    def explode(*_args: object) -> int:
        raise AssertionError("nothing may be asked when there are no process groups")

    _with_process_groups(monkeypatch, listening_to=4321)
    monkeypatch.delattr(os, missing, raising=False)
    monkeypatch.setattr(os, "tcgetpgrp" if missing == "getpgrp" else "getpgrp", explode)
    monkeypatch.setattr("sys.stdin", _DescriptorStream(7))
    assert out._owns_the_terminal()
