# 11. Aislar la lógica de una tabla intermedia dentro de un SP

Date: 2026-05-06

## Status

Accepted

## Context

Los SPs financieros (`PI_CLIENTESCFM`, `PI_BASEREPERFILAMIENTOGENERAL`, etc.) construyen decenas de tablas intermedias mediante `CREATE TEMP TABLE … AS SELECT …` y/o `INSERT INTO … SELECT …`. Cuando un usuario o un agente IA necesita responder *"¿cómo se calcula `TT_X`?"* hoy debe descargar el DDL completo (a veces > 100 KB), pagar tokens por las otras 30 tablas que no interesan y buscar el statement a mano.

Las tools existentes resuelven problemas adyacentes pero no este:

- `nz_get_procedure_ddl` devuelve **todo** el cuerpo: caro en tokens y poco accionable.
- `nz_get_procedure_section` extrae secciones lógicas (`header`/`declare`/`body`/`exception`) o un rango de líneas, pero no aísla un statement por nombre de tabla. La IA debe inferir el rango, lo cual es frágil.
- `nz_get_procedure_size` es complementaria: muestrea tamaño antes de decidir cómo proceder.
- `nz_find_table_references` (issue #107, no implementada aún) cubre el problema **inverso**: qué SPs referencian una tabla.

La tensión es entre extender una tool existente (más simple, pero rompe responsabilidad única) o crear una tool nueva (un punto más en el catálogo, pero contrato claro).

## Decision

Crear una tool nueva `nz_get_procedure_table_logic` con responsabilidad única: dado `(database, schema, procedure, table)`, devolver los `CREATE [TEMP] TABLE … AS …` y `INSERT INTO …` que **producen o pueblan** esa tabla, ya con comentarios stripped y terminados en `;`.

1. **Una razón para fallar**: el target o no existe (`not_found = true`) o existe (lista de statements). Filtrado por `kinds=["create","insert"]` (default ambos).
2. **Reutilización**: se apoya en `strip_comments` (#105) y añade dos helpers en `catalog/nzplsql_parser.py`:
   - `iter_statements(source)` — boundary `;` consciente de strings (`'a;b'`), identificadores (`"a;b"`), line comments (`-- … \n`) y block comments (`/* … */`), preservando line numbers del source crudo.
   - `extract_create_or_insert_targeting(source, table, *, kinds)` — clasifica statements y filtra por target last-segment (case-insensitive), aceptando `table`, `schema.table`, `bd.schema.table` y la sintaxis Netezza `bd..table`.
3. **Cap de respuesta**: 200 KB (más permisivo que el cap general de ~100 KB de DDL completo, porque aquí la respuesta es por definición un subconjunto auditado del cuerpo). Si se supera, error tipado `RESPONSE_TOO_LARGE` con sugerencia de filtrar por `kinds` o usar `nz_get_procedure_section`.
4. **Limitaciones conocidas (out of scope v1)**:
   - `MERGE`, `UPDATE`, `DELETE`, `TRUNCATE` — fuera de alcance, issue separado para extender `kinds` cuando haya casos de uso reales.
   - Dynamic SQL (`EXECUTE IMMEDIATE`) — no se intenta parsear cadenas armadas.
   - Resolución de dependencias inversas / directas — responsabilidad de #107 y de un futuro `nz_get_table_dependencies`.
   - No reformatea el `sql` devuelto: se entrega tal cual viene tras strip de comentarios.

## Alternatives considered

1. **Extender `nz_get_procedure_section` con `section: "table_logic"` + `table: str`**. Rechazado porque convierte una tool de extracción por *posición lógica* (`header`/`body`/…) en una multitool por *contenido*. Viola responsabilidad única (ADR 0006) y obliga a que un cambio en cualquiera de los dos modos toque el mismo handler.
2. **Devolver una vista parseada (AST) en vez de texto SQL**. Rechazado: aumenta superficie pública, obliga a versionar el AST y los consumidores actuales razonan sobre texto. Si en el futuro hay caso de uso, se añade una tool dedicada.
3. **Reutilizar `nz_clone_procedure` con transformaciones para extraer**. Rechazado: `clone` es modo `admin` y orientado a escritura; mezclarlo con lectura confunde el modelo de permisos.

## Consequences

- **Positivas**:
  - Token cost cae de ~30k a ~1-2k para responder *"¿cómo se calcula `TT_X`?"* sobre SPs grandes.
  - El parser de statements (`iter_statements`) es reutilizable por futuras tools (referencias inversas, análisis de dependencias).
  - El cap de 200 KB protege al cliente MCP de payloads patológicos (SP con 50 INSERT al mismo target).
- **Negativas / costes**:
  - +1 tool en el catálogo (28 → 29 antes de este PR; 30 contando `nz_get_procedure_size` recién aterrizado en #110). Mantenibilidad: el patrón de añadir tools sin tocar dispatcher se mantiene.
  - Falsos negativos posibles si el SP construye nombres de tabla con dynamic SQL — documentado como limitación.
- **Qué monitorizar**:
  - ¿Aparecen issues pidiendo `MERGE` / `UPDATE`? Si > 3 en 3 meses, abrir issue para extender `kinds`.
  - ¿El cap de 200 KB se golpea en SPs reales? Si sí, considerar paginación en lugar de subir el cap.

## Refinement — issue #114 (2026-05-07)

`classify_target_statement` se anclaba originalmente con `\A\s*` sobre el chunk entregado por `iter_statements`. Como `iter_statements` segmenta por `;` outside-of-strings/comments, los chunks acumulan tokens de bloque NZPLSQL desde el `;` previo: un `INSERT INTO <tabla>` dentro de `BEGIN … END;` o `IF cond THEN … END IF;` llega al clasificador con prefijo `BEGIN\n`, `IF cond THEN\n`, etc., y el regex anclado retornaba `None`. La tool reportaba `not_found=true` para SPs reales (caso testigo: `PROD_ANALITICA.DBO.PI_BASEREPERFILAMIENTOGENERAL` sobre `BaseReperfilamientoGeneral`). El fix:

- Aplica `mask_single_quoted_strings` al chunk antes de buscar, para que verbos dentro de literales (`'INSERT INTO foo'`) no produzcan falsos positivos.
- Cambia `_RE_CREATE_TABLE` y `_RE_INSERT_INTO` de anclaje `\A\s*` a búsqueda en cualquier posición con guarda de borde de palabra: `(?<![A-Za-z0-9_])CREATE\s+...` / `(?<![A-Za-z0-9_])INSERT\s+INTO\s+...`. Mantiene `re.IGNORECASE | re.VERBOSE`.
- Sustituye `re.match` por `re.search` en `classify_target_statement`.
- Tiebreak: el primer match en orden de aparición gana (CREATE vs INSERT), preservando la semántica anterior cuando el chunk ya empezaba por el verbo.

Sin cambios al contrato público de la tool ni al output schema. La limitación de scope (CREATE/INSERT, sin MERGE/UPDATE/DELETE/TRUNCATE) sigue vigente.

## References

- Issue #109 (GitHub) — spec original con criterios de aceptación.
- Issue #105 — `strip_comments` reusado.
- Issue #106 / ADR 0010 — `nz_get_procedure_size`, precedente más reciente para añadir tools de SP.
- Issue #107 — `nz_find_table_references` (análisis inverso, no en este PR).
- Issue #114 — refinement del clasificador para tolerar prefijos de bloque (ver sección dedicada arriba).
- ADR 0006 — Tools de responsabilidad única.
- `docs/architecture/tools-contract.md` § 17.
