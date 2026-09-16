"""Issue #294 — live regression: nz_execute_ddl warns on lazy NZPLSQL compile."""

from __future__ import annotations

from contextlib import closing, suppress

import pytest

from nz_mcp.auth import get_password
from nz_mcp.catalog.execute_ddl import execute_ddl
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection

pytestmark = pytest.mark.integration

_SP_NAME = "NZ_MCP_294_COMPILE_CHECK"
_SP_SCHEMA = "DBO"

# Zero-arg SP with an invalid body: the server accepts the DDL (lazy compilation)
# but the NZPLSQL compiler rejects the body on first CALL with:
# "syntax error, unexpected WORD, expecting BEGIN at or near 'THIS'"
# Using zero args so _run_compile_check can call with CALL proc() and trigger compilation.
_BAD_SP = f"""\
CREATE OR REPLACE PROCEDURE {_SP_SCHEMA}.{_SP_NAME}()
RETURNS INT4
LANGUAGE NZPLSQL AS
BEGIN_PROC
  THIS IS NOT VALID NZPLSQL AT ALL;
END_PROC;
"""


def _drop_sp(profile: Profile) -> None:
    pw = get_password(profile.name)
    conn = open_connection(profile, pw)
    try:
        with suppress(Exception), closing(conn.cursor()) as cur:
            cur.execute(f"DROP PROCEDURE {_SP_SCHEMA}.{_SP_NAME}()", ())
    finally:
        conn.close()


def test_bad_sp_compile_warning_and_validate_compile(
    integration_profile: Profile,
) -> None:
    _drop_sp(integration_profile)  # ensure clean start
    try:
        result = execute_ddl(
            integration_profile,
            sql=_BAD_SP,
            input_path=None,
            statement_type="procedure",
            dry_run=False,
            confirm=True,
            validate_compile=True,
        )
        assert result["executed"] is True, "DDL should be accepted by server"
        assert result["compile_warning"] is not None, "compile_warning must be set"
        assert result["compiled"] is False, "body must fail to compile"
        assert result["compile_error"] is not None, "compile_error must surface"
        # NPS 11.x SaaS raises "syntax error, unexpected WORD, expecting BEGIN";
        # older NPS versions raise "plpgsql: ERROR during compile of ...".
        err_lower = result["compile_error"].lower()
        assert "compile" in err_lower or "syntax error" in err_lower, (
            f"expected a NZPLSQL compile error, got: {result['compile_error']}"
        )
    finally:
        _drop_sp(integration_profile)
