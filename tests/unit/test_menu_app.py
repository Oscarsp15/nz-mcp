"""The menu itself, driven through ``Pilot`` (ADR 0029: it is testable; ADR 0030: it is this).

An interface nobody tests breaks in silence, and testability was a criterion for discarding
a library rather than a nice-to-have. ``App.run_test(headless=True, size=...)`` runs the
real application without a terminal and hands back a ``Pilot`` that presses keys and resizes
the window, so every assertion below is against the state of the real thing.

What is checked here:

- the six tasks of ADR 0032, decision 1, in order, and that a command name never appears
  outside the ``?`` modal;
- the arrows move, Enter picks, Escape leaves;
- the description follows the cursor, because that is where each task says what it does;
- the context panel reads ``Etiqueta: valor``, including the no-profile placeholder and the
  three states of ``Estado``;
- ``?`` opens the modal with the task -> command correspondence, Escape closes it and gives
  the focus back;
- the ninth degradation trigger - a window shrunk **below the minimum mid-session**;
- the screen adapts between the minimum and a large window (ADR 0028, condition 4), and at
  the minimum nothing falls off it;
- both languages render.
"""

from __future__ import annotations

import textwrap
from typing import Final

import pytest
from textual.color import Color
from textual.widget import Widget
from textual.widgets import Static

from nz_mcp.i18n import MESSAGES, Locale, t
from nz_mcp.menu import MIN_HEIGHT, MIN_WIDTH, TASKS, MenuChoice, MenuContext, MenuEntry
from nz_mcp.menu.app import CommandMenuApp
from nz_mcp.tui import NZ_DARK, NZ_LIGHT

#: A window with room to spare, and the minimum one, used side by side on purpose.
_ROOMY: Final[tuple[int, int]] = (100, 30)
_MINIMUM: Final[tuple[int, int]] = (MIN_WIDTH, MIN_HEIGHT)

#: Small enough that nothing this menu draws could fit. The kind of window an SSH client
#: ends up with when someone drags the corner of the terminal.
_TINY: Final[tuple[int, int]] = (30, 8)

#: The active profile the panel shows in most tests: fully configured, everything reads.
_CONTEXT: Final[MenuContext] = MenuContext(
    profile="prod_dw", host="nz-prod-01.corp.local", database="DWH_PROD", mode="read", status="ok"
)

#: No profile configured at all: the panel's other common state.
_NO_PROFILE: Final[MenuContext] = MenuContext(
    profile=None, host=None, database=None, mode=None, status="warning"
)


def _entries(locale: Locale = "es") -> tuple[MenuEntry, ...]:
    return tuple(
        MenuEntry(
            command=task.command,
            label=t(f"CLI.MENU.TASK.{task.id.upper()}.LABEL", locale),
            description=t(f"CLI.MENU.TASK.{task.id.upper()}.DESCRIPTION", locale),
        )
        for task in TASKS
    )


def _app(locale: Locale = "es", context: MenuContext = _CONTEXT) -> CommandMenuApp:
    return CommandMenuApp(entries=_entries(locale), locale=locale, context=context)


def _result(app: CommandMenuApp) -> MenuChoice:
    outcome = app.return_value
    assert outcome is not None, "the menu ended without saying how"
    return outcome


def _described(app: CommandMenuApp) -> str:
    return str(app.query_one("#describe", Static).content)


def _row(app: CommandMenuApp, widget_id: str) -> str:
    return str(app.query_one(f"#{widget_id}", Static).content)


@pytest.mark.asyncio
async def test_the_first_task_is_the_one_to_start_with() -> None:
    """It opens on "Configurar una conexión", which is what a fresh install needs first."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        assert _described(app) == t("CLI.MENU.TASK.CONNECT.DESCRIPTION", "es")
        await pilot.press("enter")

    assert _result(app) == MenuChoice(status="chosen", command="init")


@pytest.mark.asyncio
async def test_the_arrows_move_and_the_description_follows() -> None:
    """Each task says what it does, and it says it while it is the one being read."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("down", "down")
        await pilot.pause()
        described = _described(app)
        await pilot.press("up")
        await pilot.pause()
        moved_back = _described(app)
        await pilot.press("escape")

    assert described == t("CLI.MENU.TASK.TEST.DESCRIPTION", "es")
    assert moved_back == t("CLI.MENU.TASK.PROFILES.DESCRIPTION", "es")


@pytest.mark.asyncio
async def test_enter_picks_the_command_of_the_highlighted_task() -> None:
    """The only thing the menu decides: which one. Running it belongs to the caller."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("down", "down", "down")
        await pilot.press("enter")

    assert _result(app) == MenuChoice(status="chosen", command="serve")


@pytest.mark.asyncio
async def test_escape_leaves_without_choosing() -> None:
    """Nothing runs, and it is not an error: the caller exits with zero and prints nothing."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("escape")

    assert _result(app) == MenuChoice(status="cancelled", command=None)


