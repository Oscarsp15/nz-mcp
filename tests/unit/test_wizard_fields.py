"""The rules both wizards share: what a field is, what parses, and what is still missing.

These functions are the reason there is one wizard with two shapes rather than two wizards
(ADR 0028, condition 2). ``cli.py`` calls them from its chained questions and the
full-screen application calls them from its status line, so "what counts as a mode" is
answered once.

Nothing here touches a terminal, which is the other half of the point: the rules can be
exercised without a screen, and the confinement of ``textual`` to the application module
stays true.
"""

from __future__ import annotations

from typing import Final

import pytest

from nz_mcp.i18n import MESSAGES, t
from nz_mcp.wizard import (
    CREDENTIAL_SLOT,
    FIELD_KEYS,
    FIELD_SPECS,
    STEP_GROUPS,
    STEP_LABEL_KEYS,
    DraftFields,
    as_previous,
    field_errors,
    first_shape_error,
    from_previous,
    label_key,
    missing_slots,
    normalize_mode,
    normalize_port,
    normalize_security_level,
    shape_error_key,
    step_of,
)


class _Sink:
    """The write-only credential sink, as small as the protocol allows."""

    def insert(self, index: int, character: str) -> None:
        del index, character

    def remove(self, start: int, stop: int) -> None:
        del start, stop

    def clear(self) -> None:
        return None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("read", "read"),
        ("  WRITE  ", "write"),
        ("Admin", "admin"),
        ("root", None),
        ("", None),
    ],
)
def test_a_mode_is_one_of_three_words_however_it_is_typed(raw: str, expected: str | None) -> None:
    assert normalize_mode(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", 0), ("3", 3), (" 2 ", 2), ("4", None), ("-1", None), ("two", None), ("", None)],
)
def test_a_security_level_is_an_integer_in_range(raw: str, expected: int | None) -> None:
    assert normalize_security_level(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5480", 5480), ("1", 1), ("65535", 65535), ("0", None), ("65536", None), ("54 80", None)],
)
def test_a_port_is_a_number_a_socket_could_use(raw: str, expected: int | None) -> None:
    assert normalize_port(raw) == expected


def test_an_empty_field_is_missing_rather_than_invalid() -> None:
    """The two read differently, and conflating them makes a form nag before it helps."""
    assert shape_error_key("mode", "") is None
    assert "mode" in missing_slots(DraftFields(mode=""), password_set=True)


def test_free_text_fields_have_no_shape_to_get_wrong() -> None:
    """A host that does not resolve is the validation ladder's business, not the form's."""
    assert shape_error_key("host", "definitely not a host") is None
    assert first_shape_error(DraftFields(host="definitely not a host")) is None


def test_the_first_thing_that_will_not_parse_is_the_one_reported() -> None:
    draft = DraftFields(port="x", mode="root")
    assert first_shape_error(draft) == ("port", "CLI.WIZARD_PORT_INVALID")


def test_what_is_missing_comes_back_in_reading_order_with_the_credential_last() -> None:
    assert missing_slots(DraftFields(), password_set=False) == (
        "host",
        "database",
        "user",
        CREDENTIAL_SLOT,
    )


def test_the_optional_field_is_never_missing() -> None:
    """``ca_certs`` is optional: demanding it would be inventing a requirement."""
    draft = DraftFields(host="h", database="d", user="u")
    assert missing_slots(draft, password_set=True) == ()


def test_the_credential_is_tracked_as_a_boolean_and_nothing_else() -> None:
    """ADR 0029, condition 5, clause 1: the state model has no password field."""
    assert CREDENTIAL_SLOT not in set(DraftFields.__dataclass_fields__)
    draft = DraftFields(host="h", database="d", user="u")
    assert missing_slots(draft, password_set=False) == (CREDENTIAL_SLOT,)
    assert missing_slots(draft, password_set=True) == ()


def test_a_draft_survives_the_round_trip_into_the_chained_questions() -> None:
    """This is what makes degradation lossless.

    ``as_previous`` renders the form in the shape ``cli.py`` already uses to pre-fill its
    prompts. If this round trip lost a field, shrinking the window mid-session would cost
    someone an answer, which is exactly what issue #168 forbids.
    """
    typed = DraftFields(
        host="nz.example.com",
        port="5490",
        database="PROD",
        user="svc",
        mode="write",
        security_level="3",
        ca_certs="/etc/ssl/nz.pem",
    )
    assert from_previous(as_previous(typed)) == typed


def test_the_round_trip_types_the_numbers_the_way_profiles_toml_does() -> None:
    """``port`` and ``security_level`` are integers on disk; the form edits them as text."""
    previous = as_previous(DraftFields(host="h", port="5480", security_level="2"))
    assert previous["port"] == 5480
    assert previous["security_level"] == 2
    assert previous["host"] == "h"


