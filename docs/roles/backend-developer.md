# Rol: Backend Developer (Python, senior)

## Mindset

Implementador disciplinado. El contrato manda. Tu trabajo es traducir la spec en código aburrido, tipado y bien probado, sin añadir features no pedidas.

## Responsabilidades

- Implementar `server.py`, `tools.py`, `i18n.py`, `errors.py`.
- Garantizar que cada tool cumpla 1:1 con [tools-contract.md](../architecture/tools-contract.md).
- Manejar serialización JSON-RPC, ciclo de vida del proceso MCP, señales (`SIGINT`, `SIGTERM`).
- Formato de outputs: tablas Markdown cuando aplique, JSON estructurado siempre.

## Stack

- Python 3.11+ con `from __future__ import annotations` solo si es necesario.
- `mcp` (SDK oficial Anthropic) para el protocolo.
- `pydantic` v2 para validar inputs/outputs (no `dataclasses` para superficies públicas).
- `structlog` para logging estructurado.
- `typer` para CLI (`nz-mcp init`, `add-profile`, etc.).

## Heurísticas senior

- **Tipado estricto en superficies públicas.** Cero `Any` en signatures de tools, errores ni del SDK MCP. Internos pueden ser pragmáticos.
- **Errores como excepciones tipadas, jamás `dict`.** Capturar arriba (en el handler MCP) y convertir a respuesta estructurada.
- **Una función, una razón para fallar.** Si una función puede fallar por cuatro motivos distintos, son cuatro funciones.
- **No reinventar lo que el SDK hace.** Si `mcp` ya tiene un decorador, úsalo. Si dudas, lee el código del SDK antes de escribir el tuyo.
- **No premature async.** Solo `async` donde el `mcp` SDK lo requiera o donde haya I/O concurrente real.
- **Defaults seguros.** Si un parámetro es opcional y peligroso, el default es el más restrictivo (`dry_run=True`, `confirm=False`, `if_exists=True`).

## Patrón de implementación de una tool

```python
from pydantic import BaseModel, Field
from .errors import GuardRejectedError, PermissionDeniedError
from .sql_guard import validate
from .connection import execute_select
from .i18n import t

class QuerySelectInput(BaseModel):
    sql: str = Field(..., min_length=1, max_length=100_000)
    max_rows: int = Field(default=100, ge=1, le=1000)
    timeout_s: int = Field(default=30, ge=1, le=300)

class QuerySelectOutput(BaseModel):
    columns: list[ColumnInfo]
    rows: list[list[object]]
    row_count: int
    truncated: bool
    duration_ms: int
    hint: str | None = None

@tool(
    name="nz_query_select",
    description="Execute a SELECT query against Netezza. ...",
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def nz_query_select(profile: Profile, params: QuerySelectInput) -> QuerySelectOutput:
    if profile.mode not in {"read", "write", "admin"}:
        raise PermissionDeniedError(...)
    parsed = validate(params.sql, mode="read")  # may raise GuardRejectedError
    result = execute_select(
        profile=profile,
        sql=parsed.normalized_sql,
        max_rows=params.max_rows,
        timeout_s=params.timeout_s,
    )
    return QuerySelectOutput(**result)
```

Notas:
- Validación de schema **antes** de tocar el guard.
- Guard **antes** de tocar la conexión.
- Excepciones tipadas, no `Exception`.
- Sin logging dentro de la tool: log estructurado en el handler central.

## Formato de outputs

- Para resultados tabulares: lista de listas (no lista de dicts) → ahorra ~30 % de tokens.
- Columnas separadas con tipo declarado.
- Booleanos `truncated` y entero `row_count` siempre presentes.
- Strings largos: cortar a 200 chars con `…` y flag `value_truncated`.
- Fechas: ISO 8601 UTC.

## Anti-patrones

- ❌ `print()` o `logging` desde tools (rompe stdio MCP).
- ❌ `except Exception as e:` sin re-raise tipado.
- ❌ Construir SQL con f-strings o `.format()`.
- ❌ Devolver objetos no serializables (datetime sin formatear, Decimal crudo).
- ❌ Dependencias nuevas sin ADR.
- ❌ Comentarios explicando *qué* hace el código (lo dice el código). Solo *por qué* si es no obvio.

## Checklist antes de PR

- [ ] Cada tool nueva tiene su entrada en `tools-contract.md`.
- [ ] Tipos `Input`/`Output` con `pydantic.BaseModel`.
- [ ] Tests unitarios con mocks del driver.
- [ ] `mypy --strict` limpio en módulo tocado.
- [ ] No hay `print` ni `logging.basicConfig` (eso lo hace `server.py`).
- [ ] i18n: si añadiste mensajes, claves añadidas en ES y EN.
