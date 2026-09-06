"""The border of the menu package: entries go in, a choice comes out (ADR 0029, condition 4).

The application is stood in for here because it is exercised for real, with a ``Pilot``, in
``test_menu_app.py``. What these check is the seam the rest of the CLI sees - and that it
carries a command name and nothing about widgets, which is what has to stay true for a
per-command screen to be able to plug in later without touching this package.
"""

from __future__ import annotations

from typing import Final

import pytest

from nz_mcp.menu import MIN_HEIGHT, MIN_WIDTH, MenuChoice, MenuEntry, choose_command
from nz_mcp.menu import app as menu_app

_ENTRIES: Final[tuple[MenuEntry, ...]] = (
    MenuEntry(command="init", description="Crea tu primer perfil"),
    MenuEntry(command="version", description="Muestra la version instalada"),
)


def test_the_border_hands_the_entries_over_and_the_choice_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arguments in, a :class:`MenuChoice` out, and no application in sight for the caller."""
    built: dict[str, object] = {}

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            built.update(kwargs)

        def run(self) -> MenuChoice:
            return MenuChoice(status="chosen", command="version")

    monkeypatch.setattr(menu_app, "CommandMenuApp", _Stub)
    choice = choose_command(entries=_ENTRIES, locale="es")

    assert built["entries"] == _ENTRIES
    assert built["locale"] == "es"
    assert choice == MenuChoice(status="chosen", command="version")


def test_a_window_closed_without_an_answer_counts_as_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The safe reading of "no answer": nothing was picked, so nothing runs."""

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self) -> None:
            return None

    monkeypatch.setattr(menu_app, "CommandMenuApp", _Stub)

    assert choose_command(entries=_ENTRIES, locale="en") == MenuChoice(status="cancelled")


def test_the_minimum_is_smaller_than_the_wizard_because_the_screen_holds_less() -> None:
    """Two screens, two minimums. Copying the other one's would refuse usable windows.

    The wizard carries eight editable rows, a six-line explanation and a status line; this
    one carries eleven short names, one sentence and a line of keys.
    """
    from nz_mcp.wizard import MIN_HEIGHT as WIZARD_HEIGHT
    from nz_mcp.wizard import MIN_WIDTH as WIZARD_WIDTH

    assert MIN_WIDTH <= WIZARD_WIDTH
    assert MIN_HEIGHT <= WIZARD_HEIGHT


def test_the_package_holds_no_list_of_commands() -> None:
    """The entries are built from what typer registered, so this file cannot disagree with it.

    A hand-written list here would be a second source for the same thing, and the first one
    to go stale the day a command is added.
    """
    from pathlib import Path

    source = Path(str(menu_app.__file__)).parent / "entries.py"
    text = source.read_text(encoding="utf-8")
    for command in ("init", "list-profiles", "probe-catalog", "serve"):
        assert command not in text
