# Contrato de Tools — v0.1

> **Este documento es el source of truth del API MCP.** Cualquier cambio requiere ADR + bump de versión.
> Si implementas una tool, su schema y comportamiento **deben** coincidir 1:1 con lo aquí descrito.

## Principio de diseño

**Una tool, una operación.** No existen tools "multitool" que acepten SQL arbitrario de cualquier tipo. Cada tool valida internamente que el SQL recibido sea del tipo esperado.

## Campos de diagnóstico (timing y UX)

- **`duration_ms`**: entero ≥ 0; tiempo de pared en milisegundos para la mayoría de tools de lectura que abren sesión a Netezza (`nz_list_*`, `nz_describe_*`, `nz_get_*_ddl`, `nz_get_procedure_*`, etc.; también `nz_query_select` / `nz_table_sample`).
- **`nz_table_stats`**: `skew_class` (`balanced` \| `moderate` \| `severe`) según umbrales documentados en código; `stats_last_analyzed` desde `_v_statistic` cuando exista fila/columna.
- **`nz_get_procedure_ddl`**: `size_bytes` (UTF-8), `warning` si el DDL supera ~100 KB (sin truncar).
- **`nz_get_table_ddl`**: `notes` lista de cadenas i18n; `reconstructed` indica reconstrucción desde catálogo.
- **`nz_export_ddl`**: respuesta MCP con `content` (bloques `EmbeddedResource` `text/sql` + `TextContent` resumen) y `meta` (incluye `resource_uri` `nz-mcp://ddl/...`, `duration_ms`, y campos opcionales alineados con table/view/procedure).
- **CLI**: `nz-mcp edit-profile` actualiza campos de un perfil existente (sin password).

## Modos de permiso (recordatorio)

Cada tool declara el `mode` mínimo que requiere. El perfil activo define el `mode` otorgado. Si el perfil no alcanza, la tool falla con `PermissionDeniedError`.

| Modo otorgado al perfil | Tools permitidas |
|---|---|
| `read` | solo `read` |
| `write` | `read` + `write` |
| `admin` | `read` + `write` + `ddl` |

## Catálogo v0.1 (31 tools registradas)

> Si quieres añadir una tool nueva, lee primero [`../standards/maintainability.md`](../standards/maintainability.md) y abre un ADR. El catálogo está congelado para v0.1.

### 🔵 Lectura (`mode: read`)

#### 1. `nz_query_select`

Ejecuta una query `SELECT` validada por `sql_guard` contra el perfil activo.

| Input | Tipo | Descripción |
|---|---|---|
| `sql` | string (required) | Query SQL. Debe ser `SELECT` o `WITH ... SELECT`. |
| `max_rows` | int (default: perfil, cap 1000) | Número máximo de filas. Se inyecta como `LIMIT` si no está presente. |
| `timeout_s` | int (default: perfil, cap 300) | Timeout de ejecución. |

**Output**:
```json
{
  "columns": [{"name": "col", "type": "varchar"}],
  "rows": [["v1", "v2"]],
  "row_count": 100,
  "truncated": false,
  "duration_ms": 243,
  "hint": null
}
```

**Errores**: `GuardRejectedError`, `QueryTimeoutError`, `ConnectionError`, `ResultTooLargeError`.

---

#### 2. `nz_explain`

Devuelve el plan de ejecución de una query sin ejecutarla.

| Input | Tipo | Descripción |
|---|---|---|
| `sql` | string (required) | Sentencia a analizar (`SELECT` / `WITH … SELECT`, o `SHOW …` cuando el dialecto la parsea como comando de solo lectura). |
| `verbose` | bool (default: false) | `EXPLAIN VERBOSE` vs `EXPLAIN`. |

**Output**: `{ "plan": "...texto del plan..." }`

---

#### 3. `nz_list_databases`

Lista bases de datos visibles para el usuario del perfil.

| Input | Tipo | Descripción |
|---|---|---|
| `pattern` | string (optional) | Filtro tipo `LIKE` sobre el nombre. |

**Output**:
```json
{ "databases": [{"name": "DEV", "owner": "ADMIN"}], "duration_ms": 42 }
```

