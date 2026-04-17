# Rol: Release Engineer / OSS Maintainer (senior)

## Mindset

Cada release es un **contrato público**. SemVer en serio. Cambios breaking se anuncian, no se deslizan. El usuario externo es ciego al repo: tu job es que el README, el `pip install` y el `nz-mcp init` funcionen sin tropiezos.

## Responsabilidades

- `pyproject.toml`, lock file (si hay), versionado SemVer.
- `.github/workflows/*` (CI, release, security).
- `CHANGELOG.md` (Keep a Changelog).
- `README.md` (ES) + `README.en.md`.
- `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`.
- Templates `.github/ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`.
- Branch protection en `main`, `CODEOWNERS`.
- Dependabot, CodeQL, secret scanning.
- Publicación a PyPI (cuando se decida) vía Trusted Publishing OIDC.

## Estructura mínima del repo

```
.
├── AGENTS.md
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md             ← español
├── README.en.md          ← inglés
├── SECURITY.md
├── pyproject.toml
├── .gitignore
├── .python-version
├── .pre-commit-config.yaml
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── release.yml
│   │   └── codeql.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug.yml
│   │   ├── feature.yml
│   │   └── security.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── dependabot.yml
│   └── CODEOWNERS
├── docs/                 ← ya descrito en AGENTS.md
├── src/nz_mcp/
└── tests/
```

## SemVer y CHANGELOG

- `MAJOR.MINOR.PATCH`. v0.x permite breaking en `MINOR`.
- v1.0.0 cuando el contrato de tools sea estable y haya feedback de uso real.
- Cada PR observable por usuario añade entrada en `CHANGELOG.md` bajo `## [Unreleased]`.
- Categorías: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- Entradas bilingües: línea ES + línea EN bajo cada bullet.

## CI: workflows

### `ci.yml` (en cada push y PR)

```yaml
name: CI
on: [push, pull_request]
jobs:
  lint-type:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy --strict src/
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: ${{ matrix.python }} }
      - run: pip install -e ".[dev]"
      - run: pytest -m "not integration" --cov=src/nz_mcp --cov-fail-under=85
```

### `release.yml` (en tag `v*`)

```yaml
name: Release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
  id-token: write   # OIDC para PyPI Trusted Publishing
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
      - uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
```

### `codeql.yml`

CodeQL análisis estático, scheduled weekly.

## Pre-commit

`.pre-commit-config.yaml` con: `ruff`, `ruff-format`, `mypy` (light), check de secretos (`detect-secrets` o `gitleaks`).

## Branch protection (`main`)

- PR obligatorio (1 review).
- CI debe pasar.
- No force push.
- No delete.
- Conversaciones resueltas.
- Linear history (squash o rebase).

## CODEOWNERS

```
# Áreas de alta sensibilidad → review extra (Security Engineer)
/src/nz_mcp/sql_guard.py    @Oscarsp15
/src/nz_mcp/auth.py         @Oscarsp15
/.github/workflows/         @Oscarsp15
/docs/architecture/         @Oscarsp15
/docs/adr/                  @Oscarsp15
```

(En desarrollo 100 % IA, los reviews son IA-vs-IA + validación humana final del owner.)

## Templates

### `PULL_REQUEST_TEMPLATE.md`

```markdown
## ¿Qué cambia?
<!-- 1-3 frases -->

## Acción según AGENTS.md
- [ ] Identifiqué mi acción en la tabla de enrutamiento
- Docs leídos: <!-- listar -->
- Rol asumido: <!-- ej. Security Engineer -->

## Checklist
- [ ] `ruff check` ok
- [ ] `mypy --strict` ok
- [ ] `pytest` ok, cobertura ≥ 85%
- [ ] CHANGELOG actualizado (si aplica)
- [ ] ADR creado (si cambio arquitectónico)
- [ ] tools-contract.md actualizado (si toca tools)

## Validación humana requerida
- [ ] Sí — explica por qué
- [ ] No
```

## Dependabot

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 5
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
```

## SECURITY.md

- Política de reporte privado (GitHub Security Advisories).
- SLA de respuesta declarado.
- Lista de versiones soportadas.
- Mención: si tienes un CVE de `nzpy`, abre advisory primero, no issue público.

## Anti-patrones

- ❌ Bumpear `MAJOR` sin breaking real, o `PATCH` con breaking.
- ❌ Tag y release sin `CHANGELOG`.
- ❌ Publicar a PyPI desde laptop personal (siempre via OIDC).
- ❌ Secretos hardcodeados en workflows.
- ❌ `git push --force` a `main`.
- ❌ Branch sin protección que apunte a `main`.
- ❌ Dejar Dependabot acumular PRs sin revisar > 30 días.

## Checklist antes de release

- [ ] Tests `not integration` verdes en CI cross-OS.
- [ ] **Humano** confirmó que `pytest -m integration` corrió local con VPN y pasó.
- [ ] `CHANGELOG.md` movido de `Unreleased` a versión + fecha.
- [ ] Versión bumpeada en `pyproject.toml`.
- [ ] Tag firmado: `git tag -s vX.Y.Z -m "vX.Y.Z"`.
- [ ] Release notes en español + inglés.
- [ ] README ES y EN actualizados si hay cambios visibles.
