<!-- Título del PR debe cumplir el regex de docs/standards/git-workflow.md sección 3 -->

## ¿Qué cambia?
<!-- 1-3 frases. Por qué, no qué. -->

## Issue relacionado
Closes #<!-- N -->

## Acción según AGENTS.md
- **Ruta (keywords)**: <!-- ej: nueva tool, sql_guard -->
- **Docs leídos**:
  - <!-- ruta del doc 1 -->
  - <!-- ruta del doc 2 -->
- **Rol asumido**: <!-- ej: Backend Developer + Tech Lead -->

## Archivos esperados (según el issue)
<!-- Lista los archivos que el issue marca como "esperados" y comenta cualquier archivo extra que tocaste con justificación. -->

## Auditoría pre-merge — 7 dimensiones
> Marca todas las casillas. Bloqueantes sin marcar = no merge.
> Detalle: docs/standards/pr-audit.md

### 1. Contrato y compatibilidad
- [ ] Si toca tools: `docs/architecture/tools-contract.md` actualizado en este PR.
- [ ] Si hay cambio observable: `CHANGELOG.md` con entrada bilingüe en `Unreleased`.
- [ ] Sin breaking change inesperado.

### 2. Seguridad
- [ ] Todo SQL pasa por `sql_guard.validate()`.
- [ ] Sin SQL concatenado (parametrizado).
- [ ] Sin credenciales en código, logs, tests, fixtures, comentarios.
- [ ] Si toca `sql_guard.py` o `auth.py`: cobertura sigue en 100 %.
- [ ] Si toca `sql_guard.py`: ≥ 3 tests adversariales nuevos.

### 3. Mantenibilidad y diseño
- [ ] Toqué solo los archivos esperados (o documenté por qué no).
- [ ] Sin abstracciones nuevas sin 3 usos reales.
- [ ] Sin dependencias nuevas sin ADR.
- [ ] Funciones < 50 LoC, args < 4.
- [ ] Una intención por PR.
- [ ] PR < 400 LoC sin tests/docs (o justificado).

### 4. Tests
- [ ] Tests para todo comportamiento nuevo.
- [ ] `pytest -m "not integration"` verde local.
- [ ] Cobertura ≥ 85 % global, no cae respecto a `main`.
- [ ] Sin `pytest.skip()` ni `xfail` sin issue.

### 5. Tipado y estilo
- [ ] `ruff check .` y `ruff format --check .` limpios.
- [ ] `mypy --strict` limpio en módulos tocados.
- [ ] Sin `Any` en superficies públicas sin justificación.
- [ ] Sin `except Exception:` sin re-raise tipado.

### 6. Documentación
- [ ] Si cambia API pública: `tools-contract.md` actualizado.
- [ ] Si cambia comportamiento: `CHANGELOG.md` actualizado (ES + EN).
- [ ] Si introduce decisión arquitectónica: nuevo ADR en `docs/adr/`.
- [ ] Mensajes nuevos: claves añadidas en ES **y** EN.

### 7. Idioma y forma
- [ ] Título de PR en español, formato conventional commit.
- [ ] Branch cumple regex (validado por CI).
- [ ] Commits en español, conventional (validados por CI).
- [ ] Código y comentarios en inglés.

## Validación humana requerida
- [ ] Sí — explicar por qué:
- [ ] No

## Notas para el auditor
<!-- Contexto extra, riesgos identificados, ADRs creados, etc. -->
