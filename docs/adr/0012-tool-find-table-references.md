# 12. Análisis de impacto inverso — `nz_find_table_references`

Date: 2026-05-06

## Status

Accepted

## Context

Antes de tocar una tabla en Netezza necesitamos saber qué stored procedures la leen o escriben. Hoy el análisis se resuelve descargando todos los DDL de un schema con `nz_get_procedures_ddl_batch` y haciendo `grep` en cliente, lo que:

1. Trae **todo** el cuerpo de **todos** los SPs del schema, aunque la mayoría no referencien la tabla.
2. No distingue lectura (`FROM`/`JOIN`/`USING`) de escritura (`INSERT INTO`/`UPDATE`/`DELETE`/`MERGE`/`TRUNCATE`/`DROP`/CTAS).
3. Genera falsos positivos en comentarios y literales de cadena.

`nz_get_procedure_table_logic` (ADR 0011) cubre el problema **directo** — cómo se construye una tabla intermedia dentro de **un** SP. Aquí necesitamos el **inverso**: dado `(database, schema, table)`, qué SPs del schema la referencian, clasificadas como lectura o escritura.

## Decision

Crear una tool nueva `nz_find_table_references` (modo `read`, responsabilidad única) que:

1. Reusa `get_all_procedures_ddl` para obtener todos los SPs del schema en una sola query (precedente `nz_get_procedures_ddl_batch`, ADR 0009).
2. Aplica un filtro `LIKE` opcional sobre el nombre del SP en el catálogo (no en cliente) para acotar antes de escanear.
3. Para cada SP, escanea el cuerpo statement-por-statement con `iter_statements` (ADR 0011) y, sobre cada statement con comentarios stripped, llama a un nuevo helper `iter_table_references_in_statement` que clasifica cada ocurrencia en `read` / `write`.
4. Devuelve por SP: `procedure_name`, `signature`, `usage` (`read` / `write` / `both`), `occurrences_read`, `occurrences_write`, `last_altered`. La lista global sale ordenada descendente por `occurrences_read + occurrences_write` y por `procedure_name` como desempate determinista.

### Heurística read vs write

- **read**: tabla precedida por `FROM`, `JOIN` (con variantes `LEFT`/`RIGHT`/`INNER`/`FULL`/`CROSS` y opcional `OUTER`), o `USING (`.
- **write**: tabla precedida por `INSERT INTO`, `UPDATE`, `DELETE FROM`, `MERGE INTO`, `TRUNCATE TABLE`, `DROP TABLE` (opcional `IF EXISTS`), o `INTO` (cubre `CREATE TABLE … AS SELECT … INTO <table>` y `SELECT … INTO <table>`).
- Match case-insensitive sobre el nombre, con respeto de límites de token (`Foo` no engancha `FooBar`).
- Acepta tres formas: `tabla`, `schema.tabla`, `bd.schema.tabla`, además de la sintaxis Netezza `bd..tabla` (segmento medio vacío).
- Si `table_database` o `table_schema` se proveen, solo cuentan referencias cuyo qualifier coincida — un qualifier ausente en la fuente se interpreta como "schema actual" y se acepta.
- Comentarios (`--`, `/* */`) y literales `'...'` se filtran antes del scan.

### Caps

- **Hard cap**: `scanned_count <= 5000` SPs después del filtro `pattern`. Si se supera, error tipado nuevo `InputTooBroadError` (`code=INPUT_TOO_BROAD`) que sugiere acotar con `pattern`.
- **Soft cap**: `references` se trunca a 1000 entradas; si se pasa, `truncated=true` y la lista se ordena por suma de ocurrencias desc.
- **Timeout**: 60 s — la query al catálogo y el scan en memoria son dominantes; el cap de 5000 SPs los acota en la práctica.

## Alternatives considered

1. **Escanear con regex global sobre el body sin segmentar por `;`**. Rechazada: introduce falsos positivos por strings y por boundaries ambiguos. Reusar `iter_statements` mantiene la misma garantía que las tools anteriores (#109, #110, #111).
2. **Construir un AST NZPLSQL completo y resolver por nodos**. Rechazada: aumenta superficie pública, obliga a versionar el AST y es excesivo para el caso de uso. La heurística regex limitada cubre los verbos del dialecto Netezza con precisión razonable y limitaciones documentadas.
3. **Mezclar la lógica con `nz_get_procedure_table_logic` exponiendo un campo `direction: "produce" | "consume"`**. Rechazada: viola responsabilidad única (ADR 0006). La tool actual aísla **un** SP; esta escanea **N** SPs. Mantener tools separadas conserva la auditoría limpia y simplifica permisos / caps.
4. **Escanear cross-schema o cross-database en una sola llamada**. Rechazada en v1: agranda el dominio del cap y complica la query SQL. Issue separado podría agregar `nz_find_table_references_global`.

## Consequences

- **Positivas**:
  - Token cost cae de ~30k+ a ~1-2k para responder *"¿quién toca `T_X`?"* en un schema mediano.
  - El nuevo helper `iter_table_references_in_statement` y `count_table_references` son reutilizables por una futura tool `nz_get_table_dependencies` o por análisis cross-schema.
  - El cap duro corta llamadas accidentales contra schemas con miles de SPs.
- **Negativas / costes**:
  - +1 tool en el catálogo (30 → 31). Mantenibilidad: el patrón de "una tool, un módulo registrado" se mantiene.
  - Falsos negativos posibles si el SP arma nombres de tabla con dynamic SQL (`EXECUTE IMMEDIATE 'INSERT INTO ' || …`) — limitación documentada en el contrato y en este ADR.
- **Qué monitorizar**:
  - ¿Aparecen issues pidiendo cross-schema? Si > 3 en 3 meses, abrir issue para una tool global o un input array.
  - ¿El cap de 5000 se golpea con frecuencia? Si sí, considerar paginación con cursor en lugar de subir el cap.
  - ¿Aparecen falsos positivos por `INTO` en contextos no-CTAS? Si sí, refinar el patrón con look-behind para `SELECT`.

## Limitaciones conocidas (out of scope v1)

- **Vistas (`_v_view.DEFINITION`)** — esta tool solo cubre SPs.
- **Dynamic SQL** — cadenas armadas con `||` no se intentan parsear.
- **Análisis de columnas** — solo a nivel tabla, no qué columnas se leen/escriben.
- **Cross-schema / cross-database** — un solo `(database, schema)` por llamada.
- **Exportación a archivo** — salida solo en JSON-RPC.

## References

- Issue #107 (GitHub) — spec original con criterios de aceptación.
- ADR 0006 — Tools de responsabilidad única.
- ADR 0009 — Patrón de catálogo bulk (`nz_get_procedures_ddl_batch`).
- ADR 0011 — `iter_statements` y `extract_create_or_insert_targeting`.
- `docs/architecture/tools-contract.md` § 18.
