# Contrato de Tools — v0.1

> **Este documento es el source of truth del API MCP.** Cualquier cambio requiere ADR + bump de versión.
> Si implementas una tool, su schema y comportamiento **deben** coincidir 1:1 con lo aquí descrito.

## Principio de diseño

**Una tool, una operación.** No existen tools "multitool" que acepten SQL arbitrario de cualquier tipo. Cada tool valida internamente que el SQL recibido sea del tipo esperado.

## Campos de diagnóstico (timing y UX)

- **`duration_ms`**: entero ≥ 0; tiempo de pared en milisegundos para la mayoría de tools de lectura que abren sesión a Netezza (`nz_list_*`, `nz_describe_*`, `nz_get_*_ddl`, `nz_get_procedure_*`, etc.; también `nz_query_select` / `nz_table_sample`).
- **`nz_table_stats`**: `skew_class` (`balanced` \| `moderate` \| `severe`) según umbrales documentados en código; `stats_last_analyzed` desde `_v_statistic` cuando exista fila/columna.
- **`nz_get_procedure_ddl`**: `size_bytes` (UTF-8) del texto devuelto, `truncated` + `hint` cuando el DDL supera `max_bytes` (default ~100 KB), `warning` cuando el texto devuelto supera ~100 KB (solo posible si se sube `max_bytes`). Ver ADR 0018.
- **`nz_list_procedures`**: `max_rows` opcional (default = `max_rows_default` del perfil, cap `MAX_ROWS_CAP` = 1000); `truncated` + `hint` cuando el esquema tiene más procedimientos que `max_rows`. Ver ADR 0018.
- **`nz_get_table_ddl`**: `notes` lista de cadenas i18n; `reconstructed` indica reconstrucción desde catálogo.
- **`nz_export_ddl`**: respuesta MCP con `content` (bloques `EmbeddedResource` `text/sql` + `TextContent` resumen) y `meta` (incluye `resource_uri` `nz-mcp://ddl/...`, `duration_ms`, y campos opcionales alineados con table/view/procedure). Cuando se pasa `output_path`, `meta` añade `output_path`, `bytes_written`, `sha256` del archivo escrito, `preview`, `resource_in_response` y `header_included`; por default el `EmbeddedResource` se **omite** del response y el archivo lleva un header `SET CATALOG <db>;` (ver § 29).
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
| `pattern` | string (optional) | Filtro tipo `LIKE` sobre el nombre. Match case-insensitive (los nombres del catálogo se normalizan a mayúsculas). |

**Output**:
```json
{ "databases": [{"name": "DEV", "owner": "ADMIN"}], "duration_ms": 42 }
```

---

#### 4. `nz_list_schemas`

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | BD a inspeccionar (identificador validado para interpolación `<BD>..`). |
| `pattern` | string (optional) | Filtro tipo `LIKE` sobre el nombre de schema. Match case-insensitive. |

**Output**: `{ "schemas": [{"name": "PUBLIC", "owner": "ADMIN"}], "duration_ms": 35 }`

---

#### 5. `nz_list_tables`

