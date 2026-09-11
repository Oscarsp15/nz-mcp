"""``Ver perfiles``: one table, four actions per row, and nothing it runs itself.

Scope, and why it is this small (ADR 0032, decision 3)
--------------------------------------------------------
"Ver perfiles" chooses, it does not host: ``Enter`` on a row opens the four actions -
usar, probar, editar, borrar - and picking one closes the whole screen and hands the choice
back. Running it - ``switch-profile``, ``test-connection --profile``, ``edit-profile``,
``remove-profile`` - happens in ``cli.py``, on the ordinary terminal, through the exact
commands that already exist. None of the four is reimplemented here, and in particular
"borrar" does not ask its own confirmation: ``remove-profile`` already names the profile and
refuses by default (acceptance criterion 4 of issue #240), and asking twice would be a
second implementation of the same question.

Where the state in each row comes from
---------------------------------------
Never from a connection. ``cli.py`` builds every ``ProfileRow`` before this screen opens,
from ``profiles.toml`` and the local keyring only - no socket opens until "probar" runs,
after this screen has already closed (acceptance criterion 2 of issue #240).

How it looks is not decided here, same as the menu (ADR 0032, decision 5): colour comes
from the shared sheet and the two themes of ``nz_mcp.tui``, inherited through
``ThemedApp``. One thing the sheet cannot reach is a single cell of a ``DataTable``, which
Textual renders as plain text rather than through a CSS selector - the same constraint
``cli.py`` already documents for the level-1 active marker (``_ACTIVE_MARK_LEVEL_1``):
baking a colour into cell content would either read as a literal the structural test
rejects, or be pulled from Textual's own derived variables, which are not the exact values
the contrast suite measures. So the ``Estado`` column carries shape and word - ``OK``,
``Aviso``, ``Error``, each with its glyph - and leaves the colour to the row's ordinary
text, the same trade-off already made once in this codebase for the same reason.

How it is reached and how it is left
-------------------------------------
Only from the six-task menu's "Ver perfiles" entry, and never directly: ``list-profiles``
stays plain text (acceptance criterion 10 of issue #240). Escape leaves this screen and
hands back to the six-task menu rather than ending the process - unlike the menu itself,
this is the second of two steps, so leaving it is not the end of the session (ADR 0032,
amendment to ADR 0030 point 1: leaving in two steps is not hosting; hosting would be going
back to the table after a command ran).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, OptionList, Static
from textual.widgets.data_table import RowKey
from textual.widgets.option_list import Option

from nz_mcp.i18n import Locale, t
from nz_mcp.profiles_screen.entries import (
    MIN_HEIGHT,
    MIN_WIDTH,
    ProfileAction,
    ProfileRow,
    ProfilesChoice,
    ProfilesStatus,
)
from nz_mcp.tui import ThemedApp

_TABLE_ID: Final[str] = "profiles"

#: The glyph half of "forma + palabra + color" (ADR 0032, decision 7) - the same three the
#: menu's context panel draws, because it is the same vocabulary at both levels. Colour is
#: deliberately not part of this row: see the module docstring for why a table cell cannot
#: carry it the way a ``Static`` with a CSS class can.
_STATUS_GLYPH: Final[dict[str, str]] = {
    "ok": "\N{BLACK CIRCLE}",
    "warning": "\N{BLACK UP-POINTING TRIANGLE}",
    "error": "\N{MULTIPLICATION X}",
}

#: Marks the active row, ahead of its name (ADR 0032, decision 3: a marker ahead of the
#: active one). Shape, not colour - the same choice ``cli.py``'s own level-1 marker makes.
_ACTIVE_MARK: Final[str] = "\N{BLACK RIGHT-POINTING SMALL TRIANGLE} "

#: The four actions, in the order ADR 0032, decision 3, names them: usar, probar, editar,
#: borrar. Each id names the pair of i18n keys the label resolves through, and the command
#: ``cli.py`` runs once the screen has closed.
_ACTIONS: Final[tuple[ProfileAction, ...]] = ("use", "test", "edit", "remove")


def _status_cell(row: ProfileRow, locale: Locale) -> str:
    glyph = _STATUS_GLYPH[row.status]
    word = t(f"CLI.MENU_CONTEXT.STATUS_{row.status.upper()}", locale)
    return f"{glyph} {word}"


def _value_cell(value: str | None, locale: Locale) -> str:
    return value if value is not None else t("CLI.MENU_CONTEXT.NO_VALUE", locale)


class ProfilesApp(ThemedApp[ProfilesChoice]):
    """ "Ver perfiles": a table when there is something to show, one line when there is not."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "", show=False),
        # Only reachable on the empty state: a mounted DataTable's own binding answers
        # Enter first (it posts RowSelected), the same precedence the six-task menu
        # already relies on for its OptionList.
        Binding("enter", "configure", "", show=False),
    ]

    #: Off, as in the menu and the wizard: a second surface of keys has no place on a
    #: screen whose whole job is one table and four actions.
    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def __init__(self, *, rows: Sequence[ProfileRow], locale: Locale) -> None:
        """Build the screen.

        Args:
            rows: The profiles to show, in the order they should be read.
            locale: Language of every visible string.
        """
        super().__init__()
        self._rows: tuple[ProfileRow, ...] = tuple(rows)
        self._locale: Locale = locale
        self._mounted: bool = False

    # --- composition -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(t("CLI.PROFILES_SCREEN.TITLE", self._locale), id="title", markup=False)
            if self._rows:
                yield DataTable(id=_TABLE_ID, cursor_type="row", zebra_stripes=False)
                yield Static(t("CLI.PROFILES_SCREEN.KEYS", self._locale), id="keys", markup=False)
            else:
                yield Static(t("CLI.PROFILES_SCREEN.EMPTY", self._locale), id="empty", markup=False)
                yield Static(
                    t("CLI.PROFILES_SCREEN.EMPTY_KEYS", self._locale), id="keys", markup=False
                )

    def on_mount(self) -> None:
        if not self._rows:
            self._mounted = True
            return
        table = self.query_one(f"#{_TABLE_ID}", DataTable)
        table.add_columns(
            t("CLI.MENU_CONTEXT.PROFILE", self._locale),
            t("CLI.MENU_CONTEXT.HOST", self._locale),
            t("CLI.MENU_CONTEXT.DATABASE", self._locale),
            t("CLI.MENU_CONTEXT.MODE", self._locale),
            t("CLI.MENU_CONTEXT.STATUS", self._locale),
        )
        for row in self._rows:
            name_cell = f"{_ACTIVE_MARK if row.active else ''}{row.name}"
            table.add_row(
                name_cell,
                _value_cell(row.host, self._locale),
                _value_cell(row.database, self._locale),
                _value_cell(row.mode, self._locale),
                _status_cell(row, self._locale),
                key=row.name,
            )
        table.focus()
        self._mounted = True

    # --- events ------------------------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        """Degrade when the window drops below the minimum, same as the menu's own trigger."""
        if not self._mounted:
            return
        if event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT:
            self.exit(ProfilesChoice(status="degraded"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row: the four actions, in a modal pushed over the table."""
        event.stop()
        name = _row_name(event.row_key)
        self.push_screen(_ActionsModal(profile=name, locale=self._locale))

    # --- actions -------------------------------------------------------------------

    def action_cancel(self) -> None:
        """Escape: back to the six-task menu, not the end of the session (ADR 0032)."""
        self._finish("cancelled")

    def action_configure(self) -> None:
        """Enter on the empty state: the one offer it makes."""
        if not self._rows:
            self._finish("configure")

    def _finish(self, status: ProfilesStatus) -> None:
        self.exit(ProfilesChoice(status=status))


def _row_name(key: RowKey) -> str:
    """The profile name a row was keyed with - never ``None``, this screen always sets one."""
    value = key.value
    if value is None:  # pragma: no cover - defensive, every row here is keyed by name
        raise RuntimeError("a row of this table was not keyed with a profile name")
    return value


class _ActionsModal(ModalScreen[None]):
    """The four actions for one profile (ADR 0032, decision 3): usar, probar, editar, borrar.

    Picking one closes the whole application, not just this modal: the choice has to reach
    ``cli.py``, and ``ModalScreen.dismiss`` only returns to the screen under it. Escape
    dismisses instead, back to the table, exactly like the menu's own ``?`` modal.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "", show=False),
    ]

    def __init__(self, *, profile: str, locale: Locale) -> None:
        super().__init__()
        self._profile: str = profile
        self._locale: Locale = locale

    def compose(self) -> ComposeResult:
        with Vertical(id="actions-modal"):
            yield Static(
                t("CLI.PROFILES_SCREEN.ACTIONS_TITLE", self._locale, profile=self._profile),
                id="title",
                markup=False,
            )
            yield OptionList(
                *(
                    Option(
                        t(f"CLI.PROFILES_SCREEN.ACTION_{action.upper()}", self._locale),
                        id=action,
                    )
                    for action in _ACTIONS
                ),
                id="actions",
                markup=False,
                compact=True,
            )
            yield Static(
                t("CLI.PROFILES_SCREEN.ACTIONS_KEYS", self._locale), id="keys", markup=False
            )

    def on_mount(self) -> None:
        self.query_one("#actions", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        # Looked up rather than tested with ``in``: the lookup narrows the type on every
        # mypy the project supports (``>=1.10``), while ``in`` only narrows from 2.x, and a
        # ``cast`` that satisfies 1.x is flagged as redundant by 2.x. The ``None`` branch is
        # what proves the id is one of the four.
        action = next((known for known in _ACTIONS if known == event.option.id), None)
        if action is None:  # pragma: no cover - defensive, ids are set above
            raise RuntimeError(f"unexpected action id {event.option.id!r}")
        app = self.app
        if not isinstance(app, ProfilesApp):  # pragma: no cover - always pushed on one
            raise RuntimeError("the actions modal was pushed on an app that is not ProfilesApp")
        choice = ProfilesChoice(status="chosen", profile=self._profile, action=action)
        app.exit(choice)

    def action_close(self) -> None:
        self.dismiss()
