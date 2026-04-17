# Netezza Catalog Queries (Validated)

This document is the single source of truth for catalog SQL used by `nz-mcp`.
It captures validated behavior for IBM Netezza Performance Server and replaces
assumptions from early drafts.

## Scope

- Catalog views and SQL used by MCP tools.
- Version-specific column availability.
- Cross-database notation `<BD>.._V_*`.
- Fallbacks when expected columns/commands are unavailable.

Out of scope:

- Application code changes.
- Query centralization refactor (`queries.py`).

## Validated NPS Versions Matrix

Current validation baseline:

- NPS `11.2.1.11-IF1 [Build 4]`

| Query / tool | NPS 11.2.1.11-IF1 |
|---|---|
| `nz_list_databases` | ✅ validated |
| `nz_list_schemas` | ✅ validated |
| `nz_list_tables` | ✅ validated |
| `nz_list_views` | ✅ validated |
| `nz_get_view_ddl` | ✅ validated |
| `nz_describe_table` (columns) | ✅ validated |
| `nz_describe_table` (distribution) | ✅ validated |
| `nz_describe_table` (primary key) | ✅ validated |
| `nz_describe_table` (foreign keys) | ✅ validated |
| `nz_table_stats` | ✅ validated |
| `nz_list_procedures` | ✅ validated |
| `nz_get_procedure_ddl` | ✅ validated |
| `nz_get_procedure_section` | ✅ validated |

## Cross-database Rule

Some catalog views must be queried from an explicit database context:

- Pattern: `<BD>.._V_*`
- Example: `DEV.._V_SCHEMA`

`<BD>` interpolation must be restricted to validated identifiers only:

```regex
^[A-Z][A-Z0-9_]{0,127}$
```

Rules:

1. Uppercase before validation.
2. Reject any value that does not match the regex.
3. Never pass `<BD>` as a string literal parameter (`?`); identifiers are not SQL values.
4. Keep value placeholders (`?`) for all data values (`schema`, `table`, `pattern`, etc.).

## Query Catalog by Tool

All SQL below is the validated form and uses `?` placeholders for values.

### `nz_list_databases`

Views: `_V_DATABASE`

```sql
SELECT DATABASE, OWNER
FROM _V_DATABASE
WHERE (? IS NULL OR DATABASE LIKE ?)
ORDER BY DATABASE;
```

### `nz_list_schemas`

Views: `<BD>.._V_SCHEMA`

```sql
SELECT SCHEMA, OWNER
FROM <BD>.._V_SCHEMA
WHERE (? IS NULL OR SCHEMA LIKE ?)
ORDER BY SCHEMA;
```

### `nz_list_tables`

Views: `<BD>.._V_TABLE`

```sql
SELECT TABLENAME AS NAME, OWNER
FROM <BD>.._V_TABLE
WHERE SCHEMA = UPPER(?) AND OBJTYPE='TABLE'
  AND (? IS NULL OR TABLENAME LIKE ?)
ORDER BY TABLENAME;
```

### `nz_list_views`

Views: `<BD>.._V_VIEW`

```sql
SELECT VIEWNAME AS NAME, OWNER, CREATEDATE
FROM <BD>.._V_VIEW
WHERE SCHEMA = UPPER(?)
  AND (? IS NULL OR VIEWNAME LIKE ?)
ORDER BY VIEWNAME;
```

### `nz_get_view_ddl`

Views: `<BD>.._V_VIEW`

```sql
SELECT DEFINITION
FROM <BD>.._V_VIEW
WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?);
```

### `nz_describe_table` (columns)

Views: `<BD>.._V_RELATION_COLUMN`

```sql
SELECT ATTNAME AS COLUMN_NAME, FORMAT_TYPE AS DATA_TYPE,
       ATTNOTNULL AS NOT_NULL, COLDEFAULT AS DEFAULT_VALUE, ATTNUM
FROM <BD>.._V_RELATION_COLUMN
WHERE SCHEMA = UPPER(?) AND NAME = UPPER(?)
ORDER BY ATTNUM;
```

### `nz_describe_table` (distribution)

Views: `<BD>.._V_TABLE_DIST_MAP`

```sql
SELECT ATTNAME, DISTSEQNO
FROM <BD>.._V_TABLE_DIST_MAP
WHERE SCHEMA = UPPER(?) AND TABLENAME = UPPER(?)
ORDER BY DISTSEQNO;
```

Behavior:

- `0` rows: distribution is `RANDOM`.
- `>=1` rows: distribution is `HASH`, using ordered `ATTNAME` by `DISTSEQNO`.

### `nz_describe_table` (primary key)

Views: `<BD>.._V_RELATION_KEYDATA`

```sql
SELECT CONSTRAINTNAME, ATTNAME, CONSEQ
FROM <BD>.._V_RELATION_KEYDATA
WHERE SCHEMA = UPPER(?) AND RELATION = UPPER(?) AND CONTYPE = 'p'
ORDER BY CONSEQ;
```

### `nz_describe_table` (foreign keys)

Views: `<BD>.._V_RELATION_KEYDATA`

```sql
SELECT CONSTRAINTNAME, ATTNAME, CONSEQ,
       PKDATABASE, PKSCHEMA, PKRELATION, PKATTNAME, DEL_TYPE, UPDT_TYPE
FROM <BD>.._V_RELATION_KEYDATA
WHERE SCHEMA = UPPER(?) AND RELATION = UPPER(?) AND CONTYPE = 'f'
ORDER BY CONSTRAINTNAME, CONSEQ;
```