Lista **solo tablas** (no vistas, no procedimientos). Para vistas usar `nz_list_views`, para procedimientos `nz_list_procedures`.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | |
| `schema` | string (required) | |
| `pattern` | string (optional) | Filtro `LIKE` por nombre. Match case-insensitive. |

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
| `pattern` | string (optional) | Filtro `LIKE`. Match case-insensitive. |

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
| `pattern` | string (optional) | Filtro `LIKE` por nombre. Match case-insensitive. |
| `max_rows` | int (optional, 1..1000) | Máximo de procedimientos devueltos. Default = `max_rows_default` del perfil (100); siempre acotado a `MAX_ROWS_CAP` (1000). |

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
  ],
  "truncated": false,
  "hint": null,
  "duration_ms": 42
}
```

- `truncated` — `true` cuando el esquema tiene más procedimientos que `max_rows`; la lista se corta a `max_rows` conservando el orden del catálogo.
- `hint` — i18n (ES/EN) presente solo si `truncated`; indica el total real y cómo llegar al resto (acotar con `pattern` o subir `max_rows`).

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
| `max_bytes` | int (optional, 1024..204800, default 102400) | Tope duro en bytes UTF-8 del `ddl` devuelto. Se corta en frontera de línea. |
| `variant` | `"raw"` \| `"clean"` (default `"raw"`) | `raw` devuelve el source tal como vive en `_v_procedure` (comentarios incluidos). `clean` elimina comentarios de línea (`--`) y de bloque (`/* … */`) fuera de literales de cadena y de identificadores entrecomillados — optimiza tokens para razonamiento IA. Default `raw` preserva back-compat. |

**Output**:
```json
{
  "ddl": "CREATE OR REPLACE PROCEDURE PUBLIC.SP_X(...) ...",
  "size_bytes": 3800,
  "size_bytes_raw": 4200,
  "size_bytes_clean": 3800,
  "warning": null,
  "truncated": false,
  "hint": null,
  "duration_ms": 55
}
```

- `size_bytes` — byte length (UTF-8) del `ddl` **devuelto** (si `truncated=true` es el tamaño del fragmento, no del DDL completo).
- `size_bytes_raw` y `size_bytes_clean` — tamaño del DDL **completo** en ambas variantes, siempre presentes independientemente del `variant`; permiten al cliente decidir la variante y presupuestar tokens antes de cargar el cuerpo.
- `truncated` — `true` cuando el DDL completo supera `max_bytes` y se devolvió solo un prefijo.
- `hint` — i18n (ES/EN) presente solo si `truncated`; remite a `nz_get_procedure_size` y a `nz_get_procedure_section` con `section="range"`, `from_line` y `to_line` concretos (bloques de 500 líneas, numeración de `PROCEDURESOURCE`).
- `warning` — presente si el texto devuelto supera ~100 KB; solo puede ocurrir si el caller sube `max_bytes` por encima del default.

Con `variant="clean"` y DDL por encima del tope, el recorte se calcula sobre el prefijo **raw** para que `from_line` siga siendo válido contra `PROCEDURESOURCE`; el texto devuelto puede quedar por debajo de `max_bytes` (ADR 0018).

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
| `kinds` | array of `"create"` \| `"insert"` \| `"drop"` \| `"truncate"` \| `"update"` \| `"delete"` \| `"merge"` (default `["create", "insert"]`) | Filtra los tipos de statement a incluir. El default mantiene la cobertura v1 (CREATE/INSERT) por back-compat; los cinco verbos extra (`drop`/`truncate`/`update`/`delete`/`merge`) son opt-in y reflejan los mismos writes que cuenta `nz_find_table_references` (issue #120). |

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

- `kind` ∈ `"CREATE TABLE"` | `"CREATE TEMP TABLE"` | `"INSERT INTO"` | `"DROP TABLE"` | `"TRUNCATE TABLE"` | `"UPDATE"` | `"DELETE FROM"` | `"MERGE INTO"`. SQL dinámico (`EXECUTE IMMEDIATE`) sigue **fuera de alcance**.
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
| `pattern` | string (optional) | Filtro `LIKE` sobre el nombre del SP para acotar el escaneo. Match case-insensitive. |

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
| `pattern` | string (optional) | Filtro tipo `LIKE` sobre el nombre. Match case-insensitive. |

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
| `on_conflict` | enum: `error` (default `error`) | Único valor admitido. `skip` se eliminó: Netezza no impone `UNIQUE` ni `PRIMARY KEY`, así que un `INSERT` duplicado nunca falla y no había nada que saltar (ADR 0025). Para insertar solo lo que falta, usa `nz_insert_select` con un anti-join `WHERE NOT EXISTS (...)`. |
| `dry_run` | bool (default **true**) | Valida el `INSERT` sin ejecutarlo; devuelve `would_insert`. |
| `confirm` | bool (**required if** `dry_run=false`) | Debe ser `true` para ejecutar cuando `dry_run=false`. |

**Output** (dry-run `true`): `{ "inserted": 0, "would_insert": N, "dry_run": true, "confirm_required": true, "duration_ms": 0 }`

**Output** (ejecución real): `{ "inserted": N, "duration_ms": T, "dry_run": false }`

Si `dry_run=false` sin `confirm=true` → código estable `CONFIRM_REQUIRED`.

Implementación: una única sentencia parametrizada `INSERT INTO ... (cols) SELECT ? ... UNION ALL SELECT ? ...` (Netezza rechaza las listas `VALUES` multi-fila, issue #133). **Prohibido** construir SQL por concatenación de strings de valores (identificadores validados con el validador de catálogo).

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
| `confirm_full_table` | bool (default false) | Declara que un `WHERE` siempre verdadero (`1=1`, `TRUE`, …) es intencionado y debe afectar a **todas** las filas. |

**Output** (dry-run `true`): `{ "updated": 0, "would_update": N, "dry_run": true, "confirm_required": true, "duration_ms": T }`

**Output** (ejecución real): `{ "updated": N, "duration_ms": T, "dry_run": false }`

**Regla de seguridad**: `sql_guard` rechaza `UPDATE` sin `WHERE` y, salvo
`confirm_full_table: true`, también con un `WHERE` que se pliega a verdadero
(código `WHERE_ALWAYS_TRUE`; alcance exacto y límites en
[`../adr/0020-sql-guard-tautological-where.md`](../adr/0020-sql-guard-tautological-where.md)).

---

#### 22. `nz_delete`

Mismo patrón que `nz_update` con `where` obligatorio, `dry_run` default `true` y
`confirm_full_table` default `false`.

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

Opcionalmente persiste el DDL al filesystem del servidor MCP cuando se pasa `output_path` (ver `docs/adr/0013-export-ddl-output-path.md`). Por **default** el archivo escrito incluye un header `-- Database/Schema/Object/Exported …` seguido de `SET CATALOG <db>;` para que sea auto-contenido y re-ejecutable; el response **omite** el bloque resource para evitar el cap collision (~100 KB) cuando el DDL es grande, y reporta un `preview` con las primeras 10 líneas del archivo. Dos parámetros invierten ese comportamiento si el caller los necesita (issue #129).

| Input | Tipo | Descripción |
|---|---|---|
| `object_type` | enum: `table` \| `view` \| `procedure` (required) | |
| `database` | string (required) | |
| `schema` | string (required) | |
| `name` | string (required) | Nombre de tabla, vista o procedimiento. |
| `signature` | string (optional) | Solo procedimientos: firma/overload. |
| `include_constraints` | bool (default `true`) | Solo tablas: igual que `nz_get_table_ddl`. |
| `output_path` | string (optional) | Path absoluto en el host del MCP server donde escribir el DDL. Política: sin `..`, sin `~`, sin caracteres de control; carpeta padre debe existir; archivo no debe existir salvo `overwrite=true`. En POSIX el archivo se crea con `0600`; en Windows hereda ACL del padre (issue #127). |
| `overwrite` | bool (default `false`) | Si `true`, sobrescribe `output_path` cuando ya existe. |
| `include_resource_in_response` | bool (default `false`) | Sólo aplica cuando `output_path` está presente. Default `false`: el bloque resource se **omite** del response (sólo `TextContent` summary + `meta`) para evitar exceder el cap MCP con DDLs grandes. `true` restablece la forma anterior (resource + path); el caller asume el riesgo de truncamiento. |
| `include_header` | bool (default `true`) | Sólo aplica cuando `output_path` está presente. Default `true`: prepende un header SQL (`-- Database/Schema/Object/Exported …` + `SET CATALOG <db>;`) al archivo para que sea auto-contenido y re-ejecutable. `false` escribe el DDL byte-idéntico al `text` del resource. |

**Output exitoso**: los bloques MCP viajan en `content` (EmbeddedResource del DDL + TextContent de resumen) y `structuredContent` lleva únicamente `meta`, sin re-serializar los bloques (ver [ADR 0019](../adr/0019-sin-output-schema.md)). `meta` contiene los metadatos: `object_type`, `database`, `schema`, `name`, `resource_uri`, `duration_ms`, y según tipo `reconstructed`/`notes`, `size_bytes`/`warning`, etc. Cuando `output_path` se proveyó y la escritura tuvo éxito, `meta` añade:

- `output_path`: ruta absoluta del archivo escrito.
- `bytes_written`: longitud en bytes del payload UTF-8 escrito (incluye el header cuando `include_header=true`).
- `sha256`: digest SHA-256 hexadecimal del archivo en disco. Cuando `include_header=true` cubre header + DDL; cuando `include_header=false` coincide con el digest del `text` del resource. **El archivo es la fuente de verdad** (ADR 0013, revisión 2026-05-08).
- `preview`: primeras 10 líneas del archivo, sólo cuando `include_resource_in_response=false` (default con `output_path`). Indicador bounded para que el LLM razone sobre el contenido sin re-leer el archivo.
- `resource_in_response`: `true` cuando el response incluyó el bloque resource; `false` cuando se omitió. `null` si no se pasó `output_path`.
- `header_included`: `true` cuando el archivo lleva el header SET CATALOG; `false` cuando no. `null` si no se pasó `output_path`.

Si `output_path` no se especifica, los seis campos (`output_path`, `bytes_written`, `sha256`, `preview`, `resource_in_response`, `header_included`) vuelven `null` y el response mantiene la forma original (resource + summary).

**Errores**: cuando `output_path` está presente, las violaciones de policy (`..`, `~`, path relativo, control chars) y de filesystem-state (carpeta inexistente, archivo existente sin `overwrite`) se devuelven con código estable `INVALID_INPUT`; el detalle viaja en `error.context.detail`. La validación de policy ocurre **antes** de consultar Netezza.

**Ejemplo de archivo escrito (con `output_path` y defaults)**:

```sql
-- Database: PROD_ANALITICA
-- Schema:   DBO
-- Object:   procedure DBO.PI_CLIENTESTCM
-- Exported: 2026-05-08T05:30:00Z by uaipscrea1 (nz-mcp v0.1.0a0)
SET CATALOG PROD_ANALITICA;

