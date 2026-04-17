# ADR 0008 — `required_approving_review_count = 0` mientras solo haya un mantenedor humano

- **Fecha**: 2026-04-17
- **Estado**: aceptado
- **Decidido por**: Owner humano + Tech Lead (IA)

## Contexto

Branch protection en `main` se configuró inicialmente con `required_approving_review_count = 1` y `require_code_owner_reviews = true`. Esto bloquea cualquier PR del único mantenedor (Oscarsp15) porque GitHub no permite que un autor apruebe su propio PR.

El proyecto se desarrolla 100 % por agentes IA. La auditoría real ya ocurre vía:
- `pr-audit.md` (autor IA + auditor IA distinto, ADR 0007).
- CI obligatorio: `Lint + type`, `Branch name`, `PR title`, `PR body has Closes/Refs`, `Commit subjects`.
- `CODEOWNERS` mapeado al owner para alta sensibilidad (sigue funcionando como notificación).

## Decisión

`required_approving_review_count = 0` mientras solo haya **un mantenedor humano**. Todo lo demás se mantiene:

- PR obligatorio.
- Status checks obligatorios pasan en verde antes de merge.
- `dismiss_stale_reviews = true` (cuando empiece a haber).
- Linear history forzado.
- Sin force push.
- Sin deletions.
- Conversaciones resueltas obligatorio.
- `enforce_admins = false` (owner sigue pudiendo override en emergencia documentada).
- Squash merge único método permitido.
- Branch borrada al mergear.

## Alternativas consideradas

1. **Mantener 1 review + forzar `--admin` en cada PR** — convierte cada merge en bypass, anula la regla, ruido en logs.
2. **Mantener 1 review + auto-aprobar con bot** — añadir GitHub App propio para aprobar es ingeniería sobrada para 1 dev.
3. **Aceptar bot externo (CodiumAI / etc.) como reviewer obligatorio** — añade dep externa, costo y dependencia que no necesitamos en v0.x.

## Consecuencias

- ✅ Flujo PR funciona sin admin override.
- ✅ Auditoría real (pr-audit.md + CI) sigue intacta.
- ⚠️ Sin segunda mirada humana en cambios críticos. Mitigado: la IA auditor + CODEOWNERS notifica al owner para alta sensibilidad, y el owner siempre puede pedir cambios o revertir.
- ⚠️ Cuando aparezca un segundo mantenedor humano, **revertir a 1 review** (subir requirement, actualizar este ADR a `reemplazado por NNNN`).

## Trigger de revisión

Cuando alguno se cumpla → ADR nuevo subiendo a `required_approving_review_count = 1`:
- Aparece un segundo mantenedor humano con permisos.
- El proyecto supera 100 ⭐ y empieza a tener PRs externos significativos.
- Cualquier incidente de seguridad mergeado por falta de doble revisión.

## Monitorizar

- PRs mergeados sin revisión humana real (todos hasta que se cumpla el trigger).
- Incidentes que una segunda mirada habría detectado.
