# AGENTS.md — nz-mcp

> **ATENCIÓN AGENTE IA**: este archivo es un **índice de despacho**, no la especificación completa.
> Antes de tocar código, identifica tu acción en la [Tabla de Enrutamiento](#-tabla-de-enrutamiento-obligatoria) y lee los documentos que aplican. **No proceder sin leer.**

---

## 🚨 Reglas inviolables (léelas siempre)

1. **Jamás** loggear credenciales, resultados crudos de queries, ni password en cualquier forma.
2. **Jamás** permitir que la IA eleve el modo de permiso del perfil (`read` → `write` / `admin`). Solo lo cambia el humano editando config.
3. **Jamás** ejecutar SQL sin pasarlo por `sql_guard` primero.
4. **Jamás** hacer `git push --force` a `main` ni saltarse hooks (`--no-verify`).
5. **Jamás** añadir dependencias sin crear un ADR en `docs/adr/` justificándolas.
6. **Jamás** publicar una release sin que el humano confirme que los integration tests locales han pasado.
7. **Jamás** hacer mocking del driver en tests marcados `@pytest.mark.integration`.
8. **Jamás** escribir comentarios o nombres de funciones en español — **el código y los comentarios van en inglés**.
9. **Jamás** crear archivos temporales o de auto-ayuda en el repo (`notes.md`, `plan.md`, `scratch.py`, `wip.txt`, `analysis.md`, `TODO_LOCAL.md`, `.scratch/`, `playground/`, etc.). Si necesitas pensar en voz alta, usa `/tmp` o el área de tu propio runtime — **fuera del repo**. Validado por `scripts/check_repo_hygiene.py` (whitelist+blacklist), hook `pre-commit` y CI bloqueante. Si un archivo legítimo cae en blacklist, abre PR para añadirlo a la whitelist con ADR justificándolo.

---

## 🎯 Misión

`nz-mcp` es un servidor MCP (Model Context Protocol) que permite a asistentes IA consultar bases de datos IBM Netezza Performance Server de forma segura, con tools de responsabilidad única y permisos granulares por perfil.

**Criterio de éxito v0.1**: Claude Desktop puede, sin intervención humana, listar BDs → describir una tabla → ejecutar un `SELECT` con `LIMIT`, en <5 s y sin leaks de credenciales.

---

## 🚦 Tabla de enrutamiento obligatoria

**Identifica tu acción por las keywords y LEE los documentos marcados antes de escribir código.**

| Tu acción contiene keywords | Docs obligatorios |
|---|---|
| `nueva tool`, `add tool`, `crear herramienta`, `new tool` | [arch/tools-contract.md](docs/architecture/tools-contract.md) · [actions/add-tool.md](docs/actions/add-tool.md) · [standards/coding.md](docs/standards/coding.md) · [standards/maintainability.md](docs/standards/maintainability.md) |
| `vista`, `view`, `DDL view`, `view definition` | [arch/tools-contract.md](docs/architecture/tools-contract.md) · [roles/data-engineer.md](docs/roles/data-engineer.md) |
| `procedimiento`, `stored procedure`, `SP`, `procedure`, `NZPLSQL`, `clonar SP` | [arch/tools-contract.md](docs/architecture/tools-contract.md) · [roles/data-engineer.md](docs/roles/data-engineer.md) · [arch/security-model.md](docs/architecture/security-model.md) |
| `DDL`, `CREATE TABLE`, `SHOW TABLE`, `definición tabla` | [roles/data-engineer.md](docs/roles/data-engineer.md) · [arch/tools-contract.md](docs/architecture/tools-contract.md) |
| `mantenibilidad`, `escalabilidad`, `refactor`, `deuda técnica`, `complejidad` | [standards/maintainability.md](docs/standards/maintainability.md) |
| `auditoría`, `revisar PR`, `pre-merge`, `code review`, `aprobar PR` | [standards/pr-audit.md](docs/standards/pr-audit.md) · [standards/git-workflow.md](docs/standards/git-workflow.md) |
| `issue`, `crear issue`, `tomar issue`, `claim`, `triage`, `labels` | [standards/issue-workflow.md](docs/standards/issue-workflow.md) |
| `sql_guard`, `parser SQL`, `read-only`, `validación SQL`, `inyección` | [arch/security-model.md](docs/architecture/security-model.md) · [actions/modify-sql-guard.md](docs/actions/modify-sql-guard.md) · [roles/security-engineer.md](docs/roles/security-engineer.md) |
| `auth`, `credenciales`, `keyring`, `perfil`, `profile`, `password` | [arch/security-model.md](docs/architecture/security-model.md) · [roles/security-engineer.md](docs/roles/security-engineer.md) |
| `driver`, `nzpy`, `connection`, `pool`, `streaming`, `cursor` | [arch/overview.md](docs/architecture/overview.md) · [roles/data-engineer.md](docs/roles/data-engineer.md) |
| `catálogo`, `_v_table`, `metadata`, `describe`, `list_tables`, `stats` | [roles/data-engineer.md](docs/roles/data-engineer.md) |
| `tests`, `pytest`, `mock`, `coverage`, `integration`, `fixtures` | [standards/testing.md](docs/standards/testing.md) · [roles/qa-engineer.md](docs/roles/qa-engineer.md) |
| `CI`, `GitHub Actions`, `workflow`, `dependabot`, `secret scanning` | [roles/release-engineer.md](docs/roles/release-engineer.md) |
| `release`, `publicar`, `version`, `tag`, `CHANGELOG`, `PyPI` | [actions/release.md](docs/actions/release.md) · [roles/release-engineer.md](docs/roles/release-engineer.md) |
| `commit`, `PR`, `pull request`, `branch`, `merge` | [standards/git-workflow.md](docs/standards/git-workflow.md) |
| `i18n`, `traducción`, `mensaje usuario`, `español`, `english`, `locale` | [standards/i18n.md](docs/standards/i18n.md) |
| `README`, `docs`, `descripción tool`, `documentación` | [roles/technical-writer.md](docs/roles/technical-writer.md) · [standards/i18n.md](docs/standards/i18n.md) |
| `tool description`, `prompt`, `cómo IA usa tool`, `UX IA` | [roles/dx-engineer.md](docs/roles/dx-engineer.md) |
| `arquitectura`, `decisión`, `ADR`, `diseño` | [arch/overview.md](docs/architecture/overview.md) · nuevo ADR en `docs/adr/` |

**Si tu acción NO aparece en la tabla → detente y pregunta al humano.**

---

## ⛔ Archivos de alta sensibilidad

Nunca los modifiques sin leer primero el documento asociado.

| Archivo | Doc obligatorio previo |
|---|---|
| `src/nz_mcp/sql_guard.py` | [arch/security-model.md](docs/architecture/security-model.md) |
| `src/nz_mcp/auth.py` | [arch/security-model.md](docs/architecture/security-model.md) |
| `src/nz_mcp/connection.py` | [roles/data-engineer.md](docs/roles/data-engineer.md) |
| `.github/workflows/*.yml` | [roles/release-engineer.md](docs/roles/release-engineer.md) |
| `pyproject.toml` (versión o deps) | [actions/release.md](docs/actions/release.md) |
| `docs/architecture/tools-contract.md` | [roles/tech-lead.md](docs/roles/tech-lead.md) |

---

## 🧭 Adopta un rol antes de escribir código

Según la acción, asume uno de estos roles senior y lee su doc:

| Acción | Rol | Doc |
|---|---|---|
| Diseño de arquitectura, contrato de tools | Tech Lead | [roles/tech-lead.md](docs/roles/tech-lead.md) |
| Implementación general, serialización, i18n | Backend Developer | [roles/backend-developer.md](docs/roles/backend-developer.md) |
| Queries SQL, driver, streaming, catálogo | Data Engineer | [roles/data-engineer.md](docs/roles/data-engineer.md) |
| SQL guard, auth, threat model | Security Engineer | [roles/security-engineer.md](docs/roles/security-engineer.md) |
| Tests, mocks, cobertura | QA Engineer | [roles/qa-engineer.md](docs/roles/qa-engineer.md) |
| CI/CD, PyPI, SemVer, releases | Release Engineer / OSS | [roles/release-engineer.md](docs/roles/release-engineer.md) |
| Documentación, README ES/EN | Technical Writer | [roles/technical-writer.md](docs/roles/technical-writer.md) |
| Tool descriptions, UX para la IA | DX Engineer | [roles/dx-engineer.md](docs/roles/dx-engineer.md) |

Todos los roles se trabajan **a nivel senior**: si dudas entre dos enfoques, elige el más defensivo, el más testeable y el más explícito.

---

## 📐 Spec congelada (v0.1)

Cambios a esta tabla requieren un **ADR** en `docs/adr/`.

| Ítem | Decisión |
|---|---|
| Nombre | `nz-mcp` |
| Repo | `github.com/Oscarsp15/nz-mcp` (público, MIT) |
| Lenguaje | Python 3.11+ |
| Driver Netezza | `nzpy` (primario), `pyodbc` alternativo documentado |
| Netezza target | NPS 11.2.x (probado: `Release 11.2.1.11-IF1 [Build 4]`) |
| Transporte MCP | `stdio` |
| Clientes soportados | Claude Desktop, Claude Code, Cursor, Windsurf, VS Code MCP |
| Credenciales | `keyring` OS-native + `~/.nz-mcp/profiles.toml` |
| Perfiles | Multi-perfil, modos `read` / `write` / `admin` |
| Tools v0.1 | 24 (ver [tools-contract.md](docs/architecture/tools-contract.md)) |
| Default `max_rows` | 100 |
| Cap respuesta | ~100 KB (≈25 k tokens) |
| Timeout default | 30 s |
| Cobertura tests | 85 % global, 100 % módulos de seguridad |
| CI v0.1 | Unit + contract con mocks. Integration solo local. |
| Idioma código | Inglés |
| Idioma docs | ES (principal) + EN (`README.en.md`) |
| Idioma mensajes usuario | i18n ES/EN |
| Idioma commits / PRs / issues | Español |
| Idioma `AGENTS.md` y docs internas | Español |

---

## 📋 Checklist "Definition of Done" antes de abrir PR

> Para auditoría detallada por dimensión (seguridad, mantenibilidad, contrato, tests, docs, idioma), ver **[standards/pr-audit.md](docs/standards/pr-audit.md)** — vinculante.

- [ ] Leí los docs marcados en la tabla de enrutamiento para mi acción.
- [ ] `ruff check` sin errores.
- [ ] `mypy --strict` sin errores en módulos que toqué.
- [ ] `pytest -m "not integration"` verde en local.
- [ ] Cobertura ≥ 85 % global, 100 % en `sql_guard.py` y `auth.py`.
- [ ] Si añadí una tool: actualicé `docs/architecture/tools-contract.md`.
- [ ] Si cambié comportamiento observable: actualicé `CHANGELOG.md`.
- [ ] Si introduje decisión arquitectónica: nuevo ADR en `docs/adr/`.
- [ ] Commit y PR en **español**, claros y en imperativo.
- [ ] Código y comentarios en **inglés**.
- [ ] Si toqué un archivo de alta sensibilidad: dejé nota en el PR con el doc que leí.

---

## 📞 Escalado al humano

**Detente y pide input humano si:**
- Tu acción no está en la tabla de enrutamiento.
- Un test falla y no entiendes la causa raíz.
- Vas a tocar un archivo de alta sensibilidad sin tener un doc claro que autorice el cambio.
- Vas a cambiar un ítem de la spec congelada.
- Encuentras una decisión ambigua no cubierta por un ADR.
- El humano pidió algo que viola una regla inviolable (pide confirmación explícita citando la regla).

---

## 🗂️ Estructura de documentación

```
AGENTS.md                          ← este archivo (router)
docs/
├── architecture/
│   ├── overview.md                ← módulos, flujo, capas
│   ├── tools-contract.md          ← 16 tools con schema JSON
│   └── security-model.md          ← threat model, sql_guard, auth
├── roles/                         ← un archivo por rol senior
│   ├── tech-lead.md
│   ├── backend-developer.md
│   ├── data-engineer.md
│   ├── security-engineer.md
│   ├── qa-engineer.md
│   ├── release-engineer.md
│   ├── technical-writer.md
│   └── dx-engineer.md
├── standards/
│   ├── coding.md                  ← estilo, tipado, errores
│   ├── testing.md                 ← estrategia, mocks, marks
│   ├── git-workflow.md            ← ramas, commits, PRs
│   ├── i18n.md                    ← ES/EN, locales, mensajes
│   ├── maintainability.md         ← límites, escalabilidad, refactor
│   ├── pr-audit.md                ← auditoría obligatoria pre-merge
│   └── issue-workflow.md          ← issues AI-pickup, labels, claim
├── actions/                       ← playbooks por tipo de cambio
│   ├── add-tool.md
│   ├── modify-sql-guard.md
│   ├── release.md
│   └── write-tests.md
└── adr/                           ← decisiones arquitectónicas
    └── README.md
```

Estructura de código (cuando exista):

```
src/nz_mcp/
├── __init__.py
├── server.py          ← entry point MCP (stdio)
├── tools.py           ← registro y despacho de tools
├── connection.py      ← pool y manejo del driver nzpy
├── catalog/           ← queries al catálogo _v_* por dominio
│   ├── databases.py
│   ├── schemas.py
│   ├── tables.py      ← list, describe, get_table_ddl, sample, stats
│   ├── views.py       ← list_views, get_view_ddl
│   └── procedures.py  ← list, describe, get_ddl, get_section, clone
├── sql_guard.py       ← validación read/write/admin
├── auth.py            ← keyring + profiles.toml
├── config.py          ← carga de config y perfiles
├── i18n.py            ← mensajes ES/EN
└── errors.py          ← excepciones tipadas
tests/
├── unit/
├── contract/          ← conformidad MCP JSON-RPC
└── integration/       ← contra Netezza real (local, con VPN)
```
