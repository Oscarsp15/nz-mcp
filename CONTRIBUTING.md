# Contribuir a `nz-mcp`

¡Gracias por tu interés! Este repositorio se desarrolla **principalmente con agentes IA** siguiendo `AGENTS.md`. Los humanos también pueden contribuir.

## Antes de empezar

1. Lee [`AGENTS.md`](AGENTS.md) — es el router central.
2. Lee [`docs/standards/issue-workflow.md`](docs/standards/issue-workflow.md) — cómo se crean y toman issues.
3. Lee [`docs/standards/git-workflow.md`](docs/standards/git-workflow.md) — convenciones estrictas validadas por CI.
4. Lee [`docs/standards/pr-audit.md`](docs/standards/pr-audit.md) — auditoría obligatoria pre-merge.

## Si eres una IA

1. Identifica un issue con label `ai-ready` y sin `claimed`.
2. Sigue el [protocolo de claim](docs/standards/issue-workflow.md#protocolo-de-claim).
3. Identifica tu acción en la tabla de enrutamiento de `AGENTS.md`.
4. Lee los docs marcados como obligatorios.
5. Adopta el rol correspondiente (`docs/roles/`).
6. Implementa, autoaudita ([pr-audit.md](docs/standards/pr-audit.md)).
7. Abre PR siguiendo `PULL_REQUEST_TEMPLATE.md`.

## Si eres humano

Mismas reglas que las IAs. Las convenciones (branches, commits, PRs) están validadas por CI; no hay excepciones.

## Setup local

```bash
git clone https://github.com/Oscarsp15/nz-mcp.git
cd nz-mcp
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install --hook-type pre-push --hook-type commit-msg
pytest -m "not integration"
```

## Fork workflow for external contributors

Si no tienes permisos de escritura en el repo (caso típico en OSS), el flujo es:

```bash
# 1. Fork y clone
gh repo fork Oscarsp15/nz-mcp --clone=false
gh repo clone <tu-usuario>/nz-mcp
cd nz-mcp

# 2. Vincular upstream para sincronizar main
git remote add upstream https://github.com/Oscarsp15/nz-mcp.git

# 3. Crear branch (nombre debe cumplir el regex de git-workflow.md §1)
git checkout -b feat/<n>-<slug-en-kebab-case>

# 4. Implementar, seguir AGENTS.md, tests, etc.
pre-commit install --hook-type pre-push --hook-type commit-msg
# ... edita código ...
git commit -m "feat(<scope>): <descripción en imperativo>"

# 5. Push al fork y abrir PR contra el upstream
git push -u origin feat/<n>-<slug-en-kebab-case>
gh pr create --repo Oscarsp15/nz-mcp --title "..." --body-file body.md
```

### Primera vez

GitHub Actions pide al owner aprobar workflows manualmente la primera vez que un contributor externo dispara CI. El owner clickea **"Approve and run"** en la pestaña `Actions`. Tras eso, los siguientes pushes del mismo contributor corren automático.

### Permisos en el repo base

Contributors externos NO pueden:
- Asignarse a issues, aplicar labels, ni mergear PRs.

**No es un problema**: el workflow `auto-claim.yml` aplica el label `claimed` y el assignee automáticamente al abrir el draft PR con `Closes #N`. Ver [`docs/standards/issue-workflow.md`](docs/standards/issue-workflow.md) sección "Claim automático".

### Sincronizar fork con upstream

```bash
git fetch upstream
git checkout main
git merge --ff-only upstream/main
git push origin main
```

## Idioma

- **Código y comentarios**: inglés.
- **Branches**: slug en inglés.
- **Commits, PRs, issues, reviews**: español.
- **Docs internas (`docs/`, `AGENTS.md`)**: español.
- **README.md**: español; **README.en.md**: inglés.
- **Mensajes al usuario**: i18n ES/EN.

## Reportes de seguridad

Ver [`SECURITY.md`](SECURITY.md). **No abrir issue público** para vulnerabilidades.

## Código de conducta

Ver [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
