"""The password field that stores a counter (issue #224).

Everything here drives the **real** application through ``Pilot``, so the assertions are
about what a person's keystrokes actually do rather than about how the widget is written.
Two things are being checked at once and they pull in opposite directions:

- it has to behave like a text field - insert, delete, caret, selection - because a field
  that cannot be corrected is a field people paste into;
- and it must not hold the text, which is the whole reason it exists.

The adversarial half is deliberate: every editing test also asserts *where the characters
ended up*, and the paste tests assert that what the framework kept afterwards is empty.
"""

from __future__ import annotations

from typing import Final

import pytest
from _pytest._code import ExceptionInfo
from textual import events
from textual.widgets import Input, Static

from nz_mcp.i18n import Locale, t
from nz_mcp.wizard import MIN_HEIGHT, MIN_WIDTH, DraftFields
from nz_mcp.wizard.app import ProfileWizardApp
from nz_mcp.wizard.secret_field import SecretField

#: Long enough that no rendering could produce it by accident, and with an upper case
#: letter, a digit and punctuation, because those take three different paths through the
#: key parser of ``textual``. It also shares no four-letter run with any name in this
#: package, so the search below can look for fragments without finding class names.
_CREDENTIAL: Final[str] = "Zzq-Krd4471-Xyw"

_ROOMY: Final[tuple[int, int]] = (100, 30)

#: What gets pasted into one of the seven ordinary fields.
_PASTED_HOST: Final[str] = "pasted-host-row"


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


def _app(sink: _Sink, *, locale: Locale = "es") -> ProfileWizardApp:
    return ProfileWizardApp(
        profile="dev",
        initial=DraftFields(host="nz.example.com", database="PROD", user="svc"),
        password_set=False,
        ask_password=lambda: True,
        credential=sink,
        locale=locale,
    )


def _field(app: ProfileWizardApp) -> SecretField:
    return app.query_one(SecretField)


def _status(app: ProfileWizardApp) -> str:
    return str(app.query_one("#status", Static).content)


# --- typing -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_what_is_typed_arrives_in_order_and_the_widget_keeps_a_number() -> None:
    """The claim of the whole issue, in one test: it works, and it holds a counter."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press(*_CREDENTIAL)
        await pilot.pause()
        held = dict(_field(app).__dict__)
        await pilot.press("escape")

    assert sink.joined() == _CREDENTIAL
    assert sink.characters == list(_CREDENTIAL), "the sink got a string, not characters"
    assert held["_length"] == len(_CREDENTIAL)
    assert held["_cursor"] == len(_CREDENTIAL)
    assert [type(held[name]).__name__ for name in ("_length", "_cursor", "_anchor")] == ["int"] * 3
    assert isinstance(held["_external"], bool)
    # Not just "the whole value is absent": no run of four characters of it survives
    # anywhere in the widget, which is what a partial buffer would look like.
    windows = {_CREDENTIAL[i : i + 4] for i in range(len(_CREDENTIAL) - 3)}
    written = repr(held)
    assert not [window for window in windows if window in written], (
        f"a piece of the credential is sitting in the widget: {held}"
    )


@pytest.mark.asyncio
async def test_a_space_counts_as_a_character_and_a_control_key_does_not() -> None:
    """``is_printable`` is the line, and it is the framework's own answer, not a guess."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press("a", "space", "b", "ctrl+s")
        await pilot.pause()
        await pilot.press("escape")

    assert sink.joined() == "a b"