### `nz_table_stats`

Views: `<BD>.._V_TABLE`, `<BD>.._V_TABLE_STORAGE_STAT`

```sql
SELECT t.RELTUPLES AS ROW_COUNT,
       ts.USED_BYTES AS SIZE_BYTES_USED,
       ts.ALLOCATED_BYTES AS SIZE_BYTES_ALLOCATED,
       ts.SKEW, t.CREATEDATE AS TABLE_CREATED
FROM <BD>.._V_TABLE t
JOIN <BD>.._V_TABLE_STORAGE_STAT ts ON t.OBJID = ts.OBJID
WHERE t.SCHEMA = UPPER(?) AND t.TABLENAME = UPPER(?);
```

### `nz_list_procedures`

Views: `<BD>.._V_PROCEDURE`

```sql
SELECT PROCEDURE, OWNER, ARGUMENTS, RETURNS, PROCEDURESIGNATURE, NUMARGS
FROM <BD>.._V_PROCEDURE
WHERE SCHEMA = UPPER(?)
  AND (? IS NULL OR PROCEDURE LIKE ?)
ORDER BY PROCEDURE;
```

### `nz_get_procedure_ddl`

Views: `<BD>.._V_PROCEDURE`

```sql
SELECT PROCEDURE, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE
FROM <BD>.._V_PROCEDURE
WHERE SCHEMA = UPPER(?) AND PROCEDURE = UPPER(?);
```

### `nz_get_procedure_section`

Views: `<BD>.._V_PROCEDURE`

```sql
SELECT PROCEDURE, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE
FROM <BD>.._V_PROCEDURE
WHERE SCHEMA = UPPER(?) AND PROCEDURE = UPPER(?);
```

## Catalog Views and Columns Used

| View | Columns consumed by MCP |
|---|---|
| `_V_DATABASE` | `DATABASE`, `OWNER` |
| `_V_SCHEMA` | `SCHEMA`, `OWNER` |
| `_V_TABLE` | `TABLENAME`, `OWNER`, `OBJTYPE`, `OBJID`, `RELTUPLES`, `CREATEDATE` |
| `_V_VIEW` | `VIEWNAME`, `OWNER`, `CREATEDATE`, `DEFINITION` |
| `_V_RELATION_COLUMN` | `ATTNAME`, `FORMAT_TYPE`, `ATTNOTNULL`, `COLDEFAULT`, `ATTNUM` |
| `_V_TABLE_DIST_MAP` | `ATTNAME`, `DISTSEQNO` |
| `_V_RELATION_KEYDATA` | `CONSTRAINTNAME`, `ATTNAME`, `CONSEQ`, `CONTYPE`, `PKDATABASE`, `PKSCHEMA`, `PKRELATION`, `PKATTNAME`, `DEL_TYPE`, `UPDT_TYPE` |
| `_V_TABLE_STORAGE_STAT` | `OBJID`, `USED_BYTES`, `ALLOCATED_BYTES`, `SKEW` |
| `_V_PROCEDURE` | `PROCEDURE`, `OWNER`, `ARGUMENTS`, `RETURNS`, `PROCEDURESIGNATURE`, `NUMARGS`, `PROCEDURESOURCE` |
| `_V_SESSION` | `IPADDR` (when session metadata is queried) |

## Column Name Mismatches vs. Initial Documentation

The following assumptions were invalid for NPS `11.2.1.11-IF1`:

| View | Column not available | Valid alternative |
|---|---|---|
| `_V_RELATION_COLUMN` | `ADSRC` | `COLDEFAULT` |
| `_V_TABLE_DIST_MAP` | `DISTRIBTYPE`, `DISTRIBATTNAMES` | Reconstruct from `ATTNAME` + `DISTSEQNO`; `0` rows means `RANDOM` |
| `_V_STATISTIC` | `RELTUPLES` | Use `_V_TABLE.RELTUPLES` |
| `_V_PROCEDURE` | `PROCEDURELANGUAGE` | Set `language = "NZPLSQL"` |
| `_V_SESSION` | `CLIENT_IP` | `IPADDR` |
| `_V_TABLE_STORAGE_STAT` | `SIZE_UNCOMPRESSED` | Use `USED_BYTES` and `ALLOCATED_BYTES` only |

## Fallback Queries and Behaviors

### Distribution fallback (`nz_describe_table`)

Primary source is `<BD>.._V_TABLE_DIST_MAP`.

- If rows exist: build `HASH(column_1, ..., column_n)` from ordered `DISTSEQNO`.
- If no rows exist: report `RANDOM`.

No fallback to undocumented `DISTRIB*` columns.

### Procedure language fallback

`_V_PROCEDURE` does not expose `PROCEDURELANGUAGE` in validated NPS version.
`nz-mcp` must emit `"NZPLSQL"` as the language for procedure metadata responses.

## Commands Not Available in NPS 11.2

### `SHOW TABLE`

`SHOW TABLE` is not available in the validated NPS `11.2.1.11-IF1` baseline.

Impact:

- `nz_get_table_ddl` cannot rely on native DDL introspection.
- DDL must be reconstructed from catalog views (`_V_RELATION_COLUMN`,
  `_V_TABLE_DIST_MAP`, `_V_RELATION_KEYDATA`, and related metadata).

