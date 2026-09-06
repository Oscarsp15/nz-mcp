"""The full-screen wizard itself, driven through ``Pilot`` (ADR 0029: it is testable).

An interface nobody tests breaks in silence, and the ADR made testability a criterion for
discarding a library rather than a nice-to-have. ``App.run_test(headless=True, size=...)``
runs the real application without a terminal and hands back a ``Pilot`` that presses keys
and resizes the window, so every assertion below is against the state of the real thing.

What is checked here:

- the form collects what was typed, and the draft that comes out carries it;
- the status line names what is still missing, and what will not parse;
- the three exits: completed, cancelled, and the seventh degradation trigger - a window
  shrunk **below the minimum mid-session**, which must give back everything typed;
- the screen adapts between the minimum and a large window (ADR 0028, condition 4);
- both languages render.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Final

import pytest
from textual.widget import Widget
from textual.widgets import Input, Static

from nz_mcp.i18n import Locale, t
from nz_mcp.wizard import MIN_HEIGHT, MIN_WIDTH, DraftFields, WizardResult
from nz_mcp.wizard.app import ProfileWizardApp
from nz_mcp.wizard.secret_field import SecretField

#: A window with room to spare, and the minimum one, used side by side on purpose.
_ROOMY: Final[tuple[int, int]] = (100, 30)
_MINIMUM: Final[tuple[int, int]] = (MIN_WIDTH, MIN_HEIGHT)

#: Small enough that nothing this wizard draws could fit. The kind of window an SSH client
#: ends up with when someone drags the corner of the terminal.
_TINY: Final[tuple[int, int]] = (40, 10)


def _complete_draft() -> DraftFields:
    return DraftFields(host="nz.example.com", database="PROD", user="svc")


class _Sink:
    """A stand-in for ``cli._CredentialHolder``: characters, kept apart, outside the tree."""

    def __init__(self) -> None:
        self.characters: list[str] = []

    def insert(self, index: int, character: str) -> None:
        self.characters.insert(index, character)

    def remove(self, start: int, stop: int) -> None:
        del self.characters[start:stop]

    def clear(self) -> None:
        self.characters.clear()

    def joined(self) -> str:
        return "".join(self.characters)


def _app(
    *,
    initial: DraftFields | None = None,
    password_set: bool = True,
    ask_password: Callable[[], bool] | None = None,
    credential: _Sink | None = None,
    locale: Locale = "es",
) -> ProfileWizardApp:
    """Build the wizard with everything already answered unless a test says otherwise."""
    return ProfileWizardApp(
        profile="dev",
        initial=_complete_draft() if initial is None else initial,
        password_set=password_set,
        ask_password=(lambda: True) if ask_password is None else ask_password,
        credential=_Sink() if credential is None else credential,
        locale=locale,
    )


def _status(app: ProfileWizardApp) -> str:
    return str(app.query_one("#status", Static).content)


def _explanation(app: ProfileWizardApp) -> str:
    return str(app.query_one("#explain", Static).content)


def _result(app: ProfileWizardApp) -> WizardResult:
    value = app.return_value
    assert value is not None, "the wizard closed without saying how"
    return value


@pytest.mark.asyncio
async def test_typing_ends_up_in_the_draft_that_comes_back() -> None:
    """The point of a form: eight answers that exist at once and can be edited."""
    app = _app(initial=DraftFields(database="PROD", user="svc"))
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press(*"nz.example.com")
        await pilot.pause()
        assert app.query_one("#field-host", Input).value == "nz.example.com"
        await pilot.press("enter")
        await pilot.pause()

    result = _result(app)
    assert result.status == "completed"
    assert result.fields.host == "nz.example.com"
    assert result.fields.database == "PROD"
    assert result.password_set is True


@pytest.mark.asyncio
async def test_going_back_to_an_earlier_field_does_not_undo_the_later_ones() -> None:
    """The whole reason this screen exists (issue #221).

    Chained questions cannot do this: correcting the host means answering the seven
    questions after it again. Here the focus moves back and everything else stays put -
    and, just as importantly, focusing a field does not select its contents, so the first
    keystroke edits the value instead of replacing it.
    """
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        app.query_one("#field-user", Input).focus()
        await pilot.press("end", *"_2")
        await pilot.pause()
        app.query_one("#field-host", Input).focus()
        await pilot.press("end", *".uk")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

    result = _result(app)
    assert result.fields.host == "nz.example.com.uk"
    assert result.fields.user == "svc_2"
    assert result.fields.database == "PROD"


@pytest.mark.asyncio
async def test_the_status_line_names_what_is_still_missing() -> None:
    """ "See what is missing" is one of the four things the issue asks for."""
    app = _app(initial=DraftFields(), password_set=False)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        status = _status(app)
        await pilot.press("escape")

    assert t("CLI.WIZARD_FIELD_HOST", "es") in status
    assert t("CLI.WIZARD_FIELD_DATABASE", "es") in status
    assert t("CLI.WIZARD_FIELD_PASSWORD", "es") in status
    # ca_certs is optional, so it is never something that is "missing".
    assert t("CLI.WIZARD_FIELD_CA_CERTS", "es") not in status


@pytest.mark.asyncio
async def test_a_complete_form_says_so_before_anything_is_validated() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        status = _status(app)
        await pilot.press("escape")

    assert status == t("CLI.WIZARD_UI_READY", "es")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slot", "typed", "message_key"),
    [
        pytest.param("port", "not-a-number", "CLI.WIZARD_PORT_INVALID", id="port"),
        pytest.param("mode", "root", "CLI.WIZARD_MODE_INVALID", id="mode"),
        pytest.param("security_level", "9", "CLI.WIZARD_SECURITY_INVALID", id="security-level"),
    ],
)
async def test_a_value_that_will_not_parse_is_reported_and_blocks_the_exit(
    slot: str, typed: str, message_key: str
) -> None:
    """The same three rules the chained questions enforce, from the same functions.

    Enforced *while* typing rather than after eight questions, which is the difference a
    form buys. The message is the very same catalog entry.
    """
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        field = app.query_one(f"#field-{slot}", Input)
        field.focus()
        field.clear()
        await pilot.press(*typed)
        await pilot.pause()
        blocked = _status(app)
        await pilot.press("ctrl+s")
        await pilot.pause()
        still_running = app.return_value is None
        await pilot.press("escape")

    assert blocked == t(message_key, "es", value=typed)
    assert still_running, "a value that will not parse must not reach the validation ladder"


@pytest.mark.asyncio
async def test_the_focused_field_explains_itself() -> None:
    """ "Explain before asking" survives the change of shape (ADR 0028, condition 2).

    The chained questions print the explanation once and it scrolls away; here it is on
    screen for as long as the answer is being written. Same catalog entry, no second text.
    """
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        app.query_one("#field-mode", Input).focus()
        await pilot.pause()
        explaining_mode = _explanation(app)
        app.query_one("#field-host", Input).focus()
        await pilot.pause()
        explaining_host = _explanation(app)
        await pilot.press("escape")

    assert explaining_mode == t("CLI.WIZARD_MODE_EXPLAIN", "es")
    assert explaining_host == "", "host needs no explanation, so it gets none"


@pytest.mark.asyncio
async def test_the_credential_is_the_last_gap_and_the_focus_goes_to_it() -> None:
    """Pressing continue with everything else filled moves to the one gap, in place.

    It used to suspend the whole interface here and ask outside. Issue #224 replaced that
    with the field: the credential row is now a row like the other seven, and continuing
    lands the focus on it instead of tearing the screen down.
    """
    asked: list[int] = []
    sink = _Sink()

    def ask_password() -> bool:
        asked.append(1)
        return True

    app = _app(password_set=False, ask_password=ask_password, credential=sink)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert asked == [], "the interface must not be suspended just to ask"
        assert isinstance(app.focused, SecretField)
        await pilot.press(*"hunter2")
        await pilot.pause()
        assert _status(app) == t("CLI.WIZARD_UI_READY", "es")
        await pilot.press("enter")
        await pilot.pause()

    assert _result(app).status == "completed"
    assert _result(app).password_set is True
    assert sink.joined() == "hunter2"


@pytest.mark.asyncio
async def test_declining_to_type_the_credential_leaves_the_form_open() -> None:
    """Aborting the credential prompt must not throw the other seven answers away."""
    app = _app(password_set=False, ask_password=lambda: False)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert app.return_value is None
        assert t("CLI.WIZARD_FIELD_PASSWORD", "es") in _status(app)
        await pilot.press("escape")

    assert _result(app).fields.host == "nz.example.com"


@pytest.mark.asyncio
async def test_escape_cancels_and_says_so() -> None:
    app = _app()
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("escape")
        await pilot.pause()

    assert _result(app).status == "cancelled"


@pytest.mark.asyncio
async def test_shrinking_the_window_mid_session_degrades_without_losing_anything() -> None:
    """The seventh trigger, added by the audit of PR #222.

    The other five are decided before the application starts. This one can only be seen
    from inside it, and it is the routine case over SSH: someone drags the corner of the
    terminal and the screen no longer fits. What must **not** happen is a broken screen in
    the middle of the flow, and what must not happen either is losing the answers - that is
    the rule of issue #168.
    """
    app = _app(initial=DraftFields(database="PROD", user="svc"))
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press(*"nz.example.com")
        await pilot.pause()
        await pilot.resize_terminal(*_TINY)
        await pilot.pause()

    result = _result(app)
    assert result.status == "degraded"
    assert result.fields.host == "nz.example.com", "the answer typed before the resize was lost"
    assert result.fields.database == "PROD"
    assert result.fields.user == "svc"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("width", "height"),
    [
        pytest.param(MIN_WIDTH - 1, MIN_HEIGHT, id="one-column-too-narrow"),
        pytest.param(MIN_WIDTH, MIN_HEIGHT - 1, id="one-row-too-short"),
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
        assert _status(app) == t("CLI.WIZARD_UI_READY", "es")
        await pilot.resize_terminal(*_ROOMY)
        await pilot.pause()
        assert app.size.width == _ROOMY[0]
        assert app.return_value is None
        await pilot.press("escape")

    assert _result(app).status == "cancelled"


@pytest.mark.asyncio
async def test_everything_fits_in_the_smallest_window_the_wizard_accepts() -> None:
    """Nothing is pushed off the screen at the minimum, which is what makes it the minimum.

    Checked by measuring the rendered widgets rather than by eye: at ``MIN_WIDTH`` x
    ``MIN_HEIGHT`` every line of the screen - title, the eight rows, the longest
    explanation, the status line and the key hints - has a region on screen.
    """
    app = _app()
    async with app.run_test(size=_MINIMUM) as pilot:
        app.query_one("#field-mode", Input).focus()
        await pilot.pause()
        regions = {
            widget.id: widget.region
            for widget in app.screen.walk_children(Widget)
            if widget.id is not None
        }
        await pilot.press("escape")

    for widget_id in ("title", "explain", "status", "keys", "field-host", "field-ca_certs"):
        region = regions[widget_id]
        assert region.height > 0, f"{widget_id} has no room at {MIN_WIDTH}x{MIN_HEIGHT}"
        assert region.bottom <= MIN_HEIGHT, f"{widget_id} falls off the bottom"


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["es", "en"])
async def test_the_screen_speaks_one_language_at_a_time(locale: Locale) -> None:
    """Mixing the two on one screen is a bug of this role, not a detail."""
    app = _app(initial=DraftFields(), password_set=False, locale=locale)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.pause()
        title = str(app.query_one("#title", Static).content)
        keys = str(app.query_one("#keys", Static).content)
        status = _status(app)
        await pilot.press("escape")

    assert title == t("CLI.WIZARD_UI_TITLE", locale, profile="dev")
    assert keys == t("CLI.WIZARD_UI_KEYS", locale)
    assert t("CLI.WIZARD_FIELD_HOST", locale) in status


@pytest.mark.asyncio
async def test_continuing_with_an_empty_field_puts_the_cursor_in_it() -> None:
    """ "Show what is missing" is worth more when it also takes you there."""
    app = _app(initial=DraftFields(host="nz.example.com", user="svc"))
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("enter")
        await pilot.pause()
        focused = app.focused
        assert app.return_value is None
        assert focused is not None
        assert focused.id == "field-database"
        await pilot.press("escape")

    assert _result(app).status == "cancelled"


@pytest.mark.asyncio
async def test_the_credential_is_asked_for_while_the_application_is_suspended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Condition 5 of ADR 0029: the question happens on the real terminal, not on screen.

    ``App.suspend()`` hands the terminal back so ``cli_output.ask_secret()`` can turn the
    echo off exactly as it does in the chained questions. The headless driver the rest of
    this file uses cannot suspend, so the suspension is stood in for here - what is being
    checked is the order: the wizard is suspended *while* the credential is being typed.
    """
    from contextlib import contextmanager

    events: list[str] = []

    @contextmanager
    def suspend(_self: ProfileWizardApp) -> Iterator[None]:
        events.append("suspended")
        yield
        events.append("resumed")

    monkeypatch.setattr(ProfileWizardApp, "suspend", suspend)

    def ask_password() -> bool:
        events.append("asked")
        return True

    app = _app(password_set=False, ask_password=ask_password)
    async with app.run_test(size=_ROOMY) as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.press("escape")

    assert events == ["suspended", "asked", "resumed"]
