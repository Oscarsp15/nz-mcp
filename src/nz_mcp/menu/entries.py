"""What the menu offers, as data: which commands, in which order, described how.

Two properties are deliberate, and they are the same two that make
:mod:`nz_mcp.wizard.fields` work:

- **No terminal and no library.** Nothing here imports ``textual`` or the output layer, so
  the shape of the menu can be exercised without a screen and the confinement of ADR 0029
  stays true.
- **Nothing is decided here.** This module holds no list of commands. The entries are built
  by ``cli.py`` from the commands ``typer`` has actually registered, which is what keeps the
  menu from ever drifting away from ``--help``: same commands, same order, same sentences,
  one source. A hand-written list in this file would be a second one.

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

#: Smallest window the menu is willing to draw itself in, in cells. Below this the list,
#: the description of the highlighted command and the key hints stop fitting, so the entry
#: point prints the help instead of painting something unusable (ADR 0028, conditions 1
#: and 4; ADR 0030). Smaller than the wizard's minimum because this screen holds less: a
#: list of eleven short names, one sentence and one line of keys.
MIN_WIDTH: Final[int] = 50
MIN_HEIGHT: Final[int] = 20

#: How the menu ended.
#:
#: - ``chosen``: a command was picked and is in :attr:`MenuChoice.command`.
#: - ``cancelled``: the person left with Escape. Nothing runs, and that is not an error.
#: - ``degraded``: the window dropped below the minimum mid-session, so the caller falls
#:   back to the help screen exactly as it does for the six start-up triggers.
MenuStatus = Literal["chosen", "cancelled", "degraded"]


@dataclass(frozen=True, slots=True)
class MenuEntry:
    """One line of the menu: a command and the sentence that already describes it.

    ``description`` is not written here and not written twice: it is the ``help=`` text of
    the registered command, which comes from the i18n catalog (issue #217). If the two ever
    disagree, the menu is showing something ``--help`` does not, which is the failure this
    type exists to make impossible.
    """

    command: str
    description: str


@dataclass(frozen=True, slots=True)
class MenuChoice:
    """What the menu hands back: a command, or the reason there is none.

    The border of the package, per condition 4 of ADR 0029: the rest of the CLI asks *which
    command* and gets this, with no idea that an event loop was involved.
    """

    status: MenuStatus
    command: str | None = None
