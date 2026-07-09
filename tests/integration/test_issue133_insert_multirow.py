"""Issue #133 smoke against a real Netezza: multi-row nz_insert must succeed.

Before the fix, ``nz_insert`` with 2+ rows emitted a multi-row ``VALUES`` list,
which Netezza rejects. This test creates a throwaway table, inserts several rows
in one call, checks the count, and drops the table — all against a live profile.
"""

from __future__ import annotations

import os

import pytest

from nz_mcp.tools.ddl import (
    ColumnDef,
    CreateTableInput,
    DistributionInput,
    DropTableInput,
    nz_create_table,
    nz_drop_table,
)
from nz_mcp.tools.write import InsertInput, nz_insert

pytestmark = pytest.mark.integration

_TABLE = "NZ_MCP_ISSUE133_MULTIROW"


@pytest.mark.skipif(
    os.environ.get("NZ_MCP_RUN_INTEGRATION") != "1",
    reason="Set NZ_MCP_RUN_INTEGRATION=1 and configure a live admin profile.",
)
def test_issue133_multirow_insert_succeeds() -> None:
    db = os.environ.get("NZ_MCP_TEST_DATABASE", "DESA_MODELOS")
    schema = os.environ.get("NZ_MCP_TEST_SCHEMA", "DBO")

    nz_create_table(
        CreateTableInput(
            database=db,
            table_schema=schema,
            table=_TABLE,
            columns=[
                ColumnDef(name="ID", type="INTEGER", nullable=False),
                ColumnDef(name="NOMBRE", type="VARCHAR(50)"),
            ],
            distribution=DistributionInput(type="RANDOM", columns=[]),
            dry_run=False,
            confirm=True,
        ),
    )
    try:
        out = nz_insert(
            InsertInput(
                database=db,
                table_schema=schema,
                table=_TABLE,
                rows=[
                    {"ID": 1, "NOMBRE": "Oscar"},
                    {"ID": 2, "NOMBRE": "Claude"},
                    {"ID": 3, "NOMBRE": "Netezza"},
                ],
                on_conflict="error",
                dry_run=False,
                confirm=True,
            ),
        )
        assert out.inserted == 3
        assert out.dry_run is False
    finally:
        nz_drop_table(
            DropTableInput(
                database=db,
                table_schema=schema,
                table=_TABLE,
                confirm=True,
                if_exists=True,
            ),
        )
