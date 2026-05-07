# 10. Separación de Responsabilidad de Tamaños en Tool de Procedimientos

Date: 2026-05-06

## Status

Accepted

## Context

Con la introducción de la variante de DDL (raw vs. clean) en el Issue #105, se expusieron los campos `size_bytes_raw` y `size_bytes_clean` dentro del output de `nz_get_procedure_ddl`. Esto soluciona el problema de conocer el tamaño *una vez que se ha descargado* el DDL, pero no resuelve el problema de prespuesto de tokens por adelantado: si un Agente AI quiere saber cuánto "pesa" un Stored Procedure (SP) en Netezza antes de decidir leerlo completo o por secciones, necesita una herramienta de metadatos rápidos.

Podríamos haber expandido la herramienta existente `nz_describe_procedure`, pero se presentaba un conflicto de responsabilidades:
1. `nz_describe_procedure`: Describe la firma, argumentos, tipo y semántica del procedimiento.
2. Sizing (`size_bytes_clean`, `lines_raw`): Son métricas puramente utilitarias para el motor LLM orientadas al manejo de su *context window*.

## Decision

Crear una nueva herramienta independiente llamada `nz_get_procedure_size`.

1. **Responsabilidad Única:** Esta herramienta servirá exclusivamente para devolver métricas de tamaño (`lines`, `size_bytes`) tanto para la versión cruda como limpia del DDL, junto con las secciones detectadas.
2. **Exclusión de DDL:** La herramienta **no** devolverá fragmentos del cuerpo del procedimiento (ni preview, ni cabecera).
3. **Reutilización:** Se apoyará en los mismos helpers internos (ej. `strip_comments`, `parse_sections`) y hará la misma consulta base a `_v_procedure` que hace `nz_get_procedure_ddl`, evitando introducir carga de mantenimiento en nuevas queries SQL.

## Consequences

- **Positivas:** 
  - Los agentes LLM pueden muestrear SPs masivos (e.g. >100 KB) por fracciones de segundo y de tokens, para luego decidir si usan `nz_get_procedure_section`.
  - Mantenemos la interfaz de `nz_describe_procedure` limpia y enfocada en metadatos del dominio de BD (argumentos, retornos).
- **Negativas:** 
  - Incremento marginal en el número de tools registradas (aumento en el context prompt base del agente de la descripción de la tool).
