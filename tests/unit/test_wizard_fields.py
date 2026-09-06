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

import pytest

from nz_mcp.i18n import MESSAGES
from nz_mcp.wizard import (
    CREDENTIAL_SLOT,
    FIELD_KEYS,
    FIELD_SPECS,
    DraftFields,
    as_previous,
    first_shape_error,
    from_previous,
    label_key,
    missing_slots,
    normalize_mode,
    normalize_port,
    normalize_security_level,
    shape_error_key,
)


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
        locale="es",
    )

    assert result.status == "cancelled"
    assert result.fields == seed