def test_a_half_filled_form_only_carries_what_was_actually_typed() -> None:
    previous = as_previous(DraftFields(host="nz.example.com", database="", user="  "))
    assert previous == {
        "host": "nz.example.com",
        "port": 5480,
        "mode": "read",
        "security_level": 2,
    }


def test_a_value_that_will_not_parse_is_dropped_rather_than_carried_over() -> None:
    """A port of ``abc`` cannot become a default for the question that follows."""
    previous = as_previous(DraftFields(host="h", port="abc", security_level="9"))
    assert "port" not in previous
    assert "security_level" not in previous


def test_a_profile_read_from_disk_seeds_the_form() -> None:
    """Overwriting a profile starts from its current values, as the questions already do."""
    draft = from_previous({"host": "nz.example.com", "port": 5480, "catalog_overrides": {}})
    assert draft.host == "nz.example.com"
    assert draft.port == "5480"
    assert draft.database == ""


def test_unknown_keys_on_disk_are_ignored_rather_than_fatal() -> None:
    """Hand-edited profiles carry keys the wizard does not ask for; they are not its business."""
    assert from_previous({"catalog_overrides": {"list_tables": "SELECT 1"}}) == DraftFields()


def test_every_field_and_the_credential_have_a_label_in_both_languages() -> None:
    """A row without a label is a row nobody can fill in."""
    for slot in (*FIELD_KEYS, CREDENTIAL_SLOT):
        message = MESSAGES[label_key(slot)]
        assert message["es"].strip()
        assert message["en"].strip()


def test_every_explanation_the_form_points_at_exists_in_the_catalog() -> None:
    """The form reuses the didactic texts of the chained questions; a typo would be silent."""
    for spec in FIELD_SPECS:
        if spec.explain_key is not None:
            assert spec.explain_key in MESSAGES


def test_the_field_list_and_the_draft_cannot_drift_apart() -> None:
    assert tuple(DraftFields.__dataclass_fields__) == FIELD_KEYS


def test_the_border_of_the_package_hands_back_a_draft_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Condition 4 of ADR 0029: the caller asks for a draft, not for an application.

    The application is stood in for here because it is exercised for real, with a
    ``Pilot``, in ``test_wizard_app.py``. What this checks is the border: the arguments go
    in, a :class:`WizardResult` comes out, and nothing about widgets crosses it.
    """
    from nz_mcp.wizard import WizardResult, collect_profile_draft
    from nz_mcp.wizard import app as wizard_app

    built: dict[str, object] = {}

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            built.update(kwargs)

        def run(self) -> WizardResult:
            return WizardResult(status="completed", fields=DraftFields(host="h"), password_set=True)

    monkeypatch.setattr(wizard_app, "ProfileWizardApp", _Stub)

    result = collect_profile_draft(
        profile="dev",
        initial=DraftFields(host="seed"),
        password_set=False,
        ask_password=lambda: True,
        credential=_Sink(),
        locale="es",
    )

    assert built["profile"] == "dev"
    assert result.status == "completed"
    assert result.fields.host == "h"


def test_a_window_closed_without_an_answer_counts_as_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The safe reading of "no answer": nothing is written, and the draft comes back intact."""
    from nz_mcp.wizard import app as wizard_app
    from nz_mcp.wizard import collect_profile_draft

    class _Stub:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self) -> None:
            return None

    monkeypatch.setattr(wizard_app, "ProfileWizardApp", _Stub)

    seed = DraftFields(host="seed")
    result = collect_profile_draft(
        profile="dev",
        initial=seed,
        password_set=False,
        ask_password=lambda: True,
        credential=_Sink(),
        locale="es",
    )

    assert result.status == "cancelled"
    assert result.fields == seed


# --- the field-error log (ADR 0032, decision 4; issue #241) --------------------


def test_a_complete_form_reports_no_errors() -> None:
    draft = DraftFields(host="h", database="d", user="u")
    assert field_errors(draft, password_set=True) == ()


def test_an_empty_required_field_is_reported_with_the_generic_message() -> None:
    draft = DraftFields(host="", database="d", user="u")
    assert field_errors(draft, password_set=True) == (("host", "CLI.WIZARD_UI_ERROR_REQUIRED"),)


def test_the_optional_field_is_never_an_error() -> None:
    draft = DraftFields(host="h", database="d", user="u", ca_certs="")
    assert field_errors(draft, password_set=True) == ()


def test_the_credential_is_reported_last_when_missing() -> None:
    draft = DraftFields(host="", database="d", user="u")
    assert field_errors(draft, password_set=False) == (
        ("host", "CLI.WIZARD_UI_ERROR_REQUIRED"),
        (CREDENTIAL_SLOT, "CLI.WIZARD_UI_ERROR_REQUIRED"),
    )


