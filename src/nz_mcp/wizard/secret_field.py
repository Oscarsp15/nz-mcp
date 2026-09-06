"""A password field that stores a number instead of the password.

What it is
----------
An editable, focusable, masked field whose **entire state is three integers and a
boolean**: how many characters have been typed, where the caret is, where a selection
started, and whether the credential came from the terminal instead. There is no buffer
here, no ``value``, no reactive string. Every keystroke is handed straight to a
:class:`~nz_mcp.wizard.fields.CredentialSink` that lives outside the widget tree, and the
mask on screen is built from the counter, not from what was typed.

Why a counter, rather than an ``Input``
---------------------------------------
ADR 0029 measured that ``textual``'s ``Input`` rebuilds its value on every keystroke with
``f"{value[:start]}{text}{value[end:]}"``, so a ``Secret`` does not survive the first key
and what stays in the DOM is a bare ``str``, alive for the whole session. Nothing here
concatenates anything: ``insert`` and ``remove`` are told an *index*, and the sink keeps
the characters apart until the wizard is over.

The paste, and why it is refused
--------------------------------
Measured on ``textual`` 8.2.8, on the same interpreter as the rest of ADR 0029:

- ``events.Paste`` carries the whole pasted text as a bare ``str`` (``Paste(text: str)``),
  built by the terminal parser **before** any handler of ours runs.
- That message object is still alive **after** the handler returns. Weak-referenced, it
  survived the dispatch and 300 ms of idling, and was only collected once another message
  had been processed. While the session sits idle, the credential stays inside the
  framework's message pump, and no code in this package can shorten that.

So a paste cannot be consumed "without leaving anything anywhere": the copy exists before
we are asked and outlives our answer. This field therefore **refuses the paste without
reading it** - the ``text`` of the event is never touched, here or anywhere in the
package, and a static rule in ``tests/contract/test_wizard_credential_guardrail.py`` keeps
it that way - and points at Ctrl+P, which asks on the real terminal with the echo off and
wraps the answer in a ``Secret`` on the first line of our own code.

What is on screen
-----------------
Only while the field has the focus: one ``*`` per character, ``#`` over a selection and
``_`` for the caret. Unfocused it says whether a credential is held and nothing else, so
the screen someone walks away from - and the recap of ``cli-experience.md`` section 4 -
never carries even the length.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual import events
from textual.message import Message
from textual.widget import Widget

from nz_mcp.i18n import Locale, t
from nz_mcp.wizard.fields import CredentialSink

#: One typed character. ASCII, like everything else this wizard draws: a Windows console
#: on a legacy code page turns anything else into a question mark.
_MASK: Final[str] = "*"

#: A character inside the selection.
_SELECTED: Final[str] = "#"

#: The caret, drawn *between* characters, which is where an insertion happens.
_CARET: Final[str] = "_"

#: ``_anchor`` when there is no selection. A sentinel rather than ``None`` so the whole
#: state of this widget stays countable: three integers and a boolean, nothing else.
_NO_SELECTION: Final[int] = -1

#: Keys this field acts on. Everything else - Tab, Enter, Esc, Ctrl+S, Ctrl+P - is left to
#: bubble, so the form still moves and still submits from inside the credential row.
_EDIT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "backspace",
        "delete",
        "left",
        "right",
        "home",
        "end",
        "shift+home",
        "shift+end",
        "ctrl+a",
        "ctrl+u",
    }
)


class SecretField(Widget, can_focus=True):
    """The credential row: masked, editable, and empty of the credential."""

    class Changed(Message):
        """The field now holds a credential, or has stopped holding one.

        A boolean. It is the same thing the wizard has always published about the
        credential (ADR 0029, condition 5, clause 1) and the reason the application's
        state model still has no room for a password.
        """

        def __init__(self, held: bool) -> None:
            super().__init__()
            self.held: bool = held

    class PasteRejected(Message):
        """A paste arrived and was dropped unread. Carries nothing, on purpose."""

    DEFAULT_CSS: ClassVar[str] = """
    SecretField {
        height: 1;
        background: $panel;
    }
    SecretField:focus {
        background: $primary 40%;
    }
    """

    def __init__(self, credential: CredentialSink, locale: Locale) -> None:
        """Build the field.

        Args:
            credential: Where the characters go. Write-only by its own protocol, so this
                widget can edit the credential and can never read it back.
            locale: Language of the states it can say out loud.
        """
        super().__init__()
        self._credential: CredentialSink = credential
        self._locale: Locale = locale
        self._length: int = 0
        self._cursor: int = 0
        self._anchor: int = _NO_SELECTION
        self._external: bool = False

    # --- what is drawn -------------------------------------------------------

    def render(self) -> str:
        """The mask while typing, a state while not. Built from the counters, always.

        A credential given on the terminal keeps the state text even with the focus on it:
        its counter is zero, so the mask would be a bare caret and would read as *empty*,
        which is the one thing it is not.
        """
        if self.has_focus and not self._external:
            return self._mask()
        return t(self._state_key(), self._locale)

    def _state_key(self) -> str:
        if self._external:
            return "CLI.WIZARD_UI_PASSWORD_TERMINAL"
        return "CLI.WIZARD_UI_PASSWORD_SET" if self._length else "CLI.WIZARD_UI_PASSWORD_UNSET"

    def _mask(self) -> str:
        """One cell per character, from the counter. Nothing typed is consulted."""
        start, stop = self._selection()
        cells = [_SELECTED if start <= index < stop else _MASK for index in range(self._length)]
        if start == stop:
            cells.insert(self._cursor, _CARET)
        return "".join(cells)

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    # --- input ---------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        """Act on one key, or let it bubble.

        The character of the event is handed to :meth:`_type` without being bound to a
        name here: the only thing that ever touches it is the sink, one character at a
        time, and the sink cannot be read back.
        """
        if event.key in _EDIT_KEYS:
            self._edit(event.key)
        elif event.is_printable and event.character is not None:
            self._type(event.character)
        else:
            return
        event.stop()
        event.prevent_default()
        self.refresh()
        self.post_message(self.Changed(self.holds_credential()))

    def on_paste(self, event: events.Paste) -> None:
        """Drop the paste without reading it. The module docstring has the measurement.

        The pasted string is deliberately not touched. Reading it would not make the leak
        better or worse - it already exists and it outlives this handler - but it would
        put a full copy of the credential into the wizard's own state, which is the one
        thing this field exists to prevent.
        """
        event.stop()
        event.prevent_default()
        self.post_message(self.PasteRejected())

    # --- editing, entirely on the counters -----------------------------------

    def holds_credential(self) -> bool:
        """Whether there is a credential now. A boolean is all this field ever says."""
        return self._external or self._length > 0

    def mark_held_elsewhere(self) -> None:
        """The credential was typed on the real terminal, so the counters start over.

        The field does not learn its length, and does not draw it. Typing here replaces
        it, which the first keystroke makes obvious by restarting the mask at one cell.
        """
        self._external = True
        self._length = 0
        self._cursor = 0
        self._anchor = _NO_SELECTION
        self.refresh()
        self.post_message(self.Changed(True))

    def _selection(self) -> tuple[int, int]:
        if self._anchor in (_NO_SELECTION, self._cursor):
            return self._cursor, self._cursor
        return min(self._anchor, self._cursor), max(self._anchor, self._cursor)

    def _type(self, character: str) -> None:
        self._discard_external()
        self._delete_selection()
        self._credential.insert(self._cursor, character)
        self._length += 1
        self._cursor += 1

    def _delete_selection(self) -> bool:
        start, stop = self._selection()
        if start == stop:
            return False
        self._credential.remove(start, stop)
        self._length -= stop - start
        self._cursor = start
        self._anchor = _NO_SELECTION
        return True

    def _discard_external(self) -> None:
        """A credential given on the terminal is replaced, not appended to."""
        if not self._external:
            return
        self._credential.clear()
        self._external = False
        self._length = 0
        self._cursor = 0
        self._anchor = _NO_SELECTION

    def _edit(self, key: str) -> None:
        if key == "backspace":
            self._backspace()
        elif key == "delete":
            self._forward_delete()
        elif key == "ctrl+u":
            self._discard_external()
            self._credential.clear()
            self._length = 0
            self._cursor = 0
            self._anchor = _NO_SELECTION
        else:
            self._move(key)

    def _backspace(self) -> None:
        self._discard_external()
        if self._delete_selection() or self._cursor == 0:
            return
        self._credential.remove(self._cursor - 1, self._cursor)
        self._length -= 1
        self._cursor -= 1

    def _forward_delete(self) -> None:
        self._discard_external()
        if self._delete_selection() or self._cursor >= self._length:
            return
        self._credential.remove(self._cursor, self._cursor + 1)
        self._length -= 1

    def _move(self, key: str) -> None:
        """Caret and selection. ``shift+`` extends from wherever the selection started."""
        if key == "ctrl+a":
            self._anchor = 0
            self._cursor = self._length
            return
        if key.startswith("shift+"):
            if self._anchor == _NO_SELECTION:
                self._anchor = self._cursor
        else:
            self._anchor = _NO_SELECTION
        if key in ("left", "right"):
            step = -1 if key == "left" else 1
            self._cursor = min(max(self._cursor + step, 0), self._length)
        elif key in ("home", "shift+home"):
            self._cursor = 0
        else:
            self._cursor = self._length
