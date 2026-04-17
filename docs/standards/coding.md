# Estándares de código (Python)

## Versión y herramientas

- Python **3.11+** (mínimo soportado).
- Ejecutar local con la mismas versión que CI: `.python-version` con `3.11`.
- Linter / formatter: **ruff** (`ruff check`, `ruff format`).
- Type checker: **mypy --strict**.
- Test runner: **pytest**.
- Pre-commit obligatorio.

## Tipado

- **Tipado estricto en superficies públicas** (entry points, tools, errores).
- **Cero `Any`** en signatures públicas. Internos pueden ser pragmáticos pero justificados con comentario `# Any: <razón>`.
- Usar `from __future__ import annotations` solo si elimina circular imports reales.
- Sintaxis 3.11: `list[int]`, `dict[str, X]`, `X | None`. No `List`, `Optional`, `Union`.
- `Literal`, `Final`, `TypeAlias`, `Protocol` cuando aporten.
- `pydantic.BaseModel` v2 para inputs/outputs de tools.

```python
from typing import Literal, Final

PermissionMode = Literal["read", "write", "admin"]
DEFAULT_MAX_ROWS: Final[int] = 100
```

## Errores

- Excepciones **tipadas y propias** en `errors.py`. Jerarquía:

```
NzMcpError
├── ConfigError
│   ├── ProfileNotFoundError
│   └── InvalidProfileError
├── AuthError
│   └── KeyringUnavailableError
├── GuardRejectedError
├── PermissionDeniedError
├── ConnectionError
│   └── ConnectionFailedError
├── QueryError
│   ├── QueryTimeoutError
│   └── ResultTooLargeError
└── InternalError
```

- Cada excepción lleva `code: str` (estable) y `message_es`/`message_en` resueltos por `i18n.py`.
- **Nunca** `raise Exception(...)` o `raise RuntimeError(...)` en código nuevo.
- **Nunca** `except Exception as e: pass`. Si capturas, re-raise tipado.
- `try` cubre lo mínimo posible: la línea que puede fallar, no 30 líneas.

## Naming

- snake_case para funciones, variables, módulos.
- PascalCase para clases.
- SCREAMING_SNAKE_CASE para constantes.
- Prefijo `_` para internos del módulo.
- Prefijo `nz_` para tools (ver [tools-contract.md](../architecture/tools-contract.md)).
- Inglés siempre.

## Imports

- Orden: stdlib → terceros → locales (separados por línea en blanco).
- `ruff` lo aplica.
- Evitar `from x import *`.
- Imports relativos solo dentro del paquete (`from .errors import ...`).

## Comentarios y docstrings

- **Por defecto: sin comentarios.** Buen naming + tipos suelen bastar.
- **Comentar el porqué**, no el qué.
- Docstrings en clases públicas y funciones que cruzan módulos. Estilo Google o NumPy, consistente en todo el repo.
- En inglés.
- Evitar docstrings de relleno que repitan la signature.

## Funciones

- Una función, una responsabilidad. Si necesita 4 nombres distintos para describirla, son 4 funciones.
- Argumentos: si > 4, considerar pasar un dataclass/pydantic.
- Defaults inmutables. Nunca `def f(x=[])`.
- Funciones puras cuando se pueda; side effects aislados en módulos específicos (`connection.py`, `auth.py`).

## Async

- Solo `async` si lo exige el SDK MCP o hay I/O concurrente real.
- No mezclar sync/async sin razón. Si el módulo es async, todo el módulo async.

## Logging

- Usar `structlog` con formato JSON.
- **Jamás** `print()`. Rompe el transporte stdio MCP.
- **Jamás** loggear credenciales o resultados de queries (ver [security-model.md](../architecture/security-model.md)).
- Niveles: `DEBUG` para SQL completo, `INFO` para metadata, `WARNING` para límites alcanzados, `ERROR` para excepciones inesperadas.

## Configuración: `pyproject.toml` (extracto)

```toml
[project]
name = "nz-mcp"
version = "0.1.0"
description = "MCP server for IBM Netezza"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "mcp>=...",
    "nzpy>=...",
    "pydantic>=2",
    "sqlglot>=...",
    "keyring>=...",
    "structlog>=...",
    "typer>=...",
]

[project.optional-dependencies]
dev = [
    "pytest>=...",
    "pytest-cov>=...",
    "hypothesis>=...",
    "pytest-mock>=...",
    "ruff>=...",
    "mypy>=...",
    "pre-commit>=...",
]

[project.scripts]
nz-mcp = "nz_mcp.cli:app"

[tool.ruff]
line-length = 100
target-version = "py311"
[tool.ruff.lint]
select = ["E","F","W","I","N","UP","B","S","C4","SIM","RUF"]
ignore = []
[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]   # asserts permitidos en tests

[tool.mypy]
python_version = "3.11"
strict = true
warn_unreachable = true
disallow_any_explicit = true

[tool.pytest.ini_options]
addopts = "-ra --strict-markers --strict-config"
markers = [
    "contract: MCP conformance tests",
    "adversarial: SQL guard bypass attempts",
    "integration: real Netezza required",
    "slow: > 5s",
]
```

## Anti-patrones

- ❌ `from typing import List, Dict, Optional` (usar built-ins 3.11).
- ❌ `Any` sin comentario justificándolo.
- ❌ `try: ... except Exception: ...` sin re-raise.
- ❌ `print()` o `logging.basicConfig()` en libs.
- ❌ Mutable defaults.
- ❌ Imports relativos hacia arriba (`..`) con > 1 nivel.
- ❌ Funciones > 50 líneas (refactorizar).
- ❌ Side effects en `__init__.py` (excepto re-exports limpios).

## Checklist

- [ ] `ruff check .` y `ruff format --check .` limpios.
- [ ] `mypy --strict` limpio en módulo tocado.
- [ ] Excepciones tipadas, no genéricas.
- [ ] Sin `print`, sin `Any` injustificados.
- [ ] Funciones con una responsabilidad clara.
- [ ] Tests acompañando el código.
