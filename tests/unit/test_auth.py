"""auth.py — keyring storage."""

from __future__ import annotations

import pytest

from nz_mcp import auth
from nz_mcp.errors import CredentialNotFoundError


def test_store_and_get_password() -> None:
    auth.store_password("dev", "hunter2")
    assert auth.get_password("dev") == "hunter2"


def test_get_password_missing_raises() -> None:
    with pytest.raises(CredentialNotFoundError) as exc:
        auth.get_password("ghost")
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


def test_delete_password_idempotent() -> None:
    auth.store_password("tmp", "pw")
    auth.delete_password("tmp")
    auth.delete_password("tmp")  # second call must not raise
    with pytest.raises(CredentialNotFoundError):
        auth.get_password("tmp")


def test_username_namespacing() -> None:
    auth.store_password("a", "1")
    auth.store_password("b", "2")
    assert auth.get_password("a") == "1"
    assert auth.get_password("b") == "2"