@pytest.mark.asyncio
async def test_tab_still_moves_the_focus_out_of_the_credential_row() -> None:
    """A field that swallowed every key would be a trap: the form still has to be navigable."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press("tab")
        await pilot.pause()
        moved = not isinstance(app.focused, SecretField)
        await pilot.press("escape")

    assert moved
    assert sink.characters == []


# --- editing, all of it on the counters ---------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        pytest.param(("backspace",), "abcd", id="backspace-at-the-end"),
        pytest.param(("backspace", "backspace", "backspace"), "ab", id="backspace-repeated"),
        pytest.param(("home", "delete"), "bcde", id="home-then-delete"),
        pytest.param(("home", "x"), "xabcde", id="insert-at-the-start"),
        pytest.param(("left", "left", "x"), "abcxde", id="insert-in-the-middle"),
        pytest.param(("home", "right", "right", "x"), "abxcde", id="caret-walks-right"),
        pytest.param(("home", "end", "x"), "abcdex", id="end-goes-back-to-the-end"),
        pytest.param(("left", "backspace"), "abce", id="backspace-in-the-middle"),
        pytest.param(("home", "backspace"), "abcde", id="backspace-at-the-start-does-nothing"),
        pytest.param(("delete",), "abcde", id="delete-at-the-end-does-nothing"),
        pytest.param(("ctrl+u",), "", id="clear-everything"),
        pytest.param(("ctrl+a", "z"), "z", id="select-all-then-type"),
        pytest.param(("ctrl+a", "backspace"), "", id="select-all-then-delete"),
        pytest.param(("shift+home", "z"), "z", id="select-to-the-start"),
        pytest.param(("home", "shift+end", "backspace"), "", id="select-to-the-end"),
        pytest.param(("home", "right", "shift+end", "z"), "az", id="select-a-tail"),
        pytest.param(("left", "left", "shift+home", "delete"), "de", id="select-a-head"),
        pytest.param(
            # The anchor stays at 1 across both extensions, so the second one selects
            # backwards from it and only the first character goes.
            ("home", "right", "shift+end", "shift+home", "backspace"),
            "bcde",
            id="an-extended-selection-keeps-the-anchor-it-started-from",
        ),
    ],
)
async def test_editing_by_hand_lands_where_it_would_in_a_normal_field(
    keys: tuple[str, ...], expected: str
) -> None:
    """Every one of these is a counter operation, and every one is checked on the sink."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press(*"abcde")
        await pilot.press(*keys)
        await pilot.pause()
        await pilot.press("escape")

    assert sink.joined() == expected


@pytest.mark.asyncio
async def test_the_caret_does_not_walk_off_either_end() -> None:
    """Off-by-one on a counter is a corrupted credential, so the bounds get their own test."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press(*"ab")
        await pilot.press("left", "left", "left", "left")
        await pilot.press("x")
        await pilot.press("right", "right", "right", "right")
        await pilot.press("y")
        await pilot.pause()
        await pilot.press("escape")

    assert sink.joined() == "xaby"


# --- what is drawn ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_mask_is_built_from_the_counter_and_shows_the_caret() -> None:
    """One cell per character, an ASCII caret where the next one would go."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press(*"abc")
        await pilot.pause()
        at_the_end = _field(app).render()
        await pilot.press("home")
        await pilot.pause()
        at_the_start = _field(app).render()
        await pilot.press("ctrl+a")
        await pilot.pause()
        selected = _field(app).render()
        await pilot.press("escape")

    assert at_the_end == "***_"
    assert at_the_start == "_***"
    assert selected == "###"
    assert "a" not in at_the_end and "b" not in at_the_end


