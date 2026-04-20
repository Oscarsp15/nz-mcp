# Changelog

Todos los cambios notables a este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y este proyecto adhiere a [SemVer](https://semver.org/spec/v2.0.0.html).

Cada entrada se documenta en **español** y **english**.

## [Unreleased]

### Changed
- ES: ``configure_logging_for_stdio`` eleva el logger ``nzpy`` a ``WARNING`` bajo stdio para silenciar el DEBUG/INFO por paquete que rompe la UI de los clientes que renderizan en stderr (p.ej. la barra de progreso de ``nz-workbench kb-bootstrap``).
- EN: ``configure_logging_for_stdio`` raises the ``nzpy`` logger to ``WARNING`` under stdio so the per-packet DEBUG/INFO noise no longer shreds client UIs that render on stderr (e.g. the ``nz-workbench kb-bootstrap`` progress bar).
- ES: ``nz_insert`` — por defecto ``dry_run=true`` y ``confirm`` obligatorio para ejecutar (mismo patrón que update/delete).
- EN: ``nz_insert`` — defaults to ``dry_run=true`` and requires ``confirm`` to execute (same pattern as update/delete).
- ES: ``nz_create_table`` — por defecto ``dry_run=true``; para ejecutar en el servidor hace falta ``dry_run=false`` y ``confirm=true``. Salida alineada con otras tools DDL: ``ddl_to_execute``, ``executed``, ``duration_ms``.
- EN: ``nz_create_table`` — defaults to ``dry_run=true``; execution requires ``dry_run=false`` and ``confirm=true``. Output aligned with other DDL tools: ``ddl_to_execute``, ``executed``, ``duration_ms``.

### Added
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
