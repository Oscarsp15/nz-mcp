# Workflow de issues (AI-pickup)

> Diseñado para que **agentes IA puedan tomar issues y resolverlos sin asistencia humana adicional**, manteniendo la calidad por la auditoría dual ([pr-audit.md](pr-audit.md)).

## Principios

1. **Issue self-contained**: una IA con contexto cero del proyecto debe poder leer un issue y empezar a trabajar.
2. **Una intención por issue**: si tiene "y además…", son dos issues.
3. **Trazable**: cada PR cierra ≥ 1 issue. Cada issue cerrado por PR (o explícitamente declarado "no se hace" + razón).
4. **Reversible**: cualquier issue puede pasar a `human-only` si la IA descubre ambigüedad.

## Estructura obligatoria de un issue

Todo issue (creado por humano o IA) debe tener estos campos. Los templates los fuerzan.

| Campo | Obligatorio | Para qué |
|---|---|---|
| **Título** | ✅ | Imperativo, conventional style: `feat(tools): añade nz_X` |
| **Tipo** | ✅ | `bug` / `feature` / `tool` / `security` / `refactor` / `docs` / `adr` / `chore` |
| **Contexto** | ✅ | Por qué existe el issue, qué problema resuelve |
| **Acceptance criteria** | ✅ | Lista markdown de checkboxes verificables |
| **Acción AGENTS.md** | ✅ | Keywords de la tabla de enrutamiento que aplican |
| **Docs obligatorios** | ✅ | Lista de docs que la IA debe leer antes de empezar |
| **Rol esperado** | ✅ | Tech Lead / Backend / Data / Security / QA / Release / Writer / DX |
| **Archivos esperados** | ⚠️ | Lista hint, no exhaustiva — si la IA toca archivos no listados, la auditoría la cuestiona |
| **Out of scope** | ⚠️ | Qué explícitamente NO hacer en este PR |
| **Complejidad** | ✅ | `S` (< 100 LoC), `M` (100-400), `L` (400-1000), `XL` (> 1000 — partir) |
| **Prioridad** | ✅ | `P0` (bloqueante), `P1` (siguiente release), `P2` (cuando se pueda), `P3` (nice-to-have) |
| **Bloqueado por** | ⚠️ | IDs de issues que deben cerrarse antes |

## Sistema de labels (canónico)

Sincronizado por `.github/workflows/sync-labels.yml` desde `.github/labels.yml`. **No** crear labels ad-hoc.

### Estado del issue
- `triage` — recién creado, sin clasificar.
- `ai-ready` — bien definido, una IA puede tomarlo.
- `needs-spec` — falta definición; humano debe afinar.
- `human-only` — requiere humano (decisión arquitectónica grande, cambio de spec congelada, validación de seguridad sensible).
- `claimed` — alguna IA ya está trabajando (auto-asignado al crear el draft PR linkeado).
- `blocked` — depende de otro issue/PR sin resolver.
- `wontfix` — decidido no implementar.

### Tipo
- `type/bug`, `type/feature`, `type/tool`, `type/security`, `type/refactor`, `type/docs`, `type/adr`, `type/chore`, `type/test`.

### Área del repo
- `area/security` (sql_guard, auth)
- `area/tools` (tools/, registro, contrato)
- `area/catalog` (catalog/, queries _v_*)
- `area/connection` (driver, pool, streaming)
- `area/cli` (typer wizard, comandos)
- `area/server` (mcp server, handshake)
- `area/i18n`
- `area/ci` (GitHub Actions, releases)
- `area/docs`

### Prioridad
- `priority/P0`, `priority/P1`, `priority/P2`, `priority/P3`.

### Complejidad
- `complexity/S`, `complexity/M`, `complexity/L`, `complexity/XL`.

### Otros útiles
- `good-first-issue` — onboarding fácil (humanos o IAs nuevas).
- `help-wanted` — owner reconoce que necesita contribuciones.
- `breaking-change` — afecta contrato público.
- `regression` — algo que funcionaba dejó de funcionar.

## Protocolo de claim (para evitar dos IAs trabajando en lo mismo)

### Claim automático por bot (desde v0.1)

El **draft PR con `Closes #N`** ES el claim real. Un workflow (`.github/workflows/auto-claim.yml`) aplica en automático, al detectar el PR:

- Añade label `claimed` al issue.
- Asigna al autor del PR al issue.

Al cerrar el PR sin mergear, el bot **revoca** el claim (quita label + desasigna). Al mergear, GitHub cierra el issue por sí mismo.

**Consecuencia práctica**: ningún contributor necesita permisos de `issues:write` para reclamar un issue. Los contributors externos desde fork solo abren el PR y el bot hace el resto.

### Protocolo (aplica a todos, internos y externos)

1. Antes de empezar, comprobar que el issue **no tiene** label `claimed` ni assignee. Si los tiene, alguien más está trabajando en él.
2. **Crear draft PR** desde tu rama (o tu fork) con:
   - Título en formato conventional (`<tipo>(<scope>): <descripción>`).
   - **Cuerpo usando `.github/PULL_REQUEST_TEMPLATE.md` completo**, con `Closes #N` en la sección "Issue relacionado".