@pytest.mark.asyncio
async def test_an_unattended_screen_does_not_even_show_the_length() -> None:
    """Unfocused, the row is a state. The mask exists only while somebody is typing."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press(*_CREDENTIAL)
        await pilot.pause()
        app.query_one("#field-host", Input).focus()
        await pilot.pause()
        unfocused = _field(app).render()
        await pilot.press("escape")

    assert unfocused == t("CLI.WIZARD_UI_PASSWORD_SET", "es")
    assert "*" not in unfocused


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["es", "en"])
async def test_the_row_explains_itself_in_the_language_of_the_session(locale: Locale) -> None:
    """The same didactic line the chained questions print, while the answer is written."""
    sink = _Sink()
    app = _app(sink, locale=locale)
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.pause()
        explanation = str(app.query_one("#explain", Static).content)
        empty = _field(app).render()
        await pilot.press("escape")

    assert explanation == t("CLI.WIZARD_PASSWORD_EXPLAIN", locale)
    assert empty == "_", "an empty focused field is a caret and nothing else"


# --- the paste ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_paste_arrives_whole_and_the_widget_still_holds_a_number() -> None:
    """Pasting works - a password manager is how most people type a credential.

    The characters go through the same door as the typed ones, so the field ends up with a
    bigger counter and nothing else.
    """
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        field = _field(app)
        field.focus()
        await pilot.pause()
        field.post_message(events.Paste(_CREDENTIAL))
        await pilot.pause()
        rendered = field.render()
        held = dict(field.__dict__)
        await pilot.press("escape")

    assert sink.joined() == _CREDENTIAL
    assert sink.characters == list(_CREDENTIAL), "the sink got a string, not characters"
    assert held["_length"] == len(_CREDENTIAL)
    assert rendered == "*" * len(_CREDENTIAL) + "_"
    windows = {_CREDENTIAL[i : i + 4] for i in range(len(_CREDENTIAL) - 3)}
    assert not [window for window in windows if window in repr(held)], (
        f"a piece of the pasted credential is sitting in the widget: {held}"
    )


@pytest.mark.asyncio
async def test_the_pasted_string_is_released_as_soon_as_it_has_been_consumed() -> None:
    """The one part of the window that is ours to close, and it is closed.

    Measured on ``textual`` 8.2.8: a ``Paste`` message can outlive the handler inside the
    message pump - posted to the application it survived the dispatch and 300 ms of
    idling. We cannot shorten *its* life, so the handler drops the reference it carries
    instead, and whatever the pump is still holding stops carrying the credential.

    The message is kept alive here by this test on purpose, which is the only way to look
    at it afterwards; the reference under examination is the framework's, not ours.
    ``__rich_repr__`` is checked too, because that is what a devtools console would print.
    """
    sink = _Sink()
    app = _app(sink)
    paste = events.Paste(_CREDENTIAL)

    async with app.run_test(size=_ROOMY) as pilot:
        field = _field(app)
        field.focus()
        await pilot.pause()
        field.post_message(paste)
        await pilot.pause()
        await pilot.press("escape")

    assert sink.joined() == _CREDENTIAL, "the paste was not consumed, so this proves nothing"
    assert paste.text == "", "the message the pump may keep still carries the credential"
    assert _CREDENTIAL not in repr(list(paste.__rich_repr__()))


class _ExplodingSink(_Sink):
    """A sink that fails part-way through, the way a real one could."""

    def __init__(self, *, fails_at: int) -> None:
        super().__init__()
        self.fails_at = fails_at

    def insert(self, index: int, character: str) -> None:
        if len(self.characters) == self.fails_at:
            raise RuntimeError("the sink gave up")
        super().insert(index, character)


@pytest.mark.asyncio
async def test_a_failure_half_way_through_a_paste_does_not_leak_it_into_the_traceback() -> None:
    """The channel this design does promise to keep clean: our own error messages.

    ``event`` is a local of the paste handler, so it is printed by any renderer that shows
    frame locals - pytest by default, and the failure handler of ``textual``. Releasing the
    pasted string only when the loop finishes would therefore be a protection that works
    exactly when it is not needed. This drives a real event through the real handler and
    makes it fail in the middle, then renders the failure the way pytest does and looks for
    the credential in it.
    """
    sink = _ExplodingSink(fails_at=6)
    app = _app(sink)
    paste = events.Paste(_CREDENTIAL)

    async with app.run_test(size=_ROOMY) as pilot:
        field = _field(app)
        field.focus()
        await pilot.pause()
        try:
            field.on_paste(paste)
        except RuntimeError:
            info: ExceptionInfo[BaseException] = ExceptionInfo.from_current()
        else:  # pragma: no cover - the sink is built to fail
            raise AssertionError("the sink did not fail, so this test proved nothing")
        await pilot.press("escape")

    assert sink.characters == list(_CREDENTIAL[:6]), "the failure did not land mid-paste"
    # The traceback first: it is the channel, and it is what fails without the ``finally``.
    for style in ("long", "short", "line", "native", "value"):
        rendered = str(info.getrepr(style=style, funcargs=True, showlocals=True, chain=True))
        assert _CREDENTIAL not in rendered, f"the credential is in the --tb={style} traceback"
    assert paste.text == "", "the event kept the credential after the handler blew up"


@pytest.mark.asyncio
async def test_a_paste_lands_at_the_caret_and_replaces_a_selection() -> None:
    """It is an insertion like any other, so it obeys the caret and the selection."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        field = _field(app)
        field.focus()
        await pilot.press(*"abcd")
        await pilot.press("left", "left")
        field.post_message(events.Paste("XY"))
        await pilot.pause()
        at_the_caret = sink.joined()
        await pilot.press("ctrl+a")
        field.post_message(events.Paste("Z"))
        await pilot.pause()
        over_a_selection = sink.joined()
        await pilot.press("escape")

    assert at_the_caret == "abXYcd"
    assert over_a_selection == "Z"