---

#### 4. `nz_list_schemas`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | BD a inspeccionar (identificador validado para interpolación `<BD>..`). |
| `pattern` | string (optional) | Filtro tipo `LIKE` sobre el nombre de schema. |

**Output**: `{ "schemas": [{"name": "PUBLIC", "owner": "ADMIN"}], "duration_ms": 35 }`

---

#### 5. `nz_list_tables`

Lista **solo tablas** (no vistas, no procedimientos). Para vistas usar `nz_list_views`, para procedimientos `nz_list_procedures`.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `pattern` | string (optional) | Filtro `LIKE` por nombre. |

**Output** (solo `name` y `kind`; el conteo de filas va en `nz_table_stats`):

```json
{
  "tables": [
    {"name": "CUSTOMERS", "kind": "TABLE"}
  ],
  "duration_ms": 28
}
```

---

#### 6. `nz_describe_table`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |

**Output**:
```json
{
  "name": "CUSTOMERS",
  "kind": "TABLE",
  "columns": [
    {"name": "ID", "type": "INTEGER", "nullable": false, "default": null}
  ],
  "distribution": {"type": "HASH", "columns": ["ID"]},
  "organized_on": [],
  "primary_key": ["ID"],
  "foreign_keys": [],
  "duration_ms": 2100
}
```

---

#### 7. `nz_table_sample`

Devuelve una muestra pequeña (10 filas) para entender el shape. El `database` del input **debe coincidir** con el de la conexión del perfil activo (muestreo vía `SELECT` en la sesión).

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | Debe ser el de la conexión del perfil. |
| `schema` | string (required) | |
| `table` | string (required) | |
| `rows` | int (default 10, cap 50) | |

**Output**: mismo formato que `nz_query_select` (incl. `columns`, `rows`, `row_count`, `truncated`, `duration_ms`, `hint`).

---

#### 8. `nz_table_stats`

Estadísticas agregadas desde `_V_TABLE` y `_V_TABLE_STORAGE_STAT` (reltuples, bytes almacenados, skew, creación).

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |

**Output**:
```json
{
  "row_count": 1200000,
  "size_bytes_used": 600000000,
  "size_used_human": "572.2 MiB",
  "size_bytes_allocated": 800000000,
  "size_allocated_human": "762.9 MiB",
  "skew": 1.02,
  "skew_class": "moderate",
  "stats_last_analyzed": "2024-03-12T10:00:00+00:00",
  "table_created": "2025-01-10T00:00:00+00:00",
  "duration_ms": 4000
}
```

---

#### 9. `nz_get_table_ddl`

Devuelve el DDL `CREATE TABLE` reconstruido (columnas, tipos, distribución, constraints opcionales). **No** usa `SHOW TABLE` en el servidor: se arman claves y metadatos desde catálogos.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |
| `include_constraints` | bool (default: true) | Incluir PK/FK. |

**Output**:
```json
{
  "ddl": "CREATE TABLE PUBLIC.CUSTOMERS (\n  ID INTEGER NOT NULL,\n  ...\n)\nDISTRIBUTE ON HASH (ID);",
  "reconstructed": true,
  "notes": ["…", "…", "…"],
  "duration_ms": 120
}
```

Implementación: reconstruir desde `_v_relation_column` + `_v_table_dist_map` + `_v_relation_keydata` (misma base que `nz_describe_table`).

---

#### 10. `nz_list_views`

Lista vistas (solo vistas) en un schema.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `pattern` | string (optional) | Filtro `LIKE`. |

**Output**:
```json
{
  "views": [{"name": "VW_ACTIVE_CUSTOMERS", "owner": "ADMIN"}],
  "duration_ms": 31
}
```

Source: `_v_view`.

---

#### 11. `nz_get_view_ddl`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `view` | string (required) | |

**Output**:
```json
{
  "ddl": "CREATE VIEW PUBLIC.VW_X AS SELECT ... FROM ...",
  "duration_ms": 55
}
```

Source: `SELECT DEFINITION FROM _V_VIEW WHERE ...`.

---

#### 12. `nz_list_procedures`

