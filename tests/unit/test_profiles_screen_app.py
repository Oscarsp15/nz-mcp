""" "Ver perfiles" itself, driven through ``Pilot`` (issue #240, ADR 0032, decision 3).

Same discipline ``test_menu_app.py`` already established: ``App.run_test(headless=True,
size=...)`` runs the real application without a terminal, so every assertion below is
against the state of the real thing rather than a mock of it.

What is checked here:

- the table's five columns, in the order ADR 0032, decision 3, gives them, and that a row
  reads shape + word for its status (decision 7) with the active one marked ahead of its
  name;
- a profile that failed to load shows the placeholder rather than a stale value;
- Enter on a row opens the four actions in their fixed order, and each one hands back the
  action and the profile it was opened for;
- Escape from the modal returns to the table; Escape from the table ends the screen with
  ``cancelled`` rather than ``degraded`` or any other status - it is not the end of the
  session (ADR 0032, amendment to ADR 0030 point 1), which is asserted in
  ``test_cli_profiles_screen.py`` rather than here;
- the empty state offers to configure instead of opening a table with nothing in it, and
  Escape leaves it the same way;
- the window-shrink trigger and the minimum-width adaptation, with the same discipline
  issue #220 already fixed for the plain-text table;
- both languages render, and F2 still swaps the theme.
"""

from __future__ import annotations

from typing import Final

import pytest
from textual.color import Color
from textual.widget import Widget
from textual.widgets import DataTable, OptionList, Static

from nz_mcp.i18n import Locale, t
from nz_mcp.profiles_screen import MIN_HEIGHT, MIN_WIDTH, ProfileAction, ProfileRow, ProfilesChoice
from nz_mcp.profiles_screen.app import ProfilesApp
from nz_mcp.tui import NZ_DARK, NZ_LIGHT

_ROOMY: Final[tuple[int, int]] = (100, 30)
_MINIMUM: Final[tuple[int, int]] = (MIN_WIDTH, MIN_HEIGHT)
_TINY: Final[tuple[int, int]] = (30, 8)

#: Three profiles: the active one, a configured one that is not active, and one whose
#: section failed to load - the three shapes :func:`nz_mcp.cli._profile_rows` can hand back.
_ROWS: Final[tuple[ProfileRow, ...]] = (
    ProfileRow(
        name="prod_dw",
        host="nz-prod-01.corp.local",
        database="DWH_PROD",
        mode="read",
        status="ok",
        active=True,
    ),
    ProfileRow(
        name="staging",
        host="nz-stg-01.corp.local",
        database="DWH_STG",
        mode="write",
        status="warning",
        active=False,
    ),
    ProfileRow(name="broken", host=None, database=None, mode=None, status="error", active=False),
)


def _app(locale: Locale = "es", rows: tuple[ProfileRow, ...] = _ROWS) -> ProfilesApp:
    return ProfilesApp(rows=rows, locale=locale)


def _result(app: ProfilesApp) -> ProfilesChoice:
    outcome = app.return_value
    assert outcome is not None, "the screen ended without saying how"
    return outcome


def _table(app: ProfilesApp) -> DataTable[str]:
    return app.query_one("#profiles", DataTable)


def _row_cells(table: DataTable[str], name: str) -> list[str]:
    for key in table.rows:
        if key.value == name:
            return [str(value) for value in table.get_row(key)]
    raise AssertionError(f"no row keyed {name!r}")


# --- the table: five columns, shape + word + the active marker -------------------------


@pytest.mark.asyncio
async def test_the_five_columns_are_in_the_order_the_adr_gives() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        headers = [str(column.label) for column in _table(app).columns.values()]
        await pilot.press("escape")

    assert headers == ["Perfil", "Host", "Base", "Modo", "Estado"]


@pytest.mark.asyncio
async def test_a_row_reads_shape_and_word_and_the_active_one_is_marked() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        table = _table(app)
        active = _row_cells(table, "prod_dw")
        other = _row_cells(table, "staging")
        await pilot.press("escape")

    assert active == [
        "\N{BLACK RIGHT-POINTING SMALL TRIANGLE} prod_dw",
        "nz-prod-01.corp.local",
        "DWH_PROD",
        "read",
        "\N{BLACK CIRCLE} OK",
    ]
    # Mode is configuration, never prose - the same rule the menu's panel follows.
    assert other[3] == "write"
    assert other[4] == "\N{BLACK UP-POINTING TRIANGLE} Aviso"
    assert not other[0].startswith("\N{BLACK RIGHT-POINTING SMALL TRIANGLE}")


@pytest.mark.asyncio
async def test_a_profile_that_failed_to_load_shows_the_placeholder_not_a_stale_value() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        broken = _row_cells(_table(app), "broken")
        await pilot.press("escape")

    placeholder = t("CLI.MENU_CONTEXT.NO_VALUE", "es")
    assert broken == [
        "broken",
        placeholder,
        placeholder,
        placeholder,
        "\N{MULTIPLICATION X} Error",
    ]


# --- Enter: the four actions, in order ------------------------------------------------


