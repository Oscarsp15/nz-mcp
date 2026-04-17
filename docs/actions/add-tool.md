# Playbook — Añadir una tool nueva

> Pre-requisito: leer [tools-contract.md](../architecture/tools-contract.md), [maintainability.md](../standards/maintainability.md) y el rol [backend-developer.md](../roles/backend-developer.md).

## ¿Cuándo NO añadir una tool?

Antes de añadir, verifica:

1. ¿Una tool existente cubre el caso con un parámetro extra (sin volverla multitool)? → preferir parámetro.
2. ¿La tool nueva tiene **una sola** razón para fallar? Si tiene 3, son 3 tools.
3. ¿La IA podría confundirla con una existente? Si sí, redactar descripciones en paralelo.
4. ¿Cabe en el alcance de v0.1? Si no, abrir issue para v0.2.

## Pasos (en orden, sin saltarse)

### 1. Diseñar contrato (Tech Lead)

- Definir nombre `nz_<verbo>_<objeto>`.
- Definir input schema (pydantic) y output schema.
- Definir errores posibles y mode requerido.
- **Editar `docs/architecture/tools-contract.md`** añadiendo la entrada bajo la sección correcta. **Antes** de tocar código.
- Si el comportamiento es controvertido o cambia un patrón: ADR.

### 2. Implementar (Backend Developer)

Archivos esperados (si tocas más, revisa diseño):

- `src/nz_mcp/tools.py` → registro con decorador `@tool(...)`.
- `src/nz_mcp/catalog/<dominio>.py` o `connection.py` → query nueva si aplica.
- `src/nz_mcp/i18n.py` → claves de mensajes/hints en ES y EN.

Patrón:

```python
from .registry import tool
from .schemas import MyInput, MyOutput
from .errors import GuardRejectedError, ObjectNotFoundError
from .sql_guard import validate
from .catalog.X import fetch_X

@tool(
    name="nz_describe_X",
    description="...",                     # inglés, < 200 chars
    mode="read",
    input_model=MyInput,
    output_model=MyOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def nz_describe_X(profile, params: MyInput) -> MyOutput:
    raw = fetch_X(profile, params.database, params.schema, params.name)
    if raw is None:
        raise ObjectNotFoundError(code="OBJECT_NOT_FOUND", obj=params.name)
    return MyOutput(**raw)
```

### 3. Tests (QA)

- `tests/unit/test_tools_<nombre>.py` → mocks del driver, ≥ 1 caso happy path + ≥ 1 caso error tipado.
- `tests/contract/test_mcp_tool_schemas.py` → asegurar que la nueva tool aparece y tiene schemas.
- `tests/integration/test_real_<nombre>.py` (opcional, marcado `@pytest.mark.integration`) → contra Netezza real.
- Si toca `sql_guard.py`: tests adversariales nuevos.

### 4. Descripción para la IA (DX Engineer)

- Inglés, imperativo, < 200 chars.
- Estructura: `<verbo> <objeto>. Use for X. Do not use for Y.`
- Verificar que no compite con tools existentes.

### 5. CHANGELOG

```markdown
## [Unreleased]
### Added
- ES: nueva tool `nz_X` para …
- EN: new tool `nz_X` to …
```

### 6. Auditoría

Pasar [pr-audit.md](../standards/pr-audit.md) — todas las dimensiones.

## Anti-patrones (rechazo automático en auditoría)

- ❌ Tool que acepta operación como parámetro (`operation: "read" | "write"`).
- ❌ Tool nueva sin entrada en `tools-contract.md` en el mismo PR.
- ❌ Tool que toca `server.py` para registrarse (debe ir vía decorador).
- ❌ Sin test de contrato MCP que la cubra.
- ❌ Descripción genérica ("Powerful tool to ...").
- ❌ Reusar nombre con prefijo distinto (`describe_X` en vez de `nz_describe_X`).

## Plantilla de PR description

```markdown
## ¿Qué cambia?
Añade tool `nz_X` para <propósito en una frase>.

## Acción según AGENTS.md
- Ruta: "nueva tool"
- Docs leídos:
  - docs/architecture/tools-contract.md
  - docs/actions/add-tool.md
  - docs/standards/coding.md
  - docs/standards/maintainability.md
- Rol asumido: Backend Developer + Tech Lead (contrato).

## Archivos tocados (esperados)
- docs/architecture/tools-contract.md
- src/nz_mcp/tools.py
- src/nz_mcp/catalog/<dominio>.py
- src/nz_mcp/i18n.py
- tests/unit/test_tools_<nombre>.py
- tests/contract/test_mcp_tool_schemas.py
- CHANGELOG.md

## Auditoría pre-merge
[ ] Pasada según docs/standards/pr-audit.md
```
