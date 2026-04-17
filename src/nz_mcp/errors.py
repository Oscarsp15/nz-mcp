"""Typed exception hierarchy.

Rule: never raise bare ``Exception`` / ``RuntimeError`` from this package.
All exceptions carry a stable ``code`` (see docs/architecture/tools-contract.md).
"""

from __future__ import annotations

from typing import Any


class NzMcpError(Exception):
    """Base for all nz-mcp errors. Stable ``code`` per subclass."""

    code: str = "INTERNAL_ERROR"

    def __init__(self, *, code: str | None = None, **context: Any) -> None:
        if code is not None:
            self.code = code
        self.context: dict[str, Any] = context
        super().__init__(self._render())

    def _render(self) -> str:
        if not self.context:
            return self.code
        ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{self.code} ({ctx})"


# --- Config / profile ---------------------------------------------------------


class ConfigError(NzMcpError):
    code = "INVALID_CONFIG"


class ProfileNotFoundError(ConfigError):
    code = "PROFILE_NOT_FOUND"


class InvalidProfileError(ConfigError):
    code = "INVALID_PROFILE"


# --- Auth ---------------------------------------------------------------------


class AuthError(NzMcpError):
    code = "AUTH_FAILED"


class KeyringUnavailableError(AuthError):
    code = "KEYRING_UNAVAILABLE"


class CredentialNotFoundError(AuthError):
    code = "CREDENTIAL_NOT_FOUND"


# --- Permissions / SQL guard --------------------------------------------------


class PermissionDeniedError(NzMcpError):
    code = "PERMISSION_DENIED"


class GuardRejectedError(NzMcpError):
    code = "GUARD_REJECTED"


# --- Connection / query -------------------------------------------------------


class ConnectionError(NzMcpError):
    code = "CONNECTION_FAILED"


class QueryTimeoutError(NzMcpError):
    code = "QUERY_TIMEOUT"


class ResultTooLargeError(NzMcpError):
    code = "RESULT_TOO_LARGE"


class NetezzaError(NzMcpError):
    code = "NETEZZA_ERROR"


class ObjectNotFoundError(NzMcpError):
    code = "OBJECT_NOT_FOUND"


class SectionNotFoundError(NzMcpError):
    code = "SECTION_NOT_FOUND"


class OverloadAmbiguousError(NzMcpError):
    code = "OVERLOAD_AMBIGUOUS"


# --- Tool input validation ----------------------------------------------------


class InvalidInputError(NzMcpError):
    code = "INVALID_INPUT"