@pytest.mark.asyncio
async def test_enter_opens_the_four_actions_in_the_order_the_adr_gives() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        labels = [
            str(option.prompt) for option in app.screen.query_one("#actions", OptionList).options
        ]
        await pilot.press("escape")
        await pilot.press("escape")

    assert labels == ["Usar", "Probar", "Editar", "Borrar"]


@pytest.mark.asyncio
async def test_escape_from_the_actions_modal_returns_to_the_table() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        table = _table(app)
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.focused is table
        await pilot.press("escape")

    assert _result(app).status == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("presses", "action"),
    [
        pytest.param((), "use", id="use-is-first"),
        pytest.param(("down",), "test", id="test-is-second"),
        pytest.param(("down", "down"), "edit", id="edit-is-third"),
        pytest.param(("down", "down", "down"), "remove", id="remove-is-fourth"),
    ],
)
async def test_choosing_an_action_hands_back_the_action_and_the_profile(
    presses: tuple[str, ...], action: ProfileAction
) -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        await pilot.press("down")  # move onto "staging" first, to prove it travels along
        await pilot.press("enter")
        await pilot.pause()
        for key in presses:
            await pilot.press(key)
        await pilot.press("enter")

    assert _result(app) == ProfilesChoice(status="chosen", profile="staging", action=action)


# --- Escape from the table: not the end of the session ---------------------------------


@pytest.mark.asyncio
async def test_escape_from_the_table_is_cancelled_not_degraded() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("escape")

    assert _result(app) == ProfilesChoice(status="cancelled", profile=None, action=None)


# --- the empty state: one line, one offer -----------------------------------------------


@pytest.mark.asyncio
async def test_no_profiles_shows_one_line_and_offers_to_configure_instead_of_a_table() -> None:
    app = _app(rows=())
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        assert len(app.query(DataTable)) == 0, "an empty table must not be opened at all"
        message = str(app.query_one("#empty", Static).content)
        await pilot.press("enter")

    assert message == t("CLI.PROFILES_SCREEN.EMPTY", "es")
    assert _result(app) == ProfilesChoice(status="configure", profile=None, action=None)


@pytest.mark.asyncio
async def test_escape_on_the_empty_state_is_cancelled_too() -> None:
    app = _app(rows=())
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("escape")

    assert _result(app).status == "cancelled"


# --- degradation and width, the discipline of issue #220 --------------------------------


@pytest.mark.asyncio
async def test_shrinking_below_the_minimum_degrades() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.resize_terminal(*_TINY)
        await pilot.pause()

    assert _result(app) == ProfilesChoice(status="degraded", profile=None, action=None)


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
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.resize_terminal(width, height)
        await pilot.pause()

    assert _result(app).status == "degraded"


@pytest.mark.asyncio
async def test_a_window_between_the_minimum_and_a_large_one_just_adapts() -> None:
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
async def test_everything_fits_in_the_smallest_window_the_screen_accepts() -> None:
    """Measured, not eyeballed: title, table and keys all have a region inside the window."""
    app = _app()
    async with app.run_test(size=_MINIMUM) as pilot:
        await pilot.pause()
        regions = {
            widget.id: widget.region
            for widget in app.screen.walk_children(Widget)
            if widget.id is not None
        }
        await pilot.press("escape")

    for widget_id in ("title", "profiles", "keys"):
        region = regions[widget_id]
        assert region.height > 0, f"{widget_id} has no room at {MIN_WIDTH}x{MIN_HEIGHT}"
        assert region.bottom <= MIN_HEIGHT, f"{widget_id} falls off the bottom"


# --- language and theme ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["es", "en"])
async def test_the_screen_speaks_one_language_at_a_time(locale: Locale) -> None:
    app = _app(locale)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        title = str(app.query_one("#title", Static).content)
        keys = str(app.query_one("#keys", Static).content)
        await pilot.press("enter")
        await pilot.pause()
        action_labels = [
            str(option.prompt) for option in app.screen.query_one("#actions", OptionList).options
        ]
        await pilot.press("escape")
        await pilot.press("escape")

    assert title == t("CLI.PROFILES_SCREEN.TITLE", locale)
    assert keys == t("CLI.PROFILES_SCREEN.KEYS", locale)
    expected_actions = [
        t(f"CLI.PROFILES_SCREEN.ACTION_{action.upper()}", locale)
        for action in ("use", "test", "edit", "remove")
    ]
    assert action_labels == expected_actions


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["es", "en"])
async def test_the_empty_state_speaks_one_language_at_a_time(locale: Locale) -> None:
    app = _app(locale, rows=())
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        message = str(app.query_one("#empty", Static).content)
        keys = str(app.query_one("#keys", Static).content)
        await pilot.press("escape")

    assert message == t("CLI.PROFILES_SCREEN.EMPTY", locale)
    assert keys == t("CLI.PROFILES_SCREEN.EMPTY_KEYS", locale)


@pytest.mark.asyncio
async def test_f2_swaps_the_theme_and_the_screen_repaints_from_it() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        assert app.theme == NZ_DARK.name
        await pilot.press("f2")
        await pilot.pause()
        light = (app.theme, app.screen.styles.background)
        await pilot.press("escape")

    assert light == (NZ_LIGHT.name, Color.parse(NZ_LIGHT.background or ""))
