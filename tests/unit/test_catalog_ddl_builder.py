"""Tests for CREATE TABLE DDL reconstruction."""

from __future__ import annotations

from nz_mcp.catalog.ddl_builder import build_create_table_ddl


def test_build_ddl_hash_distribution_and_pk() -> None:
    ddl = build_create_table_ddl(
        fq_name="PUBLIC.T",
        columns=[
            {"name": "ID", "type": "INT", "nullable": False, "default": None},
            {"name": "N", "type": "VARCHAR(10)", "nullable": True, "default": None},
        ],
        distribution={"type": "HASH", "columns": ["ID"]},
        primary_key=["ID"],
        foreign_keys=[],
        include_constraints=True,
    )
    assert "CREATE TABLE PUBLIC.T" in ddl
    assert "DISTRIBUTE ON HASH (ID)" in ddl
    assert "PRIMARY KEY (ID)" in ddl
    assert "NOT NULL" in ddl


def test_build_ddl_random_no_constraints() -> None:
    ddl = build_create_table_ddl(
        fq_name="S.T",
        columns=[{"name": "X", "type": "INT", "nullable": True, "default": None}],
        distribution={"type": "RANDOM", "columns": []},
        primary_key=[],
        foreign_keys=[],
        include_constraints=False,
    )
    assert "DISTRIBUTE ON RANDOM" in ddl
    assert "PRIMARY KEY" not in ddl


def test_build_ddl_column_default_rendered() -> None:
    ddl = build_create_table_ddl(
        fq_name="S.T",
        columns=[
            {"name": "N", "type": "INT", "nullable": True, "default": "42"},
        ],
        distribution={"type": "RANDOM", "columns": []},
        primary_key=[],
        foreign_keys=[],
        include_constraints=False,
    )
    assert "DEFAULT 42" in ddl


def test_build_ddl_foreign_key() -> None:
    ddl = build_create_table_ddl(
        fq_name="S.CHILD",
        columns=[{"name": "ID", "type": "INT", "nullable": False, "default": None}],
        distribution={"type": "HASH", "columns": ["ID"]},
        primary_key=[],
        foreign_keys=[
            {
                "name": "FK1",
                "columns": ["ID"],
                "references": {
                    "database": None,
                    "schema": "S",
                    "table": "PARENT",
                    "columns": ["ID"],
                },
            },
        ],
        include_constraints=True,
    )
    assert "FOREIGN KEY (ID) REFERENCES S.PARENT (ID)" in ddl