Lista procedimientos almacenados.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `pattern` | string (optional) | |

**Output**:
```json
{
  "procedures": [
    {
      "name": "SP_LOAD_CUSTOMERS",
      "owner": "ADMIN",
      "language": "NZPLSQL",
      "arguments": "(VARCHAR, INTEGER)",
      "returns": "INTEGER"
    }
  ]
}
```

Source: `_v_procedure`.

---

#### 13. `nz_describe_procedure`

Metadata de un SP sin devolver el cuerpo completo.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `procedure` | string (required) | |
| `signature` | string (optional) | Si hay overloads, firma exacta tipo `(VARCHAR, INTEGER)`. |

**Output**:
```json
{
  "name": "SP_LOAD_CUSTOMERS",
  "owner": "ADMIN",
  "language": "NZPLSQL",
  "arguments": [{"name": "p_source", "type": "VARCHAR"}],
  "returns": "INTEGER",
  "created_at": "2025-08-12T...",
  "lines": 247,
  "sections_detected": ["header", "declare", "body", "exception"]
}
```

---

#### 14. `nz_get_procedure_size`

Extrae las métricas de tamaño (bytes y líneas, en sus variantes `raw` y `clean`) y detecta las secciones lógicas de un SP sin retornar su cuerpo completo. Ideal para token budgeting previo a descargar DDLs gigantes.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `procedure` | string (required) | |
| `signature` | string (optional) | |

**Output**:
```json
{
  "name": "SP_LOAD_CUSTOMERS",
  "signature": "SP_LOAD_CUSTOMERS(VARCHAR)",
  "size_bytes_raw": 4200,
  "size_bytes_clean": 3800,
  "lines_raw": 247,
  "lines_clean": 210,
  "sections_detected": ["header", "declare", "body", "exception"],
  "duration_ms": 15
}
```

---

#### 15. `nz_get_procedure_ddl`

Devuelve el DDL completo (`CREATE OR REPLACE PROCEDURE ...`).

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `procedure` | string (required) | |
| `signature` | string (optional) | Para overloads. |
| `variant` | `"raw"` \| `"clean"` (default `"raw"`) | `raw` devuelve el source tal como vive en `_v_procedure` (comentarios incluidos). `clean` elimina comentarios de línea (`--`) y de bloque (`/* … */`) fuera de literales de cadena y de identificadores entrecomillados — optimiza tokens para razonamiento IA. Default `raw` preserva back-compat. |

**Output**:
```json
{
  "ddl": "CREATE OR REPLACE PROCEDURE PUBLIC.SP_X(...) ...",
  "size_bytes": 3800,
  "size_bytes_raw": 4200,
  "size_bytes_clean": 3800,
  "warning": null,
  "duration_ms": 55
}
```

- `size_bytes` — byte length (UTF-8) del `ddl` devuelto (= `size_bytes_raw` si `variant="raw"`, = `size_bytes_clean` si `variant="clean"`).
- `size_bytes_raw` y `size_bytes_clean` — siempre presentes en toda llamada, independientemente del `variant`; permiten al cliente decidir la variante antes de cargar el cuerpo completo.
- `warning` — presente si `size_bytes` > ~100 KB; sugiere usar `nz_get_procedure_section`.

Source: `_v_procedure.PROCEDURESOURCE` + `PROCEDURESIGNATURE`.

---

#### 16. `nz_get_procedure_section`

Extrae una sección específica de un SP (útil para evitar gastar tokens en SPs largos).

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `procedure` | string (required) | |
| `signature` | string (optional) | |
| `section` | enum: `header` \| `declare` \| `body` \| `exception` \| `range` (required) | |
| `from_line` | int (required if `section: range`) | 1-indexed. |
| `to_line` | int (required if `section: range`) | inclusive, cap 500 líneas. |

**Output**:
```json
{
  "section": "body",
  "from_line": 12,
  "to_line": 198,
  "content": "BEGIN ... END;",
  "truncated": false
}
```

Implementación: parser ligero NZPLSQL en `catalog/procedures.py` (basado en marcadores `BEGIN_PROC`, `DECLARE`, `BEGIN`, `EXCEPTION`, `END`). Si la sección pedida no existe → `SECTION_NOT_FOUND`.

