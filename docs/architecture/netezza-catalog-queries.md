# Queries del catálogo Netezza (validadas)

Este documento es la fuente de verdad única para el SQL de catálogo usado por
`nz-mcp`. Resume el comportamiento validado contra IBM Netezza Performance
Server y reemplaza supuestos de borradores iniciales.

## Alcance

- Vistas de catálogo y SQL usados por las tools MCP.
- Disponibilidad de columnas específica por versión.
- Notación cross-database `<BD>.._V_*`.
- Fallbacks cuando columnas o comandos esperados no están disponibles.

Fuera de alcance:

- Cambios de código de aplicación.
- Refactor de centralización de queries (`queries.py`).

## Matriz de versiones NPS validadas

Baseline actual de validación:

- NPS `11.2.1.11-IF1 [Build 4]`

| Query / tool | NPS 11.2.1.11-IF1 |
|---|---|
| `nz_list_databases` | ✅ validada |
| `nz_list_schemas` | ✅ validada |
| `nz_list_tables` | ✅ validada |
| `nz_list_views` | ✅ validada |
| `nz_get_view_ddl` | ✅ validada |
| `nz_describe_table` (columns) | ✅ validada |
| `nz_describe_table` (distribution) | ✅ validada |
| `nz_describe_table` (primary key) | ✅ validada |
| `nz_describe_table` (foreign keys) | ✅ validada |
| `nz_table_stats` | ✅ validada |
| `nz_list_procedures` | ✅ validada |
| `nz_get_procedure_ddl` | ✅ validada |
| `nz_get_procedure_section` | ✅ validada |

## Regla cross-database

Algunas vistas de catálogo deben consultarse desde un contexto de base de datos explícito:

- Patrón: `<BD>.._V_*`
- Ejemplo: `DEV.._V_SCHEMA`

La interpolación de `<BD>` debe restringirse solo a identifiers validados:

```regex
^[A-Z][A-Z0-9_]{0,127}$
```

Reglas:

1. Convertir a mayúsculas antes de validar.
2. Rechazar cualquier valor que no cumpla el regex.
3. Nunca pasar `<BD>` como parámetro string (`?`); los identifiers no son valores SQL.
4. Mantener placeholders (`?`) para todos los valores de datos (`schema`, `table`, `pattern`, etc.).

## Catálogo de queries por tool

Todo el SQL siguiente está validado y usa placeholders `?` para valores.

### `nz_list_databases`

Vistas: `_V_DATABASE`

```sql
SELECT DATABASE, OWNER
FROM _V_DATABASE
WHERE (? IS NULL OR DATABASE LIKE ?)
ORDER BY DATABASE;
```

### `nz_list_schemas`

Vistas: `<BD>.._V_SCHEMA`

```sql
SELECT SCHEMA, OWNER
FROM <BD>.._V_SCHEMA
WHERE (? IS NULL OR SCHEMA LIKE ?)
ORDER BY SCHEMA;
```

### `nz_list_tables`

Vistas: `<BD>.._V_TABLE`

```sql
SELECT TABLENAME AS NAME, OWNER
FROM <BD>.._V_TABLE
WHERE SCHEMA = UPPER(?) AND OBJTYPE='TABLE'
  AND (? IS NULL OR TABLENAME LIKE ?)
ORDER BY TABLENAME;
```

### `nz_list_views`

Vistas: `<BD>.._V_VIEW`

```sql
SELECT VIEWNAME AS NAME, OWNER, CREATEDATE
FROM <BD>.._V_VIEW
WHERE SCHEMA = UPPER(?)
  AND (? IS NULL OR VIEWNAME LIKE ?)
ORDER BY VIEWNAME;
```

### `nz_get_view_ddl`

Vistas: `<BD>.._V_VIEW`

```sql
SELECT DEFINITION
FROM <BD>.._V_VIEW
WHERE SCHEMA = UPPER(?) AND VIEWNAME = UPPER(?);
```

### `nz_describe_table` (columnas)

Vistas: `<BD>.._V_RELATION_COLUMN`

```sql
SELECT ATTNAME AS COLUMN_NAME, FORMAT_TYPE AS DATA_TYPE,
       ATTNOTNULL AS NOT_NULL, COLDEFAULT AS DEFAULT_VALUE, ATTNUM
FROM <BD>.._V_RELATION_COLUMN
WHERE SCHEMA = UPPER(?) AND NAME = UPPER(?)
ORDER BY ATTNUM;
```

### `nz_describe_table` (distribución)

Vistas: `<BD>.._V_TABLE_DIST_MAP`

```sql
SELECT ATTNAME, DISTSEQNO
FROM <BD>.._V_TABLE_DIST_MAP
WHERE SCHEMA = UPPER(?) AND TABLENAME = UPPER(?)
ORDER BY DISTSEQNO;
```

