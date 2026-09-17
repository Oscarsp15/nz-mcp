"""The six curated onboarding tasks ``nz-mcp help`` lists, as data.

ADR 0035 removed the interactive menu; what is left, and what this tests, is the plain data
``help_cmd`` reads: the fixed task order and the line format that shows a task's target
command, or the break when that command is gone.
"""

from __future__ import annotations

from nz_mcp.menu import TASKS, MenuEntry, command_line


def test_the_six_tasks_are_the_fixed_order() -> None:
    """The order someone needs the tasks in, written by hand - not typer's registration order."""
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
        "tools",
    ]


def test_command_line_shows_the_target_when_it_is_registered() -> None:
    entry = MenuEntry(command="init", label="Configurar una conexión", description="")
    line = command_line(entry, unavailable="no disponible")
    assert line == "Configurar una conexión -> nz-mcp init"


def test_command_line_shows_the_break_when_the_command_is_not_registered() -> None:
    """A renamed or removed command breaks visibly, not silently."""
    entry = MenuEntry(
        command="gone", label="Configurar una conexión", description="", command_available=False
    )
    line = command_line(entry, unavailable="no disponible")
    assert line == "Configurar una conexión -> no disponible"
