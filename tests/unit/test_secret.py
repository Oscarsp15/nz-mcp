"""Adversarial tests for ``nz_mcp.secret``: every rendering path must be redacted.

A ``Secret`` is a ``str``, so it travels through the driver untouched; the risk is that
some rendering path we did not override prints the credential anyway. Each test here is
one such path -- repr, str, f-string, percent interpolation, logging, encode -- plus the
guarantees the rest of the code relies on: equality, hashing and ``reveal`` returning the
real value.
"""

from __future__ import annotations

import logging
from typing import Final

from hypothesis import given
from hypothesis import strategies as st

from nz_mcp.logging_utils import sanitize
from nz_mcp.secret import REDACTED, Secret, SecretBytes, reveal

VALUE: Final[str] = "n0t-a-real-passw0rd"


def test_repr_is_redacted() -> None:
    assert repr(Secret(VALUE)) == "Secret(***)"


def test_str_is_redacted() -> None:
    assert str(Secret(VALUE)) == REDACTED


def test_fstring_is_redacted() -> None:
    """f-strings call ``__format__``, which bypasses ``__str__`` for ``str`` subclasses."""
    assert f"{Secret(VALUE)}" == REDACTED
    assert f"{Secret(VALUE):>10}" == REDACTED


def test_percent_interpolation_is_redacted() -> None:
    """Old-style interpolation goes through ``__str__``, the path ``logging`` uses."""
    rendered = "password=%s" % Secret(VALUE)  # noqa: UP031 - the path under test
    assert rendered == "password=***"


def test_logging_a_secret_is_redacted() -> None:
    """A log record renders its args with ``%``, which goes through ``__str__``.

    The record is built directly instead of calling ``logger.info(...)``: it is the same
    rendering path (``LogRecord.getMessage``), and passing a credential to a logging call
    is exactly what static analysis is supposed to flag, even when it is safe here.
    """
    record = logging.LogRecord(
        name="nz_mcp.tests.secret",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="connecting with %s",
        args=(Secret(VALUE),),
        exc_info=None,
    )
    assert record.getMessage() == "connecting with ***"
    assert VALUE not in record.getMessage()


def test_collections_render_the_repr() -> None:
    """Containers render the ``repr`` of their items: a dict or a list must stay clean."""
    assert VALUE not in repr({"password": Secret(VALUE)})
    assert VALUE not in repr([Secret(VALUE)])


def test_encode_returns_redacted_bytes_holding_the_real_value() -> None:
    """The driver re-binds its argument to ``password.encode()``; that copy must be safe."""
    encoded = Secret(VALUE).encode("utf8")
    assert isinstance(encoded, SecretBytes)
    assert repr(encoded) == "SecretBytes(***)"
    assert str(encoded) == REDACTED
    assert encoded == VALUE.encode("utf8")
    assert encoded.reveal() == VALUE.encode("utf8")


def test_secret_behaves_as_the_real_string() -> None:
    secret = Secret(VALUE)
    assert secret == VALUE
    assert hash(secret) == hash(VALUE)
    assert len(secret) == len(VALUE)
    assert secret.startswith(VALUE[:4])


def test_reveal_returns_a_plain_str() -> None:
    revealed = Secret(VALUE).reveal()
    assert revealed == VALUE
    assert type(revealed) is str


def test_module_reveal_accepts_plain_strings() -> None:
    """Boundaries call ``reveal`` without caring which of the two types they were given."""
    assert reveal(VALUE) == VALUE
    assert reveal(Secret(VALUE)) == VALUE


def test_sanitize_still_masks_a_secret_known_value() -> None:
    """The second barrier keeps working: a ``Secret`` is a valid ``known_secrets`` entry."""
    text = f"driver said: {VALUE} rejected"
    assert sanitize(text, known_secrets={Secret(VALUE)}) == "driver said: *** rejected"


@given(value=st.text(min_size=1, max_size=60))
def test_no_rendering_path_reproduces_the_value(value: str) -> None:
    """Property: whatever the credential is, every rendering path yields the same mask."""
    secret = Secret(value)
    assert repr(secret) == "Secret(***)"
    assert str(secret) == REDACTED
    assert f"{secret}" == REDACTED
    assert repr({"pwd": secret}) == "{'pwd': Secret(***)}"
    assert repr(secret.encode()) == "SecretBytes(***)"
    # The real value survives only through the explicit door.
    assert secret.reveal() == value


def test_wrapping_a_secret_again_keeps_the_real_value() -> None:
    """Double wrapping must not store the redacted rendering (regression, 0.1.0a2).

    ``open_connection`` re-binds its argument with ``Secret(password)`` unconditionally,
    and ``auth.get_password`` already returns a ``Secret``. Before the fix, the second
    wrap stored the literal ``***`` because ``str.__new__`` renders through ``__str__``:
    every connection sent ``***`` as the password and Netezza answered AUTH_REJECTED.
    """
    once = Secret("hunter2")
    twice = Secret(once)
    thrice = Secret(twice)

    assert twice.reveal() == "hunter2"
    assert thrice.reveal() == "hunter2"
    assert str.__eq__(once, twice)
    assert str(twice) == "***"
    assert twice.encode() == b"hunter2"


def test_wrapping_secret_bytes_again_keeps_the_real_bytes() -> None:
    """Same trap on the encoded form."""
    once = SecretBytes(b"hunter2")
    twice = SecretBytes(once)

    assert bytes(twice) == b"hunter2"
    assert repr(twice) == "SecretBytes(***)"
