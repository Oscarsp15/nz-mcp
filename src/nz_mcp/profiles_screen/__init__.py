"""``Ver perfiles``, the third and last full-screen surface ADR 0032 authorises.

Same three rules the menu package holds to, and for the same reason:

- nothing outside this package, ``menu/``, ``wizard/`` and ``tui/`` imports ``textual``;
- this package does not import ``rich`` either - it gets it underneath ``textual``, the
  rendering stack ``cli_output`` already uses;
- this package does not run anything. It returns which action was chosen, for which
  profile; the caller decides what that means, the same border ``menu/`` draws for its own
  choice (ADR 0029, condition 4).

The import of the application is deferred to the moment it is used: ``nz-mcp <command>`` is
the common case and must not pay for the import of a TUI framework to print a version
string, exactly as ``menu/`` and ``wizard/`` already do.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from nz_mcp.i18n import Locale
from nz_mcp.profiles_screen.entries import (
    MIN_HEIGHT,
    MIN_WIDTH,
    ProfileAction,
    ProfileRow,
    ProfilesChoice,
    ProfilesStatus,
    ProfileStatus,
)


def choose_profile(*, rows: Sequence[ProfileRow], locale: Locale) -> ProfilesChoice:
    """Show "Ver perfiles" and return what was picked.

    The caller has already checked, through ``cli_output.interactive_ui_enabled()``, that
    the environment can host a full-screen application (ADR 0029, condition 1); this
    function builds one and does not second-guess that decision.

    Args:
        rows: The profiles to show, in the order they should be read.
        locale: Language of every visible string.

    Returns:
        What was chosen, or why nothing was.
    """
    from nz_mcp.profiles_screen.app import ProfilesApp  # noqa: PLC0415 - see module docstring

    application = ProfilesApp(rows=rows, locale=locale)
    result = application.run()
    return ProfilesChoice(status="cancelled") if result is None else result


__all__: Final[tuple[str, ...]] = (
    "MIN_HEIGHT",
    "MIN_WIDTH",
    "ProfileAction",
    "ProfileRow",
    "ProfileStatus",
    "ProfilesChoice",
    "ProfilesStatus",
    "choose_profile",
)
