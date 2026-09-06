"""Full-screen configuration wizard, and the only place ``textual`` may be named.

The rest of the CLI asks this package for *the profile draft* and gets one back, or a
reason there is none. It never sees an application, a widget or an event loop: that is
condition 4 of ADR 0029, and it is what makes the interactive path and the
chained-questions path interchangeable from the outside - and what keeps a future major
of ``textual`` inside one directory.

Two rules hold the confinement up, and both are enforced by
``tests/contract/test_serve_stdout_protocol_only.py``:

- nothing outside this package imports ``textual``;
- this package does not import ``rich`` either. It gets it underneath ``textual``, which
  is the same rendering stack ``cli_output`` already uses, not a second one.

The import of the application is deliberately deferred to the moment it is used. Ten of
the eleven commands are text and always will be; making them pay for the import of a TUI
framework at start-up would be a cost with no reader.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from nz_mcp.i18n import Locale
from nz_mcp.wizard.fields import (
    CREDENTIAL_SLOT,
    FIELD_KEYS,
    FIELD_SPECS,
    MIN_HEIGHT,
    MIN_WIDTH,
    MODES,
    DraftFields,
    FieldSpec,
    WizardResult,
    WizardStatus,
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


def collect_profile_draft(
    *,
    profile: str,
    initial: DraftFields,
    password_set: bool,
    ask_password: Callable[[], bool],
    locale: Locale,
) -> WizardResult:
    """Run the full-screen wizard and return what it collected.

    The caller has already checked, through ``cli_output.interactive_ui_enabled()``, that
    the environment can host a full-screen application: this function builds one and does
    not second-guess that decision (ADR 0029, condition 1 - the gate is ours and it is
    decided before anything is constructed).

    Args:
        profile: Name of the profile being configured.
        initial: Answers to start from.
        password_set: Whether a credential is already held. A boolean; see
            :mod:`nz_mcp.wizard.fields`.
        ask_password: Asks for the credential outside the widget tree and returns whether
            one is now held.
        locale: Language of every visible string.

    Returns:
        The draft and how the session ended. A closed window with no explicit choice
        counts as ``cancelled``, which is the safe reading: nothing gets written.
    """
    from nz_mcp.wizard.app import ProfileWizardApp  # noqa: PLC0415 - see module docstring

    application = ProfileWizardApp(
        profile=profile,
        initial=initial,
        password_set=password_set,
        ask_password=ask_password,
        locale=locale,
    )
    result = application.run()
    if result is None:
        return WizardResult(status="cancelled", fields=initial, password_set=password_set)
    return result


__all__: Final[tuple[str, ...]] = (
    "CREDENTIAL_SLOT",
    "FIELD_KEYS",
    "FIELD_SPECS",
    "MIN_HEIGHT",
    "MIN_WIDTH",
    "MODES",
    "DraftFields",
    "FieldSpec",
    "WizardResult",
    "WizardStatus",
    "as_previous",
    "collect_profile_draft",
    "first_shape_error",
    "from_previous",
    "label_key",
    "missing_slots",
    "normalize_mode",
    "normalize_port",
    "normalize_security_level",
    "shape_error_key",
)
