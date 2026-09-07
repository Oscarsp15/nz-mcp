"""The interactive menu, and the second place in the project where ``textual`` may be named.

``nz-mcp`` with no arguments used to print the help and stop. It now opens a menu, picks a
command and runs it - and the rest of the CLI asks this package for *a choice* and gets one
back, never an application, a widget or an event loop. That border is condition 4 of ADR
0029 applied to a second surface (ADR 0030), and it is what makes the menu and the help
screen interchangeable from the outside.

Three rules hold the confinement up, and the first two are enforced by
``tests/contract/test_serve_stdout_protocol_only.py``:

- nothing outside this package and ``wizard/`` imports ``textual``;
- this package does not import ``rich`` either. It gets it underneath ``textual``, which is
  the same rendering stack ``cli_output`` already uses, not a second one;
- this package does not run anything. It returns the name of a command; the caller decides
  what that means.

The import of the application is deferred to the moment it is used, exactly as in
``wizard/``: ``nz-mcp <command>`` is the common case and must not pay for the import of a
TUI framework to print a version string.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from nz_mcp.i18n import Locale
from nz_mcp.menu.entries import (
    MIN_HEIGHT,
    MIN_WIDTH,
    MenuChoice,
    MenuEntry,
    MenuStatus,
)


def choose_command(*, entries: Sequence[MenuEntry], locale: Locale) -> MenuChoice:
    """Show the menu and return what was picked.

    The caller has already checked, through ``cli_output.interactive_ui_enabled()``, that
    the environment can host a full-screen application: this function builds one and does
    not second-guess that decision (ADR 0029, condition 1 - the gate is ours and it is
    decided before anything is constructed).

    Args:
        entries: The commands to offer, in the order they should be read.
        locale: Language of every visible string.

    Returns:
        The command that was picked, or why none was. A window closed without an explicit
        choice counts as ``cancelled``, which is the safe reading: nothing runs.
    """
    from nz_mcp.menu.app import CommandMenuApp  # noqa: PLC0415 - see module docstring

    application = CommandMenuApp(entries=entries, locale=locale)
    result = application.run()
    return MenuChoice(status="cancelled") if result is None else result


__all__: Final[tuple[str, ...]] = (
    "MIN_HEIGHT",
    "MIN_WIDTH",
    "MenuChoice",
    "MenuEntry",
    "MenuStatus",
    "choose_command",
)