@pytest.mark.asyncio
async def test_a_pasted_line_break_does_not_become_part_of_the_credential() -> None:
    """Password managers add a trailing newline. It is not part of what you copied."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        field = _field(app)
        field.focus()
        await pilot.pause()
        field.post_message(events.Paste("hun\tter2\r\n"))
        await pilot.pause()
        await pilot.press("escape")

    assert sink.joined() == "hunter2"


@pytest.mark.asyncio
async def test_a_paste_replaces_a_credential_that_came_from_the_terminal() -> None:
    """Same rule as typing: two sources never concatenate into a broken credential."""
    sink = _Sink()
    sink.characters = list("from-the-terminal")

    app = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(host="h", database="d", user="u"),
        password_set=False,
        ask_password=lambda: True,
        credential=sink,
        locale="es",
    )
    async with app.run_test(size=_ROOMY) as pilot:
        field = _field(app)
        field.focus()
        await pilot.press("ctrl+p")
        await pilot.pause()
        field.post_message(events.Paste("pasted"))
        await pilot.pause()
        await pilot.press("escape")

    assert sink.joined() == "pasted"


@pytest.mark.asyncio
async def test_a_paste_into_one_of_the_other_seven_fields_still_works() -> None:
    """Nothing about the credential row changed how the ordinary fields behave."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=_ROOMY) as pilot:
        host = app.query_one("#field-host", Input)
        host.focus()
        host.value = ""
        host.post_message(events.Paste(_PASTED_HOST))
        await pilot.pause()
        value = host.value
        await pilot.press("escape")

    # Equality rather than a substring: this is the whole content of the field, and a
    # substring check on something host-shaped reads as URL sanitisation to a scanner.
    assert value == _PASTED_HOST


# --- the net, and how it meets the field --------------------------------------


@pytest.mark.asyncio
async def test_the_terminal_prompt_is_still_there_and_does_not_draw_a_length() -> None:
    """Ctrl+P keeps working, and what it collects is never described on screen."""
    sink = _Sink()
    asked: list[int] = []

    def ask_password() -> bool:
        asked.append(1)
        return True

    app = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(host="h", database="d", user="u"),
        password_set=False,
        ask_password=ask_password,
        credential=sink,
        locale="es",
    )
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press("ctrl+p")
        await pilot.pause()
        rendered = _field(app).render()
        held = _field(app).holds_credential()
        length = _field(app).__dict__["_length"]
        await pilot.press("escape")

    assert asked == [1]
    assert held is True
    assert length == 0, "the field learnt the length of something typed off screen"
    assert "*" not in rendered
    assert rendered == t("CLI.WIZARD_UI_PASSWORD_TERMINAL", "es"), (
        "with the counter at zero a mask would be a bare caret, which reads as empty"
    )


@pytest.mark.asyncio
async def test_typing_after_the_terminal_prompt_replaces_it_instead_of_appending() -> None:
    """Two sources, one credential. The first keystroke starts over, visibly."""
    sink = _Sink()
    sink.characters = list("from-the-terminal")

    app = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(host="h", database="d", user="u"),
        password_set=False,
        ask_password=lambda: True,
        credential=sink,
        locale="es",
    )
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.press(*"new")
        await pilot.pause()
        rendered = _field(app).render()
        await pilot.press("escape")

    assert sink.joined() == "new", "the two sources were concatenated into a broken credential"
    assert rendered == "***_"


@pytest.mark.asyncio
async def test_backspace_on_a_terminal_credential_clears_it_rather_than_corrupting_it() -> None:
    """The field cannot see the length, so the only safe reading of "delete" is "all of it"."""
    sink = _Sink()
    sink.characters = list("from-the-terminal")

    app = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(host="h", database="d", user="u"),
        password_set=False,
        ask_password=lambda: True,
        credential=sink,
        locale="es",
    )
    async with app.run_test(size=_ROOMY) as pilot:
        _field(app).focus()
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.press("backspace")
        await pilot.pause()
        held = _field(app).holds_credential()
        await pilot.press("escape")

    assert sink.characters == []
    assert held is False


@pytest.mark.asyncio
async def test_the_form_knows_the_credential_is_missing_until_a_key_is_pressed() -> None:
    """The status line and the field agree, because the field is the one that decides."""
    sink = _Sink()
    app = _app(sink)
    async with app.run_test(size=(MIN_WIDTH, MIN_HEIGHT)) as pilot:
        await pilot.pause()
        before = _status(app)
        _field(app).focus()
        await pilot.press("x")
        await pilot.pause()
        after = _status(app)
        await pilot.press("backspace")
        await pilot.pause()
        emptied = _status(app)
        await pilot.press("escape")

    assert before == t("CLI.WIZARD_UI_MISSING", "es", fields=t("CLI.WIZARD_FIELD_PASSWORD", "es"))
    assert after == t("CLI.WIZARD_UI_READY", "es")
    assert emptied == before, "emptying the field must put the credential back on the missing list"
