"""Errors hierarchy tests."""

from __future__ import annotations

import pytest

from nz_mcp.errors import (
    AuthError,
    ConnectionError,
    CredentialNotFoundError,
    GuardRejectedError,
    NetezzaError,
    NzMcpError,
    PermissionDeniedError,
    ProfileNotFoundError,
)


def test_default_code_when_omitted() -> None:
    err = NzMcpError()
    assert err.code == "INTERNAL_ERROR"


def test_subclass_codes_are_distinct() -> None:
    codes = {
        AuthError().code,
        CredentialNotFoundError().code,
        ConnectionError().code,
        GuardRejectedError().code,
        NetezzaError().code,
        PermissionDeniedError().code,
        ProfileNotFoundError().code,
    }
    assert len(codes) == 7


def test_context_appears_in_str() -> None:
    err = ProfileNotFoundError(profile="ghost")
    rendered = str(err)
    assert "ghost" in rendered
    assert "PROFILE_NOT_FOUND" in rendered


def test_explicit_code_overrides_default() -> None:
    err = NzMcpError(code="CUSTOM")
    assert err.code == "CUSTOM"


def test_inheritance_chain() -> None:
    assert issubclass(CredentialNotFoundError, AuthError)
    assert issubclass(AuthError, NzMcpError)
    with pytest.raises(NzMcpError):
        raise CredentialNotFoundError(profile="x")
