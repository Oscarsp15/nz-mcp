"""Issue #135 smoke against a real Netezza: ORGANIZE ON needs DISTRIBUTE ON first.

With the clauses emitted in the wrong order the server answers
``found 'DISTRIBUTE' (at char N) expecting a keyword`` and no table is created, so any
``nz_create_table`` / ``nz_create_table_as`` call carrying ``organized_on`` failed.
Both tests create a throwaway table in a development schema and drop it afterwards.
"""

from __future__ import annotations

import pytest

from nz_mcp.tools.ddl import (
    ColumnDef,
    CreateTableAsInput,
    CreateTableInput,
    DistributionInput,
    DropTableInput,
    nz_create_table,
    nz_create_table_as,
    nz_drop_table,
)

pytestmark = pytest.mark.integration


def test_issue135_create_table_with_organize_on(
    integration_database: str,
    integration_schema: str,
) -> None:
    db, schema = integration_database, integration_schema
    table = "NZ_MCP_ISSUE135_ORDER"
    try:
        out = nz_create_table(
            CreateTableInput(
                database=db,
                table_schema=schema,
                table=table,
                columns=[
                    ColumnDef(name="ID", type="INTEGER", nullable=False),
                    ColumnDef(name="F", type="DATE"),
                ],
                distribution=DistributionInput(type="HASH", columns=["ID"]),
                organized_on=["F"],
                if_not_exists=False,
                dry_run=False,
                confirm=True,
            ),
        )
        assert out.executed is True
        ddl = out.ddl_to_execute
        assert ddl.index("DISTRIBUTE ON") < ddl.index("ORGANIZE ON")
    finally:
        nz_drop_table(
            DropTableInput(database=db, table_schema=schema, table=table, confirm=True),
        )


def test_issue135_create_table_as_with_organize_on(
    integration_database: str,
    integration_schema: str,
) -> None:
    db, schema = integration_database, integration_schema
    table = "NZ_MCP_ISSUE135_CTAS"
    try:
        out = nz_create_table_as(
            CreateTableAsInput(
                database=db,
                target_schema=schema,
                target_table=table,
                select_sql="SELECT TABLENAME AS N, OBJID AS ID FROM _V_TABLE LIMIT 5",
                distribution=DistributionInput(type="HASH", columns=["ID"]),
                organized_on=["N"],
                dry_run=False,
                confirm=True,
            ),
        )
        assert out.executed is True
    finally:
        nz_drop_table(
            DropTableInput(database=db, table_schema=schema, table=table, confirm=True),
        )
