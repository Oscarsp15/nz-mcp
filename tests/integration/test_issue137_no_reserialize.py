"""Issue #137 smoke against a real Netezza: nz_query_select runs the SQL as written.

``inject_limit`` used to re-serialize the statement with sqlglot's postgres dialect, so
the server received a rewritten query (``NVL`` to ``COALESCE``, ``DECODE`` to ``CASE``,
``LAST_DAY`` to a ``DATE_TRUNC`` expression) and a ``LIMIT`` raised to ``max_rows``.
These checks are read-only: they hit the system catalog and ``_V_DUAL``.
"""

from __future__ import annotations

import os

import pytest

from nz_mcp.tools.query import QuerySelectInput, nz_query_select

pytestmark = pytest.mark.integration

_SKIP = pytest.mark.skipif(
    os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1",
    reason="Set NZ_MCP_RUN_INTEGRATION=1 and configure a live read profile.",
)


@_SKIP
def test_issue137_user_limit_is_not_raised_to_max_rows() -> None:
    """``LIMIT 3`` must return 3 rows even when ``max_rows`` allows 100."""
    out = nz_query_select(
        QuerySelectInput(sql="SELECT TABLENAME FROM _V_TABLE LIMIT 3", max_rows=100)
    )
    assert out.row_count == 3


@_SKIP
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT NVL(CAST(NULL AS VARCHAR(5)), 'ok') AS V FROM _V_DUAL", "ok"),
        ("SELECT DECODE(1, 1, 'A', 'Z') AS V FROM _V_DUAL", "A"),
        ("SELECT NVL2(1, 'a', 'b') AS V FROM _V_DUAL", "a"),
    ],
)
def test_issue137_netezza_functions_reach_the_engine(sql: str, expected: str) -> None:
    out = nz_query_select(QuerySelectInput(sql=sql, max_rows=10))
    assert out.rows[0][0] == expected


@_SKIP
def test_issue137_trailing_semicolon_still_runs() -> None:
    out = nz_query_select(QuerySelectInput(sql="SELECT TABLENAME FROM _V_TABLE;", max_rows=5))
    assert out.row_count == 5


@_SKIP
def test_issue137_untouched_statement_keeps_its_semicolon() -> None:
    """The engine accepts the trailing ``;`` that the untouched text carries along."""
    out = nz_query_select(
        QuerySelectInput(sql="SELECT TABLENAME FROM _V_TABLE LIMIT 3 ;  ", max_rows=100)
    )
    assert out.row_count == 3
