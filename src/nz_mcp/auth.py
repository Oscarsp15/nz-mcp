"""Credential storage in OS-native keyring.

Service: ``nz-mcp``. Username: ``profile:<name>``.
"""

from __future__ import annotations

from typing import Final

import keyring
from keyring.errors import KeyringError

from nz_mcp.errors import CredentialNotFoundError, KeyringUnavailableError

SERVICE: Final[str] = "nz-mcp"


def _username(profile_name: str) -> str:
    return f"profile:{profile_name}"


def store_password(profile_name: str, password: str) -> None:
    try:
        keyring.set_password(SERVICE, _username(profile_name), password)
    except KeyringError as exc:
        raise KeyringUnavailableError(profile=profile_name, detail=str(exc)) from exc


def get_password(profile_name: str) -> str:
    try:
        password = keyring.get_password(SERVICE, _username(profile_name))
    except KeyringError as exc:
        raise KeyringUnavailableError(profile=profile_name, detail=str(exc)) from exc
    if password is None:
        raise CredentialNotFoundError(profile=profile_name)
    return password


def delete_password(profile_name: str) -> None:
    try:
        keyring.delete_password(SERVICE, _username(profile_name))
    except keyring.errors.PasswordDeleteError:  # pragma: no cover - benign
        return
    except KeyringError as exc:
        raise KeyringUnavailableError(profile=profile_name, detail=str(exc)) from exc
