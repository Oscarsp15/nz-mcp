"""auth.py — keyring storage."""

from __future__ import annotations

import keyring
import pytest
from keyring.errors import KeyringError

from nz_mcp import auth
from nz_mcp.errors import CredentialNotFoundError, KeyringUnavailableError
from nz_mcp.secret import Secret


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


def test_get_password_returns_a_secret() -> None:
    """The credential enters the process here, so it is wrapped here (issue #191)."""
    auth.store_password("dev", "hunter2")
    stored = auth.get_password("dev")
    assert isinstance(stored, Secret)
    assert stored == "hunter2"
    assert "hunter2" not in repr(stored)


def test_store_password_persists_the_real_value_of_a_secret() -> None:
    """A Secret renders as ``***``; what reaches the keyring must be the real value."""
    auth.store_password("dev", Secret("hunter2"))
    assert auth.get_password("dev").reveal() == "hunter2"


def _raise_keyring_error(*_args: object, **_kwargs: object) -> None:
    raise KeyringError("no backend available")


def test_store_password_wraps_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyring, "set_password", _raise_keyring_error)
    with pytest.raises(KeyringUnavailableError) as exc:
        auth.store_password("dev", "hunter2")
    assert exc.value.context["profile"] == "dev"


def test_get_password_wraps_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyring, "get_password", _raise_keyring_error)
    with pytest.raises(KeyringUnavailableError):
        auth.get_password("dev")


def test_delete_password_wraps_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyring, "delete_password", _raise_keyring_error)
    with pytest.raises(KeyringUnavailableError):
        auth.delete_password("dev")
