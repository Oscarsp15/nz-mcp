"""Adversarial tests for the environment guard ``assert_env_safe``.

The rail must reject any ``PROD_`` reference when the active database is not itself
a production database, and never over-block a genuine production session.
"""

from __future__ import annotations

import pytest

from nz_mcp.errors import GuardRejectedError
from nz_mcp.sql_guard import assert_env_safe


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "sql",
    [
        "CREATE OR REPLACE VIEW DBO.V AS SELECT * FROM PROD_ANALITICA..T",
        "CALL PROD_MODELOS.DBO.RUN()",
        "SELECT * FROM prod_analitica..t",  # lower-case must still trip
        "INSERT INTO PROD_DW.DBO.T VALUES (1)",
    ],
)
def test_prod_ref_blocked_in_non_prod_db(sql: str) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        assert_env_safe(sql, active_database="DESA_MODELOS")
    assert exc.value.code == "PROD_REF_IN_NONPROD"


@pytest.mark.adversarial
def test_multiple_prod_refs_reported_sorted_and_unique() -> None:
    sql = "SELECT * FROM PROD_B..t JOIN PROD_A..s ON 1=1 JOIN PROD_B..u ON 1=1"
    with pytest.raises(GuardRejectedError) as exc:
        assert_env_safe(sql, active_database="DESA_MODELOS")
    assert exc.value.context["refs"] == "PROD_A, PROD_B"


def test_no_prod_ref_passes_in_non_prod_db() -> None:
    assert_env_safe("CREATE OR REPLACE VIEW DBO.V AS SELECT 1 AS C", active_database="DESA_MODELOS")


def test_prod_db_allows_prod_refs() -> None:
    assert_env_safe("SELECT * FROM PROD_ANALITICA..T", active_database="PROD_ANALITICA")


def test_prod_db_case_insensitive_prefix() -> None:
    # active database with lower-case prefix is still a production database
    assert_env_safe("SELECT * FROM PROD_X..T", active_database="prod_ventas")
