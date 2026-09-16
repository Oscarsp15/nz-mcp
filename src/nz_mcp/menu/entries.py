"""The six curated onboarding tasks ``nz-mcp help`` lists, as data.

Not a menu any more (ADR 0035 removed the last full-screen surface) - just the ordered,
hand-written list of tasks a person who just installed this would recognise, each pointing
at the real command that does it. What survives from the interactive design is exactly the
property that made it safe to remove: no terminal and no library. Nothing here writes to a
stream or imports anything but the standard library, so the shape of the list can be
exercised without a screen.

The correspondence a task owes to a real command is checked, not assumed:
``command_available`` on :class:`MenuEntry` cross-checks :attr:`MenuTask.command` against
what typer has registered at the moment ``nz-mcp help`` runs, so a task pointing at a
renamed or removed command breaks **visibly** instead of silently claiming it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class MenuTask:
    """One of the six fixed tasks: its id and the command it hands off to.

    ``id`` names the pair of i18n keys the task resolves through, by convention -
    ``CLI.MENU.TASK.<ID>.LABEL`` for the verb that is shown and ``CLI.MENU.TASK.<ID>.
    DESCRIPTION`` for the sentence under it. ``command`` is the typer command
    ``nz-mcp help`` points at; it is never shown on screen, only used to build the line.
    """

    id: str
    command: str


#: The six tasks, in the order someone needs them in, not the order typer happens to
#: register commands in.
TASKS: Final[tuple[MenuTask, ...]] = (
    MenuTask(id="connect", command="init"),
    MenuTask(id="profiles", command="list-profiles"),
    MenuTask(id="test", command="test-connection"),
    MenuTask(id="serve", command="serve"),
    MenuTask(id="doctor", command="doctor"),
    MenuTask(id="tools", command="probe-catalog"),
)


@dataclass(frozen=True, slots=True)
class MenuEntry:
    """One row of ``nz-mcp help``, resolved for one locale: a task, ready to print.

    Both :attr:`label` and :attr:`description` are already-translated text, resolved once
    by the caller from :attr:`MenuTask`'s i18n keys.
    """

    command: str
    label: str
    description: str
    #: Whether ``command`` is, right now, one of the commands typer has registered. Read
    #: by ``nz-mcp help`` and by nothing else: the task list does not hide a task whose
    #: command went missing, it shows the break.
    command_available: bool = True


def command_line(entry: MenuEntry, *, unavailable: str) -> str:
    """One row of ``nz-mcp help``: a task and the command it hands off to.

    ASCII arrow on purpose: this has to be readable on a level-0 terminal.
    """
    target = f"nz-mcp {entry.command}" if entry.command_available else unavailable
    return f"{entry.label} -> {target}"
