# Equipo de agentes IA — nz-mcp

Perfiles de subagente (Claude Code) reutilizables para que cualquier sesión retome el proyecto con un equipo ya definido. Cada perfil es un **wrapper delgado**: no duplica la spec, apunta a la fuente canónica (`AGENTS.md` + `docs/roles/`).

## Cómo funciona
1. `AGENTS.md` es el índice de despacho: su **tabla de enrutamiento** mapea keywords de tu tarea → docs obligatorios.
2. `docs/roles/<rol>.md` es la especificación de cada rol.
3. Cada archivo `.claude/agents/<rol>.md` define un subagente que **lee esos dos** antes de actuar.

## Perfiles

| Agente | Rol (`docs/roles/`) | Para qué |
|--------|---------------------|----------|
| `backend-developer` | backend-developer | Bugs de lógica, nuevas tools, DML/INSERT/UPDATE |
| `data-engineer` | data-engineer | Dialecto Netezza: DDL, DISTRIBUTE/ORGANIZE, vistas, SPs |
| `security-engineer` | security-engineer | sql_guard, auth, SSL/securityLevel, sanitización |
| `qa-engineer` | qa-engineer | Tests unit/contract/integración fieles al motor real |
| `dx-engineer` | dx-engineer | Hints de error, descripciones de tools, i18n |
| `technical-writer` | technical-writer | Docs, ADRs, guías ES/EN |
| `release-engineer` | release-engineer | CI, versionado, CHANGELOG, releases |
| `tech-lead` | tech-lead | Prioriza, triajea, revisa y delega |
| `integration-tester` | (qa, ejecución) | Corre `pytest -m integration` contra Netezza real **(requiere VPN)** |

## Backlog
Las tareas abiertas viven como **issues `ai-task`** (label `ai-ready`) en GitHub. Un agente toma una, lee los "Docs obligatorios" del issue y entrega un PR. Ver `.github/ISSUE_TEMPLATE/ai-task.yml` y el workflow `auto-claim`.

## Nota sobre integración (VPN)
La instancia Netezza es on-premise/SaaS y solo accesible por VPN corporativa; CI corre `pytest -m "not integration"` (ver `docs/adr/0004-integration-tests-locales.md`). El agente `integration-tester` cubre ese hueco ejecutando los tests reales desde la PC del dev cuando la VPN está activa.
