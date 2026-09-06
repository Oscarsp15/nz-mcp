"""The full-screen configuration wizard: the only module in the project that imports ``textual``.

Scope, and why it is this small
-------------------------------
This application does **one** thing: it collects the seven non-secret answers and reports
whether the credential has been provided. It does not validate against Netezza, it does
not write ``profiles.toml``, it does not touch the keyring, and it does not print a
result. All of that already exists in ``cli.py`` and runs *after* this screen closes, on
the ordinary terminal, through ``cli_output`` (ADR 0028, condition 2 and risk 4: a
full-screen interface clears the screen on exit, so the diagnosis has to be written where
it survives).

The credential (ADR 0029, condition 5)
--------------------------------------
It never enters the widget tree, and this module is built so that it *cannot*:

- the state model is :class:`nz_mcp.wizard.fields.DraftFields`, which has no password
  field, and one boolean next to it;
- asking for it is a callable handed in from outside, invoked inside ``App.suspend()`` so
  the question happens on the real terminal, and it returns a **boolean**;
- nothing in this package imports ``nz_mcp.secret`` or ``nz_mcp.auth``, so the type the
  credential travels in does not exist here.

That is checked, not promised: ``tests/contract/test_wizard_credential_guardrail.py``
parses this package and fails the build on a violation, and a second test drives the real
application and walks the finished widget tree looking for the value.

Degradation (ADR 0028, condition 1)
-----------------------------------
The five start-up triggers are decided before this module is even imported, by
``cli_output.interactive_ui_enabled()``. The sixth one lives here, because only a running
application can see it: a window shrunk **below the minimum during the session** closes
the screen with ``degraded`` and hands back everything typed so far, so the chained
questions resume with those answers as their defaults instead of from nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, Final

from textual import events
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Static

from nz_mcp.i18n import Locale, t
from nz_mcp.wizard.fields import (
    CREDENTIAL_SLOT,
    FIELD_SPECS,
    MIN_HEIGHT,
    MIN_WIDTH,
    DraftFields,
    WizardResult,
    WizardStatus,
    first_shape_error,
    label_key,
    missing_slots,
)

#: Prefix of the id of every editable row, so ``#field-host`` reads as what it is.
_FIELD_ID_PREFIX: Final[str] = "field-"


class ProfileWizardApp(App[WizardResult]):
    """One screen: the eight answers, what is still missing, and how to leave.

    Deliberately plain. No borders, no panels, no header, no command palette and no
    scrollbars: every one of them would be a Unicode box character or a surface to
    maintain, and the design of the CLI rules both out (``cli-experience.md`` §6.4 and the
    contention of risk 1 in ADR 0028 - ASCII only, because a Windows console on a legacy
    code page turns anything else into ``?``).
    """

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
    .row {
        height: 1;
    }
    .label {
        width: 15;
        height: 1;
        color: $text-muted;
    }
    Input {
        background: $panel;
    }
    Input:focus {
        background: $primary 40%;
    }
    /* No padding: this row has to line up with the values of the fields above it, and
       a compact Input starts its text right at the edge. */
    #credential-state {
        height: 1;
    }
    #explain {
        height: 6;
        margin-top: 1;
        color: $text-muted;
    }
    #status {
        height: 1;
    }
    #status.-blocked {
        color: $warning;
    }
    #status.-invalid {
        color: $error;
    }
    #status.-ready {
        color: $success;
    }
    #keys {
        height: 1;
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "submit", "", show=False),
        Binding("escape", "cancel", "", show=False),
        Binding("ctrl+p", "ask_credential", "", show=False),
    ]

    #: The palette is a whole second surface with its own keys and its own failure modes,
    #: and this screen has eight fields. Off.
    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def __init__(
        self,
        *,
        profile: str,
        initial: DraftFields,
        password_set: bool,
        ask_password: Callable[[], bool],
        locale: Locale,
    ) -> None:
        """Build the screen.

        Args:
            profile: Name of the profile being configured, shown in the title.
            initial: Answers to start from - the current values when a profile is being
                overwritten, or the defaults.
            password_set: Whether the credential has already been captured. A boolean, and
                never the credential itself.
            ask_password: Asks for the credential outside this application and returns
                whether one is now held. It returns a boolean by contract: this object has
                no way to read what it collected.
            locale: Language of every visible string.
        """
        super().__init__()
        self._profile = profile
        self._initial = initial
        self._password_set: bool = password_set
        self._ask_password: Callable[[], bool] = ask_password
        self._locale: Locale = locale
        self._mounted: bool = False

    # --- composition ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(
                t("CLI.WIZARD_UI_TITLE", self._locale, profile=self._profile),
                id="title",
                markup=False,
            )
            for spec in FIELD_SPECS:
                with Horizontal(classes="row"):
                    yield Label(t(spec.label_key, self._locale), classes="label", markup=False)
                    yield Input(
                        value=getattr(self._initial, spec.key),
                        id=f"{_FIELD_ID_PREFIX}{spec.key}",
                        # Compact: no border. The default one is drawn with Unicode box
                        # characters, which a Windows console on a legacy code page turns
                        # into ``?``; the field is marked out by its background instead.
                        compact=True,
                        # Not selecting the contents on focus is the difference between a
                        # form and a questionnaire. Coming back to a field is how a value
                        # gets *corrected*, and the default would wipe it on the first
                        # keystroke - which is the very thing this screen exists to avoid.
                        select_on_focus=False,
                    )
            with Horizontal(classes="row"):
                yield Label(
                    t(label_key(CREDENTIAL_SLOT), self._locale), classes="label", markup=False
                )
                yield Static("", id="credential-state", markup=False)
            yield Static("", id="explain", markup=False)
            yield Static("", id="status", markup=False)
            yield Static(t("CLI.WIZARD_UI_KEYS", self._locale), id="keys", markup=False)

    def on_mount(self) -> None:
        """Focus the first field and say what is missing before anything is typed."""
        self.query_one(f"#{_FIELD_ID_PREFIX}{FIELD_SPECS[0].key}", Input).focus()
        self._mounted = True
        self._update_state()

    # --- events --------------------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        """Degrade when the window drops below the minimum, keeping what was typed.

        The sixth trigger of ADR 0028, added by the audit of PR #222: shrinking a window
        mid-session is routine over SSH, and the other five only look at start-up. Leaving
        with ``degraded`` rather than repainting a broken screen is what turns a bug into a
        documented fallback - and the draft goes back with it, because losing eight
        answers to a window resize is exactly what issue #168 forbids.
        """
        if not self._mounted:
            return
        if event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT:
            self._finish("degraded")

    def on_input_changed(self, event: Input.Changed) -> None:
        del event  # the whole form is re-read; which field changed does not matter
        self._update_state()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter means "I am done": continue, or point at what is still missing."""
        event.stop()
        self.action_submit()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        del event  # the focused widget is read back from the screen
        self._refresh_explanation()

    # --- actions -------------------------------------------------------------

    def action_submit(self) -> None:
        """Leave with the draft, or move the focus to the first thing that blocks it."""
        draft = self._read_draft()
        shape = first_shape_error(draft)
        if shape is not None:
            self._focus_slot(shape[0])
            self._update_state()
            return
        missing = missing_slots(draft, password_set=self._password_set)
        if not missing:
            self._finish("completed")
            return
        if missing[0] == CREDENTIAL_SLOT:
            self.action_ask_credential()
            return
        self._focus_slot(missing[0])
        self._update_state()

    def action_cancel(self) -> None:
        self._finish("cancelled")

    def action_ask_credential(self) -> None:
        """Ask for the credential on the real terminal, never inside a widget.

        ``App.suspend()`` hands the terminal back so ``cli_output.ask_secret()`` can turn
        the echo off and ask for the confirmation exactly as it does in the chained
        questions. Some drivers cannot suspend - the headless one the tests use is the
        practical case - and there the question is still asked through the same callable,
        with the echo still off; what must not happen, and cannot, is the value reaching a
        widget.
        """
        try:
            with self.suspend():
                captured = self._ask_password()
        except SuspendNotSupported:
            captured = self._ask_password()
        if captured:
            self._password_set = True
        self.refresh()
        self._update_state()

    # --- state ---------------------------------------------------------------

    def _read_draft(self) -> DraftFields:
        """The current answers, read back from the fields rather than mirrored."""
        draft = DraftFields()
        for spec in FIELD_SPECS:
            widget = self.query_one(f"#{_FIELD_ID_PREFIX}{spec.key}", Input)
            setattr(draft, spec.key, widget.value)
        return draft

    def _focus_slot(self, slot: str) -> None:
        self.query_one(f"#{_FIELD_ID_PREFIX}{slot}", Input).focus()

    def _finish(self, status: WizardStatus) -> None:
        self.exit(
            WizardResult(
                status=status,
                fields=self._read_draft(),
                password_set=self._password_set,
            )
        )

    def _update_state(self) -> None:
        """Recompute the two lines that change: the credential row and the status line."""
        state_key = (
            "CLI.WIZARD_UI_PASSWORD_SET" if self._password_set else "CLI.WIZARD_UI_PASSWORD_UNSET"
        )
        self.query_one("#credential-state", Static).update(t(state_key, self._locale))
        message, marker = self._status_line()
        status = self.query_one("#status", Static)
        status.set_classes(f"-{marker}")
        status.update(message)

    def _status_line(self) -> tuple[str, str]:
        """What the single status line says: the blocker first, the go-ahead last.

        Colour only underlines it. The sentence carries the whole meaning, so redirecting
        the terminal or not seeing colour costs nothing (``cli-experience.md`` §6.5).
        """
        draft = self._read_draft()
        shape = first_shape_error(draft)
        if shape is not None:
            slot, message_key = shape
            return t(message_key, self._locale, value=getattr(draft, slot)), "invalid"
        missing = missing_slots(draft, password_set=self._password_set)
        if missing:
            names = ", ".join(t(label_key(slot), self._locale) for slot in missing)
            return t("CLI.WIZARD_UI_MISSING", self._locale, fields=names), "blocked"
        return t("CLI.WIZARD_UI_READY", self._locale), "ready"

    def _refresh_explanation(self) -> None:
        """Show the didactic line of the focused field: explain *while* answering.

        The chained questions print the explanation once, above the prompt, and it scrolls
        away. Here it stays for as long as the answer is being written, which is the same
        promise kept better - and it is the same catalog entry, not a second text to keep
        in sync.
        """
        focused = self.focused
        widget_id = "" if focused is None else (focused.id or "")
        slot = widget_id.removeprefix(_FIELD_ID_PREFIX) if widget_id else ""
        spec = next((item for item in FIELD_SPECS if item.key == slot), None)
        explanation = (
            "" if spec is None or spec.explain_key is None else t(spec.explain_key, self._locale)
        )
        self.query_one("#explain", Static).update(explanation)
