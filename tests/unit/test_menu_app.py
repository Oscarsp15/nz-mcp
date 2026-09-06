"""The menu itself, driven through ``Pilot`` (ADR 0029: it is testable; ADR 0030: it is this).

An interface nobody tests breaks in silence, and testability was a criterion for discarding
a library rather than a nice-to-have. ``App.run_test(headless=True, size=...)`` runs the
real application without a terminal and hands back a ``Pilot`` that presses keys and resizes
the window, so every assertion below is against the state of the real thing.

What is checked here:

- the arrows move, Enter picks, Escape leaves;
- the description follows the cursor, because that is where each entry says what it does;
- the seventh degradation trigger - a window shrunk **below the minimum mid-session**;
- the screen adapts between the minimum and a large window (ADR 0028, condition 4), and at
  the minimum nothing falls off it;
- both languages render.
"""

from __future__ import annotations

import textwrap
from typing import Final

import pytest
from textual.widget import Widget
from textual.widgets import Static

from nz_mcp.i18n import MESSAGES, Locale, t
from nz_mcp.menu import MIN_HEIGHT, MIN_WIDTH, MenuChoice, MenuEntry
from nz_mcp.menu.app import CommandMenuApp

#: A window with room to spare, and the minimum one, used side by side on purpose.
_ROOMY: Final[tuple[int, int]] = (100, 30)
_MINIMUM: Final[tuple[int, int]] = (MIN_WIDTH, MIN_HEIGHT)

#: Small enough that nothing this menu draws could fit. The kind of window an SSH client
#: ends up with when someone drags the corner of the terminal.
_TINY: Final[tuple[int, int]] = (30, 8)

#: The real eleven, in the real order, described with the real catalog entries: a menu built
#: out of invented data would be testing a different screen from the one people see.
_COMMANDS: Final[tuple[str, ...]] = (
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
)


def _entries(locale: Locale = "es") -> tuple[MenuEntry, ...]:
    return tuple(
        MenuEntry(
            command=command,
            description=t("CLI.HELP." + command.upper().replace("-", "_"), locale),
        )
        for command in _COMMANDS
    )


def _app(locale: Locale = "es") -> CommandMenuApp:
    return CommandMenuApp(entries=_entries(locale), locale=locale)


def _result(app: CommandMenuApp) -> MenuChoice:
    outcome = app.return_value
    assert outcome is not None, "the menu ended without saying how"
    return outcome


def _described(app: CommandMenuApp) -> str:
    return str(app.query_one("#describe", Static).content)


@pytest.mark.asyncio
async def test_the_first_command_is_the_one_to_start_with() -> None:
    """It opens on ``init``, which is what someone who just installed this needs.

    The order is the help screen's order, so the first row is the first step, and the
    description under it says so without anyone having to move.
    """
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        assert _described(app) == t("CLI.HELP.INIT", "es")
        await pilot.press("enter")

    assert _result(app) == MenuChoice(status="chosen", command="init")


@pytest.mark.asyncio
async def test_the_arrows_move_and_the_description_follows() -> None:
    """Each entry says what it does, and it says it while it is the one being read."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("down", "down")
        await pilot.pause()
        described = _described(app)
        await pilot.press("up")
        await pilot.pause()
        moved_back = _described(app)
        await pilot.press("escape")

    assert described == t("CLI.HELP.LIST_PROFILES", "es")
    assert moved_back == t("CLI.HELP.TEST_CONNECTION", "es")


@pytest.mark.asyncio
async def test_enter_picks_the_highlighted_command() -> None:
    """The only thing the menu decides: which one. Running it belongs to the caller."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("down", "down", "down")
        await pilot.press("enter")

    assert _result(app) == MenuChoice(status="chosen", command="switch-profile")


@pytest.mark.asyncio
async def test_escape_leaves_without_choosing() -> None:
    """Nothing runs, and it is not an error: the caller exits with zero and prints nothing."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("escape")

    assert _result(app) == MenuChoice(status="cancelled", command=None)


@pytest.mark.asyncio
async def test_shrinking_below_the_minimum_degrades() -> None:
    """The seventh trigger, and the only one that cannot be seen before starting.

    Dragging a terminal corner is routine over SSH. Closing with ``degraded`` is what turns
    a broken repaint into the documented fallback: the entry point prints the help.
    """
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.resize_terminal(*_TINY)
        await pilot.pause()

    assert _result(app) == MenuChoice(status="degraded", command=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("width", "height"),
    [
        pytest.param(MIN_WIDTH - 1, MIN_HEIGHT, id="one-cell-too-narrow"),
        pytest.param(MIN_WIDTH, MIN_HEIGHT - 1, id="one-cell-too-short"),
    ],
)
async def test_the_boundary_of_the_live_check_is_the_declared_minimum(
    width: int, height: int
) -> None:
    """One cell below the minimum on either axis is already below it."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.resize_terminal(width, height)
        await pilot.pause()

    assert _result(app).status == "degraded"


