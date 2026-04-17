# Git workflow

> **Reglas estrictas, validadas por CI.** Si tu branch / commit / PR no cumple el regex, **el CI falla y el PR no mergea.** No hay margen de interpretación.

## 1. Branches

### Regex (validado por CI)

```
^(feat|fix|chore|refactor|docs|test|security|perf|build|ci)/(\d+-)?[a-z0-9]+(-[a-z0-9]+){0,8}$
```

### Reglas duras

| Regla | Detalle |
|---|---|
| Tipo permitido | `feat` `fix` `chore` `refactor` `docs` `test` `security` `perf` `build` `ci` |
| Separador tipo/slug | `/` (uno solo) |
| Issue ref opcional al inicio del slug | `<n>-` ej: `42-` |
| Slug | minúsculas a-z, dígitos 0-9, guiones medios `-`. Sin `_`, sin acentos, sin mayúsculas, sin espacios |
| Longitud slug | 1 a 9 tokens separados por `-`, máximo 50 caracteres totales (incluyendo `tipo/`) |
| Único intento de pluralización | `feats/` ❌ — usar `feat/` |
| Ramas permanentes | solo `main` |

### Ramas base (de dónde salen, a dónde van)

| Branch | Sale de | Vuelve a (PR target) |
|---|---|---|
| `feat/...`, `fix/...`, `refactor/...`, `perf/...` | `main` | `main` |
| `docs/...`, `chore/...`, `ci/...`, `test/...`, `build/...` | `main` | `main` |
| `security/...` | `main` | `main` (o release branch si emergencia) |
| `release/vX.Y.Z` (solo Release Engineer) | `main` | `main` |

**No hay** `develop`, `staging`, ni similares en v0.1.

### Lifecycle

- Vida máxima: **5 días desde el primer commit**. CI marca `stale-branch` después.
- Vida máxima: 5 días → si hace falta más, partir el trabajo en N issues / N branches.
- Una vez mergeada (squash a main), la rama remota se borra automáticamente.

### Ejemplos

✅ Válidos:
- `feat/42-nz-list-procedures`
- `fix/sql-guard-rejects-stacked-comments`
- `refactor/connection-cursor-streaming`
- `docs/47-readme-en-update`
- `security/sanitizer-keyring-fallback`
- `ci/add-codeql-workflow`

❌ Inválidos:
- `feature/x` (tipo no válido)
- `feat-add-tool` (separador incorrecto)
- `feat/Add_Tool` (mayúsculas, guion bajo)
- `feat/añadir-tool` (acento)
- `feat/this-is-a-very-very-very-very-very-long-slug-that-overflows` (> 50 chars)
- `wip` (sin tipo)
- `oscar-sandbox` (sin tipo)

---

## 2. Commits

### Regex del subject (validado por CI en cada commit del PR)

```
^(feat|fix|chore|refactor|docs|test|security|perf|build|ci)(\([a-z0-9-]+\))?(!)?: [^\s].{0,71}$
```

### Reglas duras

| Regla | Detalle |
|---|---|
| Formato | `<tipo>(<scope>)<!>: <descripción>` |
| Tipos | mismos 10 que para branches |
| Scope | minúsculas, dígitos, guiones medios. Refleja **área del código** (`tools`, `sql_guard`, `auth`, `ci`, `docs`, ...). Opcional en `chore`/`docs` genéricos. |
| `!` | obligatorio si es breaking change |
| `:` | seguido de 1 espacio exacto |
| Descripción | imperativo, presente, español, primera letra minúscula. Sin punto final. |
| Longitud subject | máximo **72 caracteres** |
| Línea en blanco | obligatoria entre subject y body si hay body |
| Body (opcional) | español, líneas ≤ 100 chars, explica **por qué** no qué |
| Trailers | `Closes #N`, `Refs #N`, `Refs docs/adr/NNNN-x.md`, `Co-Authored-By: ...` |

### Reglas de partir commits

- Un commit, un cambio coherente.
- No mezclar `feat` y `fix` en el mismo commit.
- No mezclar refactor con cambio funcional.
- Si tu mensaje necesita `y`, son dos commits.

### Ejemplos

✅ Válidos:
- `feat(tools): añade nz_get_view_ddl`
- `fix(sql_guard): rechaza CTE con DELETE en RETURNING`
- `refactor(connection): extrae streaming a helper privado`
- `docs(security-model): documenta sanitizer de credenciales`
- `chore(deps): actualiza nzpy a 1.16.0`
- `feat(tools)!: renombra nz_query a nz_query_select`

❌ Inválidos:
- `Update stuff` (sin tipo)
- `feat: añade tool y arregla bug` (dos intenciones)
- `feat(Tools): añade X` (scope con mayúscula)
- `feat(tools):añade X` (sin espacio tras `:`)
- `feat(tools): Añade X` (mayúscula inicial en descripción)
- `feat(tools): añade X.` (punto final)
- `WIP: probando` (no se permite `WIP` ni en branches ni en commits)
- `feat(tools): aaaaaaa...` con > 72 chars

