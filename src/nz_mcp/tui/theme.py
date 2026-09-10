"""The visual layer every full-screen surface shares: one stylesheet, two themes (ADR 0032).

Where colour lives
------------------
Here, and nowhere else. ``nz.tcss`` names surfaces and roles through ``$variables`` and never
writes a value; the two :class:`~textual.theme.Theme` objects below are the only place in the
product where a hexadecimal is spelled out. Every text/background pair they declare is
measured in ``tests/unit/test_tui_theme.py`` against the 4.5:1 floor of ADR 0032, decision
6, and the same file rejects any module of a screen that fixes a colour by hand: the rule of
decision 5 is enforced, not remembered.

Light is designed, not inverted (ADR 0032, decision 5): in ``nz-light`` the cards sit above
the background and the fields sink below it, which is the opposite of what a dark theme does.
Textual asks for a ``primary``; there is one accent, so ``primary`` is the accent and every
variable the framework derives from it follows the teal instead of a second colour.

The session
-----------
The theme chosen with F2 outlives the screen that chose it. The menu closes before the command
it launches runs (ADR 0030, decision 1), so the wizard that opens next is a new application in
the same process: :data:`_SESSION` carries the choice across, and nothing else does. It is not
written to disk and it does not survive the process - a preference file would be a feature,
and no ADR asks for one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from textual.app import App, ReturnType
from textual.binding import Binding, BindingType
from textual.theme import Theme

#: The one sheet. Located next to this module so it ships inside the wheel with it.
STYLESHEET: Final[Path] = Path(__file__).with_name("nz.tcss")

#: ``nz-dark`` - ADR 0032, decision 6. Everything that carries meaning clears 4.5:1 on the
#: background, the surface and the panel; the two bands are seen, not read, and only the
#: foreground and the accent are ever written on them.
NZ_DARK: Final[Theme] = Theme(
    name="nz-dark",
    primary="#5EEAD4",
    accent="#5EEAD4",
    foreground="#D6E0E2",
    background="#10171A",
    surface="#141D20",
    panel="#1C272B",
    success="#4ADE80",
    warning="#FBBF24",
    error="#F87171",
    dark=True,
    variables={
        # Textual would derive a muted text from black or white at 60%; declared instead,
        # so the pair is a measured one and not a guess.
        "text-muted": "#8E9B9D",
        # The row under the cursor: one band when the list is blurred, a brighter one when
        # it has the focus. Two carriers at once - the band and the bold.
        "band-idle": "#16262A",
        "band-focus": "#204045",
    },
)

#: ``nz-light`` - ADR 0032, decision 6. Cards (``surface``) above the background, fields
#: (``panel``) below it.
NZ_LIGHT: Final[Theme] = Theme(
    name="nz-light",
    primary="#0B6B63",
    accent="#0B6B63",
    foreground="#111A18",
    background="#E9EFED",
    surface="#FCFEFD",
    panel="#D5DEDB",
    success="#166534",
    warning="#92400E",
    error="#B91C1C",
    dark=False,
    variables={
        "text-muted": "#4E5856",
        "band-idle": "#DCE9E6",
        "band-focus": "#C9DFDA",
    },
)

THEMES: Final[tuple[Theme, Theme]] = (NZ_DARK, NZ_LIGHT)


@dataclass
class _ThemeSession:
    """Which theme is active, kept for the screens still to open in this process."""

    name: str = NZ_DARK.name


_SESSION: Final[_ThemeSession] = _ThemeSession()


class ThemedApp(App[ReturnType]):
    """A full-screen surface that draws from the shared sheet and answers F2.

    Every screen ADR 0032 authorises subclasses this and nothing else: the sheet, the two
    themes and the key that swaps them are inherited, so no screen can drift from the
    others on any of the three. A screen keeps its own bindings; Textual merges them with
    the one declared here.
    """

    CSS_PATH: ClassVar[Path] = STYLESHEET

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f2", "toggle_theme", "", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        for theme in THEMES:
            self.register_theme(theme)
        # Applied here and not in ``on_mount``: the sheet is read before anything mounts,
        # and it names variables only these two themes define.
        self.theme = _SESSION.name

    def action_toggle_theme(self) -> None:
        """F2: the other theme, for this screen and for every one that opens after it."""
        self.theme = NZ_LIGHT.name if self.theme == NZ_DARK.name else NZ_DARK.name
        _SESSION.name = self.theme
