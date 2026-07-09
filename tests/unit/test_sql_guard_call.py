"""Guard tests for the CALL statement kind (EXECUTE-class, admin-only)."""

from __future__ import annotations

import pytest

from nz_mcp.errors import GuardRejectedError
from nz_mcp.sql_guard import StatementKind, validate


def test_call_classified_and_allowed_in_admin() -> None:
    parsed = validate("CALL DBO.MYPROC(?, ?)", mode="admin")
    assert parsed.kind is StatementKind.CALL
    assert parsed.raw == "CALL DBO.MYPROC(?, ?)"


@pytest.mark.adversarial
@pytest.mark.parametrize("mode", ["read", "write"])
def test_call_rejected_outside_admin(mode: str) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("CALL DBO.MYPROC()", mode=mode)  # type: ignore[arg-type]
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


@pytest.mark.adversarial
def test_stacked_call_rejected() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("CALL DBO.MYPROC(); DROP TABLE t", mode="admin")
    assert exc.value.code == "STACKED_NOT_ALLOWED"


@pytest.mark.adversarial
def test_call_no_args_allowed_in_admin() -> None:
    assert validate("CALL DBO.MYPROC()", mode="admin").kind is StatementKind.CALL


@pytest.mark.adversarial
def test_call_with_literal_arg_rejected() -> None:
    # Literal arguments must never reach the DB inline; the intercept only accepts ``?``.
    with pytest.raises(GuardRejectedError) as exc:
        validate("CALL DBO.MYPROC(1)", mode="admin")
    assert exc.value.code == "UNKNOWN_STATEMENT"


@pytest.mark.adversarial
def test_call_with_string_literal_arg_rejected() -> None:
    with pytest.raises(GuardRejectedError):
        validate("CALL DBO.MYPROC('x')", mode="admin")
