# Auditoría de PR pre-merge

> Este doc es **vinculante**. Ningún PR se mergea sin pasar la auditoría completa.
> El **autor** ejecuta la auditoría sobre su propio PR. El **auditor** (otra IA u owner humano) la verifica.

## Roles

| Rol | Responsabilidad |
|---|---|
| **Autor (IA)** | Implementa, autoaudita, marca el checklist en el PR. |
| **Auditor (IA distinta o humano)** | Verifica el checklist independientemente. Tiene autoridad de **veto**. |
| **Owner (humano)** | Decide cuando autor y auditor están en desacuerdo. Validación final pre-release. |

**Regla de oro**: el auditor **no puede ser el mismo agente IA** que el autor en la misma sesión. Si solo hay un agente disponible, el owner humano es auditor.

## Las 7 dimensiones de auditoría

Cada PR se evalúa en estas 7 dimensiones. Cada una tiene **bloqueantes** (failing → no merge) y **observaciones** (failing → comentario, no bloquea).

### 1. Contrato y compatibilidad

**Bloqueantes:**
- [ ] Si hay cambio en una tool: `tools-contract.md` actualizado **en el mismo PR**.
- [ ] Si hay cambio observable por usuario: `CHANGELOG.md` con entrada bajo `## [Unreleased]`.
- [ ] Sin breaking en patch (solo en MINOR para v0.x, MAJOR para v1+).
- [ ] Si se renombra/elimina código de error: hay ventana de deprecación o ADR justificándolo.

**Observaciones:**
- [ ] Naming consistente con tools existentes (`nz_<verbo>_<objeto>`).

### 2. Seguridad

**Bloqueantes:**
- [ ] Todo SQL ejecutable pasa por `sql_guard.validate()`.
- [ ] Sin concatenación de SQL con strings (todo parametrizado).
- [ ] Sin `print()` ni `logging` exponiendo valores sensibles.
- [ ] Sin password en logs, configs, tests, fixtures, comentarios.
- [ ] Si toca `sql_guard.py` o `auth.py`: cobertura sigue en 100 %.
- [ ] Si toca `sql_guard.py`: añadidos ≥ 3 tests adversariales nuevos relevantes.
- [ ] Sin reducción de estrictez en guards sin **ADR + aprobación humana explícita**.
- [ ] Sin `--no-verify`, `--force` ni saltarse hooks.

**Observaciones:**
- [ ] Sanitizer cubre cualquier nuevo path de logging.

### 3. Mantenibilidad y diseño

**Bloqueantes:**
- [ ] PR cae en los **archivos esperados** según [maintainability.md](maintainability.md) (añadir tool ≠ tocar `server.py`).
- [ ] Sin nuevas abstracciones sin 3 usos reales.
- [ ] Sin nuevas dependencias sin ADR.
- [ ] Funciones < 50 líneas, clases < 300, args < 4.
- [ ] Cambios estructurales tienen **ADR**.
- [ ] PR < 400 líneas (sin tests/docs) o justificación explícita.
- [ ] **Una intención por PR** (no "y además…").

**Observaciones:**
- [ ] Sin magic strings repetidos (extraer a `Final`).
- [ ] Naming consistente con [coding.md](coding.md).

### 4. Tests

**Bloqueantes:**
- [ ] Hay tests para todo comportamiento nuevo.
- [ ] `pytest -m "not integration"` verde.
- [ ] Cobertura global ≥ 85 %, no cae respecto a `main`.
- [ ] `sql_guard.py` y `auth.py` siguen en 100 %.
- [ ] Si introduce tool nueva: hay test de contrato MCP que la incluye.
- [ ] Sin `pytest.skip()` ni `xfail` sin issue asociado.
- [ ] Sin `time.sleep()` ni dependencia de orden.

**Observaciones:**
- [ ] Property-based donde aplique (parsers, sanitizers).

### 5. Tipado y estilo

**Bloqueantes:**
- [ ] `ruff check .` limpio.
- [ ] `ruff format --check .` limpio.
- [ ] `mypy --strict` limpio en módulos tocados.
- [ ] Sin `Any` en superficies públicas (sin justificación).
- [ ] Sin `except Exception:` sin re-raise tipado.

