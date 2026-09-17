"""Live smoke for ``nz_maintenance`` against a real Netezza profile (issue #307).

Creates its own throwaway table, runs each maintenance action on it, and drops it.
Requires ``NZ_MCP_RUN_INTEGRATION=1`` and an admin profile (see ``conftest.py``).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from nz_mcp.errors import NetezzaError
from nz_mcp.tools.ddl import (
    ColumnDef,
    CreateTableInput,
    DistributionInput,
    DropTableInput,
    nz_create_table,
    nz_drop_table,
)
from nz_mcp.tools.maintenance import MaintenanceInput, nz_maintenance

pytestmark = pytest.mark.integration

_TABLE = "NZ_MCP_MAINT_307"

_EXPECTED_PREFIX = {
    "generate_statistics": "GENERATE STATISTICS ON",
    "groom": "GROOM TABLE",
    "vacuum": "VACUUM",
}


@pytest.fixture
def maintenance_table(
    integration_database: str,
    integration_schema: str,
) -> Iterator[None]:
    nz_create_table(
        CreateTableInput(
            database=integration_database,
            table_schema=integration_schema,
            table=_TABLE,
            columns=[ColumnDef(name="ID", type="INT"), ColumnDef(name="V", type="VARCHAR(20)")],
            distribution=DistributionInput(type="RANDOM", columns=[]),
            dry_run=False,
            confirm=True,
        ),
    )
    try:
        yield None
    finally:
        nz_drop_table(
            DropTableInput(
                database=integration_database,
                table_schema=integration_schema,
                table=_TABLE,
                confirm=True,
                if_exists=True,
            ),
        )


@pytest.mark.parametrize("action", ["generate_statistics", "groom", "vacuum"])
def test_dry_run_returns_statement(
    maintenance_table: None,
    integration_database: str,
    integration_schema: str,
    action: str,
) -> None:
    out = nz_maintenance(
        MaintenanceInput(
            database=integration_database,
            table_schema=integration_schema,
            table=_TABLE,
            action=action,  # type: ignore[arg-type]
        ),
    )
    assert out.dry_run is True
    assert out.executed is False
    assert out.statements_to_execute is not None
    assert out.statements_to_execute[0].startswith(_EXPECTED_PREFIX[action])


@pytest.mark.parametrize("action", ["generate_statistics", "groom"])
def test_real_execution(
    maintenance_table: None,
    integration_database: str,
    integration_schema: str,
    action: str,
) -> None:
    out = nz_maintenance(
        MaintenanceInput(
            database=integration_database,
            table_schema=integration_schema,
            table=_TABLE,
            action=action,  # type: ignore[arg-type]
            dry_run=False,
            confirm=True,
        ),
    )
    assert out.executed is True
    assert out.statements_executed == 1


def test_real_vacuum_needs_privilege(
    maintenance_table: None,
    integration_database: str,
    integration_schema: str,
) -> None:
    """NPS restricts ``VACUUM`` to privileged users; the syntax itself is valid.

    Accept either outcome: success on a privileged account, or the server's permission
    error on a service account. A parse error would mean the allowlist syntax is wrong.
    """
    try:
        out = nz_maintenance(
            MaintenanceInput(
                database=integration_database,
                table_schema=integration_schema,
                table=_TABLE,
                action="vacuum",
                dry_run=False,
                confirm=True,
            ),
        )
    except NetezzaError as exc:
        assert "permission denied" in str(exc).lower()
    else:
        assert out.executed is True