---

#### 17. `nz_get_procedure_table_logic`

Aísla la lógica de **una** tabla intermedia dentro de un SP: devuelve los `CREATE [TEMP] TABLE … AS …` y/o `INSERT INTO …` que la producen o pueblan, ya con comentarios stripped y terminados en `;`. Útil para responder *"¿cómo se calcula `TT_X`?"* sin pagar tokens por las otras tablas del SP.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `procedure` | string (required) | |
| `signature` | string (optional) | Para overloads. |
| `table` | string (required) | Nombre simple de la tabla (case-insensitive). No se aceptan `schema.table` — la lógica es interna al SP. |
| `kinds` | array of `"create"` \| `"insert"` (default `["create", "insert"]`) | Filtra los tipos de statement a incluir. |

**Output**:
```json
{
  "table": "TT_OBLIGACIONESCLIENTES",
  "statements": [
    {
      "kind": "CREATE TEMP TABLE",
      "sql": "CREATE TEMP TABLE TT_OBLIGACIONESCLIENTES AS SELECT ...;",
      "line_start": 142,
      "line_end": 168,
      "size_bytes": 812
    }
  ],
  "count": 1,
  "not_found": false,
  "duration_ms": 12
}
```

- `kind` ∈ `"CREATE TABLE"` | `"CREATE TEMP TABLE"` | `"INSERT INTO"`. `MERGE`, `UPDATE`, `DELETE`, `TRUNCATE` y SQL dinámico están **fuera de alcance** en v1.
- `sql` viene sin comentarios (`--`, `/* */`); strings (`'a;b'`) e identificadores entre comillas (`"a;b"`) se preservan.
- `line_start` / `line_end` apuntan al cuerpo **crudo** original (con comentarios) para auditoría.
- Si la tabla solo aparece como `FROM`/`JOIN` y nunca como target → `count = 0`, `not_found = true`. Para análisis inverso usar la tool de referencias.
- Cap total de respuesta: 200 KB → `RESPONSE_TOO_LARGE` (sugiere filtrar por `kinds` o usar `nz_get_procedure_section`).

