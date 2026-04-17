# ADR 0001 — Adoptar Python 3.11 como mínimo

- **Fecha**: 2026-04-16
- **Estado**: aceptado
- **Decidido por**: Tech Lead (IA) + validación humana

## Contexto

`nz-mcp` se distribuye a la comunidad. Necesitamos elegir versión mínima de Python que balancee:
- Features modernas del lenguaje (match, mejor tipado, `tomllib`).
- Adopción real entre usuarios (no forzar a la última versión).
- Soporte largo (no quedar atrapados en una versión cercana a EOL).

## Decisión

Soportar Python **3.11+** como versión mínima. CI prueba 3.11 y 3.12 cross-OS.

## Alternativas consideradas

1. **3.10** — funciona, pero deja fuera `tomllib` nativo y mejoras grandes de tracebacks/perf de 3.11.
2. **3.12** — muy nuevo aún para forzar a usuarios; algunas distros y entornos corporativos van detrás.
3. **3.13** — descartado por inmadurez en el ecosistema de deps en abril 2026.

## Consecuencias

- ✅ `tomllib` nativo (sin `tomli` como dep).
- ✅ Mejor tipado y `Self`, `LiteralString`.
- ✅ Tracebacks más útiles, mejor perf.
- ⚠️ Usuarios en 3.10 deben actualizar — documentado en README.
- ⚠️ Cuando 3.11 entre en EOL (~ oct 2027) reevaluar.

## Monitorizar

- Issues con label `python-version` que pidan 3.10.
- EOL schedule oficial.
