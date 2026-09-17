"""Guard tests for the MAINTENANCE statement kind (admin-only, closed allowlist)."""

from __future__ import annotations

import pytest

from nz_mcp import sql_guard
from nz_mcp.errors import GuardRejectedError
from nz_mcp.sql_guard import StatementKind, validate


@pytest.mark.parametrize(
    "sql",
    [
        "GENERATE STATISTICS ON DBO.T",
        "GROOM TABLE DBO.T",
        "VACUUM DBO.T",
        "generate statistics on dbo.t",
        "GROOM TABLE DBO.T;",
    ],
)
def test_maintenance_forms_classified_and_allowed_in_admin(sql: str) -> None:
    parsed = validate(sql, mode="admin")
    assert parsed.kind is StatementKind.MAINTENANCE
    assert parsed.raw == sql


@pytest.mark.adversarial
@pytest.mark.parametrize("mode", ["read", "write"])
@pytest.mark.parametrize(
    "sql",
    ["GENERATE STATISTICS ON DBO.T", "GROOM TABLE DBO.T", "VACUUM DBO.T"],
)
def test_maintenance_rejected_outside_admin(mode: str, sql: str) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode=mode)  # type: ignore[arg-type]
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


@pytest.mark.adversarial
def test_maintenance_stacked_rejected() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("GROOM TABLE DBO.T; DROP TABLE DBO.X", mode="admin")
    assert exc.value.code in {"STACKED_NOT_ALLOWED", "UNKNOWN_STATEMENT"}


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "sql",
    [
        "GROOM TABLE T",  # unqualified
        "GROOM TABLE DBO.T EXTRA",  # trailing token
        "GENERATE STATISTICS ON DBO.T (C1)",  # column list not in allowlist
        "GENERATE STATISTICS DBO.T",  # missing ON
        "VACUUM FULL T",  # Postgres form, never allowed
        "VACUUM TABLE DBO.T",  # Postgres form; NPS takes VACUUM directly on the table
        'GROOM TABLE "DBO"."T"',  # quoted identifiers not in allowlist
        "GROOM TABLE DBO.T; DROP TABLE DBO.X",  # stacked
        "GROOM TABLE DBO.T -- ; DROP TABLE DBO.X",  # comment smuggling
    ],
)
def test_maintenance_non_allowlisted_forms_rejected(sql: str) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="admin")
    assert exc.value.code in {"UNKNOWN_STATEMENT", "STACKED_NOT_ALLOWED"}


def test_maintenance_with_invalid_identifier_is_rejected() -> None:
    """The regex bounds only the shape; the catalog rules bound the length."""
    with pytest.raises(GuardRejectedError) as exc:
        validate(f"GROOM TABLE {'A' * 200}.T", mode="admin")
    assert exc.value.code == "UNKNOWN_STATEMENT"


def test_validate_maintenance_rejects_a_non_matching_statement() -> None:
    """Defensive re-match: the private helper never trusts its caller."""
    with pytest.raises(GuardRejectedError) as exc:
        sql_guard._validate_maintenance("GROOM TABLE T", mode="admin")
    assert exc.value.code == "UNKNOWN_STATEMENT"