CREATE OR REPLACE PROCEDURE DBO.PI_CLIENTESTCM(DATE, CHARACTER VARYING(20), BYTEINT)
RETURNS INTEGER
LANGUAGE NZPLSQL AS
…
```

El header sólo contiene metadata segura (BD, schema, objeto, timestamp UTC, nombre del perfil, versión nz-mcp) — nunca host, user, password ni connection string (regla inviolable 1 de `AGENTS.md`, anclado por test adversarial).

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

#### 32. `nz_execute_ddl`

Compila un `CREATE [OR REPLACE] PROCEDURE` (NZPLSQL) **completo** o un `CREATE [OR REPLACE] VIEW` provisto por el caller —inline o leído de `input_path`— contra la base de datos del **perfil activo** (modo `admin`). A diferencia de `nz_clone_procedure` (que reconstruye el DDL desde el catálogo), aquí el DDL lo escribe el usuario. El cuerpo NZPLSQL es opaco para `sql_guard` (se valida por la ruta de cabecera, igual que el clonado). Pensado para mantener SPs/vistas versionados en archivos `.sql` y compilarlos (incluida la nube `nzsaas`). Ver `docs/adr/0014-tool-execute-ddl.md`.

| Input | Tipo | Descripción |
|---|---|---|
| `sql` | string (optional) | DDL inline. Exactamente uno de `sql` / `input_path`. |
| `input_path` | string (optional) | Path absoluto en el host del MCP server. Misma política que `nz_export_ddl.output_path` (sin `..`, sin `~`, sin control chars); el archivo debe existir y pesar ≤ 1 MiB. |
| `statement_type` | enum: `procedure` \| `view` (required) | Debe coincidir con la forma del DDL: `procedure` exige el marcador `LANGUAGE NZPLSQL AS`; `view` exige `CREATE [OR REPLACE] VIEW`. |
| `dry_run` | bool (default **true**) | Si `true`, valida y devuelve `sql_to_execute` sin ejecutar. |
| `confirm` | bool (**required if** `dry_run=false`) | |
| `allow_prod_reads` | bool (default **false**) | Si `true`, **omite solo** la guarda `PROD_REF_IN_NONPROD`. El caller certifica que ya volteó todas las **escrituras** a la BD activa y que los `PROD_*` restantes son **solo lecturas**. Aplica igual en `dry_run` y en compilación real. El resto de validaciones (statement único, cabecera, modo admin, `statement_type`) siguen vigentes. |

**Output**:
```json
{
  "dry_run": true,
  "sql_to_execute": "CREATE OR REPLACE PROCEDURE DBO.PI_X(...) ... LANGUAGE NZPLSQL AS ...",
  "executed": false,
  "duration_ms": 0
}
```

**Reglas**:
- Guarda de entorno (`assert_env_safe`): si la BD del perfil activo **no** empieza con `PROD_`, cualquier identificador `PROD_*` en el SQL → `GUARD_REJECTED` código `PROD_REF_IN_NONPROD`. Evita compilar en desarrollo código que apunta a producción. Es un escaneo conservador (un literal con `PROD_` también dispara; falla cerrado).
- `allow_prod_reads=true` desactiva **únicamente** esa guarda: compilar un `CREATE` es inerte (las escrituras reales solo ocurren en `CALL`), así que el flag relaja el escaneo textual de compilación, no el comportamiento en ejecución. El default `false` conserva el bloqueo (falla cerrado). No se intenta distinguir lecturas de escrituras: el flag es la certificación explícita del caller.
- Todo el SQL pasa por `sql_guard.validate(mode="admin")`; se exige `CREATE`.
- Ejecuta contra la BD del perfil activo (no acepta `database` cross-DB).
- No usar para tablas (`nz_create_table`) ni para ejecutar un procedimiento (`nz_call_procedure`).

---

#### 33. `nz_call_procedure`

Ejecuta un procedimiento almacenado vía `CALL schema.proc(args)` y devuelve el return code + los mensajes `NOTICE`/`RAISE` que emite el SP (modo `admin`). Aplica a on-prem y a la nube `nzsaas`. Ver `docs/adr/0015-sql-guard-call-statement.md`.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | Debe coincidir con la BD del perfil activo. |
| `schema` | string (required) | |
| `procedure` | string (required) | |
| `args` | array de escalares (optional) | `str`/`int`/`float`/`bool`/`null`. Se pasan **parametrizados** (`?`), nunca concatenados. Máx 100. |
| `signature` | string (optional) | Firma de tipos `(TIPO, …)` del overload; si se da, se valida que el nº de args coincida. |
| `dry_run` | bool (default **true**) | Si `true`, devuelve `call_sql` sin ejecutar. |
| `confirm` | bool (**required if** `dry_run=false`) | |
| `timeout_s` | int (optional, 1..300) | Timeout de la conexión efímera; default el del perfil. |

**Output**:
```json
{
  "dry_run": false,
  "call_sql": "CALL DBO.NZMCP_SMOKE_CALL(?)",
  "executed": true,
  "return_value": "50",
  "messages": ["nz-mcp: recibido 5", "nz-mcp: paso 2 ok"],
  "duration_ms": 110
}
```

**Reglas**:
- `sql_guard` clasifica `CALL` (kind `CALL`) y lo permite **solo en `admin`** (rechazo `STATEMENT_NOT_ALLOWED` en read/write). Ruta dedicada de regex que **solo acepta placeholders `?`**: un argumento literal se rechaza (`UNKNOWN_STATEMENT`), forzando parametrización.
- Guarda de entorno `assert_env_safe`: un `CALL` a un SP `PROD_*` desde un perfil no productivo → `PROD_REF_IN_NONPROD`.
- `return_value` es el valor devuelto por el SP (o `null` si no hay result set); `messages` son los `NOTICE`/`RAISE` capturados de `cursor.notices`.
- No usar para crear un SP (`nz_execute_ddl`) ni para leer su DDL (`nz_get_procedure_ddl`).

---

#### 34. `nz_drop_procedure`

Elimina un overload de procedimiento vía `DROP PROCEDURE schema.proc(tipos)` (modo `admin`, `confirm` obligatorio). Netezza desambigua overloads por la **firma de tipos de argumentos**, que es obligatoria. Aplica a on-prem y a la nube `nzsaas`.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | Debe coincidir con la BD del perfil activo. |
| `schema` | string (required) | |
| `procedure` | string (required) | |
| `signature` | string (required) | Lista de **tipos** de argumentos del overload, p. ej. `(DATE, VARCHAR(20))` o `INT4`. Se valida token a token (patrón de tipo) antes de interpolarse; todo el statement pasa por `sql_guard`. |
| `confirm` | bool (**required**, debe ser `true`) | Sin `dry_run`, igual que `nz_drop_table`. |
| `if_exists` | bool (default `true`) | Si `true` y el procedimiento no existe, es un no-op (`dropped=false`). NPS no parsea `IF EXISTS` en `DROP PROCEDURE`, así que se resuelve en la capa Python (chequeo de catálogo). |

**Output**: `{ "dropped": true, "duration_ms": 12 }` — `dropped=false` cuando `if_exists=true` y no existía.

**Reglas**:
- `sql_guard.validate(mode="admin")` clasifica el statement como `DROP`.
- No usar para tablas (`nz_drop_table`) ni para crear/ejecutar procedimientos (`nz_execute_ddl` / `nz_call_procedure`).

---

#### 35. `nz_switch_database`

Cambia la **base de datos de trabajo del perfil activo** reutilizando sus credenciales, para que las tools siguientes resuelvan nombres sin calificar contra ella (p. ej. moverse a `DESA_MAESTROBI` y consultar `DBO.EFE_MC_CREDITOS` sin prefijo de BD). Pensado para un mismo servidor/usuario con muchas BDs, sin pre-crear un perfil por BD. Ver `docs/adr/0016-tool-switch-database.md`.

| Input | Tipo | Descripción |
|---|---|---|
| `database` | string (required) | Nombre de la BD destino. Se valida (`[A-Z][A-Z0-9_]*`) y debe ser **visible** en `_v_database` para el usuario del perfil. |

**Output**: `{ "switched_to": "DESA_MAESTROBI", "previous_database": "DESA_MODELOS", "profile": "nzsaas", "mode": "admin" }`

**Reglas**:
- Actualiza el campo `database` del perfil activo en `profiles.toml` (persiste, como `nz_switch_profile` con `active`). El output da `previous_database` para poder volver.
- **No** cambia `host`/`user`/`mode` (para eso está `nz_switch_profile`); cambiar de BD es benigno (ya se puede leer cualquier BD con `BD..objeto`).
- BD no visible → `OBJECT_NOT_FOUND` con la lista disponible. Cambiar a la misma BD es un no-op (no consulta el catálogo).

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
| `nz_execute_ddl` | false | false | true |
| `nz_call_procedure` | false | **true** | false |
| `nz_truncate`, `nz_drop_table`, `nz_drop_procedure` | false | **true** | true |
| `nz_switch_profile`, `nz_switch_database` | false | false | true |

### Formato de errores

Todas las tools devuelven errores con estructura estable:

```json
{
  "error": {
    "code": "GUARD_REJECTED",
    "message_en": "SELECT tool received a DELETE statement",
    "message_es": "La tool SELECT recibió una sentencia DELETE",
    "hint_en": "Use nz_delete instead",
    "hint_es": "Usa nz_delete en su lugar",
    "context": {}
  }
}
```

`hint_en` / `hint_es` están **siempre presentes** y valen `null` cuando ninguna regla es lo bastante específica: un campo que aparece y desaparece es más difícil de ramificar para un modelo que un `null` (ADR 0023). Un hint genérico ("revisa los argumentos") no se emite nunca. Cuando el error se construye con hints en su `context` (caso de `CONNECTION_FAILED`), el servidor los **promociona** al nivel superior y los quita del `context` para no enviarlos dos veces.

Códigos estables (contrato):
`GUARD_REJECTED`, `PERMISSION_DENIED`, `PROFILE_NOT_FOUND`, `CONNECTION_FAILED`, `QUERY_TIMEOUT`, `RESULT_TOO_LARGE`, `RESPONSE_TOO_LARGE`, `INPUT_TOO_BROAD`, `INVALID_INPUT`, `CONFIRM_REQUIRED`, `NETEZZA_ERROR`, `INTERNAL_ERROR`, `OBJECT_NOT_FOUND`, `SECTION_NOT_FOUND`, `PROCEDURE_ALREADY_EXISTS`, `OVERLOAD_AMBIGUOUS`, `CLONE_VALIDATION_FAILED`.

`INVALID_INPUT` cubre tanto las validaciones de las tools como **todo** `ValidationError` de pydantic al validar los argumentos. En el caso de pydantic el `detail` es un resumen compacto `campo: motivo` separado por `; ` (sin la URL de docs ni el valor de entrada que `str(exc)` incluye), acotado a 5 campos más `(+N more)`. Si faltan argumentos obligatorios el hint los nombra; si sobran argumentos desconocidos y no falta ninguno, nombra los que hay que quitar; en cualquier otro caso el hint es `null`.

`OBJECT_NOT_FOUND` lleva en su `context` `object_type` (`table`, `procedure`, `database`) más las coordenadas del objeto. Cuando el tipo tiene una tool de listado que responde a la pregunta y se conocen `database` y `schema`, el hint remite a ella (`nz_list_tables` / `nz_list_procedures`). `nz_switch_database` no lleva hint: ya devuelve la lista de bases visibles en su propio `detail`.

`NETEZZA_ERROR` clasifica el texto del driver contra una tabla de patrones y adjunta el hint correspondiente (catálogo i18n `NETEZZA_ERROR.HINT.<patrón>`): `MULTI_ROW_VALUES` (Netezza rechaza `VALUES (..),(..)` → usar `nz_insert` o `nz_insert_select`), `RELATION_NOT_FOUND`, `ATTRIBUTE_NOT_FOUND` y `PERMISSION_DENIED`. Un texto no visto antes no recibe hint.

`CONNECTION_FAILED` añade en su `context` un campo `cause` con la causa clasificada del fallo, y publica en `hint_es` / `hint_en` (nivel superior del error) la salida accionable para esa causa (catálogo i18n `CONNECTION_FAILED.HINT.<cause>`). Valores estables de `cause`: `AUTH_REJECTED` (credenciales rechazadas), `DATABASE_UNAVAILABLE` (la BD no existe o no hay permiso), `HOST_UNREACHABLE` (host o puerto sin respuesta), `TLS_FAILED` (fallo de negociación TLS) y `UNKNOWN` (sin clasificar). El `detail` sigue siendo el texto del driver, ahora enriquecido con el diagnóstico que nzpy solo escribía en su logger.

### Descripciones de tool (lo que ve la IA)

- En **inglés**, imperativo, < 200 caracteres.
- Estructura: `"<verbo> <objeto>. <cuándo usar>. <cuándo NO usar>."`
- Ejemplo: `"Execute a SELECT query against Netezza. Use for data retrieval. Do not use for INSERT/UPDATE/DELETE — use the dedicated tools instead."`

Ver [`../roles/dx-engineer.md`](../roles/dx-engineer.md) para guía completa.
