# Changelog

Todos los cambios notables a este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y este proyecto adhiere a [SemVer](https://semver.org/spec/v2.0.0.html).

Cada entrada se documenta en **español** y **english**.

## [Unreleased]

### Added
- ES: `nz_export_ddl` admite dos parámetros opcionales `output_path: str | None = None` y `overwrite: bool = False`. Cuando se pasa `output_path`, la tool persiste el DDL al filesystem del servidor MCP en `output_path` además de devolver el bloque resource y enriquece `meta` con `output_path`, `bytes_written` y `sha256` (hex SHA-256 del payload UTF-8). El archivo escrito es **byte-idéntico** al `text` del resource: UTF-8 sin BOM, sin reformateo, sin traducción CRLF (anclado por test). Política de paths validada antes de consultar Netezza: solo paths absolutos, sin segmentos `..`, sin `~`, sin caracteres de control ASCII; la carpeta padre debe existir (no se crea automáticamente); el archivo no debe existir salvo `overwrite=true`. En POSIX el archivo se crea con permisos `0600`; en Windows hereda la ACL del directorio padre (Python `Path.chmod` no setea bits POSIX en NT) — diferencia documentada en `docs/adr/0013-export-ddl-output-path.md`. Las violaciones de path / filesystem-state se devuelven con código estable `INVALID_INPUT` (detalle en `error.context.detail`). Sin `output_path` el comportamiento de la tool es idéntico al actual (back-compat estricta). Lógica de filesystem aislada en `src/nz_mcp/io/safe_write.py` con 100 % de cobertura unitaria. Witness E2E: `PROD_MAESTROBI.DBO.V_CONTINGENCIACREDITOSFULL` con perfil `uaipscrea1` (issue #127, ADR 0013).
- EN: `nz_export_ddl` accepts two new optional parameters `output_path: str | None = None` and `overwrite: bool = False`. When `output_path` is provided, the tool persists the DDL to the MCP server's filesystem at `output_path` in addition to returning the resource block, and enriches `meta` with `output_path`, `bytes_written` and `sha256` (hex SHA-256 of the UTF-8 payload). The file written is **byte-identical** to the resource `text`: UTF-8 without BOM, no reformatting, no CRLF translation (anchored by a regression test). Path policy validated before any catalog query: absolute paths only, no `..` segments, no `~`, no ASCII control characters; the parent directory must exist (auto-creation is intentionally disabled); the file must not exist unless `overwrite=true`. POSIX creates the file with `0600`; on Windows the ACL of the parent directory is inherited (Python's `Path.chmod` cannot set POSIX bits on NT) — documented in `docs/adr/0013-export-ddl-output-path.md`. Path / filesystem-state violations surface with the stable error code `INVALID_INPUT` (detail in `error.context.detail`). Without `output_path` the tool's behaviour is identical to the previous one (strict back-compat). Filesystem logic isolated in `src/nz_mcp/io/safe_write.py` with 100 % unit coverage. E2E witness: `PROD_MAESTROBI.DBO.V_CONTINGENCIACREDITOSFULL` with profile `uaipscrea1` (issue #127, ADR 0013).

### Fixed
- ES: `nz_get_view_ddl` y `nz_export_ddl(object_type='view')` ahora devuelven el DDL real cuando la vista vive en una BD distinta a la del perfil activo. Antes Netezza proyectaba el sentinel literal `'Not a view'` en `_V_VIEW.DEFINITION` para cualquier consulta cross-database, porque la columna se calcula lazy desde `_T_RULE` del catálogo *actual* de la sesión y el join silencioso fallaba al cruzar bases. El fix emite `SET CATALOG <database>` en la conexión efímera de la tool justo antes del `SELECT` contra `<BD>.._V_VIEW`; cada llamada abre y cierra su propia conexión nzpy, así que el cambio de catálogo no contamina queries posteriores. El identificador de BD se valida con `validate_database_identifier` (alfabeto `[A-Z][A-Z0-9_]*`) antes de interpolarse en el `SET CATALOG` (Netezza no admite parámetros bind en esta sentencia). `nz_get_table_ddl` y `nz_get_procedure_ddl` no se tocan: ya funcionan bien cross-DB porque reconstruyen desde catálogos seguros (`_v_relation_column`, `_v_procedure`). Witness E2E: `PROD_MAESTROBI.DBO.V_CONTINGENCIACREDITOSFULL` con perfil `uaipscrea1` (default DB `DESA_MODELOS`) (issue #125).
- EN: `nz_get_view_ddl` and `nz_export_ddl(object_type='view')` now return the real DDL when the view lives in a database different from the active profile. Previously Netezza projected the literal sentinel `'Not a view'` into `_V_VIEW.DEFINITION` for any cross-database lookup, because the column is computed lazily from `_T_RULE` of the session's *current* catalog and the silent join failed across databases. The fix emits `SET CATALOG <database>` on the tool's ephemeral connection right before the `SELECT` against `<BD>.._V_VIEW`; each call opens and closes its own nzpy connection, so the catalog change does not leak into subsequent queries. The DB identifier is validated by `validate_database_identifier` (alphabet `[A-Z][A-Z0-9_]*`) before being interpolated into the `SET CATALOG` (Netezza does not accept bind parameters there). `nz_get_table_ddl` and `nz_get_procedure_ddl` are untouched: they already work cross-DB by reconstructing from safe catalogs (`_v_relation_column`, `_v_procedure`). E2E witness: `PROD_MAESTROBI.DBO.V_CONTINGENCIACREDITOSFULL` with profile `uaipscrea1` (default DB `DESA_MODELOS`) (issue #125).
- ES: `nz_list_tables`, `nz_list_views`, `nz_list_procedures`, `nz_list_schemas`, `nz_list_databases`, `nz_get_procedures_ddl_batch` y `nz_find_table_references` ahora hacen match case-insensitive sobre el parámetro `pattern`. Antes el `LIKE` se evaluaba contra el case original del input, y como Netezza normaliza los nombres del catálogo a mayúsculas, un patrón con minúsculas devolvía 0 filas aunque el objeto existiera (`pattern='EFE_MC_codigogestion'` → `[]`, `pattern='EFE_MC_CODIGOGESTION'` → 1 fila). Las queries en `catalog/queries.py` ahora envuelven el placeholder con `UPPER(?)`, manteniendo la semántica de wildcards (`%`/`_`) que el usuario haya escrito (issue #123).
- EN: `nz_list_tables`, `nz_list_views`, `nz_list_procedures`, `nz_list_schemas`, `nz_list_databases`, `nz_get_procedures_ddl_batch` and `nz_find_table_references` now match the `pattern` argument case-insensitively. Previously the `LIKE` ran against the original-case input, but Netezza stores catalog names in upper case, so a lower-case pattern returned 0 rows even when the object existed (`pattern='EFE_MC_codigogestion'` → `[]`, `pattern='EFE_MC_CODIGOGESTION'` → 1 row). The catalog SQL in `catalog/queries.py` now wraps the placeholder with `UPPER(?)`, preserving the wildcard semantics (`%`/`_`) the user supplied (issue #123).
- ES: `parse_sections` ahora detecta secciones en SPs cuyos literales contienen caracteres de salto de línea (CR, VT, FF, NEL, U+2028, U+2029) o cuyos comentarios `--` / `/* */` contienen apóstrofos sueltos. Antes `mask_single_quoted_strings` colapsaba esos caracteres dentro de literales y `splitlines()` del masked source quedaba más corto que el del source crudo, lo que hacía que la búsqueda del `END;` exterior perdiera líneas (`sections_detected: []` en SPs con CR). Adicionalmente, un `'` dentro de un comentario abría una "literal fantasma" que blanqueaba el resto del cuerpo. Nuevo helper `mask_literals_preserving_lines` enmascara contenido de literales y de comentarios pero preserva todos los caracteres de boundary, garantizando `len(masked.splitlines()) == len(source.splitlines())`. Witness: `PROD_ANALITICA.DBO.PI_BASEREPERFILAMIENTOGENERAL` (issue #119).
- EN: `parse_sections` now detects sections in SPs whose literals contain line-boundary characters (CR, VT, FF, NEL, U+2028, U+2029) or whose `--` / `/* */` comments contain stray apostrophes. Previously `mask_single_quoted_strings` collapsed those characters inside literals and the masked source's `splitlines()` was shorter than the raw source's, so the outer `END;` search dropped lines (`sections_detected: []` for SPs containing CR). Additionally, a `'` inside a comment opened a "phantom literal" that blanked out the rest of the body. New `mask_literals_preserving_lines` helper masks both literal and comment contents while preserving every boundary character, guaranteeing `len(masked.splitlines()) == len(source.splitlines())`. Witness: `PROD_ANALITICA.DBO.PI_BASEREPERFILAMIENTOGENERAL` (issue #119).
- ES: `parse_procedure_arguments` reconoce los tipos compuestos canónicos de Netezza: `CHARACTER VARYING(N)`, `NATIONAL CHARACTER VARYING(N)`, `NATIONAL CHARACTER(N)`, `DOUBLE PRECISION`, `TIME WITH TIME ZONE`, `TIMESTAMP WITH TIME ZONE`. Antes el parser asumía que el primer token de cada argumento era el `name` y dividía `CHARACTER VARYING(20)` en `name="CHARACTER", type="VARYING(20)"`, generando un argumento espurio. Ahora el helper `_starts_with_compound_type` detecta el tipo compuesto al inicio del chunk (ignorando el sufijo `(N)`) y decide correctamente si hay un nombre formal previo o solo un tipo (en cuyo caso se genera `arg1`, `arg2`, …). Witness: `PI_BASEREPERFILAMIENTOGENERAL(DATE, DATE, CHARACTER VARYING(20))` ahora devuelve 3 args (issue #121).
- EN: `parse_procedure_arguments` recognises Netezza canonical compound types: `CHARACTER VARYING(N)`, `NATIONAL CHARACTER VARYING(N)`, `NATIONAL CHARACTER(N)`, `DOUBLE PRECISION`, `TIME WITH TIME ZONE`, `TIMESTAMP WITH TIME ZONE`. Previously the parser assumed the first token of each argument was the `name`, splitting `CHARACTER VARYING(20)` into `name="CHARACTER", type="VARYING(20)"` and producing a spurious argument. The new `_starts_with_compound_type` helper detects the compound type at chunk start (ignoring the `(N)` suffix) and decides whether a formal name precedes it or only a type is given (in which case `arg1`, `arg2`, … synthetic names are generated). Witness: `PI_BASEREPERFILAMIENTOGENERAL(DATE, DATE, CHARACTER VARYING(20))` now returns 3 args (issue #121).

### Changed
- ES: `nz_get_procedure_table_logic` admite cinco nuevos valores en `kinds`: `"drop"`, `"truncate"`, `"update"`, `"delete"`, `"merge"`. Default permanece `["create", "insert"]` (back-compat estricto). El output schema (`StatementItem.kind`) se amplía con `"DROP TABLE"`, `"TRUNCATE TABLE"`, `"UPDATE"`, `"DELETE FROM"`, `"MERGE INTO"`. `classify_target_statement` detecta los cinco verbos con guarda de borde de palabra y modificadores Netezza (`DROP TABLE [IF EXISTS]`, `MERGE INTO`, etc.); el tiebreak "primer match en orden de aparición gana" se mantiene. Cierra la asimetría con `nz_find_table_references` (que ya contaba estos verbos como writes) y desbloquea el patrón idempotente real de Netezza `drop table TT_X if exists; create table TT_X as …;` para tools de análisis IA (issue #120, ADR 0011 v2).
- EN: `nz_get_procedure_table_logic` accepts five new values in `kinds`: `"drop"`, `"truncate"`, `"update"`, `"delete"`, `"merge"`. The default stays `["create", "insert"]` (strict back-compat). Output schema (`StatementItem.kind`) gains `"DROP TABLE"`, `"TRUNCATE TABLE"`, `"UPDATE"`, `"DELETE FROM"`, `"MERGE INTO"`. `classify_target_statement` detects all five verbs with word-boundary guards and Netezza modifiers (`DROP TABLE [IF EXISTS]`, `MERGE INTO`, etc.); the "first match in source order wins" tiebreak is preserved. Closes the asymmetry with `nz_find_table_references` (which already counted these verbs as writes) and unblocks the real Netezza idempotency pattern `drop table TT_X if exists; create table TT_X as …;` for AI analysis tools (issue #120, ADR 0011 v2).

### Fixed
- ES: `classify_target_statement` (en `catalog/nzplsql_parser.py`) ahora tolera prefijos de bloque NZPLSQL (`BEGIN`, `IF … THEN`, `ELSE`, `EXCEPTION`, `FOR … LOOP`, `WHILE`, …) al clasificar el verbo CREATE/INSERT del statement. Antes el regex estaba anclado con `\A\s*`, así que cuando `iter_statements` entregaba un chunk acumulado desde el `;` previo (típico cuando el INSERT/CREATE va dentro de un bloque), el clasificador devolvía `None` y la tool `nz_get_procedure_table_logic` reportaba `not_found=true` para SPs reales (caso testigo: `PROD_ANALITICA.DBO.PI_BASEREPERFILAMIENTOGENERAL` sobre `BaseReperfilamientoGeneral`). Ahora se aplica `mask_single_quoted_strings` al chunk y se busca el verbo en cualquier posición con guarda de borde de palabra (`(?<![A-Za-z0-9_])`); literales `'…'` no producen falsos positivos. Se mantiene la semántica de "primer match en orden de aparición gana" para chunks con múltiples CREATE/INSERT (issue #114).
- EN: `classify_target_statement` (in `catalog/nzplsql_parser.py`) now tolerates NZPLSQL block-control prefixes (`BEGIN`, `IF … THEN`, `ELSE`, `EXCEPTION`, `FOR … LOOP`, `WHILE`, …) when classifying the CREATE/INSERT verb of a statement. The regex was previously anchored with `\A\s*`, so whenever `iter_statements` yielded a chunk that accumulated text from the previous `;` boundary (typical when the INSERT/CREATE lives inside a block), the classifier returned `None` and the `nz_get_procedure_table_logic` tool reported `not_found=true` for real SPs (witness: `PROD_ANALITICA.DBO.PI_BASEREPERFILAMIENTOGENERAL` over `BaseReperfilamientoGeneral`). The fix applies `mask_single_quoted_strings` to the chunk and searches for the verb anywhere with a word-boundary guard (`(?<![A-Za-z0-9_])`); `'…'` literals do not produce false positives. The "first match in source order wins" semantics is preserved for chunks containing multiple CREATE/INSERT verbs (issue #114).

### Changed
- ES: `_WRITE_PREFIX` en `catalog/nzplsql_parser.py` ahora detecta `CREATE [TEMP|TEMPORARY] TABLE [IF NOT EXISTS] <tabla>` como write. Antes solo se contaba la forma `… INTO <tabla>` (CTAS con `INTO` explícito / `SELECT INTO`); la forma CTAS estándar (`CREATE TABLE foo AS SELECT …`) no se clasificaba como write, causando discrepancias entre `nz_find_table_references` y `nz_get_procedure_table_logic` (issue #114).
- EN: `_WRITE_PREFIX` in `catalog/nzplsql_parser.py` now detects `CREATE [TEMP|TEMPORARY] TABLE [IF NOT EXISTS] <table>` as a write. Previously only the `… INTO <table>` form (explicit-INTO CTAS / `SELECT INTO`) was counted; the standard CTAS form (`CREATE TABLE foo AS SELECT …`) was not classified as a write, causing discrepancies between `nz_find_table_references` and `nz_get_procedure_table_logic` (issue #114).

### Added
- ES: tool `nz_find_table_references` — análisis **inverso** de impacto: dado `(database, schema, table)`, devuelve los SPs del schema que leen o escriben esa tabla, con cuentas separadas (`occurrences_read`, `occurrences_write`) y `usage` ∈ `read`/`write`/`both`. Detección consciente de comentarios y literales: read = `FROM`/`JOIN` (incl. `LEFT/RIGHT/INNER/FULL/CROSS [OUTER]`)/`USING (`; write = `INSERT INTO`/`UPDATE`/`DELETE FROM`/`MERGE INTO`/`TRUNCATE TABLE`/`DROP TABLE [IF EXISTS]`/`... INTO <tabla>` (CTAS / `SELECT INTO`). Caps: `scanned_count` ≤ 5000 (`INPUT_TOO_BROAD` con sugerencia de usar `pattern`), `references` truncadas a 1000 ordenadas desc por suma de ocurrencias (`truncated: true`). Out of scope v1: vistas, dynamic SQL, análisis de columnas, cross-schema/cross-database (issue #107, ADR 0012).
- EN: `nz_find_table_references` tool — **reverse** impact analysis: given `(database, schema, table)`, returns the SPs in that schema that read or write the table, with separate counts (`occurrences_read`, `occurrences_write`) and `usage` ∈ `read`/`write`/`both`. Comment- and literal-aware detection: read = `FROM`/`JOIN` (incl. `LEFT/RIGHT/INNER/FULL/CROSS [OUTER]`)/`USING (`; write = `INSERT INTO`/`UPDATE`/`DELETE FROM`/`MERGE INTO`/`TRUNCATE TABLE`/`DROP TABLE [IF EXISTS]`/`... INTO <table>` (CTAS / `SELECT INTO`). Caps: `scanned_count` ≤ 5000 (`INPUT_TOO_BROAD` with `pattern` suggestion), `references` truncated to 1000 sorted desc by total occurrences (`truncated: true`). Out of scope v1: views, dynamic SQL, column-level analysis, cross-schema/cross-database (issue #107, ADR 0012).
- ES: error tipado `InputTooBroadError` (código `INPUT_TOO_BROAD`) — emitido cuando un escaneo a catálogo abarcaría más SPs que el cap configurado; sugiere acotar con `pattern`.
- EN: typed `InputTooBroadError` (code `INPUT_TOO_BROAD`) — emitted when a catalog scan would cover more SPs than the configured cap; suggests narrowing with `pattern`.
- ES: helpers `iter_table_references_in_statement` y `count_table_references` en `catalog/nzplsql_parser.py` — clasifican ocurrencias de una tabla como `read` / `write` con respeto de límites de token y filtros opcionales por `bd` / `schema` qualifier.
- EN: `iter_table_references_in_statement` and `count_table_references` helpers in `catalog/nzplsql_parser.py` — classify table occurrences as `read` / `write` with token-boundary respect and optional `db` / `schema` qualifier filters.
- ES: tool `nz_get_procedure_table_logic` — aísla los `CREATE [TEMP] TABLE … AS …` y/o `INSERT INTO …` de un SP que producen o pueblan una tabla intermedia concreta. Devuelve los statements con comentarios stripped y terminados en `;`, junto con `line_start` / `line_end` referidos al cuerpo crudo para auditoría. Soporta filtrado por `kinds`, detección case-insensitive del nombre de tabla con `schema.table` / `bd.schema.table` / `bd..table`. Cap de respuesta 200 KB (`RESPONSE_TOO_LARGE`). Out of scope v1: `MERGE`, `UPDATE`, `DELETE`, `TRUNCATE`, dynamic SQL (issue #109, ADR 0011).
- EN: `nz_get_procedure_table_logic` tool — isolates `CREATE [TEMP] TABLE … AS …` and/or `INSERT INTO …` statements inside an SP that produce or populate a given intermediate table. Returns statements with comments stripped and terminated by `;`, plus `line_start` / `line_end` mapped to the raw body for audit. Supports `kinds` filter and case-insensitive table-name match across `schema.table` / `bd.schema.table` / `bd..table` forms. 200 KB response cap (`RESPONSE_TOO_LARGE`). Out of scope v1: `MERGE`, `UPDATE`, `DELETE`, `TRUNCATE`, dynamic SQL (issue #109, ADR 0011).
- ES: error tipado `ResponseTooLargeError` (código `RESPONSE_TOO_LARGE`) para casos donde el payload estructurado de una tool excede su cap; distinto de `RESULT_TOO_LARGE` (filas truncadas).
- EN: typed `ResponseTooLargeError` (code `RESPONSE_TOO_LARGE`) for cases where a tool's structured payload exceeds its cap; distinct from `RESULT_TOO_LARGE` (truncated row data).
- ES: helpers `iter_statements` y `extract_create_or_insert_targeting` en `catalog/nzplsql_parser.py` — boundaries `;` conscientes de strings, identificadores y comentarios; clasificación de CREATE/INSERT con detección de targets `bd..table` Netezza.
- EN: `iter_statements` and `extract_create_or_insert_targeting` helpers in `catalog/nzplsql_parser.py` — string/identifier/comment-aware `;` boundaries; CREATE/INSERT classification with Netezza `bd..table` target detection.
- ES: tool `nz_get_procedure_size` — permite obtener las métricas de tamaño (líneas y bytes, en variantes `raw` y `clean`) y detectar secciones lógicas de un SP sin retornar su cuerpo completo, ideal para token budgeting previo (issue #106).
- EN: `nz_get_procedure_size` tool — returns size metrics (lines and bytes, in `raw` and `clean` variants) and detects logical sections of an SP without fetching its full body, ideal for token budgeting before loading DDL (issue #106).
- ES: `nz_get_procedure_ddl` — nuevo campo de input `variant` (`"raw"` | `"clean"`, default `"raw"`). `clean` elimina comentarios de línea (`--`) y de bloque (`/* … */`) fuera de literales de cadena e identificadores entrecomillados, reduciendo hasta un 30 % el consumo de tokens en razonamiento IA. Default `raw` preserva back-compat (issue #105).
- EN: `nz_get_procedure_ddl` — new `variant` input field (`"raw"` | `"clean"`, default `"raw"`). `clean` strips line (`--`) and block (`/* … */`) comments outside string literals and quoted identifiers, cutting token cost by up to 30 % for AI reasoning. Default `raw` preserves back-compat (issue #105).
- ES: `nz_get_procedure_ddl` — nuevos campos de output `size_bytes_raw` e `size_bytes_clean` (siempre presentes, independientemente del `variant`); permiten al cliente comparar tamaños antes de decidir qué variante cargar (issue #105).
- EN: `nz_get_procedure_ddl` — new output fields `size_bytes_raw` and `size_bytes_clean` (always present regardless of `variant`); allow the caller to compare sizes before choosing which variant to load (issue #105).

### Changed
- ES: ``configure_logging_for_stdio`` eleva el logger ``nzpy`` a ``WARNING`` bajo stdio para silenciar el DEBUG/INFO por paquete que rompe la UI de los clientes que renderizan en stderr (p.ej. la barra de progreso de ``nz-workbench kb-bootstrap``).
- EN: ``configure_logging_for_stdio`` raises the ``nzpy`` logger to ``WARNING`` under stdio so the per-packet DEBUG/INFO noise no longer shreds client UIs that render on stderr (e.g. the ``nz-workbench kb-bootstrap`` progress bar).
- ES: ``open_connection`` pasa ``logLevel=2`` (WARNING en la convención de nzpy) a ``nzpy.connect``. nzpy hace ``setLevel(logLevel)`` sobre el logger hijo ``nzpy.Connection[<db>}]`` en cada conexión, bypasseando el nivel del padre; sin este flag el silenciado del logger padre no tenía efecto real.
- EN: ``open_connection`` passes ``logLevel=2`` (WARNING in nzpy's convention) to ``nzpy.connect``. nzpy calls ``setLevel(logLevel)`` on the per-connection child logger ``nzpy.Connection[<db>}]``, bypassing parent-level filtering; without this flag the parent-logger silencing had no effect in practice.
- ES: ``_NOISY_LOGGERS`` incluye ``"mcp"`` para silenciar el INFO por tool call que emite el SDK (``mcp.server.lowlevel.server: Processing request of type CallToolRequest``). Rompía la animación de la barra Rich en clientes como ``nz-workbench kb-bootstrap``.
- EN: ``_NOISY_LOGGERS`` now includes ``"mcp"`` to silence the SDK's per-tool-call INFO line (``mcp.server.lowlevel.server: Processing request of type CallToolRequest``). It was shredding Rich bar animations in clients like ``nz-workbench kb-bootstrap``.
- ES: ``nz_insert`` — por defecto ``dry_run=true`` y ``confirm`` obligatorio para ejecutar (mismo patrón que update/delete).
- EN: ``nz_insert`` — defaults to ``dry_run=true`` and requires ``confirm`` to execute (same pattern as update/delete).
- ES: ``nz_create_table`` — por defecto ``dry_run=true``; para ejecutar en el servidor hace falta ``dry_run=false`` y ``confirm=true``. Salida alineada con otras tools DDL: ``ddl_to_execute``, ``executed``, ``duration_ms``.
- EN: ``nz_create_table`` — defaults to ``dry_run=true``; execution requires ``dry_run=false`` and ``confirm=true``. Output aligned with other DDL tools: ``ddl_to_execute``, ``executed``, ``duration_ms``.

### Fixed
- ES: ``parse_sections`` — corrige ``IndexError`` en ``_find_plain_outer_end`` y ``_first_plain_begin`` al procesar SPs con literales de string multilínea. ``mask_single_quoted_strings`` colapsa newlines dentro de ``'…'`` en espacios, haciendo ``masked.splitlines()`` más corto que ``source.splitlines()``; el loop usaba el conteo del source como límite pero indexaba en masked (issue #113).
- EN: ``parse_sections`` — fix ``IndexError`` in ``_find_plain_outer_end`` and ``_first_plain_begin`` when processing SPs containing multi-line string literals. ``mask_single_quoted_strings`` collapses newlines inside ``'…'`` to spaces, making ``masked.splitlines()`` shorter than ``source.splitlines()``; the loop used the source line count as its bound but indexed into masked lines (issue #113).

### Added
- ES: tool ``nz_get_procedures_ddl_batch`` para obtener los DDL de todos los procedimientos de un schema en lote, reduciendo la carga en indexación masiva (issue #101).
- EN: ``nz_get_procedures_ddl_batch`` tool to batch fetch DDLs for all procedures in a schema, reducing load during bulk indexing (issue #101).
- ES: ``sql_guard`` — ``UNION`` / ``UNION ALL`` entre solo ``SELECT`` se clasifican como ``SELECT`` (desbloquea ``nz_insert_select`` / CTAS con multi-fila vía UNION).
- EN: ``sql_guard`` — ``UNION`` / ``UNION ALL`` of ``SELECT``-only branches classify as ``SELECT`` (enables ``nz_insert_select`` / CTAS multi-row via UNION).
- ES: ``nz_insert_select`` — ``INSERT INTO … SELECT …`` con ``select_sql`` validado (modo ``write``); ``dry_run``/``confirm``; ``estimate_rows`` opcional para previsualizar filas con ``COUNT`` (costoso).
- EN: ``nz_insert_select`` — ``INSERT INTO … SELECT …`` with validated ``select_sql`` (``write`` mode); ``dry_run``/``confirm``; optional ``estimate_rows`` for ``COUNT`` preview (expensive).
- ES: ``nz_create_table_as`` — CTAS (``CREATE TABLE … AS SELECT …``) con distribución Netezza (modo ``admin``); rechaza si el destino ya existe; ``estimate_rows`` opcional.
- EN: ``nz_create_table_as`` — CTAS with Netezza distribution (``admin`` mode); rejects if target exists; optional ``estimate_rows``.
- ES: tool ``nz_export_ddl`` — DDL de tabla/vista/procedimiento como bloques MCP (resource ``text/sql`` + texto resumen) y ``meta`` con URI ``nz-mcp://ddl/...``; pensada para copia nativa en clientes como Claude Desktop.
- EN: ``nz_export_ddl`` tool — table/view/procedure DDL as MCP content blocks (``text/sql`` embedded resource + summary text) and ``meta`` with ``nz-mcp://ddl/...`` URI; intended for native copy UX in clients such as Claude Desktop.
- ES: ``duration_ms`` en outputs de tools de lectura que consultan Netezza (listados, describe, DDL de tabla/vista/procedimiento, secciones).
- EN: ``duration_ms`` on read-tool outputs that hit Netezza (list/describe/table-view-procedure DDL and sections).
- ES: ``nz_table_stats`` — ``skew_class`` (balanced/moderate/severe) con bandas de sesgo.
- EN: ``nz_table_stats`` — ``skew_class`` (balanced/moderate/severe) skew bands.
- ES: ``nz_get_procedure_ddl`` — ``size_bytes`` y ``warning`` si el DDL supera ~100 KB (sin truncar).
- EN: ``nz_get_procedure_ddl`` — ``size_bytes`` and ``warning`` when DDL exceeds ~100 KB (not truncated).
- ES: ``nz_get_table_ddl`` — ``notes`` ampliadas (reconstrucción desde catálogo y caveats); campo ``reconstructed`` documentado en el schema.
- EN: ``nz_get_table_ddl`` — expanded ``notes`` (catalog reconstruction and caveats); ``reconstructed`` documented on the schema.
- ES: error ``PROFILE_NOT_FOUND`` en ``nz_switch_profile`` con ``available_profiles`` en el contexto; persistencia de ``active`` en ``profiles.toml``.
- EN: ``PROFILE_NOT_FOUND`` from ``nz_switch_profile`` includes ``available_profiles`` in context; persists ``active`` in ``profiles.toml``.
- ES: comando CLI ``nz-mcp edit-profile`` para actualizar modo/límites de un perfil existente (dependencia ``tomli-w``).
- EN: CLI command ``nz-mcp edit-profile`` to update mode/limits on an existing profile (``tomli-w`` dependency).

### Fixed
- ES: ``nz_clone_procedure`` / ``sql_guard`` — la cabecera ``CREATE PROCEDURE`` acepta tipos parametrizados con paréntesis anidados (p. ej. ``VARCHAR(20)``, ``NUMERIC(10,2)``); patrón compartido en ``procedure_head_pattern``. ``RETURNS VARCHAR`` / ``CHARACTER VARYING`` sin tamaño en DDL de catálogo se normaliza con longitud por defecto (4000) y advertencia (issue #89).
- EN: ``nz_clone_procedure`` / ``sql_guard`` — ``CREATE PROCEDURE`` header accepts nested-paren parameter types (e.g. ``VARCHAR(20)``, ``NUMERIC(10,2)``); shared pattern in ``procedure_head_pattern``. ``RETURNS VARCHAR`` / ``CHARACTER VARYING`` without length in catalog DDL are normalized with default length (4000) and a warning (issue #89).
- ES: servidor MCP stdio — ``structlog`` y logging estándar se configuran hacia ``stderr`` al arrancar ``serve`` / ``run_stdio_server``, evitando que Claude Desktop falle al parsear JSON-RPC por texto no JSON en ``stdout`` (issue #86).
- EN: MCP stdio server — ``structlog`` and stdlib logging are configured to ``stderr`` when starting ``serve`` / ``run_stdio_server``, preventing Claude Desktop JSON-RPC parse errors from non-JSON text on ``stdout`` (issue #86).
- ES: ``nz_table_stats`` — ya no usa ``_V_STATISTIC.LASTUPDATETIMESTAMP`` (columna inexistente en NPS 11.2.x); ``stats_last_analyzed`` queda siempre ``null``.
- EN: ``nz_table_stats`` — no longer references ``_V_STATISTIC.LASTUPDATETIMESTAMP`` (missing on NPS 11.2.x); ``stats_last_analyzed`` is always ``null``.
- ES: ``nz_clone_procedure`` — envuelve el cuerpo NZPLSQL con ``BEGIN_PROC``/``END_PROC`` para ejecución en Netezza.
- EN: ``nz_clone_procedure`` — wraps NZPLSQL body with ``BEGIN_PROC``/``END_PROC`` for Netezza execution.
- ES: ``nz_drop_table`` con ``if_exists=true`` — emite ``DROP TABLE esquema.tabla IF EXISTS`` (sintaxis Netezza NPS 11.x), no ``DROP TABLE IF EXISTS ...`` (error de parser en el servidor).
- EN: ``nz_drop_table`` with ``if_exists=true`` — emits ``DROP TABLE schema.table IF EXISTS`` (Netezza NPS 11.x syntax), not ``DROP TABLE IF EXISTS ...`` (server parse error).
- ES: ``nz_create_table`` / ``execute_create_table`` — columna con ``default`` omitido o ``null`` en JSON ya no falla; se omite la cláusula ``DEFAULT`` (equivalente a sin default). Rechazo explícito de ``default`` string con ``;`` (inyección).
- EN: ``nz_create_table`` / ``execute_create_table`` — column with omitted or JSON ``null`` ``default`` no longer errors; the ``DEFAULT`` clause is omitted (same as no default). String defaults containing ``;`` are rejected (injection).
- ES: ``sql_guard`` — ``CREATE PROCEDURE ... LANGUAGE NZPLSQL AS`` se valida por cabecera (modo ``admin``); el cuerpo NZPLSQL no se parsea con ``sqlglot``, desbloqueando ``nz_clone_procedure`` con DDL real.
- EN: ``sql_guard`` — ``CREATE PROCEDURE ... LANGUAGE NZPLSQL AS`` is header-validated (``admin`` mode); the NZPLSQL body is not parsed with ``sqlglot``, unblocking ``nz_clone_procedure`` with real DDL.
- ES: ``list_tools`` / ``outputSchema`` — los ``$ref`` a ``#/$defs/...`` se inlinean antes de envolver ``result``, para que clientes MCP (p. ej. Claude Desktop) no fallen con ``PointerToNowhere``.
- EN: ``list_tools`` / ``outputSchema`` — ``$ref`` targets under ``#/$defs/...`` are inlined before wrapping ``result``, so MCP clients (e.g. Claude Desktop) do not hit ``PointerToNowhere``.
- ES: el catálogo acepta filas devueltas como ``list`` (nzpy) además de ``tuple``; helper compartido ``is_sequence_row`` en consultas a ``_v_*``.
- EN: catalog parsing accepts nzpy ``list`` rows as well as ``tuple`` rows; shared ``is_sequence_row`` helper for ``_v_*`` queries.
- ES: dependencia ``typer>=0.15`` para compatibilidad con **click 8.2** (CLI sin errores de import).
- EN: bumped **typer** to ``>=0.15`` for **click 8.2** compatibility (CLI import errors fixed).
- ES: ``nz_explain`` / ``fetch_explain_text`` — si no hay result set y nzpy lanza ``ProgrammingError``, se concatena el plan desde ``cursor.notices``.
- EN: ``nz_explain`` / ``fetch_explain_text`` — when there is no rowset and nzpy raises ``ProgrammingError``, plan text is taken from ``cursor.notices``.
- ES: metadatos de columnas en ``execute_select`` mapean OIDs comunes a nombres legibles (p. ej. ``integer``, ``varchar``).
- EN: ``execute_select`` column metadata maps common type OIDs to readable names (e.g. ``integer``, ``varchar``).
- ES: ``resolve_locale()`` usa también ``locale.getdefaultlocale()`` cuando faltan ``LANG`` / ``NZ_MCP_LANG`` (útil en Windows).
- EN: ``resolve_locale()`` also consults ``locale.getdefaultlocale()`` when ``LANG`` / ``NZ_MCP_LANG`` are unset (helps on Windows).
- ES: textos de ``help=`` en CLI (p. ej. ``add-profile``, ``test-connection``) unificados en inglés.
- EN: CLI ``help=`` strings (e.g. ``add-profile``, ``test-connection``) standardized to English.
- ES: ``nz_get_procedure_ddl`` — cabecera ``CREATE OR REPLACE PROCEDURE`` sin duplicar el nombre cuando ``PROCEDURESIGNATURE`` ya incluye ``NAME(args)`` (NPS 11.x).
- EN: ``nz_get_procedure_ddl`` — ``CREATE OR REPLACE PROCEDURE`` header no longer duplicates the procedure name when ``PROCEDURESIGNATURE`` already includes ``NAME(args)`` (NPS 11.x).
- ES: parser NZPLSQL — secciones ``body``/``declare`` con fuentes sin ``BEGIN_PROC``/``END_PROC`` (``BEGIN``/``END`` planos y bloques anidados).
- EN: NZPLSQL parser — ``body``/``declare`` sections for sources without ``BEGIN_PROC``/``END_PROC`` (plain ``BEGIN``/``END`` and nested blocks).
- ES: ``execute_select`` / ``nz_query_select`` — pistas i18n distintas por motivo de truncado: filas, bytes de salida o tiempo.
- EN: ``execute_select`` / ``nz_query_select`` — distinct i18n hints for truncation: rows, output bytes, or time budget.
- ES: ``nz_describe_table`` — distribución HASH leyendo ``_v_table_dist_map`` con filtro ``DATABASE`` además de schema/tabla.
- EN: ``nz_describe_table`` — HASH distribution from ``_v_table_dist_map`` using ``DATABASE`` plus schema/table filters.

### Documentation
- ES: README y ``docs/guides/claude-desktop-setup.md`` — instalación recomendada con pipx/venv y rutas de ``command`` para Claude Desktop.
- EN: README plus ``docs/guides/claude-desktop-setup.md`` — pipx/venv-first install and ``command`` paths for Claude Desktop.

### Security
- ES: los mensajes de error del driver en `open_connection`, `list_databases` y `probe-catalog` pasan por `sanitize()` con `known_secrets` para no filtrar contraseñas en el `detail` expuesto al cliente MCP.
- EN: driver error messages in `open_connection`, `list_databases`, and `probe-catalog` are passed through `sanitize()` with `known_secrets` so passwords are not leaked in MCP-exposed `detail` fields.

### Changed
- ES: `nz-mcp test-connection` ya no es stub: usa `open_connection`, ejecuta `SELECT CAST(VERSION() AS VARCHAR(200))`, informa `OK: connected to … as <user>` o `FAIL: …` (detalle sanitizado) y código de salida 0/1.
- EN: `nz-mcp test-connection` is no longer a stub: uses `open_connection`, runs `SELECT CAST(VERSION() AS VARCHAR(200))`, prints `OK: connected to … as <user>` or `FAIL: …` (sanitized detail) with exit code 0/1.

### Added
- ES: tool `nz_create_table` — `CREATE TABLE` con columnas tipadas, `IF NOT EXISTS`, `DISTRIBUTE ON` / `ORGANIZE ON` (núcleo validado con `sql_guard` en `admin`; cláusulas Netezza añadidas con identificadores validados).
- EN: `nz_create_table` tool — `CREATE TABLE` with typed columns, `IF NOT EXISTS`, `DISTRIBUTE ON` / `ORGANIZE ON` (parseable core validated with `sql_guard` in `admin`; Netezza clauses appended using validated identifiers).
- ES: tool `nz_truncate` — `TRUNCATE TABLE` con perfil `admin` y `confirm=true` obligatorio.
- EN: `nz_truncate` tool — `TRUNCATE TABLE` with `admin` profile and mandatory `confirm=true`.
- ES: tool `nz_drop_table` — `DROP TABLE` con `IF EXISTS` opcional y `confirm=true` obligatorio.
- EN: `nz_drop_table` tool — `DROP TABLE` with optional `IF EXISTS` and mandatory `confirm=true`.
- ES: tool `nz_clone_procedure` — clona un SP entre bases/schemas (`mode=admin`), transformaciones solo sobre el body, `dry_run`/`confirm`, warnings por refs `DB..`, `PROCEDURE_ALREADY_EXISTS` si el destino existe sin `replace_if_exists`, auditoría structlog con `ddl_hash` (SHA-256).
- EN: `nz_clone_procedure` tool — clones an SP across databases/schemas (`mode=admin`), body-only transformations, `dry_run`/`confirm`, warnings for `DB..` refs, `PROCEDURE_ALREADY_EXISTS` when the target exists without `replace_if_exists`, structlog audit with SHA-256 `ddl_hash`.
- ES: paquete write — `nz_insert`, `nz_update`, `nz_delete` con SQL parametrizado, `sql_guard` en modo `write`, dry-run con `COUNT` y `confirm` para mutaciones reales.
- EN: write package — `nz_insert`, `nz_update`, `nz_delete` with parameterized SQL, `sql_guard` in `write` mode, dry-run via `COUNT` and `confirm` for real mutations.
- ES: paquete de procedures — `nz_list_procedures`, `nz_describe_procedure`, `nz_get_procedure_ddl`, `nz_get_procedure_section` (parser NZPLSQL por marcadores, rangos de líneas acotados).
- EN: procedures package — `nz_list_procedures`, `nz_describe_procedure`, `nz_get_procedure_ddl`, `nz_get_procedure_section` (marker-based NZPLSQL parser, capped line ranges).
- ES: tools `nz_table_sample`, `nz_table_stats` y `nz_get_table_ddl` — muestra de filas (`execute_select`), estadísticas de almacenamiento/datasets humanos IEC, y DDL `CREATE TABLE` reconstruido desde catálogo.
- EN: `nz_table_sample`, `nz_table_stats`, and `nz_get_table_ddl` tools — row sampling via `execute_select`, storage/IEC-formatted stats, and catalog-reconstructed `CREATE TABLE` DDL.
- ES: módulos `catalog/formatters.py` (`format_bytes_iec`) y `catalog/ddl_builder.py` (`build_create_table_ddl`).
- EN: `catalog/formatters.py` (`format_bytes_iec`) and `catalog/ddl_builder.py` (`build_create_table_ddl`) modules.
- ES: tools `nz_query_select` y `nz_explain` — ejecución de `SELECT` validado con `sql_guard`, `LIMIT` automático/streaming, y planes `EXPLAIN`/`EXPLAIN VERBOSE` sin ejecutar la query.
- EN: `nz_query_select` and `nz_explain` tools — `sql_guard`-validated `SELECT` execution with automatic `LIMIT`/streaming, and `EXPLAIN`/`EXPLAIN VERBOSE` plans without executing the query.
- ES: tool `nz_describe_table` para metadata de tabla (columnas, distribución, PK, FK) vía catálogo `_v_*`.
- EN: `nz_describe_table` tool for table metadata (columns, distribution, PK, FK) via `_v_*` catalog views.
- ES: tool `nz_get_view_ddl` para obtener el DDL `CREATE VIEW` desde `_v_view` (cross-database).
- EN: `nz_get_view_ddl` tool to fetch `CREATE VIEW` DDL from `_v_view` (cross-database).
- ES: tool `nz_list_views` para listar vistas en un schema vía catálogo `_v_view` (cross-database).
- EN: `nz_list_views` tool to list views in a schema via `_v_view` catalog (cross-database).
- ES: tool `nz_list_tables` para listar tablas base en un schema vía catálogo `_v_table` (sin vistas; cross-database).
- EN: `nz_list_tables` tool to list base tables in a schema via `_v_table` catalog (not views; cross-database).
- ES: tool `nz_list_schemas` para listar schemas en una base vía catálogo `_v_schema` (cross-database).
- EN: `nz_list_schemas` tool to list schemas in a database via `_v_schema` catalog (cross-database).
- ES: comando CLI `nz-mcp probe-catalog` para validar todas las consultas de catálogo contra Netezza (parámetros dummy, duración, filas; salida `--json` opcional).
- EN: `nz-mcp probe-catalog` CLI to validate all catalog queries against Netezza (dummy parameters, duration, rows; optional `--json` output).
- ES: soporte `catalog_overrides` por perfil para resolver SQL de catálogo por `query_id` desde `profiles.toml`.
- EN: added per-profile `catalog_overrides` to resolve catalog SQL by `query_id` from `profiles.toml`.
- ES: módulo `catalog/resolver.py` con validación de `query_id` desconocido y warning para uso de `<BD>..` en queries no cross-db.
- EN: added `catalog/resolver.py` with unknown `query_id` validation and warning when `<BD>..` is used on non cross-db queries.
- ES: validador de identificador de base de datos (`validate_database_identifier`) y render seguro `render_cross_db` para notación `<BD>.._V_*`.
- EN: added database identifier validator (`validate_database_identifier`) and safe `render_cross_db` support for `<BD>.._V_*` notation.
- ES: sección de seguridad para interpolación cross-database en `security-model.md` y pruebas adversariales/property-based del módulo.
- EN: added security guidance for cross-database interpolation in `security-model.md` plus adversarial/property-based tests.
- ES: tool `nz_list_databases` implementada con query a `_v_database` y filtro `LIKE` opcional.
- EN: implemented `nz_list_databases` tool using `_v_database` with optional `LIKE` filter.
- ES: capa de conexión real con `nzpy` (`open_connection`) con `timeout`, `application_name="nz-mcp"` y errores tipados.
- EN: real `nzpy` connection layer (`open_connection`) with `timeout`, `application_name="nz-mcp"`, and typed errors.
- ES: tests unitarios para conexión, catálogo y tool; además de test de integración local para `nz_list_databases`.
- EN: unit tests for connection, catalog, and tool; plus local integration test for `nz_list_databases`.
- ES: integración MCP real por stdio en `nz-mcp serve`, conectando `initialize`, `tools/list` y `tools/call` al dispatcher interno.
- EN: real MCP stdio integration in `nz-mcp serve`, wiring `initialize`, `tools/list`, and `tools/call` to the internal dispatcher.
- ES: test de contrato wire-level in-process para validar handshake, listado de tools y llamada con error estructurado.
- EN: in-process wire-level contract test to validate handshake, tools listing, and structured-error tool calls.
- ES: comando CLI `nz-mcp doctor` con diagnóstico local (sin red/Netezza) e informe i18n ES/EN.
- EN: `nz-mcp doctor` CLI for local diagnostics (no network/Netezza) with ES/EN i18n report.
- ES: estructura inicial del repositorio con `AGENTS.md` como router de despacho para agentes IA.
- EN: initial repository scaffolding with `AGENTS.md` as dispatch router for AI agents.
- ES: docs completas de arquitectura, roles senior (×8), estándares y ADRs (×7).
- EN: complete docs for architecture, senior roles (x8), standards and ADRs (x7).
- ES: contrato de tools v0.1 con 24 tools de responsabilidad única.
- EN: v0.1 tools contract with 24 single-responsibility tools.
- ES: estándar de issues AI-pickup-ready con templates y labels canónicos.
- EN: AI-pickup-ready issue standard with templates and canonical labels.
- ES: tools `nz_current_profile` y `nz_switch_profile` (sesión).
- EN: `nz_current_profile` and `nz_switch_profile` tools (session).
- ES: módulo `sql_guard` con clasificación basada en `sqlglot` y modos `read`/`write`/`admin`.
- EN: `sql_guard` module with `sqlglot`-based classification and `read`/`write`/`admin` modes.
- ES: gestión de credenciales con `keyring` OS-native + perfiles en TOML.
- EN: credentials management via OS-native `keyring` + TOML profiles.
- ES: catálogo i18n ES/EN para mensajes de error y hints.
- EN: ES/EN i18n catalog for error messages and hints.
- ES: CLI `nz-mcp init`, `add-profile`, `list-profiles`, `doctor`, `test-connection`, `serve`.
- EN: `nz-mcp init`, `add-profile`, `list-profiles`, `doctor`, `test-connection`, `serve` CLI.
- ES: CI con lint, type-check, tests y validación de convenciones (branches, commits, PRs).
- EN: CI with lint, type-check, tests and convention validation (branches, commits, PRs).
