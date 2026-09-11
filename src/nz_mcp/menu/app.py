"""The interactive menu: one of the three packages in the project that import ``textual``.

Scope, and why it is this small
-------------------------------
This application does **one** thing: it lets someone pick one of six tasks (ADR 0032,
decision 1) and says which command answers it. It does not run anything, it does not know
what a command does beyond its own sentence, and it does not print a result. Everything
that happens after a choice happens in ``cli.py``, on the ordinary terminal, through
``cli_output`` - which is also why the screen closes before the command runs instead of
hosting it (ADR 0030: the menu chooses, it does not host).

What it draws, and what it deliberately does not
------------------------------------------------
A title, the six tasks (never a command name - ADR 0032, decision 1), one line describing
the highlighted one, a context panel for the active profile, and the keys. Nothing else. No
banner, no logo, no emoji: every one of them is ruled out by ``cli-experience.md`` §6.

How it looks is not decided here. Colour and theme come from the sheet and the two themes of
:mod:`nz_mcp.tui` (ADR 0032, decision 5), inherited through :class:`~nz_mcp.tui.ThemedApp`
with the key that swaps them; this module owns the layout and nothing more.

The description sits **under** the list rather than next to each name, and that is a
measurement rather than a taste, inherited from the eleven-command version of this screen:
at the minimum width the list column would leave too little room for a sentence next to
every row. One description shown whole, for the row being read, says more than six cut in
half - and it is the same thing the wizard already does with the explanation of the focused
field.

``?``: the one place a command name appears (ADR 0032, decision 2)
--------------------------------------------------------------------
Every other line on this screen speaks in tasks. ``?`` opens the single exception: a modal
with the task -> command correspondence, built from :class:`~nz_mcp.menu.entries.MenuEntry`
the same way ``nz-mcp help`` builds its plain-text version of the same list (issue #239).
Escape closes it and hands focus back to whatever had it, which is Textual's own behaviour
for a screen that was pushed rather than replaced.

Degradation (ADR 0028, condition 1, inherited by ADR 0030)
----------------------------------------------------------
The eight start-up triggers are decided before this module is even imported, by
``cli_output.interactive_ui_enabled()``. One more lives here, because only a running
application can see it: a window shrunk **below the minimum during the session** closes the
screen with ``degraded``, and the entry point prints the help - the same fallback as for
the other eight.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from nz_mcp.i18n import Locale, t
from nz_mcp.menu.entries import (
    MIN_HEIGHT,
    MIN_WIDTH,
    MenuChoice,
    MenuContext,
    MenuEntry,
    MenuStatus,
    command_line,
)
from nz_mcp.tui import ThemedApp

#: Id of the list widget, so ``#commands`` reads as what it is.
_COMMANDS_ID: Final[str] = "commands"

#: The glyph half of "forma + palabra + color" (ADR 0032, decision 7). Not a colour - the
#: colour comes from the ``-ok`` / ``-warning`` / ``-error`` classes in ``nz.tcss`` - so this
#: is a shape, exactly like ``_ACTIVE_MARK`` in ``cli.py`` is a shape and not a colour.
_STATUS_GLYPH: Final[dict[str, str]] = {
    "ok": "\N{BLACK CIRCLE}",
    "warning": "\N{BLACK UP-POINTING TRIANGLE}",
    "error": "\N{MULTIPLICATION X}",
}

#: The i18n keys of the context panel's plain lookup rows, in the order ADR 0032, decision
#: 1, gives for its own example: Perfil, Host, Base. Mode and the status word are resolved
#: by the two helpers below rather than through this table, because neither is a plain
#: catalog lookup.
_CONTEXT_ROWS: Final[tuple[tuple[str, str], ...]] = (
    ("CLI.MENU_CONTEXT.PROFILE", "profile"),
    ("CLI.MENU_CONTEXT.HOST", "host"),
    ("CLI.MENU_CONTEXT.DATABASE", "database"),
)


class CommandMenuApp(ThemedApp[MenuChoice]):
    """One screen: six tasks, the active profile, and how to leave."""

    BINDINGS: ClassVar[list[BindingType]] = [
        # Enter is the list's own binding and arrives as OptionSelected; only the way out
        # and the one command name of the screen need one here.
        Binding("escape", "cancel", "", show=False),
        Binding("question_mark", "help", "", show=False),
    ]

    #: A second surface with its own keys and its own failure modes, on a screen whose
    #: entire job is to offer six of them. Off, as in the wizard.
    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def __init__(
        self, *, entries: Sequence[MenuEntry], locale: Locale, context: MenuContext
    ) -> None:
        """Build the screen.

        Args:
            entries: The tasks to offer, in the order they should be read.
            locale: Language of every visible string.
            context: The active profile, for the panel.
        """
        super().__init__()
        self._entries: tuple[MenuEntry, ...] = tuple(entries)
        self._locale: Locale = locale
        self._active_profile: MenuContext = context
        self._mounted: bool = False

    # --- composition ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(t("CLI.MENU_TITLE", self._locale), id="title", markup=False)
            with Horizontal(id="body"):
                with Vertical(id="tasks"):
                    yield OptionList(
                        *(Option(entry.label, id=entry.command) for entry in self._entries),
                        id=_COMMANDS_ID,
                        # Markup off: a label is a literal, and square brackets in one would
                        # otherwise be read as styling. Compact: no border, for the reason
                        # the wizard has none either - the default is drawn with Unicode box
                        # characters.
                        markup=False,
                        compact=True,
                    )
                    yield Static("", id="describe", markup=False)
                with Vertical(id="context"):
                    yield Static(
                        t("CLI.MENU_CONTEXT.TITLE", self._locale),
                        id="context-title",
                        markup=False,
                    )
                    for key, field in _CONTEXT_ROWS:
                        yield Static(
                            self._row(key, getattr(self._active_profile, field)),
                            id=f"context-{field}",
                            classes="row",
                            markup=False,
                        )
                    yield Static(self._mode_row(), id="context-mode", classes="row", markup=False)
                    yield Static(
                        self._status_row(),
                        id="context-status",
                        classes=f"row -{self._active_profile.status}",
                        markup=False,
                    )
            yield Static(t("CLI.MENU_KEYS", self._locale), id="keys", markup=False)

    def on_mount(self) -> None:
        """Start on the first task - "Configurar una conexion", the one to start with."""
        commands = self.query_one(f"#{_COMMANDS_ID}", OptionList)
        commands.focus()
        if self._entries:
            commands.highlighted = 0
        self._mounted = True
        self._describe(0 if self._entries else None)

    # --- events --------------------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        """Degrade when the window drops below the minimum.

        The ninth trigger. Shrinking a window mid-session is routine over SSH, and the
        other eight only look at start-up; leaving with ``degraded`` rather than repainting a
        broken screen is what turns a bug into a documented fallback - here, the help.
        """
        if not self._mounted:
            return
        if event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT:
            self._finish("degraded")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Say what the task under the cursor does, while it is under the cursor."""
        self._describe(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter means "do this one": the screen closes and the caller takes over."""
        event.stop()
        self.exit(MenuChoice(status="chosen", command=self._entries[event.option_index].command))

    # --- actions -------------------------------------------------------------

    def action_cancel(self) -> None:
        """Escape means "never mind". Nothing runs, and that is not an error."""
        self._finish("cancelled")

    def action_help(self) -> None:
        """``?``: the task -> command correspondence, and the only place it is shown."""
        self.push_screen(_HelpModal(entries=self._entries, locale=self._locale))

    # --- state ---------------------------------------------------------------

    def _describe(self, index: int | None) -> None:
        """Show the sentence of the task at ``index``, or nothing when there is none."""
        description = "" if index is None else self._entries[index].description
        self.query_one("#describe", Static).update(description)

    def _finish(self, status: MenuStatus) -> None:
        self.exit(MenuChoice(status=status))

    def _row(self, label_key: str, value: str | None) -> str:
        """One ``Etiqueta: valor`` line of the context panel (ADR 0032, decision 1)."""
        shown = value if value is not None else t("CLI.MENU_CONTEXT.NO_VALUE", self._locale)
        return f"{t(label_key, self._locale)}: {shown}"

    def _mode_row(self) -> str:
        """``Modo`` as configuration spells it - never prose (ADR 0032, decision 1)."""
        mode = self._active_profile.mode or t("CLI.MENU_CONTEXT.NO_VALUE", self._locale)
        return f"{t('CLI.MENU_CONTEXT.MODE', self._locale)}: {mode}"

    def _status_row(self) -> str:
        """``Estado``: shape and word together, colour carried by the ``-<status>`` class."""
        glyph = _STATUS_GLYPH[self._active_profile.status]
        word = t(f"CLI.MENU_CONTEXT.STATUS_{self._active_profile.status.upper()}", self._locale)
        return f"{t('CLI.MENU_CONTEXT.STATUS', self._locale)}: {glyph} {word}"


class _HelpModal(ModalScreen[None]):
    """``?``'s modal: the task -> command correspondence, and nothing else (ADR 0032, decision 2).

    A :class:`~textual.screen.ModalScreen` pushed onto the running application, not a fourth
    surface: it shares the one stylesheet the app already loaded and closes with the app's
    own focus-restoring behaviour, so the list under it is exactly where the cursor left it.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "", show=False),
    ]

    def __init__(self, *, entries: Sequence[MenuEntry], locale: Locale) -> None:
        super().__init__()
        self._entries: tuple[MenuEntry, ...] = tuple(entries)
        self._locale: Locale = locale

    def compose(self) -> ComposeResult:
        unavailable = t("CLI.MENU_HELP_MODAL.UNAVAILABLE", self._locale)
        with Vertical(id="help-modal"):
            yield Static(t("CLI.MENU_HELP_MODAL.TITLE", self._locale), id="title", markup=False)
            for entry in self._entries:
                yield Static(command_line(entry, unavailable=unavailable), markup=False)
            yield Static(t("CLI.MENU_HELP_MODAL.KEYS", self._locale), id="keys", markup=False)

    def action_close(self) -> None:
        self.dismiss()
