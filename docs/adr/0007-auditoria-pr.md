# ADR 0007 — Auditoría de PR con autor + auditor IA distintos

- **Fecha**: 2026-04-16
- **Estado**: aceptado
- **Decidido por**: Tech Lead + Owner humano

## Contexto

El proyecto se desarrolla **100 % con IA**. El humano (owner) valida al final pero no escribe código. Necesitamos un mecanismo de calidad que:

- No dependa exclusivamente del juicio del humano (no escala, fatiga, sesgo).
- No sea autocomplaciente (un mismo agente que autor + reviewer tiende a pasar todo).
- Sea reproducible y auditable.

## Decisión

Toda PR pasa por **dos pasadas**:

1. **Autoauditoría** (autor): el agente que escribió el código recorre las 7 dimensiones de [pr-audit.md](../standards/pr-audit.md) y marca el checklist.
2. **Auditoría independiente** (auditor distinto): otra instancia de IA (sesión nueva, contexto limpio) repite las 7 dimensiones desde cero. Tiene autoridad de **veto** sobre bloqueantes.
3. **Owner humano** decide en caso de disputa o cuando aplica una regla de escalado.

El **auditor no puede ser la misma sesión** que el autor. Si solo hay un agente disponible en el momento, el owner humano hace de auditor.

Las 7 dimensiones: contrato, seguridad, mantenibilidad, tests, tipado/estilo, documentación, idioma/forma.

## Alternativas consideradas

1. **Solo autoauditoría** — el agente que escribió el código tiende a no encontrar sus propios fallos (sesgo de confirmación). Rechazado.
2. **Solo humano review** — no escala, retrasa flow.
3. **CI lint estricto + humano** — los linters no detectan problemas de diseño, contrato o seguridad arquitectónica.
4. **Auditor humano siempre** — el humano es el cuello de botella; este proyecto está diseñado para que el humano haga validación final, no review línea por línea.

## Consecuencias

- ✅ Detección temprana de bloqueantes sin requerir al humano.
- ✅ Memoria del proceso (PR template + checklist marcados → trazabilidad).
- ✅ Auditor con contexto limpio cataliza descubrir asunciones implícitas.
- ⚠️ Coste extra por PR (otra pasada de IA). Aceptable dado el riesgo del MCP de tocar BD productiva.
- ⚠️ Riesgo: dos agentes con mismos sesgos del mismo modelo. Mitigado por checklist riguroso por dimensión.

## Monitorizar

- Bloqueantes encontrados por auditor que el autor no detectó (señal de calidad del proceso).
- Releases con bugs que la auditoría debería haber pillado (señal de gaps en el checklist).
- Tiempo medio de PR (autoría → merge) (no debe explotar).
