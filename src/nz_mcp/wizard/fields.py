"""The profile draft as data: which fields exist, what they mean, what is valid.

This module is the shared vocabulary of the two wizards. The chained-questions wizard in
``cli.py`` and the full-screen one in :mod:`nz_mcp.wizard.app` ask the same eight things,
accept the same values and reject the same mistakes, and they do it by calling the
functions below rather than by each holding its own copy of the rules (ADR 0028,
condition 2: the interface collects a draft and calls what already exists).

Two properties are deliberate and load-bearing:

- **No terminal and no library.** Nothing here imports ``textual``, ``rich`` or the output
  layer, so the rules can be exercised without a screen and the confinement of ADR 0029
  stays true.
- **No credential.** :class:`DraftFields` holds the seven fields that are safe to keep in
  a widget and stops there; the password is never one of them (ADR 0029, condition 5,
  clause 1). What travels next to these fields is a boolean, "set" or "not set", and the
  value itself lives outside every widget tree - reached only through
  :class:`CredentialSink`, which is declared here and is write-only on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from typing import Final, Literal, Protocol, cast

from nz_mcp.config import (
    DEFAULT_PORT,
    DEFAULT_SECURITY_LEVEL,
    MAX_SECURITY_LEVEL,
    MIN_SECURITY_LEVEL,
    PermissionMode,
)

#: The three accepted answers to "what may the AI do with this profile".
MODES: Final[tuple[str, ...]] = ("read", "write", "admin")

#: Highest TCP port a socket can be asked for.
_MAX_PORT: Final[int] = 65535

#: Identifier of the credential in the "what is still missing" list. It is a label, never
#: a container: no value is ever stored under it.
CREDENTIAL_SLOT: Final[str] = "password"

#: Smallest window the full-screen wizard is willing to draw itself in, in cells. Below
#: this the eight rows, the explanation and the status line stop fitting, so the command
#: degrades to the chained questions instead of painting something unusable (ADR 0028,
#: conditions 1 and 4). Both at start-up and, since the audit of PR #222, in the middle of
#: a session. Comfortably under the 80x24 that has been the default for forty years.
MIN_WIDTH: Final[int] = 60
MIN_HEIGHT: Final[int] = 21

#: How the collection step ended.
#:
#: - ``completed``: the eight answers are in, carry on to the validation ladder.
#: - ``degraded``: the environment stopped being able to host the screen mid-session;
#:   whatever was typed comes back so the chained questions can resume from it.
#: - ``cancelled``: the person asked to leave. Nothing is written.
WizardStatus = Literal["completed", "degraded", "cancelled"]


class CredentialSink(Protocol):
    """Where the credential goes while the screen is up: somewhere that is not a widget.

    This is the second door into the package, and it is deliberately **write-only**. It
    can be told to put a character at a position, to drop a range and to forget
    everything; it cannot be asked what it holds. So a widget that owns one can edit the
    credential without ever being able to read it back, and neither can anything that
    reaches the widget - which is the property ADR 0029 condition 5 is really about.

    One character at a time is the other half of the design. The implementation
    (``cli._CredentialHolder``) keeps those characters in a list and joins them exactly
    once, when the wizard is over: at no point during the session does any live object
    hold the credential as a contiguous string. A ``str`` buffer would instead build a
    complete copy of it on every keystroke, which is the very failure ADR 0029 measured
    inside ``textual``'s own ``Input``.
    """

    def insert(self, index: int, character: str) -> None:
        """Put ``character`` at ``index``."""

    def remove(self, start: int, stop: int) -> None:
        """Drop the characters in ``[start, stop)``."""

    def clear(self) -> None:
        """Forget everything held so far."""


@dataclass(slots=True)
class DraftFields:
    """The seven non-secret answers, as raw text, in the order they are asked.

    Text and not parsed values on purpose: a form lets someone type ``548`` on the way to
    ``5480``, and a draft that refuses to hold an incomplete answer cannot be edited. The
    parsing happens at the edges, in :func:`normalize_port` and its siblings.
    """

    host: str = ""
    port: str = str(DEFAULT_PORT)
    database: str = ""
    user: str = ""
    mode: str = "read"
    security_level: str = str(DEFAULT_SECURITY_LEVEL)
    ca_certs: str = ""


@dataclass(frozen=True, slots=True)
class WizardResult:
    """What the full-screen wizard hands back: a draft, or the reason there is none.

    The border of the package, per condition 4 of ADR 0029: the rest of the CLI asks for
    "the profile draft" and gets this, with no idea that an event loop was involved. Note
    what is *not* here - no credential, only ``password_set``.
    """

    status: WizardStatus
    fields: DraftFields
    password_set: bool


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One row of the form: where the value lives and how it is introduced.

    ``explain_key`` is the didactic line the chained-questions wizard prints before
    asking. The full-screen wizard shows the same text for whichever field holds the
    focus, which keeps the same promise - explain before asking - with the explanation
    available for as long as the answer is being written instead of once, above it.
    """

    key: str
    label_key: str
    explain_key: str | None
    required: bool


