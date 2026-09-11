"""What the menu offers, as data: six fixed tasks, the active profile, a choice.

One property is still deliberate, and it is the one :mod:`nz_mcp.wizard.fields` also holds
to: **no terminal and no library.** Nothing here imports ``textual`` or the output layer, so
the shape of the menu can be exercised without a screen and the confinement of ADR 0029
stays true.

What changed from ADR 0030
---------------------------
The previous version of this module held no list of commands on purpose: the entries were
built from what ``typer`` had registered, so the menu could never drift from ``--help``.
ADR 0032, decision 1, spends that property deliberately: the menu now lists **tasks**, not
commands, and a task is not the name of a registered command - it is a sentence a person
who just installed this would recognise. :data:`TASKS` is the hand-written list that
replaces the derivation, six entries in the fixed order the ADR gives, each one naming the
i18n keys of its own label and sentence rather than carrying resolved text (``cli.py``
resolves them per locale, the same seam :mod:`nz_mcp.wizard.fields` uses for its field
labels).

The correspondence a task still owes to a real command does not disappear: it moves to
``?`` (ADR 0032, decision 2), which cross-checks :attr:`MenuTask.command` against what typer
has registered at the moment the menu opens. ``command_available`` on :class:`MenuEntry` is
that check's result, carried alongside the resolved text so a task pointing at a renamed or
removed command breaks **visibly**, in ``?`` and in ``nz-mcp help``, instead of silently
here (ADR 0032, risk 1).

The seam for later
------------------
Issue #226 calls this the shell that per-command screens will plug into. The seam is the
**return value**: :class:`MenuChoice` says *which* command was picked and never *how* to
run it. Deciding what a choice means belongs to the caller, so the day some command gets a
screen of its own, the caller dispatches to it and this package does not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

#: Smallest window the menu is willing to draw itself in, in cells. Below this the task
#: list, the context panel and the key hints stop fitting, so the entry point prints the
#: help instead of painting something unusable (ADR 0028, conditions 1 and 4; ADR 0030).
#: Kept at or under the wizard's own minimum (60x21): this screen still holds less than a
#: form with eight fields, even with the panel ADR 0032 adds.
MIN_WIDTH: Final[int] = 60
MIN_HEIGHT: Final[int] = 18

#: How the menu ended.
#:
#: - ``chosen``: a command was picked and is in :attr:`MenuChoice.command`.
#: - ``cancelled``: the person left with Escape. Nothing runs, and that is not an error.
#: - ``degraded``: the window dropped below the minimum mid-session, so the caller falls
#:   back to the help screen exactly as it does for the seven start-up triggers.
MenuStatus = Literal["chosen", "cancelled", "degraded"]


@dataclass(frozen=True, slots=True)
class MenuTask:
    """One of the six fixed tasks of ADR 0032, decision 1: its id and its target command.

    ``id`` names the pair of i18n keys the task resolves through, by convention -
    ``CLI.MENU.TASK.<ID>.LABEL`` for the verb that is shown and ``CLI.MENU.TASK.<ID>.
    DESCRIPTION`` for the sentence under it. ``command`` is the typer command this task
    hands off to once chosen; it is never shown on screen, only used to launch it and to
    build the ``?`` correspondence.
    """

    id: str
    command: str


#: The six tasks, in the fixed order ADR 0032, decision 1, gives: the order someone needs
#: them in, not the order typer happens to register commands in. "View profiles" hands off
#: to ``list-profiles`` today (issue #240 gives it a screen of its own); "View tools" hands
#: off to ``probe-catalog``, which is what actually reads as the catalog of tools the ADR's
#: own table names.
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
    """One row of the menu, resolved for one locale: a task, ready to draw.

    ``label`` is what the list shows; ``command`` never is (ADR 0032, decision 1). Both
    :attr:`label` and :attr:`description` are already-translated text, resolved once by the
    caller from :attr:`MenuTask`'s i18n keys - the same split ``cli.py`` already used for
    the help texts this type replaced.
    """

    command: str
    label: str
    description: str
    #: Whether ``command`` is, right now, one of the commands typer has registered. Read by
    #: ``?`` and by ``nz-mcp help`` and by nothing else: the task list itself does not hide
    #: a task whose command went missing, it shows the break (ADR 0032, risk 1).
    command_available: bool = True


def command_line(entry: MenuEntry, *, unavailable: str) -> str:
    """One row of ``?`` and of ``nz-mcp help``: a task and the command it hands off to.

    Both surfaces call this the same function, so the one correspondence ADR 0032, decision
    2, describes cannot read differently depending on where it is printed. ASCII arrow on
    purpose: ``nz-mcp help`` has to be readable on a level-0 terminal, and the modal reuses
    the exact same string rather than a nicer-looking second one.
    """
    target = f"nz-mcp {entry.command}" if entry.command_available else unavailable
    return f"{entry.label} -> {target}"


#: The three states the context panel's ``Estado`` row can be in (ADR 0032, decisions 1 and
#: 7). It is a reading of the profile *configuration*, not of a live connection: the panel
#: is built before any command runs, so it cannot promise anything about Netezza itself.
#:
#: - ``ok``: the active profile loads and validates.
#: - ``warning``: nothing is configured as active - not broken, just not set up yet.
#: - ``error``: an active profile is named but does not load.
ContextStatus = Literal["ok", "warning", "error"]


@dataclass(frozen=True, slots=True)
class MenuContext:
    """The active profile, read the way the context panel shows it (ADR 0032, decision 1).

    Every field but ``status`` is ``None`` when there is nothing to say - no active profile,
    or one that does not load - and the panel prints the catalog's own placeholder for
    ``None`` rather than a sentence (issue #239, acceptance criterion 4). ``mode`` is left
    exactly as configuration spells it (``read`` / ``write`` / ``admin``): ADR 0032, decision
    1, is explicit that this value is never prose.
    """

    profile: str | None
    host: str | None
    database: str | None
    mode: str | None
    status: ContextStatus


@dataclass(frozen=True, slots=True)
class MenuChoice:
    """What the menu hands back: a command, or the reason there is none.

    The border of the package, per condition 4 of ADR 0029: the rest of the CLI asks *which
    command* and gets this, with no idea that an event loop was involved.
    """

    status: MenuStatus
    command: str | None = None
