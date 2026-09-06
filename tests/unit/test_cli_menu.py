"""``nz-mcp`` with no arguments: the menu when it can open, the help when it cannot (#226).

The condition that can sink this feature is the same one that could sink the wizard:
**nobody may be left unable to use the CLI because an interface would not start.** So each
of the eight degradation triggers gets a test of its own, and each one starts from a helper
that opens the gate completely - otherwise a test would pass because a *different* trigger
fired, which is how a broken gate stays green (the discipline of PR #223).

The other half is what must not change. ``nz-mcp --help`` and ``nz-mcp <command>`` are what
whoever pipes the output or reads the documentation depends on, and they are pinned here
against the real click machinery rather than against a mock of it.
"""

from __future__ import annotations

import io
import os
import sys
from typing import Final

import pytest
import typer

from nz_mcp import __version__
from nz_mcp import cli_output as out
from nz_mcp.cli import _HELP_LOCALE, app
from nz_mcp.i18n import MESSAGES, t
from nz_mcp.menu import MIN_HEIGHT, MIN_WIDTH, MenuChoice

#: Exit code ``click`` uses for "no arguments", and the one this CLI answered with before
#: the menu existed. Preserved to the number.
_NO_ARGUMENTS: Final[int] = 2


class _FakeTerminal(io.StringIO):
    """A stream that claims to be a terminal and keeps whatever is written to it.

    Both halves matter: the gate asks ``isatty`` and the assertions need the text, and a
    capture fixture cannot give both at once - pytest's own capture objects are not
    terminals, which is itself one of the triggers.
    """

    def __init__(self, *, terminal: bool = True) -> None:
        super().__init__()
        self._terminal = terminal

    def isatty(self) -> bool:
        return self._terminal