@pytest.mark.parametrize(
    ("slot", "typed", "message_key"),
    [
        pytest.param("port", "not-a-number", "CLI.WIZARD_UI_ERROR_PORT", id="port"),
        pytest.param("mode", "root", "CLI.WIZARD_UI_ERROR_MODE", id="mode"),
        pytest.param("security_level", "9", "CLI.WIZARD_UI_ERROR_SECURITY", id="security-level"),
    ],
)
def test_a_value_that_will_not_parse_gets_its_own_short_message(
    slot: str, typed: str, message_key: str
) -> None:
    """The full-screen form's vocabulary, separate from the chained questions' sentences.

    ``CLI.WIZARD_PORT_INVALID`` and its siblings repeat the typed value; these do not
    (ADR 0032, decision 4: no sentence where a datum fits).
    """
    draft = DraftFields(host="h", database="d", user="u", **{slot: typed})
    assert field_errors(draft, password_set=True) == ((slot, message_key),)


def test_a_blank_value_is_missing_rather_than_invalid_in_the_error_log() -> None:
    draft = DraftFields(host="h", database="d", user="u", port="")
    assert field_errors(draft, password_set=True) == (("port", "CLI.WIZARD_UI_ERROR_REQUIRED"),)


def test_every_error_message_exists_in_both_languages() -> None:
    for message_key in (
        "CLI.WIZARD_UI_ERROR_REQUIRED",
        "CLI.WIZARD_UI_ERROR_PORT",
        "CLI.WIZARD_UI_ERROR_MODE",
        "CLI.WIZARD_UI_ERROR_SECURITY",
    ):
        message = MESSAGES[message_key]
        assert message["es"].strip()
        assert message["en"].strip()


# --- the stepper's three groups (ADR 0032, decision 4; issue #241) -------------


def test_every_field_and_the_credential_sit_in_exactly_one_step() -> None:
    """The stepper can always say which step the focus is in - nothing falls through."""
    covered = [slot for group in STEP_GROUPS for slot in group]
    assert sorted(covered) == sorted((*FIELD_KEYS, CREDENTIAL_SLOT))
    assert len(covered) == len(set(covered)), "a slot counted in two steps at once"


def test_there_are_exactly_three_steps() -> None:
    assert len(STEP_GROUPS) == len(STEP_LABEL_KEYS) == 3


@pytest.mark.parametrize(
    ("slot", "step"),
    [
        ("host", 0),
        ("port", 0),
        ("database", 0),
        ("user", 1),
        (CREDENTIAL_SLOT, 1),
        ("mode", 2),
        ("security_level", 2),
        ("ca_certs", 2),
    ],
)
def test_step_of_names_the_group_a_slot_belongs_to(slot: str, step: int) -> None:
    assert step_of(slot) == step


def test_step_of_an_unknown_slot_falls_back_to_the_first_step() -> None:
    assert step_of("not-a-real-field") == 0


def test_every_step_label_exists_in_both_languages() -> None:
    for key in STEP_LABEL_KEYS:
        message = MESSAGES[key]
        assert message["es"].strip()
        assert message["en"].strip()


# --- the register: technical and terse, no celebration (ADR 0032, decision 7) --

#: Case-insensitive fragments the ADR bans by name. Checked against every ES string this
#: issue added, because the register is exactly what distinguishes "Perfil guardado:
#: <nombre>" from the "todo bien" this decision rules out.
_BANNED_FRAGMENTS: Final[tuple[str, ...]] = ("todo bien", "listo", "genial")

#: Every i18n key issue #241 adds. A closed list, not a scan of the whole catalog: older
#: debt is not this issue's to fix, and a hardcoded list means a future key is checked only
#: once someone remembers to add it here - which is the same trade-off the credential
#: guardrail's allowlists make, on purpose.
_NEW_KEYS: Final[tuple[str, ...]] = (
    *STEP_LABEL_KEYS,
    "CLI.WIZARD_UI_ERROR_REQUIRED",
    "CLI.WIZARD_UI_ERROR_PORT",
    "CLI.WIZARD_UI_ERROR_MODE",
    "CLI.WIZARD_UI_ERROR_SECURITY",
    "CLI.WIZARD_UI_TOAST_SAVED",
)


def test_none_of_the_new_keys_use_a_banned_word() -> None:
    for key in _NEW_KEYS:
        es = MESSAGES[key]["es"].lower()
        for fragment in _BANNED_FRAGMENTS:
            assert fragment not in es, f"{key} uses the banned word {fragment!r}: {es!r}"


def test_the_toast_is_one_line_and_names_the_profile() -> None:
    for locale in ("es", "en"):
        rendered = t("CLI.WIZARD_UI_TOAST_SAVED", locale, profile="prod_dw")
        assert "\n" not in rendered
        assert "prod_dw" in rendered