---

## 3. Pull Request

### Regex del título

Mismo que commit subject:

```
^(feat|fix|chore|refactor|docs|test|security|perf|build|ci)(\([a-z0-9-]+\))?(!)?: [^\s].{0,71}$
```

### Reglas duras

| Regla | Detalle |
|---|---|
| Título | igual formato que commit subject |
| Una intención por PR | si hay "y además", abrir 2 PRs |
| Cuerpo | usa `PULL_REQUEST_TEMPLATE.md` íntegro, todos los checkboxes presentes |
| `Closes #N` | obligatorio (cada PR cierra ≥ 1 issue) |
| Tamaño | < 400 LoC sin contar tests/docs. Si más → justificación explícita |
| Estado inicial | si aún hay trabajo: `Draft`. Cuando esté listo: `Ready for review` |
| Auto-review | obligatorio antes de pasar a `Ready for review` |
| Auditoría | según [pr-audit.md](pr-audit.md) — los 7 dimensiones marcados en el cuerpo |

### Estrategia de merge

- **Squash y merge.** Único método permitido.
- El mensaje del squash es **el título del PR** (formato conventional).
- El cuerpo del squash es **el cuerpo del PR** (referencias a issues, ADRs).

---

## 4. Tags y releases

### Regex del tag

```
^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-(alpha|beta|rc)\.[1-9]\d*)?$
```

- Solo Release Engineer crea tags.
- Tag firmado: `git tag -s vX.Y.Z -m "vX.Y.Z"`.
- Push: `git push origin vX.Y.Z` → dispara `release.yml`.

---

## 5. Reglas de protección de `main` (configuradas en GitHub)

- Sin push directo. Solo via PR.
- 1 review obligatorio.
- CI debe pasar (`ci`, `validate-conventions`, `codeql`).
- No force push.
- No delete.
- Linear history (squash merge fuerza esto).
- Conversaciones resueltas.
- Bloquear merge si la PR cambia `CODEOWNERS` sin review del owner.

---

## 6. Prohibiciones (rechazo automático)

- ❌ `git push --force` a `main` o a ramas con PR abierto.
- ❌ `git push --force-with-lease` a ramas compartidas sin avisar en el PR.
- ❌ `--no-verify` para saltarse hooks.
- ❌ `--no-gpg-sign`.
- ❌ `git rebase -i` sobre commits ya pusheados a `main`.
- ❌ Mergear PR propio sin que CI haya completado.
- ❌ Squash que oculta varios cambios no relacionados (es una sola intención por PR).
- ❌ Branches sin tipo (`oscar-test`, `wip`, `tmp`).
- ❌ Commits de `WIP`, `tmp`, `prueba`, `arreglo final`, etc.
- ❌ Código "porsiacaso", abstracciones especulativas, parámetros opcionales sin uso real.

---

## 7. Validación local (pre-push)

`.git/hooks/pre-push` (instalado por `pre-commit install --hook-type pre-push`) corre el mismo regex que el CI. **No** subas con `--no-verify`; si el hook falla, arregla.

`.pre-commit-config.yaml` incluye:

```yaml
- repo: local
  hooks:
    - id: branch-name
      name: Validar nombre de branch
      entry: scripts/check_branch_name.sh
      language: script
      always_run: true
      pass_filenames: false
      stages: [pre-push]
    - id: commit-msg
      name: Validar mensaje de commit
      entry: scripts/check_commit_msg.sh
      language: script
      stages: [commit-msg]
```

---

## 8. Validación remota (CI)

Workflow `.github/workflows/validate-conventions.yml` corre en cada PR y push:

1. Verifica nombre de branch.
2. Verifica todos los commits del PR (subject regex).
3. Verifica título del PR.
4. Verifica que el cuerpo del PR contiene `Closes #` o `Refs #`.

Si alguno falla → CI rojo → no merge.

---

## 9. Idioma

- **Branches**: slug en inglés (sin acentos, kebab-case).
- **Commits subject**: imperativo en español.
- **Commit body**: español.
- **PR título**: imperativo en español.
- **PR cuerpo**: español.
- **Issues**: español.
- **Reviews y comentarios**: español.
- **Código y comentarios en código**: inglés.
- **CHANGELOG**: bilingüe ES + EN por línea.
- **README.md**: español. **README.en.md**: inglés.

---

## 10. Checklist antes de pedir review

- [ ] Branch cumple regex.
- [ ] Todos los commits del PR cumplen regex.
- [ ] Título del PR cumple regex.
- [ ] PR contiene `Closes #N` o `Refs #N`.
- [ ] PR template completo (todas las casillas presentes, no necesariamente todas marcadas).
- [ ] Auto-auditoría según [pr-audit.md](pr-audit.md).
- [ ] CI verde local (`ruff`, `mypy`, `pytest -m "not integration"`).
- [ ] Cobertura no bajó.
- [ ] CHANGELOG actualizado si aplica.
- [ ] Una intención sola.
- [ ] PR < 400 LoC (sin tests/docs) o justificado.