def open_the_gate(monkeypatch: pytest.MonkeyPatch) -> _FakeTerminal:
    """Set everything the gate looks at to the value that lets the menu through.

    Called from the body of each test rather than from a fixture on purpose: pytest
    reinstates its own capture objects on ``sys.stdout`` and ``sys.stderr`` when the call
    phase begins, which is *after* fixture setup, so a fixture that replaced them would be
    quietly undone and every test here would pass for the wrong reason.
    """
    monkeypatch.delenv(out.NO_TUI_ENV, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", str(MIN_WIDTH + 20))
    monkeypatch.setenv("LINES", str(MIN_HEIGHT + 4))
    monkeypatch.setattr(out, "_terminfo_declares_full_screen", lambda _term: True)
    monkeypatch.setattr(out, "detect_legacy_windows", lambda: False)
    # The streams below are stand-ins with no file descriptor, so the foreground check has
    # nothing real to ask; it is stubbed here and exercised for real, against the two
    # process groups, in ``test_wizard_gate.py``.
    monkeypatch.setattr(out, "_owns_the_terminal", lambda: True)
    stdout = _FakeTerminal()
    monkeypatch.setattr("sys.stdin", _FakeTerminal())
    monkeypatch.setattr("sys.stdout", stdout)
    monkeypatch.setattr("sys.stderr", _FakeTerminal())
    return stdout


def refuse_to_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make opening the menu a test failure.

    Used by every degradation test: the point is not only that the help gets printed, it is
    that **nothing was built** before deciding. The gate returns a value; it must be the
    thing that stops the screen, not a screen that stops itself.
    """

    def refuse(**_kwargs: object) -> MenuChoice:
        raise AssertionError("the menu was built even though the gate was closed")

    monkeypatch.setattr("nz_mcp.cli.choose_command", refuse)


def run_cli(*args: str) -> tuple[int, str]:
    """Run the CLI through click exactly as the installed command does.

    Not ``CliRunner``: it replaces the standard streams with its own, which are not
    terminals, so every test here would be exercising the "no terminal" trigger and nothing
    else.
    """
    command = typer.main.get_command(app)
    with pytest.raises(SystemExit) as exit_info:
        command.main(args=list(args), prog_name="nz-mcp")
    code = exit_info.value.code
    written = getattr(sys.stdout, "getvalue", lambda: "")()
    return (0 if code is None else int(code)), str(written)


# --- the eight triggers, each from a fully open gate --------------------------


def test_an_open_gate_opens_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline. Without it, every test below could be passing for the wrong reason."""
    open_the_gate(monkeypatch)
    monkeypatch.setattr(
        "nz_mcp.cli.choose_command",
        lambda **_kwargs: MenuChoice(status="chosen", command="version"),
    )
    code, written = run_cli()
    assert code == 0
    assert __version__ in written


def test_the_escape_hatch_prints_the_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 1. Someone on a bad SSH session sets this once and forgets about it."""
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    monkeypatch.setenv(out.NO_TUI_ENV, "1")
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


def test_a_dumb_terminal_prints_the_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 2, and the one the library will not check for us.

    Measured on ``textual`` 8.2.8: the word ``dumb`` does not appear in the package.
    """
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


@pytest.mark.parametrize("stream", ["stdin", "stdout", "stderr"])
def test_a_redirected_stream_prints_the_help(monkeypatch: pytest.MonkeyPatch, stream: str) -> None:
    """Trigger 3, once per stream: piped, redirected, in CI, driven by another process.

    ``nz-mcp | less`` and ``nz-mcp > commands.txt`` are the everyday shapes of this, and
    both have to keep producing the help they always produced.
    """
    stdout = open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    replacement = _FakeTerminal(terminal=False)
    monkeypatch.setattr(f"sys.{stream}", stdout if stream == "stdout" else replacement)
    if stream == "stdout":
        monkeypatch.setattr(stdout, "_terminal", False, raising=False)
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


def test_a_process_in_the_background_prints_the_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 4, and the one with the worst failure of the eight.

    ``nz-mcp &``, or a process that inherited the descriptors through ``nohup`` or
    ``setsid``: three valid terminals, a real ``TERM``, a good window, so **not one of the
    other seven fires**. Opening a screen there means reading the keyboard, which on POSIX
    answers with ``SIGTTIN``: the process stops with the alternate screen open and leaves
    the terminal unusable for whoever was sitting at it. Printing the help costs nothing and
    lets the background job finish.
    """
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    monkeypatch.setattr(out, "_owns_the_terminal", lambda: False)
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


def test_a_terminal_without_guarantees_prints_the_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 5: a POSIX ``TERM`` terminfo cannot use. Routine inside containers.

    Every other trigger is quiet here - the three streams are terminals and the window is a
    good size - so without this one a full-screen application would start with no guarantee
    that a single escape sequence it sends means anything.
    """
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("TERM", "banana-9000")
    monkeypatch.setattr(out, "_terminfo_declares_full_screen", lambda _term: False)
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


def test_a_console_without_vt_prints_the_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trigger 6: the legacy Windows console, which is where this product mostly runs."""
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    monkeypatch.setattr(out, "detect_legacy_windows", lambda: True)
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


@pytest.mark.parametrize(
    ("columns", "lines"),
    [
        pytest.param(MIN_WIDTH - 1, MIN_HEIGHT + 4, id="too-narrow"),
        pytest.param(MIN_WIDTH + 20, MIN_HEIGHT - 1, id="too-short"),
        pytest.param(40, 12, id="a-small-ssh-window"),
    ],
)
def test_a_window_below_the_minimum_prints_the_help(
    monkeypatch: pytest.MonkeyPatch, columns: int, lines: int
) -> None:
    """Trigger 7, on both axes. Small remote windows are the routine case, not the edge."""
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    monkeypatch.setenv("COLUMNS", str(columns))
    monkeypatch.setenv("LINES", str(lines))
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


def test_shrinking_below_the_minimum_mid_session_prints_the_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trigger 8, the one only a running application can see.

    The menu hands back ``degraded`` and the entry point does what it does for the other
    seven: the help, on stdout, with the exit code it has always had. That the application
    really does report it is tested in ``test_menu_app.py`` by shrinking the window.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setattr(
        "nz_mcp.cli.choose_command", lambda **_kwargs: MenuChoice(status="degraded")
    )
    code, written = run_cli()
    assert code == _NO_ARGUMENTS
    assert "init" in written


# --- what must not change -----------------------------------------------------


def test_help_still_works_with_the_gate_wide_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """``nz-mcp --help`` is documentation and pipe surface: it never opens a screen."""
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    code, written = run_cli("--help")
    assert code == 0
    for command in ("init", "test-connection", "doctor", "serve"):
        assert command in written


def test_a_named_command_still_runs_with_the_gate_wide_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``nz-mcp <command>`` does not pass through the menu, whatever the terminal is."""
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    code, written = run_cli("version")
    assert code == 0
    assert written.strip() == __version__


def test_the_help_is_the_one_click_already_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback screen is not rebuilt here, so it cannot drift from the help.

    Same commands, same order, same sentences: what a person got before this feature
    existed is what they get when the interface cannot open.
    """
    open_the_gate(monkeypatch)
    refuse_to_open(monkeypatch)
    monkeypatch.setenv(out.NO_TUI_ENV, "1")
    _, bare = run_cli()
    open_the_gate(monkeypatch)
    _, explicit = run_cli("--help")
    assert bare.strip() == explicit.strip()


def test_leaving_the_menu_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escape means "never mind", and never mind is not a usage error.

    Nothing is printed either: the help would be noise at the one moment someone has just
    said they are done.
    """
    open_the_gate(monkeypatch)
    monkeypatch.setattr(
        "nz_mcp.cli.choose_command", lambda **_kwargs: MenuChoice(status="cancelled")
    )
    code, written = run_cli()
    assert code == 0
    assert written == ""


def test_the_gate_is_asked_about_this_screen_and_not_about_the_other_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two screens, two minimum sizes, and each one has to be asked about its own.

    The menu holds less than the configuration wizard, so it fits in a smaller window;
    asking with the wizard's numbers would turn the menu away from windows it is perfectly
    happy in.
    """
    open_the_gate(monkeypatch)
    asked: dict[str, int] = {}

    def record(**kwargs: int) -> bool:
        asked.update(kwargs)
        return False

    monkeypatch.setattr(out, "interactive_ui_enabled", record)
    refuse_to_open(monkeypatch)
    run_cli()
    assert asked == {"min_width": MIN_WIDTH, "min_height": MIN_HEIGHT}


# --- the entries: one source, shared with the help ----------------------------


def _capture_entries(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Run the menu path and hand back the arguments the border function was called with."""
    seen: dict[str, object] = {}

    def capture(**kwargs: object) -> MenuChoice:
        seen.update(kwargs)
        return MenuChoice(status="cancelled")

    monkeypatch.setattr("nz_mcp.cli.choose_command", capture)
    run_cli()
    return seen


def test_the_entries_are_the_registered_commands_in_the_same_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The menu offers what the help lists, in the order someone needs them.

    Built from the commands typer registered rather than from a list of our own, so a
    command added tomorrow appears in both places or in neither.
    """
    open_the_gate(monkeypatch)
    entries = list(_capture_entries(monkeypatch)["entries"])  # type: ignore[call-overload]
    assert [entry.command for entry in entries] == [
        "init",
        "test-connection",
        "list-profiles",
        "switch-profile",
        "add-profile",
        "edit-profile",
        "remove-profile",
        "doctor",
        "probe-catalog",
        "version",
        "serve",
    ]


def test_every_entry_says_what_the_catalog_says(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sentences are not written twice: they are the help entries of issue #217.

    A second copy would be a second thing to translate, and the first one to go stale.
    """
    open_the_gate(monkeypatch)
    seen = _capture_entries(monkeypatch)
    for entry in list(seen["entries"]):  # type: ignore[call-overload]
        key = "CLI.HELP." + entry.command.upper().replace("-", "_")
        assert key in MESSAGES
        # The help language, not the runtime one: typer captures ``help=`` while the module
        # is imported, so that is the language the menu inherits along with the text.
        assert entry.description == t(key, _HELP_LOCALE)


def test_the_minimum_window_fits_in_the_oldest_default_terminal() -> None:
    """80x24 has been the default for forty years; asking for more would exclude people."""
    assert MIN_WIDTH <= 80
    assert MIN_HEIGHT <= 24


# --- launching what was picked -------------------------------------------------


def test_a_command_that_needs_a_name_asks_for_it_in_plain_text(
    monkeypatch: pytest.MonkeyPatch, two_profiles: object
) -> None:
    """Four commands take the name of a profile, and a menu without them would be a poor one.

    The question is asked **after** the screen has closed, by the same prompt the chained
    wizard uses, and its text is the parameter's own help - already written and already
    translated. What it is not is a screen for the command: the command stays plain text and
    receives exactly the arguments a person would have typed.
    """
    del two_profiles  # the fixture points the config at a temporary directory
    open_the_gate(monkeypatch)
    monkeypatch.setattr(
        "nz_mcp.cli.choose_command",
        lambda **_kwargs: MenuChoice(status="chosen", command="switch-profile"),
    )
    asked: list[str] = []

    def answer(question: str, **_kwargs: object) -> str:
        asked.append(question)
        return "prod"

    monkeypatch.setattr(out, "ask", answer)
    code, _ = run_cli()
    assert code == 0
    assert asked == [t("CLI.HELP.OPT.EXISTING_PROFILE_NAME", _HELP_LOCALE)]


def test_a_command_that_needs_nothing_is_asked_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seven of the eleven run bare, and those must not grow a question out of nowhere."""
    open_the_gate(monkeypatch)
    monkeypatch.setattr(
        "nz_mcp.cli.choose_command",
        lambda **_kwargs: MenuChoice(status="chosen", command="version"),
    )

    def refuse(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("a command with no required parameters was asked for one")

    monkeypatch.setattr(out, "ask", refuse)
    code, written = run_cli()
    assert code == 0
    assert written.strip() == __version__
