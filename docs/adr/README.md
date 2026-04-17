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
| 0001 | [Adoptar Python 3.11 como mínimo](0001-adoptar-python-3-11.md) | aceptado | 2026-04-16 |
| 0002 | [Usar nzpy como driver primario](0002-driver-nzpy.md) | aceptado | 2026-04-16 |
| 0003 | [Credenciales en keyring OS-native](0003-credenciales-keyring.md) | aceptado | 2026-04-16 |
| 0004 | [Tests de integración solo locales en v0.1](0004-integration-tests-locales.md) | aceptado | 2026-04-16 |
| 0005 | [Sin frontend ni UI propia](0005-sin-frontend.md) | aceptado | 2026-04-16 |
| 0006 | [Tools con responsabilidad única](0006-tools-responsabilidad-unica.md) | aceptado | 2026-04-16 |
| 0007 | [Auditoría de PR con autor + auditor IA distintos](0007-auditoria-pr.md) | aceptado | 2026-04-16 |
| 0008 | [`required_approving_review_count = 0` mientras solo haya un mantenedor humano](0008-required-reviews-cero-solo-dev.md) | aceptado | 2026-04-17 |