@pytest.mark.asyncio
async def test_a_window_between_the_minimum_and_a_large_one_just_adapts() -> None:
    """Condition 4 of ADR 0028: above the minimum it resizes, it does not degrade."""
    app = _app()
    async with app.run_test(size=_MINIMUM) as pilot:
        await pilot.pause()
        assert app.return_value is None, "the minimum window must be usable, not degraded"
        await pilot.resize_terminal(*_ROOMY)
        await pilot.pause()
        assert app.size.width == _ROOMY[0]
        assert app.return_value is None
        await pilot.press("escape")

    assert _result(app).status == "cancelled"


@pytest.mark.asyncio
async def test_everything_fits_in_the_smallest_window_the_menu_accepts() -> None:
    """Nothing is pushed off the screen at the minimum, which is what makes it the minimum.

    Measured rather than eyeballed: at ``MIN_WIDTH`` x ``MIN_HEIGHT`` the title, the eleven
    commands, the description and the key hints all have a region, and none of them ends
    past the bottom of the window.
    """
    app = _app()
    async with app.run_test(size=_MINIMUM) as pilot:
        await pilot.pause()
        regions = {
            widget.id: widget.region
            for widget in app.screen.walk_children(Widget)
            if widget.id is not None
        }
        await pilot.press("escape")

    for widget_id in ("title", "commands", "describe", "keys"):
        region = regions[widget_id]
        assert region.height > 0, f"{widget_id} has no room at {MIN_WIDTH}x{MIN_HEIGHT}"
        assert region.bottom <= MIN_HEIGHT, f"{widget_id} falls off the bottom"
    # The list has to show all eleven at once: a menu that scrolls hides options behind a
    # gesture nobody was told about.
    assert regions["commands"].height >= len(_COMMANDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["es", "en"])
async def test_the_longest_description_fits_at_the_minimum_width(locale: Locale) -> None:
    """The line under the list is the only long text on screen, so it decides the width.

    Checked against every command in both languages rather than against the one that looks
    longest: the reason the descriptions are not next to each name is exactly this
    measurement, and it has to keep holding when a sentence is rewritten.
    """
    app = _app(locale)
    async with app.run_test(size=_MINIMUM) as pilot:
        await pilot.pause()
        region = app.query_one("#describe", Static).region
        await pilot.press("escape")

    for entry in _entries(locale):
        wrapped = textwrap.wrap(entry.description, width=region.width)
        assert len(wrapped) <= region.height, f"{entry.command} does not fit"


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["es", "en"])
async def test_the_screen_speaks_one_language_at_a_time(locale: Locale) -> None:
    """Mixing the two on one screen is a bug of this role, not a detail."""
    app = _app(locale)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        title = str(app.query_one("#title", Static).content)
        keys = str(app.query_one("#keys", Static).content)
        described = _described(app)
        await pilot.press("escape")

    assert title == t("CLI.MENU_TITLE", locale)
    assert keys == t("CLI.MENU_KEYS", locale)
    assert described == t("CLI.HELP.INIT", locale)


@pytest.mark.asyncio
async def test_the_screen_is_drawable_on_a_console_with_a_legacy_code_page() -> None:
    """Its own text has to survive cp437 and cp850, like every other string this CLI draws.

    The gate already turns a console without VT away, so this is about the two strings the
    menu adds rather than about the frame: an em dash in either would render as ``?``.
    """
    for locale in ("es", "en"):
        for key in ("CLI.MENU_TITLE", "CLI.MENU_KEYS"):
            for code_page in ("cp437", "cp850"):
                MESSAGES[key][locale].encode(code_page)


@pytest.mark.asyncio
async def test_a_menu_with_nothing_to_offer_is_not_a_crash() -> None:
    """It cannot happen today, and the shell should survive it anyway.

    The entries come from the registered commands, so there are always eleven; this pins
    that the screen does not assume it, because the whole point of the package is that
    somebody else decides what goes in it.
    """
    app = CommandMenuApp(entries=(), locale="es")
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        assert _described(app) == ""
        await pilot.press("escape")

    assert _result(app).status == "cancelled"
