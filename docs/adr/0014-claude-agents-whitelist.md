# 14. Versionar perfiles de agente IA en `.claude/agents/` y whitelistear `.claude/` en hygiene

Date: 2026-06-26

## Status

Accepted

## Context

El proyecto se desarrolla con asistentes IA siguiendo el índice de despacho de [AGENTS.md](../../AGENTS.md) y los roles de [docs/roles/](../roles/). Hasta ahora, cuando una sesión IA armaba un equipo de subagentes (uno por rol), esa configuración vivía solo en la sesión y se perdía: cada vez había que reconstruirla.

Claude Code permite definir subagentes reutilizables como archivos Markdown en `.claude/agents/<nombre>.md` (frontmatter `name`/`description`/`tools` + prompt de sistema). Versionarlos en el repo da una **base reanudable**: cualquiera que retome el proyecto obtiene el equipo ya definido, alineado con `AGENTS.md` y `docs/roles/`.

El obstáculo: la regla inviolable #9 de AGENTS.md prohíbe archivos de auto-ayuda en el repo, validada por `scripts/check_repo_hygiene.py`, cuyo `ALLOWED_TOP_DIRS` no incluye `.claude/`. La propia regla indica el procedimiento: si un directorio es legítimo, se añade a la whitelist **con un ADR que lo justifique** (las whitelists son contrato, no impulso).

## Decision

1. Añadir `.claude` a `ALLOWED_TOP_DIRS` en `scripts/check_repo_hygiene.py`.
2. Versionar en `.claude/agents/` un perfil por rol existente en `docs/roles/` (backend-developer, data-engineer, security-engineer, qa-engineer, dx-engineer, technical-writer, release-engineer, tech-lead), más un `integration-tester` que ejecuta `pytest -m integration` contra la instancia real de Netezza (accesible solo por VPN; ver [ADR-0004](0004-integration-tests-locales.md)).
3. Cada perfil es un **wrapper delgado**: no duplica especificación, remite a `AGENTS.md` (reglas + tabla de enrutamiento) y a `docs/roles/<rol>.md`.

El blacklist de tokens scratch (`notes`, `plan`, `wip`, …) sigue activo dentro de `.claude/`; solo se exime el directorio del whitelist top-level.

## Consequences

- ✅ Equipo de agentes reproducible y versionado; futuras sesiones parten de una base común.
- ✅ Los perfiles heredan automáticamente las reglas inviolables al apuntar a `AGENTS.md`.
- ✅ Se cubre el hueco de los integration tests (VPN) con un agente explícito.
- ⚠️ `.claude/` podría usarse para colar archivos no relacionados; mitigado porque el blacklist de tokens scratch sigue aplicando y el contenido se revisa en PR.
- ⚠️ Acopla el repo a la convención de Claude Code; aceptable: es la herramienta de desarrollo primaria del proyecto.
