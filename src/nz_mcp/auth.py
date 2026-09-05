"""Credential storage in OS-native keyring.

Service: ``nz-mcp``. Username: ``profile:<name>``.

``get_password`` returns a :class:`~nz_mcp.secret.Secret`, not a plain ``str``: this is
the single place where the credential enters the process, so wrapping it here is what
keeps it out of every traceback frame downstream (see ADR 0026). Callers may keep typing
their parameters as ``str`` -- ``Secret`` is a ``str``.
"""

from __future__ import annotations

from typing import Final

import keyring
from keyring.errors import KeyringError

from nz_mcp.errors import CredentialNotFoundError, KeyringUnavailableError
from nz_mcp.secret import Secret, reveal

SERVICE: Final[str] = "nz-mcp"


def _username(profile_name: str) -> str:
    return f"profile:{profile_name}"


def store_password(profile_name: str, password: str) -> None:
    try:
        # Unwrap at the boundary: a keyring backend may coerce the value with ``str()``,
        # which a Secret redacts on purpose, and would store ``***`` as the password.
        keyring.set_password(SERVICE, _username(profile_name), reveal(password))
    except KeyringError as exc:
        raise KeyringUnavailableError(profile=profile_name, detail=str(exc)) from exc


def get_password(profile_name: str) -> Secret:
    try:
        password = keyring.get_password(SERVICE, _username(profile_name))
    except KeyringError as exc:
        raise KeyringUnavailableError(profile=profile_name, detail=str(exc)) from exc
    if password is None:
        raise CredentialNotFoundError(profile=profile_name)
    return Secret(password)


def delete_password(profile_name: str) -> None:
    try:
        keyring.delete_password(SERVICE, _username(profile_name))
    except keyring.errors.PasswordDeleteError:  # pragma: no cover - benign
        return
    except KeyringError as exc:
        raise KeyringUnavailableError(profile=profile_name, detail=str(exc)) from exc
