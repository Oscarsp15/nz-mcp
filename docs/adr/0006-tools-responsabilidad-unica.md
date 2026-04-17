# ADR 0006 — Tools con responsabilidad única

- **Fecha**: 2026-04-16
- **Estado**: aceptado
- **Decidido por**: Tech Lead + Security Engineer (IA) + validación humana

## Contexto

Existen dos modelos de diseño para tools MCP que tocan SQL:

1. **Multitool**: una sola tool `nz_execute_sql` que acepta cualquier SQL y un parámetro `mode`.
2. **Una tool por operación**: tools específicas (`nz_query_select`, `nz_insert`, `nz_update`, `nz_delete`, `nz_truncate`, `nz_drop_table`, etc.) — cada una valida que el SQL recibido sea de su tipo.

Trade-offs:

- Multitool: superficie de API más pequeña (1 tool vs ~20).
- Una tool por op: superficie clara para el LLM, validación más fácil de auditar, anotaciones MCP correctas (`destructiveHint`, `readOnlyHint`) por tool.

## Decisión

**Una tool por operación.** Catálogo v0.1 con 24 tools agrupadas por categoría (lectura, escritura, DDL, sesión).

## Alternativas consideradas

1. **Multitool puro** — peor UX para el LLM (la descripción es ambigua), peor seguridad (`mode` es runtime, no contrato), peores `annotations` (no podemos marcar `destructiveHint` solo cuando aplique).
2. **Híbrido** (lectura unificada + escritura específica) — inconsistente, mismo problema parcial.
3. **Tools dinámicas** (descubrir según permisos del perfil) — confunde al LLM y rompe el principio de contrato estable.

## Consecuencias

- ✅ Cada tool tiene una descripción clara y `annotations` precisas.
- ✅ El LLM aprende a usar la tool correcta sin ramificar lógica.
- ✅ Tests por tool, validación por tool, métricas por tool.
- ✅ Permite tools especializadas (`nz_get_view_ddl`, `nz_get_procedure_section`, `nz_clone_procedure`) que serían imposibles en multitool.
- ⚠️ Más superficie de mantenimiento. Mitigado por registro decorador en `tools.py`.
- ⚠️ Más texto que el LLM debe procesar al listar tools (acotado: ~24 tools < umbral problemático).

## Monitorizar

- Si una tool nunca se usa según logs → candidata a deprecar.
- Si dos tools compiten en la mente del LLM (logs de uso erróneo) → revisar descripciones.