3. (Opcional, recomendado) Comentar en el issue: `🤖 Tomando este issue. Sesión: <id-corto>. PR: #<pr-n>.` — aumenta trazabilidad pero el bot hace el claim igualmente.
4. **Renunciar** si descubres que el issue es más grande, ambiguo o requiere `human-only`:
   - Cierra el draft PR **sin merge**. El bot revoca el claim automáticamente.
   - Comenta en el issue: `🤖 Renuncio: <razón>. Vuelvo a dejar el issue libre.`
5. **Timeout de claim**: si un `claimed` lleva > 7 días sin commit en su PR linkeado, otra IA puede reclamarlo (comentando primero). Ver `.github/workflows/stale-claim.yml`.

### Contributors externos desde fork (OSS típico)

Contributors sin permisos de `issues:write` en el repo base:

1. `gh repo fork Oscarsp15/nz-mcp` → trabaja en el fork.
2. Rama con nombre cumpliendo regex de [`git-workflow.md`](git-workflow.md) §1.
3. Push al fork; `gh pr create --repo Oscarsp15/nz-mcp` abre PR hacia `Oscarsp15:main`.
4. Primera vez: el owner debe aprobar workflows manualmente en `Actions` (política `Require approval for first-time contributors`). Tras una aprobación, los siguientes pushes corren automático.
5. El **auto-claim** aplica igual — no se requiere `issues:write` en el repo base.
6. Tras merge: GitHub borra la rama del fork automáticamente (ya configurado con `delete_branch_on_merge=true`).

Ver también `CONTRIBUTING.md` sección **"Fork workflow for external contributors"**.

**Detector de doble-trabajo**: workflow `stale-claim.yml` corre semanalmente y comenta los `claimed` sin actividad reciente.

## Flujo extremo a extremo

```
[Humano o IA crea issue con template]
        │
        ▼
[Label inicial: triage]
        │
        ▼
[Owner / Tech Lead reclasifica → ai-ready o needs-spec o human-only]
        │
        ▼ (ai-ready)
[Otra IA escanea ai-ready sin claim, elige uno por prioridad/complexity]
        │
        ▼
[Claim: comentario + assignee + label claimed + draft PR Closes #N]
        │
        ▼
[Lee AGENTS.md → ruta keywords → docs obligatorios → adopta rol]
        │
        ▼
[Implementa, autoaudita pr-audit.md]
        │
        ▼
[PR ready for review]
        │
        ▼
[Auditor IA distinto + opcional review humano]
        │
        ▼
[Squash merge → issue auto-cerrado por "Closes #N"]
```

## ¿Quién decide qué label inicial?

- **Humano (owner)** clasifica issues nuevos creados por humanos.
- **Para issues creados por IA** (auto-discovery, refactors, follow-ups): la IA propone labels en el cuerpo del issue (`Sugerencias de labels: type/refactor area/tools complexity/M priority/P2`); el owner ratifica con `/triage` o reclasifica manualmente.

## Reglas para issues creados por IA

- Si una IA descubre un bug mientras trabaja en otro issue, **abre issue separado** con label `triage`. No mete el fix en el PR actual (rompe "una intención por PR").
- Si una IA detecta deuda técnica, **abre issue** con `type/refactor` `triage` y referencia desde el código (`# TODO(#N): ...`).
- Si una IA propone una decisión arquitectónica, **abre issue** con `type/adr` `human-only`.

## Buenas prácticas de redacción

- **Sé específico**: "Cuando la query devuelve 0 filas, la respuesta tiene `truncated=true`" > "el output es raro a veces".
- **Adjunta evidencia**: stack trace, query, profile, versión.
- **Acceptance criteria verificables**: "El test `test_X` pasa" > "Funciona bien".
- **Sin información sensible**: nunca pegar passwords, tokens, datos reales con PII.

## Ejemplo de issue bien hecho (formato resultante del template)

```markdown
## Tipo
type/tool

## Contexto
La tool `nz_describe_table` no devuelve la información de organized-on para tablas que la usan. Esto genera planes de query subóptimos cuando la IA decide filtros.

## Acceptance criteria
- [ ] El output incluye campo `organized_on: list[str]` (vacío si no aplica).
- [ ] Test unitario con tabla mockeada que tiene organized-on.
- [ ] Test contract verifica el schema actualizado.
- [ ] tools-contract.md actualizado.
- [ ] CHANGELOG entrada bilingüe en Unreleased.

## Acción AGENTS.md
Keywords: `describe`, `metadata`, `catálogo`

## Docs obligatorios
- docs/architecture/tools-contract.md
- docs/roles/data-engineer.md
- docs/standards/coding.md
- docs/standards/pr-audit.md

## Rol esperado
Data Engineer + Backend Developer

## Archivos esperados (hint)
- src/nz_mcp/catalog/tables.py
- src/nz_mcp/tools/tables.py (o donde viva la tool)
- tests/unit/test_tools_describe_table.py
- docs/architecture/tools-contract.md
- CHANGELOG.md

## Out of scope
- No tocar `nz_get_table_ddl` en este PR.
- No añadir campos nuevos al output más allá de `organized_on`.

## Complejidad
S

## Prioridad
P2

## Bloqueado por
—
```

## Anti-patrones

- ❌ Issue sin acceptance criteria verificables.
- ❌ Issue de "mejorar X" sin definir qué.
- ❌ Tomar un issue sin label `ai-ready`.
- ❌ Trabajar sin claim (otra IA puede empezar lo mismo).
- ❌ Mezclar dos issues en un PR.
- ❌ Cerrar issue sin PR ni explicación.
- ❌ Crear labels ad-hoc fuera de `labels.yml`.