Comportamiento:

- `0` filas: la distribución es `RANDOM`.
- `>=1` filas: la distribución es `HASH`, usando `ATTNAME` ordenado por `DISTSEQNO`.

### `nz_describe_table` (primary key)

Vistas: `<BD>.._V_RELATION_KEYDATA`

```sql
SELECT CONSTRAINTNAME, ATTNAME, CONSEQ
FROM <BD>.._V_RELATION_KEYDATA
WHERE SCHEMA = UPPER(?) AND RELATION = UPPER(?) AND CONTYPE = 'p'
ORDER BY CONSEQ;
```

### `nz_describe_table` (foreign keys)

Vistas: `<BD>.._V_RELATION_KEYDATA`

```sql
SELECT CONSTRAINTNAME, ATTNAME, CONSEQ,
       PKDATABASE, PKSCHEMA, PKRELATION, PKATTNAME, DEL_TYPE, UPDT_TYPE
FROM <BD>.._V_RELATION_KEYDATA
WHERE SCHEMA = UPPER(?) AND RELATION = UPPER(?) AND CONTYPE = 'f'
ORDER BY CONSTRAINTNAME, CONSEQ;
```

### `nz_table_stats`

Vistas: `<BD>.._V_TABLE`, `<BD>.._V_TABLE_STORAGE_STAT`

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

Vistas: `<BD>.._V_PROCEDURE`

```sql
SELECT PROCEDURE, OWNER, ARGUMENTS, RETURNS, PROCEDURESIGNATURE, NUMARGS
FROM <BD>.._V_PROCEDURE
WHERE SCHEMA = UPPER(?)
  AND (? IS NULL OR PROCEDURE LIKE ?)
ORDER BY PROCEDURE;
```

### `nz_get_procedure_ddl`

Vistas: `<BD>.._V_PROCEDURE`

```sql
SELECT PROCEDURE, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE
FROM <BD>.._V_PROCEDURE
WHERE SCHEMA = UPPER(?) AND PROCEDURE = UPPER(?);
```

### `nz_get_procedure_section`

Vistas: `<BD>.._V_PROCEDURE`

```sql
SELECT PROCEDURE, ARGUMENTS, RETURNS, PROCEDURESOURCE, PROCEDURESIGNATURE
FROM <BD>.._V_PROCEDURE
WHERE SCHEMA = UPPER(?) AND PROCEDURE = UPPER(?);
```

## Vistas del catálogo y columnas consumidas

| Vista | Columnas consumidas por MCP |
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
| `_V_SESSION` | `IPADDR` (cuando se consulta metadata de sesión) |

## Columnas con nombre distinto a lo documentado inicialmente

Los siguientes supuestos fueron inválidos para NPS `11.2.1.11-IF1`:

| Vista | Columna no disponible | Alternativa válida |
|---|---|---|
| `_V_RELATION_COLUMN` | `ADSRC` | `COLDEFAULT` |
| `_V_TABLE_DIST_MAP` | `DISTRIBTYPE`, `DISTRIBATTNAMES` | Reconstruir desde `ATTNAME` + `DISTSEQNO`; `0` filas implica `RANDOM` |
| `_V_STATISTIC` | `RELTUPLES` | Usar `_V_TABLE.RELTUPLES` |
| `_V_PROCEDURE` | `PROCEDURELANGUAGE` | Definir `language = "NZPLSQL"` |
| `_V_SESSION` | `CLIENT_IP` | `IPADDR` |
| `_V_TABLE_STORAGE_STAT` | `SIZE_UNCOMPRESSED` | Usar solo `USED_BYTES` y `ALLOCATED_BYTES` |

## Queries y comportamientos de fallback

### Fallback de distribución (`nz_describe_table`)

La fuente primaria es `<BD>.._V_TABLE_DIST_MAP`.

- Si hay filas: construir `HASH(column_1, ..., column_n)` desde `DISTSEQNO` ordenado.
- Si no hay filas: reportar `RANDOM`.

No usar fallback a columnas no documentadas `DISTRIB*`.

### Fallback de lenguaje de procedimiento

`_V_PROCEDURE` no expone `PROCEDURELANGUAGE` en la versión NPS validada.
`nz-mcp` debe emitir `"NZPLSQL"` como lenguaje en respuestas de metadata de procedimientos.

## Comandos no disponibles en NPS 11.2

### `SHOW TABLE`

`SHOW TABLE` no está disponible en el baseline validado NPS `11.2.1.11-IF1`.

Impacto:

- `nz_get_table_ddl` no puede depender de introspección DDL nativa.
- El DDL debe reconstruirse desde vistas de catálogo (`_V_RELATION_COLUMN`,
  `_V_TABLE_DIST_MAP`, `_V_RELATION_KEYDATA` y metadata relacionada).

