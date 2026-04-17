# Playbook — Release

> Solo el rol Release Engineer ejecuta releases. La validación final es **humana**.
> Lee primero [release-engineer.md](../roles/release-engineer.md).

## Pre-requisitos

- Branch `main` limpia, CI verde en último commit.
- `CHANGELOG.md` con sección `## [Unreleased]` poblada con todos los cambios desde la release anterior.
- `pyproject.toml` con `version` actualizada (preview manual: bump al número objetivo).

## Pasos

### 1. Determinar la versión (SemVer)

| Tipo de cambios desde última release | Bump |
|---|---|
| Solo `Fixed`, `Security` patch | PATCH |
| Algún `Added` o `Changed` no breaking | MINOR |
| `Removed` o breaking en `Changed` (v1+) | MAJOR |
| En v0.x: breaking cabe en MINOR | MINOR |

### 2. Pre-flight (local)

```bash
ruff check .
ruff format --check .
mypy --strict src/
pytest -m "not integration" --cov=src/nz_mcp --cov-fail-under=85
```

Todo debe pasar.

### 3. Validación humana de integration

> Bloqueante. Sin esto, no hay release.

```bash
# Con VPN activa, perfil de pruebas configurado
pytest -m integration -v
```

Documentar en el commit de release: "integration tests passed local on YYYY-MM-DD by <human>".

### 4. Cerrar `CHANGELOG.md`

- Mover `## [Unreleased]` a `## [vX.Y.Z] — YYYY-MM-DD`.
- Añadir nuevo `## [Unreleased]` vacío en la cima (con subsecciones placeholder).
- Mantener formato Keep a Changelog.
- Incluir links de comparación al final.

### 5. Bump version

- Editar `pyproject.toml` → `version = "X.Y.Z"`.
- Si hay `__version__` en `src/nz_mcp/__init__.py`, sincronizar.

### 6. Commit y tag

```bash
git checkout -b release/vX.Y.Z
git add CHANGELOG.md pyproject.toml src/nz_mcp/__init__.py
git commit -m "chore(release): vX.Y.Z"
# PR → review → merge a main
# Tras merge:
git checkout main
git pull
git tag -s vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

El push del tag dispara `release.yml`:
- Build con `python -m build`.
- Publica a PyPI vía Trusted Publishing OIDC.
- Crea GitHub Release con notas auto-generadas.

### 7. Verificación post-release

- [ ] PyPI muestra la versión nueva.
- [ ] `pipx install nz-mcp==X.Y.Z` funciona en una máquina limpia.
- [ ] `nz-mcp --version` reporta `X.Y.Z`.
- [ ] GitHub Release publicada con notas.
- [ ] README badges actualizados (versión).
- [ ] Anuncio (si aplica) en discusiones del repo.

## Anti-patrones

- ❌ Release desde laptop sin pasar por tag + workflow.
- ❌ Bumpear PATCH con breaking change.
- ❌ Tag sin firmar.
- ❌ Soltar release sin integration tests verificados por humano.
- ❌ Hardcodear secretos PyPI en workflows (siempre OIDC).
- ❌ Releases consecutivos en < 1 hora sin razón clara (probablemente algo se rompió).

## Si algo sale mal

- **Build falla**: revierte el tag local (`git tag -d vX.Y.Z`), arregla, intenta de nuevo. **No** dejes el tag remoto roto.
- **PyPI publish falla**: verifica permisos OIDC; nunca hagas `twine upload` manual desde laptop.
- **Versión equivocada publicada**: PyPI no permite borrar; publicar `X.Y.Z+1` con `## [Yanked]` en CHANGELOG.

## Plantilla de release notes (si las auto-generadas no bastan)

```markdown
## vX.Y.Z — YYYY-MM-DD

### Highlights
- <una línea por cambio importante, ES>
- <one line per important change, EN>

### Added
- ES: …
- EN: …

### Changed / Fixed / Security / Removed
…

### Compatibilidad
- Python 3.11, 3.12
- Netezza NPS 11.x

### Migración (si aplica)
…
```