@pytest.mark.asyncio
async def test_shrinking_below_the_minimum_degrades() -> None:
    """The ninth trigger, and the only one that cannot be seen before starting.

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

    Measured rather than eyeballed: at ``MIN_WIDTH`` x ``MIN_HEIGHT`` the title, the six
    tasks, the description, the context panel and the key hints all have a region, and none
    of them ends past the bottom of the window.
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

    for widget_id in ("title", "commands", "describe", "context", "keys"):
        region = regions[widget_id]
        assert region.height > 0, f"{widget_id} has no room at {MIN_WIDTH}x{MIN_HEIGHT}"
        assert region.bottom <= MIN_HEIGHT, f"{widget_id} falls off the bottom"
    # The list has to show all six at once: a menu that scrolls hides options behind a
    # gesture nobody was told about.
    assert regions["commands"].height >= len(TASKS)


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["es", "en"])
async def test_the_longest_description_fits_at_the_minimum_width(locale: Locale) -> None:
    """The line under the list is the only long text on screen, so it decides the width.

    Checked against every task in both languages rather than against the one that looks
    longest: the reason the descriptions are not next to each label is exactly this
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
    assert described == t("CLI.MENU.TASK.CONNECT.DESCRIPTION", locale)


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
async def test_f2_swaps_the_theme_and_the_screen_repaints_from_it() -> None:
    """ADR 0032, decision 5: two themes, one key, and the colour comes from the theme.

    The background is read back from the rendered screen rather than from the theme
    object, so this fails if the sheet stopped drawing from the theme, not only if F2
    stopped switching the name.
    """
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        assert app.theme == NZ_DARK.name
        await pilot.press("f2")
        await pilot.pause()
        light = (app.theme, app.screen.styles.background)
        await pilot.press("f2")
        await pilot.pause()
        dark = (app.theme, app.screen.styles.background)
        await pilot.press("escape")

    assert light == (NZ_LIGHT.name, Color.parse(NZ_LIGHT.background or ""))
    assert dark == (NZ_DARK.name, Color.parse(NZ_DARK.background or ""))


@pytest.mark.asyncio
async def test_a_menu_with_nothing_to_offer_is_not_a_crash() -> None:
    """It cannot happen today, and the shell should survive it anyway.

    The entries come from the six fixed tasks, so there are always six; this pins that the
    screen does not assume it, because the whole point of the package is that somebody else
    decides what goes in it.
    """
    app = CommandMenuApp(entries=(), locale="es", context=_NO_PROFILE)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        assert _described(app) == ""
        await pilot.press("escape")

    assert _result(app).status == "cancelled"


# --- the context panel: "Etiqueta: valor" (ADR 0032, decision 1) -----------------------


@pytest.mark.asyncio
async def test_the_context_panel_reads_label_colon_value() -> None:
    app = _app(context=_CONTEXT)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        profile = _row(app, "context-profile")
        host = _row(app, "context-host")
        database = _row(app, "context-database")
        mode = _row(app, "context-mode")
        status = _row(app, "context-status")
        await pilot.press("escape")

    assert profile == "Perfil: prod_dw"
    assert host == "Host: nz-prod-01.corp.local"
    assert database == "Base: DWH_PROD"
    # Mode is configuration, never prose (ADR 0032, decision 1).
    assert mode == "Modo: read"
    assert status == "Estado: \N{BLACK CIRCLE} OK"


@pytest.mark.asyncio
async def test_no_active_profile_is_a_value_not_a_sentence() -> None:
    """Acceptance criterion 4 of issue #239: the placeholder is a value, not a phrase."""
    app = _app(context=_NO_PROFILE)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        profile = _row(app, "context-profile")
        mode = _row(app, "context-mode")
        status = _row(app, "context-status")
        await pilot.press("escape")

    placeholder = t("CLI.MENU_CONTEXT.NO_VALUE", "es")
    assert profile == f"Perfil: {placeholder}"
    assert mode == f"Modo: {placeholder}"
    assert status == "Estado: \N{BLACK UP-POINTING TRIANGLE} Aviso"


@pytest.mark.asyncio
async def test_a_profile_that_will_not_load_is_the_error_state() -> None:
    broken = MenuContext(profile="broken", host=None, database=None, mode=None, status="error")
    app = _app(context=broken)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        profile = _row(app, "context-profile")
        status = _row(app, "context-status")
        await pilot.press("escape")

    assert profile == "Perfil: broken"
    assert status == "Estado: \N{MULTIPLICATION X} Error"


# --- "?": the one place a command name appears (ADR 0032, decision 2) ------------------


@pytest.mark.asyncio
async def test_question_mark_opens_the_modal_with_the_task_command_correspondence() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        lines = [str(static.content) for static in app.screen.query(Static)]
        await pilot.press("escape")
        await pilot.press("escape")

    assert lines[0] == t("CLI.MENU_HELP_MODAL.TITLE", "es")
    assert "Configurar una conexión -> nz-mcp init" in lines
    assert "Ver herramientas -> nz-mcp probe-catalog" in lines


@pytest.mark.asyncio
async def test_escape_closes_the_modal_and_returns_the_focus() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        commands = app.query_one("#commands")
        await pilot.press("question_mark")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.focused is commands
        await pilot.press("escape")

    assert _result(app).status == "cancelled"


@pytest.mark.asyncio
async def test_no_command_name_is_drawn_outside_the_modal() -> None:
    """Acceptance criterion 2 of issue #239, walked over the real widget tree."""
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        texts = [
            str(widget.content)
            for widget in app.screen.walk_children(Widget)
            if isinstance(widget, Static)
        ]
        await pilot.press("escape")

    for task in TASKS:
        for text in texts:
            assert task.command not in text, f"{task.command!r} leaked into {text!r}"
