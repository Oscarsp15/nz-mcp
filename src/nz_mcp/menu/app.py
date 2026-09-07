"""The interactive menu: one of the two modules in the project that import ``textual``.

Scope, and why it is this small
-------------------------------
This application does **one** thing: it lets someone pick one of the commands it was given
and says which one. It does not run anything, it does not know what a command does, and it
does not print a result. Everything that happens after a choice happens in ``cli.py``, on
the ordinary terminal, through ``cli_output`` - which is also why the screen closes before
the command runs instead of hosting it (ADR 0030: the menu chooses, it does not host).

What it draws, and what it deliberately does not
------------------------------------------------
A title, the list of command names, one line describing the highlighted one, and the keys.
Nothing else. No banner, no logo, no emoji, no borders and no panels grouping the commands:
every one of them is ruled out by ``cli-experience.md`` §6, and the last one buys structure
the ordering already provides.

The description sits **under** the list rather than next to each name, and that is a
measurement rather than a taste. At the minimum width the list column would leave about
thirty cells for a sentence that is up to eighty characters long, so every single row would
end in an ellipsis. One description shown whole, for the row being read, says more than
eleven cut in half - and it is the same thing the wizard already does with the explanation
of the focused field.

Degradation (ADR 0028, condition 1, inherited by ADR 0030)
----------------------------------------------------------
The seven start-up triggers are decided before this module is even imported, by
``cli_output.interactive_ui_enabled()``. The eighth one lives here, because only a running
application can see it: a window shrunk **below the minimum during the session** closes the
screen with ``degraded``, and the entry point prints the help - the same fallback as for
the other seven.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from nz_mcp.i18n import Locale, t
from nz_mcp.menu.entries import MIN_HEIGHT, MIN_WIDTH, MenuChoice, MenuEntry, MenuStatus

#: Id of the list widget, so ``#commands`` reads as what it is.
_COMMANDS_ID: Final[str] = "commands"


class CommandMenuApp(App[MenuChoice]):
    """One screen: the commands, what the highlighted one does, and how to leave."""

    CSS: ClassVar[str] = """
    Screen {
        background: $surface;
    }
    #frame {
        padding: 1 2;
    }
    #title {
        text-style: bold;
        margin-bottom: 1;
    }
    /* 1fr and not auto: if this list ever outgrows the window it scrolls, instead of
       pushing the description and the keys off the bottom. */
    OptionList {
        height: 1fr;
        background: $surface;
        border: none;
        padding: 0;
    }
    #describe {
        height: 3;
        margin-top: 1;
        color: $text-muted;
    }
    #keys {
        height: 1;
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # Enter is the list's own binding and arrives as OptionSelected; only the way out
        # needs one here.
        Binding("escape", "cancel", "", show=False),
    ]

    #: A second surface with its own keys and its own failure modes, on a screen whose
    #: entire job is to offer eleven of them. Off, as in the wizard.
    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def __init__(self, *, entries: Sequence[MenuEntry], locale: Locale) -> None:
        """Build the screen.

        Args:
            entries: The commands to offer, in the order they should be read.
            locale: Language of every visible string.
        """
        super().__init__()
        self._entries: tuple[MenuEntry, ...] = tuple(entries)
        self._locale: Locale = locale
        self._mounted: bool = False

    # --- composition ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(t("CLI.MENU_TITLE", self._locale), id="title", markup=False)
            yield OptionList(
                *(Option(entry.command, id=entry.command) for entry in self._entries),
                id=_COMMANDS_ID,
                # Markup off: a command name is a literal, and square brackets in one would
                # otherwise be read as styling. Compact: no border, for the reason the
                # wizard has none either - the default is drawn with Unicode box characters.
                markup=False,
                compact=True,
            )
            yield Static("", id="describe", markup=False)
            yield Static(t("CLI.MENU_KEYS", self._locale), id="keys", markup=False)

    def on_mount(self) -> None:
        """Start on the first command - which is ``init``, the one to start with."""
        commands = self.query_one(f"#{_COMMANDS_ID}", OptionList)
        commands.focus()
        if self._entries:
            commands.highlighted = 0
        self._mounted = True
        self._describe(0 if self._entries else None)

    # --- events --------------------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        """Degrade when the window drops below the minimum.

        The eighth trigger. Shrinking a window mid-session is routine over SSH, and the
        other seven only look at start-up; leaving with ``degraded`` rather than repainting a
        broken screen is what turns a bug into a documented fallback - here, the help.
        """
        if not self._mounted:
            return
        if event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT:
            self._finish("degraded")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Say what the command under the cursor does, while it is under the cursor."""
        self._describe(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter means "run this one": the screen closes and the caller takes over."""
        event.stop()
        self.exit(MenuChoice(status="chosen", command=self._entries[event.option_index].command))

    # --- actions -------------------------------------------------------------

    def action_cancel(self) -> None:
        """Escape means "never mind". Nothing runs, and that is not an error."""
        self._finish("cancelled")

    # --- state ---------------------------------------------------------------

    def _describe(self, index: int | None) -> None:
        """Show the sentence of the command at ``index``, or nothing when there is none."""
        description = "" if index is None else self._entries[index].description
        self.query_one("#describe", Static).update(description)

    def _finish(self, status: MenuStatus) -> None:
        self.exit(MenuChoice(status=status))