FIELD_SPECS: Final[tuple[FieldSpec, ...]] = (
    FieldSpec("host", "CLI.WIZARD_FIELD_HOST", None, True),
    FieldSpec("port", "CLI.WIZARD_FIELD_PORT", None, True),
    FieldSpec("database", "CLI.WIZARD_FIELD_DATABASE", "CLI.WIZARD_DATABASE_EXPLAIN", True),
    FieldSpec("user", "CLI.WIZARD_FIELD_USER", None, True),
    FieldSpec("mode", "CLI.WIZARD_FIELD_MODE", "CLI.WIZARD_MODE_EXPLAIN", True),
    FieldSpec("security_level", "CLI.WIZARD_FIELD_SECURITY", "CLI.WIZARD_SECURITY_EXPLAIN", True),
    FieldSpec("ca_certs", "CLI.WIZARD_FIELD_CA_CERTS", "CLI.WIZARD_CA_CERTS_EXPLAIN", False),
)

#: Keys of :class:`DraftFields`, in form order. Derived from the specs so the two cannot
#: drift apart.
FIELD_KEYS: Final[tuple[str, ...]] = tuple(spec.key for spec in FIELD_SPECS)

#: The i18n key that names each slot in a message, credential included. "What is still
#: missing" has to be able to name the credential without ever holding it.
_SLOT_LABEL_KEYS: Final[dict[str, str]] = {
    **{spec.key: spec.label_key for spec in FIELD_SPECS},
    CREDENTIAL_SLOT: "CLI.WIZARD_FIELD_PASSWORD",
}


def label_key(slot: str) -> str:
    """i18n key of the short label of ``slot``, credential slot included."""
    return _SLOT_LABEL_KEYS[slot]


def normalize_mode(raw: str) -> PermissionMode | None:
    """Parse a permission mode, or ``None`` when the answer is not one of the three."""
    value = raw.strip().lower()
    return cast(PermissionMode, value) if value in MODES else None


def normalize_security_level(raw: str) -> int | None:
    """Parse a security level, or ``None`` when it is not an integer in range."""
    value = raw.strip()
    if not value.isdigit():
        return None
    number = int(value)
    return number if MIN_SECURITY_LEVEL <= number <= MAX_SECURITY_LEVEL else None


def normalize_port(raw: str) -> int | None:
    """Parse a TCP port, or ``None`` when it is not a number a socket could use."""
    value = raw.strip()
    if not value.isdigit():
        return None
    number = int(value)
    return number if 1 <= number <= _MAX_PORT else None


#: Message shown when a field holds something that will not parse. Only the three fields
#: with a shape of their own can be wrong at this stage; the rest are free text, and a
#: host that does not resolve is the validation ladder's business, not the form's.
_SHAPE_ERROR_KEYS: Final[dict[str, str]] = {
    "port": "CLI.WIZARD_PORT_INVALID",
    "mode": "CLI.WIZARD_MODE_INVALID",
    "security_level": "CLI.WIZARD_SECURITY_INVALID",
}


def shape_error_key(slot: str, value: str) -> str | None:
    """i18n key describing why ``value`` cannot be used for ``slot``, or ``None``.

    Blank is not an error here: an empty required field is *missing*, which reads
    differently and is reported by :func:`missing_slots`.
    """
    if not value.strip():
        return None
    parsers = {
        "port": normalize_port,
        "mode": normalize_mode,
        "security_level": normalize_security_level,
    }
    parser = parsers.get(slot)
    if parser is None or parser(value) is not None:
        return None
    return _SHAPE_ERROR_KEYS[slot]


def first_shape_error(draft: DraftFields) -> tuple[str, str] | None:
    """First field whose value will not parse, as ``(slot, message key)``."""
    for spec in FIELD_SPECS:
        key = shape_error_key(spec.key, getattr(draft, spec.key))
        if key is not None:
            return spec.key, key
    return None


def missing_slots(draft: DraftFields, *, password_set: bool) -> tuple[str, ...]:
    """Slots still to fill, in form order, credential last.

    ``password_set`` is a boolean and never the credential: that is the whole point of the
    split (ADR 0029, condition 5).
    """
    missing = [
        spec.key for spec in FIELD_SPECS if spec.required and not getattr(draft, spec.key).strip()
    ]
    if not password_set:
        missing.append(CREDENTIAL_SLOT)
    return tuple(missing)


def as_previous(draft: DraftFields) -> dict[str, object]:
    """Render the draft in the shape the chained-questions wizard uses for its defaults.

    This is what makes degradation lossless. ``cli.py`` already knows how to pre-fill every
    prompt from a mapping of previous values - that is how overwriting a profile works -
    so handing it the half-filled form restarts the questions with the answers already
    typed instead of from nothing (issue #168).
    """
    previous: dict[str, object] = {}
    for key in FIELD_KEYS:
        value = str(getattr(draft, key)).strip()
        if not value:
            continue
        if key == "port":
            port = normalize_port(value)
            if port is not None:
                previous[key] = port
        elif key == "security_level":
            level = normalize_security_level(value)
            if level is not None:
                previous[key] = level
        else:
            previous[key] = value
    return previous


def from_previous(previous: dict[str, object]) -> DraftFields:
    """Seed a draft from the values a profile already has, ignoring anything unusable."""
    known = {field.name for field in dataclass_fields(DraftFields)}
    updates = {
        key: str(value)
        for key, value in previous.items()
        if key in known and value not in (None, "")
    }
    return replace(DraftFields(), **updates) if updates else DraftFields()
