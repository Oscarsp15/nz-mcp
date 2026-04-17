"""Central catalog query registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

NPS_112_IF1: Final[str] = "NPS 11.2.1.11-IF1"


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    id: str
    sql: str
    catalog_views: tuple[str, ...]
    description: str
    tested_versions: tuple[str, ...] = ()
    cross_database: bool = False


LIST_DATABASES: Final[CatalogQuery] = CatalogQuery(
    id="list_databases",
    sql=(
        "SELECT DATABASE, OWNER FROM _v_database "
        "WHERE (? IS NULL OR DATABASE LIKE ?) ORDER BY DATABASE"
    ),
    catalog_views=("_V_DATABASE",),
    description="Lists visible databases with an optional LIKE filter.",
    tested_versions=(NPS_112_IF1,),
)

LIST_SCHEMAS: Final[CatalogQuery] = CatalogQuery(
    id="list_schemas",
    sql=(
        "SELECT SCHEMA, OWNER FROM <BD>.._V_SCHEMA "
        "WHERE (? IS NULL OR SCHEMA LIKE ?) ORDER BY SCHEMA"
    ),
    catalog_views=("_V_SCHEMA",),
    description="Lists schemas for a specific database using cross-database notation.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_TABLES: Final[CatalogQuery] = CatalogQuery(
    id="list_tables",
    sql=(
        "SELECT TABLENAME AS NAME, OWNER FROM <BD>.._V_TABLE "
        "WHERE SCHEMA = UPPER(?) AND OBJTYPE='TABLE' "
        "AND (? IS NULL OR TABLENAME LIKE ?) ORDER BY TABLENAME"
    ),
    catalog_views=("_V_TABLE",),
    description="Lists tables for a schema with optional name filter.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_VIEWS: Final[CatalogQuery] = CatalogQuery(
    id="list_views",
    sql=(
        "SELECT VIEWNAME AS NAME, OWNER, CREATEDATE FROM <BD>.._V_VIEW "
        "WHERE SCHEMA = UPPER(?) AND (? IS NULL OR VIEWNAME LIKE ?) ORDER BY VIEWNAME"
    ),
    catalog_views=("_V_VIEW",),
    description="Lists views for a schema with optional name filter.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

GET_VIEW_DDL: Final[CatalogQuery] = CatalogQuery(
    id="get_view_ddl",
    sql="SELECT DEFINITION FROM <BD>.._V_VIEW WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?)",
    catalog_views=("_V_VIEW",),
    description="Returns CREATE VIEW definition text.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

DESCRIBE_TABLE_COLUMNS: Final[CatalogQuery] = CatalogQuery(
    id="describe_table_columns",
    sql=(
        "SELECT ATTNAME AS COLUMN_NAME, FORMAT_TYPE AS DATA_TYPE, "
        "ATTNOTNULL AS NOT_NULL, COLDEFAULT AS DEFAULT_VALUE, ATTNUM "
        "FROM <BD>.._V_RELATION_COLUMN "
        "WHERE SCHEMA = UPPER(?) AND NAME = UPPER(?) ORDER BY ATTNUM"
    ),
    catalog_views=("_V_RELATION_COLUMN",),
    description="Returns table column metadata in ordinal order.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

DESCRIBE_TABLE_DISTRIBUTION: Final[CatalogQuery] = CatalogQuery(
    id="describe_table_distribution",
    sql=(
        "SELECT ATTNAME, DISTSEQNO FROM <BD>.._V_TABLE_DIST_MAP "
        "WHERE SCHEMA = UPPER(?) AND TABLENAME = UPPER(?) ORDER BY DISTSEQNO"
    ),
    catalog_views=("_V_TABLE_DIST_MAP",),
    description="Returns distribution keys used to infer HASH vs RANDOM.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

DESCRIBE_TABLE_PK: Final[CatalogQuery] = CatalogQuery(
    id="describe_table_pk",
    sql=(
        "SELECT CONSTRAINTNAME, ATTNAME, CONSEQ FROM <BD>.._V_RELATION_KEYDATA "
        "WHERE SCHEMA = UPPER(?) AND RELATION = UPPER(?) AND CONTYPE = 'p' "
        "ORDER BY CONSEQ"
    ),
    catalog_views=("_V_RELATION_KEYDATA",),
    description="Returns primary key columns in key order.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

DESCRIBE_TABLE_FK: Final[CatalogQuery] = CatalogQuery(
    id="describe_table_fk",
    sql=(
        "SELECT CONSTRAINTNAME, ATTNAME, CONSEQ, PKDATABASE, PKSCHEMA, PKRELATION, "
        "PKATTNAME, DEL_TYPE, UPDT_TYPE FROM <BD>.._V_RELATION_KEYDATA "
        "WHERE SCHEMA = UPPER(?) AND RELATION = UPPER(?) AND CONTYPE = 'f' "
        "ORDER BY CONSTRAINTNAME, CONSEQ"
    ),
    catalog_views=("_V_RELATION_KEYDATA",),
    description="Returns foreign keys and referenced columns.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

TABLE_STATS: Final[CatalogQuery] = CatalogQuery(
    id="table_stats",
    sql=(
        "SELECT t.RELTUPLES AS ROW_COUNT, ts.USED_BYTES AS SIZE_BYTES_USED, "
        "ts.ALLOCATED_BYTES AS SIZE_BYTES_ALLOCATED, ts.SKEW, "
        "t.CREATEDATE AS TABLE_CREATED FROM <BD>.._V_TABLE t "
        "JOIN <BD>.._V_TABLE_STORAGE_STAT ts ON t.OBJID = ts.OBJID "
        "WHERE t.SCHEMA = UPPER(?) AND t.TABLENAME = UPPER(?)"
    ),
    catalog_views=("_V_TABLE", "_V_TABLE_STORAGE_STAT"),
    description="Returns row estimate and storage metrics for one table.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_PROCEDURES: Final[CatalogQuery] = CatalogQuery(
    id="list_procedures",
    sql=(
        "SELECT PROCEDURE, OWNER, ARGUMENTS, RETURNS, PROCEDURESIGNATURE, NUMARGS "
        "FROM <BD>.._V_PROCEDURE WHERE SCHEMA = UPPER(?) "
        "AND (? IS NULL OR PROCEDURE LIKE ?) ORDER BY PROCEDURE"
    ),
    catalog_views=("_V_PROCEDURE",),
    description="Lists procedures for a schema with optional name filter.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

GET_PROCEDURE_DDL: Final[CatalogQuery] = CatalogQuery(
    id="get_procedure_ddl",
    sql=(
        "SELECT PROCEDURE, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE "
        "FROM <BD>.._V_PROCEDURE WHERE SCHEMA = UPPER(?) AND PROCEDURE = UPPER(?)"
    ),
    catalog_views=("_V_PROCEDURE",),
    description="Returns procedure source and signature metadata.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

GET_PROCEDURE_SECTION: Final[CatalogQuery] = CatalogQuery(
    id="get_procedure_section",
    sql=(
        "SELECT PROCEDURE, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE "
        "FROM <BD>.._V_PROCEDURE WHERE SCHEMA = UPPER(?) AND PROCEDURE = UPPER(?)"
    ),
    catalog_views=("_V_PROCEDURE",),
    description="Returns procedure source used for section extraction.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

ALL_QUERIES: Final[tuple[CatalogQuery, ...]] = (
    LIST_DATABASES,
    LIST_SCHEMAS,
    LIST_TABLES,
    LIST_VIEWS,
    GET_VIEW_DDL,
    DESCRIBE_TABLE_COLUMNS,
    DESCRIBE_TABLE_DISTRIBUTION,
    DESCRIBE_TABLE_PK,
    DESCRIBE_TABLE_FK,
    TABLE_STATS,
    LIST_PROCEDURES,
    GET_PROCEDURE_DDL,
    GET_PROCEDURE_SECTION,
)
