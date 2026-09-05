# Architecture Decision Records (ADR)

Aquí vive la **memoria de decisiones** del proyecto. Cada ADR captura el por qué de un cambio estructural.

## ¿Cuándo escribir un ADR?

- Cambias la spec congelada de [AGENTS.md](../../AGENTS.md).
- Añades dependencia.
- Cambias un patrón arquitectónico (registro de tools, módulo nuevo, capa nueva).
- Reduces estrictez de un guard de seguridad.
- Eliges entre dos enfoques con trade-offs no triviales.
- Difieres una capacidad a una versión futura.

Si dudas: escribe ADR. Es barato y futuro-tú lo agradecerá.

## ¿Cuándo NO?

- Cambios cosméticos (rename de variable, formato).
- Bug fixes que respetan la spec.
- Refactors que no cambian comportamiento.

## Plantilla

Ver [tech-lead.md](../roles/tech-lead.md#plantilla-adr-para-copiar-a-docsadrnnnn-nombremd).

## Convenciones

- Numerados con 4 dígitos (`0001-titulo.md`).
- Título en imperativo, kebab-case.
- Estado: `propuesto` → `aceptado` → opcionalmente `reemplazado por NNNN` u `obsoleto`.
- Fecha en ISO `YYYY-MM-DD`.
- Inglés o español: español por consistencia con el resto de docs internas.

## Índice

| # | Título | Estado | Fecha |
|---|---|---|---|
| 0001 | [# ADR 0001 — Adoptar Python 3.11 como mínimo](0001-adoptar-python-3-11.md) | aceptado |  |
| 0002 | [# ADR 0002 — Usar nzpy como driver primario de Netezza](0002-driver-nzpy.md) | aceptado |  |
| 0003 | [# ADR 0003 — Credenciales en `keyring` OS-native, metadata en TOML](0003-credenciales-keyring.md) | aceptado |  |
| 0004 | [# ADR 0004 — Integration tests solo locales en v0.1](0004-integration-tests-locales.md) | aceptado |  |
| 0005 | [# ADR 0005 — Sin frontend ni UI propia](0005-sin-frontend.md) | aceptado |  |
| 0006 | [# ADR 0006 — Tools con responsabilidad única](0006-tools-responsabilidad-unica.md) | aceptado |  |
| 0007 | [# ADR 0007 — Auditoría de PR con autor + auditor IA distintos](0007-auditoria-pr.md) | aceptado |  |
| 0008 | [# ADR 0008 — `required_approving_review_count = 0` mientras solo haya un mantenedor humano](0008-required-reviews-cero-solo-dev.md) | aceptado |  |
| 0009 | [# ADR 0009 — Expand tool catalog with bulk INSERT…SELECT and CTAS](0009-tool-catalog-bulk-ctas.md) | aceptado |  |
| 0010 | [Separación de Responsabilidad de Tamaños en Tool de Procedimientos](0010-tool-procedure-size.md) | aceptado | 2026-05-06 |
| 0011 | [Aislar la lógica de una tabla intermedia dentro de un SP](0011-tool-procedure-table-logic.md) | aceptado | 2026-05-06 |
| 0012 | [Análisis de impacto inverso — `nz_find_table_references`](0012-tool-find-table-references.md) | aceptado | 2026-05-06 |
| 0013 | [`nz_export_ddl` admite `output_path` para escribir el DDL a disco](0013-export-ddl-output-path.md) | aceptado | 2026-05-08 |
| 0014 | [Versionar perfiles de agente IA en `.claude/agents/` y whitelistear `.claude/` en hygiene](0014-claude-agents-whitelist.md) | aceptado | 2026-06-26 |
| 0014 | [`nz_execute_ddl` compila procedimientos/vistas y guarda de entorno `PROD_`](0014-tool-execute-ddl.md) | aceptado | 2026-07-09 |
| 0015 | [`CALL` como operación EXECUTE en `sql_guard`, gated a admin](0015-sql-guard-call-statement.md) | aceptado | 2026-07-09 |
| 0016 | [`nz_switch_database` — cambiar la BD de trabajo del perfil activo](0016-tool-switch-database.md) | aceptado | 2026-07-09 |
| 0017 | [`security_level` configurable por perfil, seguro por defecto](0017-connection-security-level.md) | aceptado | 2026-07-09 |
| 0018 | [Acotar la salida de `nz_list_procedures` y `nz_get_procedure_ddl`](0018-cap-procedures-output.md) | aceptado | 2026-09-04 |
| 0019 | [Dejar de declarar `outputSchema` en `tools/list`](0019-sin-output-schema.md) | aceptado | 2026-09-04 |
| 0020 | [Rechazar predicados WHERE siempre verdaderos salvo confirmación explícita](0020-sql-guard-tautological-where.md) | aceptado | 2026-09-04 |
| 0021 | [Diagnóstico real del fallo de conexión: capturar el logger de nzpy](0021-diagnostico-fallo-conexion.md) | aceptado | 2026-09-05 |
| 0022 | [Validar el SQL de `catalog_overrides` con `sql_guard`](0022-validar-catalog-overrides.md) | aceptado | 2026-09-05 |
| 0023 | [Mensajes de error accionables: detalle localizado + hint específico o nada](0023-mensajes-error-accionables.md) | aceptado | 2026-09-05 |

> **Colisión de numeración**: dos ADR comparten el número `0014`. Las referencias en prosa a "ADR 0014" del CHANGELOG y de la ADR 0015 apuntan a [`0014-tool-execute-ddl.md`](0014-tool-execute-ddl.md). No se renumeran para no romper esos enlaces.
