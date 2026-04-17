"""Sanitizer tests — must never leak credentials."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from nz_mcp.logging_utils import sanitize


def test_masks_password_assignment() -> None:
    out = sanitize("connecting password=hunter2 to host=foo")
    assert "hunter2" not in out
    assert "password=***" in out


def test_masks_pwd_and_token_and_secret() -> None:
    for label, secret in [("pwd", "abc123"), ("token", "xyz"), ("secret", "shh")]:
        out = sanitize(f"foo {label}={secret} bar")
        assert secret not in out


def test_masks_bearer_token() -> None:
    out = sanitize("Authorization: Bearer abc.def-ghi")
    assert "abc.def-ghi" not in out


def test_known_secret_is_masked_anywhere() -> None:
    out = sanitize("the password is sup3r-s3cr3t!", known_secrets={"sup3r-s3cr3t!"})
    assert "sup3r-s3cr3t!" not in out


def test_short_known_secret_is_ignored() -> None:
    """Short strings would mask common words; require length >= 4."""
    out = sanitize("ok", known_secrets={"ok"})
    assert out == "ok"


_PRINTABLE = st.characters(min_codepoint=33, max_codepoint=126)


@given(st.text(alphabet=_PRINTABLE, min_size=8, max_size=64))
def test_known_secret_property(secret: str) -> None:
    line = f"connecting password={secret} to db"
    assert secret not in sanitize(line, known_secrets={secret})
