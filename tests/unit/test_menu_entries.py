"""The border of the menu package: entries go in, a choice comes out (ADR 0029, condition 4).

The application is stood in for here because it is exercised for real, with a ``Pilot``, in
``test_menu_app.py``. What these check is the seam the rest of the CLI sees - and that it
carries a command name and nothing about widgets, which is what has to stay true for a
per-command screen to be able to plug in later without touching this package.
"""

from __future__ import annotations

from typing import Final

import pytest

from nz_mcp.menu import (
    MIN_HEIGHT,
    MIN_WIDTH,
    TASKS,
    MenuChoice,
    MenuContext,
    MenuEntry,
    choose_command,
    command_line,
)
from nz_mcp.menu import app as menu_app

_CONTEXT: Final[MenuContext] = MenuContext(
    profile=None, host=None, database=None, mode=None, status="warning"
)

_ENTRIES: Final[tuple[MenuEntry, ...]] = (
    MenuEntry(command="init", label="Configurar una conexión", description="Crea tu primer perfil"),
    MenuEntry(
        command="version", label="Ver la versión", description="Muestra la version instalada"
    ),
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
    choice = choose_command(entries=_ENTRIES, locale="es", context=_CONTEXT)

    assert built["entries"] == _ENTRIES
    assert built["locale"] == "es"
    assert built["context"] == _CONTEXT
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

    assert choose_command(entries=_ENTRIES, locale="en", context=_CONTEXT) == MenuChoice(
        status="cancelled"
    )


def test_the_minimum_is_at_most_the_wizards_because_the_screen_holds_less() -> None:
    """Two screens, two minimums. Copying the other one's would refuse usable windows.

    The wizard carries eight editable rows, a six-line explanation and a status line; this
    one carries six tasks, one sentence, a five-row context panel and a line of keys.
    """
    from nz_mcp.wizard import MIN_HEIGHT as WIZARD_HEIGHT
    from nz_mcp.wizard import MIN_WIDTH as WIZARD_WIDTH

    assert MIN_WIDTH <= WIZARD_WIDTH
    assert MIN_HEIGHT <= WIZARD_HEIGHT


def test_the_six_tasks_are_the_fixed_order_of_adr_0032() -> None:
    """ADR 0032, decision 1: the order someone needs the tasks in, written by hand.

    Not derived from typer's registration order any more - that derivation is exactly what
    this decision spends (ADR 0030, point 4).
    """
    assert [task.id for task in TASKS] == [
        "connect",
        "profiles",
        "test",
        "serve",
        "doctor",
        "tools",
    ]
    assert [task.command for task in TASKS] == [
        "init",
        "list-profiles",
        "test-connection",
        "serve",
        "doctor",
        "probe-catalog",
    ]


def test_command_line_shows_the_target_when_it_is_registered() -> None:
    entry = MenuEntry(command="init", label="Configurar una conexión", description="")
    line = command_line(entry, unavailable="no disponible")
    assert line == "Configurar una conexión -> nz-mcp init"


def test_command_line_shows_the_break_when_the_command_is_not_registered() -> None:
    """ADR 0032, risk 1: a renamed or removed command breaks visibly, not silently."""
    entry = MenuEntry(
        command="gone", label="Configurar una conexión", description="", command_available=False
    )
    line = command_line(entry, unavailable="no disponible")
    assert line == "Configurar una conexión -> no disponible"
