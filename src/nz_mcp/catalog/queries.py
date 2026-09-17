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
        "WHERE (? IS NULL OR DATABASE LIKE UPPER(?)) ORDER BY DATABASE"
    ),
    catalog_views=("_V_DATABASE",),
    description="Lists visible databases with an optional LIKE filter (case-insensitive).",
    tested_versions=(NPS_112_IF1,),
)

LIST_SCHEMAS: Final[CatalogQuery] = CatalogQuery(
    id="list_schemas",
    sql=(
        "SELECT SCHEMA, OWNER FROM <BD>.._V_SCHEMA "
        "WHERE (? IS NULL OR SCHEMA LIKE UPPER(?)) ORDER BY SCHEMA"
    ),
    catalog_views=("_V_SCHEMA",),
    description=(
        "Lists schemas for a specific database using cross-database notation; "
        "the optional pattern matches case-insensitively."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_TABLES: Final[CatalogQuery] = CatalogQuery(
    id="list_tables",
    sql=(
        "SELECT TABLENAME AS NAME, OWNER, OBJTYPE FROM <BD>.._V_TABLE "
        "WHERE SCHEMA = UPPER(?) AND (? IS NULL OR OBJTYPE = UPPER(?)) "
        "AND (? IS NULL OR TABLENAME LIKE UPPER(?)) ORDER BY TABLENAME"
    ),
    catalog_views=("_V_TABLE",),
    description=(
        "Lists tables for a schema with an optional case-insensitive name filter. "
        "OBJTYPE filter is optional (NULL means both TABLE and EXTERNAL TABLE)."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

DESCRIBE_TABLE_OBJTYPE: Final[CatalogQuery] = CatalogQuery(
    id="describe_table_objtype",
    sql=("SELECT OBJTYPE FROM <BD>.._V_TABLE WHERE SCHEMA = UPPER(?) AND TABLENAME = UPPER(?)"),
    catalog_views=("_V_TABLE",),
    description=(
        "Resolves the real OBJTYPE (TABLE or EXTERNAL TABLE) for describe_table. "
        "No row means the relation is a view, not a table."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_VIEWS: Final[CatalogQuery] = CatalogQuery(
    id="list_views",
    sql=(
        "SELECT VIEWNAME AS NAME, OWNER, CREATEDATE FROM <BD>.._V_VIEW "
        "WHERE SCHEMA = UPPER(?) AND (? IS NULL OR VIEWNAME LIKE UPPER(?)) "
        "ORDER BY VIEWNAME"
    ),
    catalog_views=("_V_VIEW",),
    description="Lists views for a schema with an optional case-insensitive name filter.",
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

RELATION_KIND: Final[CatalogQuery] = CatalogQuery(
    id="relation_kind",
    sql=(
        "SELECT CAST(OBJTYPE AS VARCHAR(64)) AS KIND FROM <BD>.._V_TABLE "
        "WHERE SCHEMA = UPPER(?) AND TABLENAME = UPPER(?) "
        "UNION ALL "
        "SELECT CAST('VIEW' AS VARCHAR(64)) AS KIND FROM <BD>.._V_VIEW "
        "WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?)"
    ),
    catalog_views=("_V_TABLE", "_V_VIEW"),
    description=(
        "Resolves a relation's real kind (TABLE/EXTERNAL TABLE/VIEW) in one round trip; "
        "no row means the object is not visible. Used by view lineage tools."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_VIEW_DEFINITIONS: Final[CatalogQuery] = CatalogQuery(
    id="list_view_definitions",
    sql=(
        "SELECT VIEWNAME, DEFINITION FROM <BD>.._V_VIEW WHERE SCHEMA = UPPER(?) ORDER BY VIEWNAME"
    ),
    catalog_views=("_V_VIEW",),
    description=(
        "Returns every view name and definition in a schema; used to resolve reverse "
        "dependencies (which views reference an object) by parsing each definition."
    ),
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
        "WHERE DATABASE = UPPER(?) AND SCHEMA = UPPER(?) AND TABLENAME = UPPER(?) "
        "ORDER BY DISTSEQNO"
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
        "CAST(t.CREATEDATE AS VARCHAR(19)) AS TABLE_CREATED "
        "FROM <BD>.._V_TABLE t "
        "JOIN <BD>.._V_TABLE_STORAGE_STAT ts ON t.OBJID = ts.OBJID "
        "WHERE t.SCHEMA = UPPER(?) AND t.TABLENAME = UPPER(?)"
    ),
    catalog_views=("_V_TABLE", "_V_TABLE_STORAGE_STAT"),
    description=(
        "Returns row estimate, storage metrics, and table create date "
        "(NPS 11.x has no stable stats-analyzed timestamp in _V_STATISTIC)."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

TABLE_STATS_BATCH: Final[CatalogQuery] = CatalogQuery(
    id="table_stats_batch",
    sql=(
        "SELECT t.TABLENAME AS TABLE_NAME, t.RELTUPLES AS ROW_COUNT, "
        "ts.USED_BYTES AS SIZE_BYTES_USED, ts.ALLOCATED_BYTES AS SIZE_BYTES_ALLOCATED, "
        "ts.SKEW, CAST(t.CREATEDATE AS VARCHAR(19)) AS TABLE_CREATED "
        "FROM <BD>.._V_TABLE t "
        "JOIN <BD>.._V_TABLE_STORAGE_STAT ts ON t.OBJID = ts.OBJID "
        "WHERE t.SCHEMA = UPPER(?) ORDER BY t.TABLENAME"
    ),
    catalog_views=("_V_TABLE", "_V_TABLE_STORAGE_STAT"),
    description=(
        "Returns row estimate and storage metrics for every table in a schema, ordered "
        "by name; the caller ranks by size or rows and applies its own top-N cut."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_PROCEDURES: Final[CatalogQuery] = CatalogQuery(
    id="list_procedures",
    sql=(
        "SELECT PROCEDURE, OWNER, ARGUMENTS, RETURNS, PROCEDURESIGNATURE, NUMARGS "
        "FROM <BD>.._V_PROCEDURE WHERE SCHEMA = UPPER(?) "
        "AND (? IS NULL OR PROCEDURE LIKE UPPER(?)) ORDER BY PROCEDURE"
    ),
    catalog_views=("_V_PROCEDURE",),
    description="Lists procedures for a schema with an optional case-insensitive name filter.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

GET_PROCEDURE_DDL: Final[CatalogQuery] = CatalogQuery(
    id="get_procedure_ddl",
    sql=(
        "SELECT PROCEDURE, OWNER, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE "
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
        "SELECT PROCEDURE, OWNER, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE "
        "FROM <BD>.._V_PROCEDURE WHERE SCHEMA = UPPER(?) AND PROCEDURE = UPPER(?)"
    ),
    catalog_views=("_V_PROCEDURE",),
    description="Returns procedure source used for section extraction.",
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

GET_ALL_PROCEDURES_DDL: Final[CatalogQuery] = CatalogQuery(
    id="get_all_procedures_ddl",
    sql=(
        "SELECT PROCEDURE, OWNER, ARGUMENTS, RETURNS, PROCEDURESOURCE, "
        "PROCEDURESIGNATURE, CREATEDATE "
        "FROM <BD>.._V_PROCEDURE WHERE SCHEMA = UPPER(?) "
        "AND (? IS NULL OR PROCEDURE LIKE UPPER(?)) ORDER BY PROCEDURE"
    ),
    catalog_views=("_V_PROCEDURE",),
    description=(
        "Returns all procedure DDLs for a schema with an optional case-insensitive name filter."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

FIND_COLUMN: Final[CatalogQuery] = CatalogQuery(
    id="find_column",
    sql=(
        "SELECT SCHEMA, NAME, ATTNAME, FORMAT_TYPE FROM <BD>.._V_RELATION_COLUMN "
        "WHERE TYPE IN ('TABLE', 'VIEW') AND ATTNAME LIKE UPPER(?) "
        "AND (? IS NULL OR SCHEMA LIKE UPPER(?)) AND (? IS NULL OR NAME LIKE UPPER(?)) "
        "ORDER BY SCHEMA, NAME, ATTNAME"
    ),
    catalog_views=("_V_RELATION_COLUMN",),
    description=(
        "Finds columns by name pattern across base tables and views in a database, "
        "with optional schema/table name filters."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

LIST_CONSTRAINTS: Final[CatalogQuery] = CatalogQuery(
    id="list_constraints",
    sql=(
        "SELECT RELATION, CONSTRAINTNAME, CONTYPE, ATTNAME, CONSEQ "
        "FROM <BD>.._V_RELATION_KEYDATA "
        "WHERE SCHEMA = UPPER(?) AND CONTYPE IN ('p', 'f', 'u') "
        "AND (? IS NULL OR RELATION = UPPER(?)) "
        "ORDER BY RELATION, CONSTRAINTNAME, CONSEQ"
    ),
    catalog_views=("_V_RELATION_KEYDATA",),
    description=(
        "Lists primary/foreign/unique constraints for a schema, or one table when given, "
        "grouped by constraint with columns in key order."
    ),
    tested_versions=(NPS_112_IF1,),
    cross_database=True,
)

ALL_QUERIES: Final[tuple[CatalogQuery, ...]] = (
    LIST_DATABASES,
    LIST_SCHEMAS,
    LIST_TABLES,
    LIST_VIEWS,
    GET_VIEW_DDL,
    RELATION_KIND,
    LIST_VIEW_DEFINITIONS,
    DESCRIBE_TABLE_COLUMNS,
    DESCRIBE_TABLE_OBJTYPE,
    DESCRIBE_TABLE_DISTRIBUTION,
    DESCRIBE_TABLE_PK,
    DESCRIBE_TABLE_FK,
    TABLE_STATS,
    TABLE_STATS_BATCH,
    LIST_PROCEDURES,
    GET_PROCEDURE_DDL,
    GET_PROCEDURE_SECTION,
    GET_ALL_PROCEDURES_DDL,
    FIND_COLUMN,
    LIST_CONSTRAINTS,
)

CATALOG_QUERY_MAP: Final[dict[str, CatalogQuery]] = {query.id: query for query in ALL_QUERIES}