Implementación: `iter_statements` (boundary `;` consciente de strings y comentarios) + `extract_create_or_insert_targeting` en `catalog/nzplsql_parser.py`, reutilizando `strip_comments` (#105). Ver [`../adr/0011-tool-procedure-table-logic.md`](../adr/0011-tool-procedure-table-logic.md).

---

#### 18. `nz_find_table_references`

Análisis **inverso** de impacto: dado `(database, schema, table)`, devuelve los SPs del schema que **leen** o **escriben** esa tabla, con cuentas separadas. Para responder *"¿quién toca `T_X`?"* sin descargar todos los DDL del schema. Para análisis **directo** dentro de un único SP (cómo se construye `T_X` ahí dentro) usar `nz_get_procedure_table_logic`.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | BD donde están los SPs a escanear. |
| `schema` | string (required) | Schema a escanear (sin recursividad). |
| `table` | string (required) | Nombre de la tabla a buscar (case-insensitive). |
| `table_database` | string (optional) | Filtra referencias prefijadas con esta BD; si se omite, acepta cualquier BD o sin prefijo. |
| `table_schema` | string (optional) | Análogo a `table_database`. |
| `pattern` | string (optional) | Filtro `LIKE` sobre el nombre del SP para acotar el escaneo. |

**Output**:
```json
{
  "references": [
    {
      "procedure_name": "PI_DEUDAINGRESOS",
      "signature": "PI_DEUDAINGRESOS(DATE)",
      "usage": "both",
      "occurrences_read": 3,
      "occurrences_write": 1,
      "last_altered": "2026-04-20 09:15:00"
    }
  ],
  "scanned_count": 142,
  "match_count": 1,
  "truncated": false,
  "duration_ms": 820
}
```

- `usage` ∈ `"read"` | `"write"` | `"both"`. `both` cuando el mismo SP tiene ambas operaciones contra la tabla.
- **Detección read**: `FROM <tabla>`, `JOIN <tabla>` (incluye `LEFT`/`RIGHT`/`INNER`/`FULL`/`CROSS` y opcional `OUTER`), `USING (<tabla>)`.
- **Detección write**: `INSERT INTO <tabla>`, `UPDATE <tabla>`, `DELETE FROM <tabla>`, `MERGE INTO <tabla>`, `TRUNCATE TABLE <tabla>`, `DROP TABLE [IF EXISTS] <tabla>`, `CREATE [TEMP|TEMPORARY] TABLE [IF NOT EXISTS] <tabla>` (CTAS estándar), y `... INTO <tabla>` (cubre `SELECT INTO`).
- Match case-insensitive sobre el nombre, con respeto de límites de token (`Foo` no engancha `FooBar`). Acepta `tabla`, `schema.tabla`, `bd.schema.tabla` y la sintaxis Netezza `bd..tabla`.
- Comentarios (`--`, `/* */`) y literales `'…'` se filtran antes del scan.
- **Caps**:
  - Hard cap: `scanned_count <= 5000`. Si el `pattern` no acota suficiente → `INPUT_TOO_BROAD` con sugerencia de usar `pattern`.
  - Soft cap: `references` truncadas a 1000 entradas, ordenadas desc por `occurrences_read + occurrences_write` (desempate por nombre); en ese caso `truncated: true`.
  - Timeout default: 60 s.
- **Out of scope v1**: vistas (`_v_view.DEFINITION`), dynamic SQL (`EXECUTE IMMEDIATE 'INSERT INTO ' || …`), análisis de columnas, cross-schema/cross-database, exportación a archivo. Documentado en [`../adr/0012-tool-find-table-references.md`](../adr/0012-tool-find-table-references.md).

Implementación: una sola query a `_v_procedure` (mismo helper que `nz_get_procedures_ddl_batch`), seguida de `iter_statements` + `iter_table_references_in_statement` en `catalog/nzplsql_parser.py`.

---

#### 19. `nz_get_procedures_ddl_batch`

Obtiene los DDL completos de todos los procedimientos almacenados de un schema en un solo paso. Útil para indexación masiva sin ejecutar cientos de queries individuales.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `pattern` | string (optional) | Filtro tipo `LIKE` sobre el nombre. |

**Output**:
```json
{
  "procedures": [
    {
      "name": "SP_CALCULAR_SALDO",
      "owner": "ADMIN",
      "arguments": "(P_CUENTA INTEGER, P_FECHA DATE)",
      "returns": "INTEGER",
      "ddl": "CREATE OR REPLACE PROCEDURE ...",
      "signature": "SP_CALCULAR_SALDO(INTEGER, DATE)",
      "last_altered": "2026-04-15 10:30:00",
      "size_bytes": 4523
    }
  ],
  "count": 1,
  "total_size_bytes": 4523,
  "warning": null,
  "duration_ms": 1250
}
```

Implementación: usa una sola query al catálogo `_V_PROCEDURE` por schema. Emite warning si un DDL supera ~100 KB o si el total supera ~1 MB, pero no trunca.

---

### 🟡 Escritura (`mode: write`)

> Todas requieren `NZ_ALLOW_WRITE=true` implícito por `mode: write` o superior en el perfil.

#### 20. `nz_insert`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |
| `rows` | array of objects (required) | Cada objeto es `{columna: valor}`. |
| `on_conflict` | enum: `error` \| `skip` (default `error`) | |
| `dry_run` | bool (default **true**) | Valida el `INSERT` sin ejecutarlo; devuelve `would_insert`. |
| `confirm` | bool (**required if** `dry_run=false`) | Debe ser `true` para ejecutar cuando `dry_run=false`. |

**Output** (dry-run `true`): `{ "inserted": 0, "would_insert": N, "dry_run": true, "confirm_required": true, "duration_ms": 0 }`

**Output** (ejecución real): `{ "inserted": N, "duration_ms": T, "dry_run": false }`

Si `dry_run=false` sin `confirm=true` → código estable `CONFIRM_REQUIRED`.

Implementación: `INSERT INTO ... VALUES (...)` parametrizado. **Prohibido** construir SQL por concatenación de strings de valores (identificadores validados con el validador de catálogo).

---

#### 21. `nz_update`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |
| `set` | object (required) | Pares columna→valor a setear. |
| `where` | string (required) | Predicado WHERE. **No vacío**. |
| `dry_run` | bool (default true) | Ejecuta `SELECT COUNT(*) WHERE ...` primero y pide `confirm: true` para aplicar. |
| `confirm` | bool (default false) | Requerido si `dry_run: false`. |

**Output** (dry-run `true`): `{ "updated": 0, "would_update": N, "dry_run": true, "confirm_required": true, "duration_ms": T }`

**Output** (ejecución real): `{ "updated": N, "duration_ms": T, "dry_run": false }`

**Regla de seguridad**: `sql_guard` rechaza `UPDATE` sin `WHERE`.

---

#### 22. `nz_delete`

Mismo patrón que `nz_update` con `where` obligatorio, `dry_run` default `true`.

**Output** (dry-run `true`): `{ "deleted": 0, "would_delete": N, "dry_run": true, "confirm_required": true, "duration_ms": T }`

**Output** (ejecución real): `{ "deleted": N, "duration_ms": T, "dry_run": false }`

Si `dry_run=false` sin `confirm=true` → código estable `CONFIRM_REQUIRED`.

---

### 🔴 DDL (`mode: admin`)

#### 23. `nz_create_table`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |
| `columns` | array (required) | `{name, type, nullable, default}` |
| `distribution` | object (optional) | `{type: HASH\|RANDOM, columns: [...]}` |
| `organized_on` | array (optional) | |
| `if_not_exists` | bool (default true) | |
| `dry_run` | bool (default **true**) | Si `true`, solo devuelve el DDL que se ejecutaría. |
| `confirm` | bool (**required if** `dry_run=false`) | Debe ser `true` para ejecutar cuando `dry_run=false`. |

**Output** (dry-run `true`): `{ "dry_run": true, "ddl_to_execute": "...", "executed": false, "duration_ms": 0 }`

**Output** (ejecución real): `{ "dry_run": false, "ddl_to_execute": "...", "executed": true, "duration_ms": T }`

Si `dry_run=false` sin `confirm=true` → código estable `CONFIRM_REQUIRED`.

---

#### 24. `nz_truncate`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |
| `confirm` | bool (**required**, no default) | Debe venir `true` explícitamente. |

**Output**: `{ "truncated": true, "duration_ms": T }`

---

#### 25. `nz_drop_table`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `table` | string (required) | |
| `confirm` | bool (**required**, no default) | |
| `if_exists` | bool (default true) | Emite sintaxis Netezza ``DROP TABLE schema.table IF EXISTS`` (sufijo). |

**Output**: `{ "dropped": true }`

---

#### 26. `nz_clone_procedure`

Clona un procedimiento almacenado de un origen a un destino (otro database/schema o renombrado).

| Input | Tipo | Descripción |
|---|---|---|
| `source_database` | string (required) | |
| `source_schema` | string (required) | |
| `source_procedure` | string (required) | |
| `source_signature` | string (optional) | Para overloads. |
| `target_database` | string (required) | Puede coincidir con `source_database`. |
| `target_schema` | string (required) | |
| `target_procedure` | string (optional) | Si se omite, conserva nombre del origen. |
| `replace_if_exists` | bool (default false) | Si `true`, emite `CREATE OR REPLACE`. |
| `transformations` | array (optional) | Reemplazos sobre el cuerpo: `[{from, to, regex: bool}]`. Limitado a < 20. |
| `dry_run` | bool (default true) | Si `true`, solo devuelve el DDL final que se ejecutaría. |
| `confirm` | bool (**required if** `dry_run=false`) | |

**Output**:
```json
{
  "dry_run": true,
  "ddl_to_execute": "CREATE OR REPLACE PROCEDURE TARGET_DB.PUBLIC.SP_X(...) ...",
  "executed": false,
  "warnings": ["body references TABLE SOURCE_DB.PUBLIC.X — verify it exists in target"]
}
```

**Reglas**:
- Si `target_database == source_database` y `target_procedure` igual → debe `replace_if_exists=true` o falla con `PROCEDURE_ALREADY_EXISTS`.
- Detección heurística de referencias cross-DB (warnings, no bloqueo).
- Toda transformación textual se aplica al **body**, nunca al header firmado.
- Auditoría: log estructurado con `source_*`, `target_*`, `ddl_hash`.

---

### ⚪ Sesión

#### 27. `nz_current_profile`

Sin inputs.

**Output**:
```json
{
  "profile": "prod",
  "mode": "read",
  "host": "nz.example.com",
  "database_default": "DEV",
  "user": "svc_claude",
  "available_profiles": ["dev", "prod"]
}
```

No incluye password ni secretos.

---

#### 28. `nz_switch_profile`

| Input | Tipo | Descripción |
|---|---|---|
| `profile` | string (required) | Nombre del perfil definido en `profiles.toml`. |

**Output**: `{ "switched_to": "dev", "mode": "read" }` — también persiste `active = …` en `profiles.toml` para procesos nuevos.

**Errores**: si el perfil no existe, `PROFILE_NOT_FOUND` con `context.available_profiles` (y mensajes i18n con la lista).

**Regla crítica**: cambiar de perfil **nunca** eleva el `mode` por encima del configurado en `profiles.toml`. La IA no puede subir privilegios; solo puede moverse entre perfiles preconfigurados por el humano.

---

#### 29. `nz_export_ddl`

Unifica la obtención de DDL de **tabla**, **vista** o **procedimiento** y lo devuelve como **resultado MCP nativo**: bloque **resource** embebido (`mimeType: text/sql`, URI estable `nz-mcp://ddl/...`) más un bloque **text** con resumen. Pensado para clientes que muestran tarjeta de recurso / copia (p. ej. Claude Desktop). Delega en la misma lógica de catálogo que `nz_get_*_ddl`.

| Input | Tipo | Descripción |
|---|---|---|
| `object_type` | enum: `table` \| `view` \| `procedure` (required) | |
| `database` | string (required) | |
| `schema` | string (required) | |
| `name` | string (required) | Nombre de tabla, vista o procedimiento. |
| `signature` | string (optional) | Solo procedimientos: firma/overload. |
| `include_constraints` | bool (default `true`) | Solo tablas: igual que `nz_get_table_ddl`. |

**Output exitoso** (`structuredContent`): objeto con `content` (array de bloques MCP serializados) y `meta` (metadatos: `object_type`, `database`, `schema`, `name`, `resource_uri`, `duration_ms`, y según tipo `reconstructed`/`notes`, `size_bytes`/`warning`, etc.).

**Transporte MCP**: el servidor puede devolver `CallToolResult` con los bloques tipados en `content` (no solo JSON plano).

---

#### 30. `nz_insert_select`

`INSERT INTO schema.target [(columns)] SELECT ...` — copia masiva o multi-fila vía `UNION ALL`. El sub-`select_sql` se valida con `sql_guard` en modo `write` (solo `SELECT`); los literales van en el texto del SELECT (no parametrizados).

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `target_schema` | string (required) | |
| `target_table` | string (required) | |
| `target_columns` | array of string (optional) | Si se omite, el orden de columnas sigue la proyección del SELECT. |
| `select_sql` | string (required, max 65536) | Cuerpo `SELECT` (puede incluir `UNION ALL`). |
| `dry_run` | bool (default **true**) | Si `true`, no ejecuta; devuelve `sql_to_execute`. |
| `estimate_rows` | bool (default **false**) | Si `true` y `dry_run=true`, ejecuta `COUNT(*)` sobre el subquery (puede ser costoso). |
| `confirm` | bool (**required if** `dry_run=false`) | |

**Output (dry-run)**: `dry_run`, `sql_to_execute`, `would_insert` (solo si `estimate_rows`), `executed: false`, `duration_ms`, `warnings`, `confirm_required` cuando aplica.

**Output (ejecución)**: `dry_run: false`, `executed: true`, `inserted`, `duration_ms`, `warnings`.

---

#### 31. `nz_create_table_as`

`CREATE TABLE schema.target AS SELECT ...` con `DISTRIBUTE ON` / `ORGANIZE ON` (modo `admin`). Rechaza si el destino ya existe (catálogo). El `select_sql` se valida como `SELECT`; el núcleo `CREATE TABLE ... AS` se valida con `sql_guard`; los sufijos Netezza se añaden como plantillas con identificadores validados (igual que `nz_create_table`).

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `target_schema` | string (required) | |
| `target_table` | string (required) | No debe existir. |
| `select_sql` | string (required, max 65536) | |
| `distribution` | object (optional) | `{type: HASH\|RANDOM, columns: [...]}`; default `RANDOM`. |
| `organized_on` | array (optional) | |
| `dry_run` | bool (default **true**) | |
| `estimate_rows` | bool (default **false**) | Si `true` y `dry_run=true`, ejecuta `COUNT(*)` del subquery (puede ser costoso). |
| `confirm` | bool (**required if** `dry_run=false`) | |

**Output (dry-run)**: `dry_run`, `ddl_to_execute`, `would_create_rows` (solo si `estimate_rows`), `executed: false`, `duration_ms`.

**Output (ejecución)**: `dry_run: false`, `ddl_to_execute`, `executed: true`, `duration_ms`.

---

## Convenciones comunes

### Tool annotations (MCP)

Cada tool declara `annotations` para que el cliente MCP muestre diálogos adecuados:

| Tool | `readOnlyHint` | `destructiveHint` | `idempotentHint` |
|---|---|---|---|
| `nz_query_select`, `nz_explain`, `nz_list_*`, `nz_describe_*`, `nz_table_sample`, `nz_table_stats`, `nz_get_table_ddl`, `nz_get_view_ddl`, `nz_get_procedure_ddl`, `nz_get_procedure_section`, `nz_get_procedure_size`, `nz_get_procedure_table_logic`, `nz_get_procedures_ddl_batch`, `nz_find_table_references`, `nz_export_ddl`, `nz_current_profile` | true | false | true |
| `nz_insert` | false | false | false |
| `nz_insert_select` | false | false | false |
| `nz_update`, `nz_delete` | false | true | false |
| `nz_create_table` | false | false | true |
| `nz_create_table_as` | false | false | false |
| `nz_clone_procedure` | false | false | true |
| `nz_truncate`, `nz_drop_table` | false | **true** | true |
| `nz_switch_profile` | false | false | true |

### Formato de errores

Todas las tools devuelven errores con estructura estable:

```json
{
  "error": {
    "code": "GUARD_REJECTED",
    "message_en": "SELECT tool received a DELETE statement",
    "message_es": "La tool SELECT recibió una sentencia DELETE",
    "hint_en": "Use nz_delete instead",
    "hint_es": "Usa nz_delete en su lugar"
  }
}
```

Códigos estables (contrato):
`GUARD_REJECTED`, `PERMISSION_DENIED`, `PROFILE_NOT_FOUND`, `CONNECTION_FAILED`, `QUERY_TIMEOUT`, `RESULT_TOO_LARGE`, `RESPONSE_TOO_LARGE`, `INPUT_TOO_BROAD`, `INVALID_INPUT`, `CONFIRM_REQUIRED`, `NETEZZA_ERROR`, `INTERNAL_ERROR`, `OBJECT_NOT_FOUND`, `SECTION_NOT_FOUND`, `PROCEDURE_ALREADY_EXISTS`, `OVERLOAD_AMBIGUOUS`, `CLONE_VALIDATION_FAILED`.

### Descripciones de tool (lo que ve la IA)

- En **inglés**, imperativo, < 200 caracteres.
- Estructura: `"<verbo> <objeto>. <cuándo usar>. <cuándo NO usar>."`
- Ejemplo: `"Execute a SELECT query against Netezza. Use for data retrieval. Do not use for INSERT/UPDATE/DELETE — use the dedicated tools instead."`

Ver [`../roles/dx-engineer.md`](../roles/dx-engineer.md) para guía completa.