**Observaciones:**
- [ ] Docstrings en clases/funciones públicas que cruzan módulos.

### 6. Documentación

**Bloqueantes:**
- [ ] Si cambia API pública: `tools-contract.md` actualizado.
- [ ] Si cambia comportamiento observable: `CHANGELOG.md` (entrada ES + EN).
- [ ] Si introduce decisión arquitectónica: ADR en `docs/adr/`.
- [ ] Mensajes nuevos: claves añadidas en ES **y** EN, test de paridad pasa.

**Observaciones:**
- [ ] README ES y EN actualizados si afecta a uso público.

### 7. Idioma y forma del PR

**Bloqueantes:**
- [ ] Título de PR en español, formato conventional commit.
- [ ] Descripción usa el `PULL_REQUEST_TEMPLATE.md` completo.
- [ ] Código y comentarios en inglés.
- [ ] Commits en español, conventional.

**Observaciones:**
- [ ] Squash message limpio (no historia de WIPs).

---

## Procedimiento

### Paso 1 — Auto-auditoría (autor)

1. Releer el diff completo línea por línea **antes** de nada.
2. Recorrer las 7 dimensiones, marcar checklist.
3. Si algún bloqueante falla: **no abrir el PR**, arreglar primero.
4. Si una dimensión necesita decisión arquitectónica nueva: crear ADR.
5. Abrir PR con checklist marcado en la descripción.

### Paso 2 — Auditoría independiente (auditor)

1. Auditor **no lee el checklist marcado del autor primero** — recorre las dimensiones por su cuenta.
2. Compara su resultado con el del autor. Discrepancia ≠ error: discutir.
3. Si bloqueante falla: comentario tipo `BLOQUEANTE: <dimensión> — <motivo>`.
4. Si observación: comentario normal.

### Paso 3 — Resolución

- Bloqueantes deben resolverse o convertirse en discusión arquitectónica (ADR + humano).
- Observaciones se resuelven o se difieren a issue (`label: tech-debt`).

### Paso 4 — Merge

- Solo cuando **todos los bloqueantes** están resueltos y **todas las conversaciones** cerradas.
- Squash merge.
- CI debe estar verde en el último commit.

---

## Plantilla de comentario de auditor

```markdown
## Auditoría — <fecha> — <auditor>

### Bloqueantes
- [ ] BLOQUEANTE: Seguridad — el guard no rechaza CTE con DELETE en RETURNING. Falta test adversarial.
- [ ] BLOQUEANTE: Mantenibilidad — la PR toca `server.py` para añadir una tool, viola el patrón.

### Observaciones
- Naming: `nz_get_proc` debería ser `nz_get_procedure_ddl` por consistencia con `nz_get_view_ddl`.
- Hint en respuesta podría ser más accionable.

### Aprobado en
- ✅ Contrato
- ✅ Tests
- ✅ Tipado
- ✅ Docs
- ✅ Idioma

### Veredicto
❌ **No mergear** hasta resolver bloqueantes.
```

---

## Casos de escalado al humano

El auditor IA escala al owner humano si:

1. Hay desacuerdo entre autor y auditor que no se resuelve en 2 ciclos.
2. Un bloqueante cae en zona gris (ej. "esto técnicamente cumple pero huele mal").
3. El cambio toca archivos de **alta sensibilidad** y la auditoría sola no basta.
4. Se propone reducir estrictez de un guard.
5. Se propone añadir dependencia poco conocida.
6. Conflicto entre dos ADRs.

---

## Métricas (referencia, no bloqueante)

El auditor puede marcar señales de salud:
- ¿Cuántos bloqueantes encontró? (alto → autor debería pre-auditarse mejor.)
- ¿Cuántos ciclos para mergear? (> 3 → algo está mal en la spec o el rol asumido.)
- ¿La PR rompió cobertura en algún módulo?

Estas métricas no bloquean merge pero alimentan retro.

---

## Resumen ejecutable

```
1. Lee tu diff entero.
2. Pasa las 7 dimensiones, marca todo.
3. Cualquier bloqueante sin marcar → no abres PR.
4. Auditor independiente repite las 7 dimensiones desde cero.
5. Bloqueantes pendientes → no merge.
6. Squash → main.
```

Si te saltas un paso, el sistema falla. Sin atajos.
