# Rol: QA / Test Engineer (senior)

## Mindset

Los tests no son ceremonia, son **el contrato vivo** del sistema. Si un comportamiento no tiene test, no existe. Si un test falla intermitentemente, se arregla; no se silencia.

## Doc principal

[../standards/testing.md](../standards/testing.md) tiene la estrategia detallada. Este rol-doc cubre el *cómo trabajas*.

## Responsabilidades

- Mantener la pirámide de tests: muchos unit, algunos contract, pocos integration.
- Cobertura objetivo: **85 % global**, **100 %** en `sql_guard.py` y `auth.py`.
- Property-based testing en parsers y validadores.
- Tests adversariales en `sql_guard`.
- Fixtures reproducibles para Netezza (mocks + integration local).

## Tipos de tests y `pytest.mark`

| Marca | Para | Corre en CI | Corre en local |
|---|---|---|---|
| (sin marca) | Unit con mocks | ✅ | ✅ |
| `@pytest.mark.contract` | Conformidad MCP JSON-RPC | ✅ | ✅ |
| `@pytest.mark.adversarial` | Bypass del `sql_guard` | ✅ | ✅ |
| `@pytest.mark.integration` | Contra Netezza real | ❌ (v0.1) | ✅ con VPN |
| `@pytest.mark.slow` | > 5 s | opt-in | opt-in |

`pytest.ini`:
```ini
[pytest]
markers =
    contract: tests de conformidad MCP
    adversarial: tests de bypass de seguridad
    integration: requieren Netezza real (correr local con VPN)
    slow: tardan > 5s
addopts = -ra --strict-markers --strict-config
```

## Estructura de tests

```
tests/
├── conftest.py              ← fixtures globales (fake_profile, fake_cursor, etc.)
├── unit/
│   ├── test_sql_guard.py
│   ├── test_sql_guard_adversarial.py
│   ├── test_auth.py
│   ├── test_tools_query_select.py
│   ├── test_connection.py
│   ├── test_i18n.py
│   └── ...
├── contract/
│   ├── test_mcp_handshake.py
│   ├── test_mcp_tool_schemas.py
│   └── test_error_format.py
├── integration/
│   ├── test_real_connection.py
│   ├── test_real_catalog.py
│   └── test_real_query.py
└── property/
    ├── test_sql_guard_props.py
    └── test_sanitizer_props.py
```

## Mock del driver: patrón

```python
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def fake_cursor():
    cur = MagicMock()
    cur.fetchmany.side_effect = [
        [(1, "Alice"), (2, "Bob")],
        [],   # señal de fin
    ]
    cur.description = [("ID", "INTEGER"), ("NAME", "VARCHAR")]
    return cur

@pytest.fixture
def fake_connection(fake_cursor):
    conn = MagicMock()
    conn.cursor.return_value = fake_cursor
    return conn

def test_execute_select_streams_until_max_rows(fake_connection):
    result = execute_select(
        connection=fake_connection,
        sql="SELECT * FROM t LIMIT 1",
        max_rows=1,
        timeout_s=10,
    )
    assert result["row_count"] == 1
    assert result["truncated"] is True
```

## Property-based testing (hypothesis)

Para `sql_guard` y `sanitize`:

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=200))
def test_sanitize_never_leaks_known_secret(s):
    secret = "super-secret-password-123"
    contaminated = f"connecting with password={secret} {s}"
    assert secret not in sanitize(contaminated, known_secrets={secret})

@given(st.sampled_from(["SELECT 1", "SELECT * FROM t WHERE id = 1"]))
def test_select_passes_in_read_mode(sql):
    assert validate(sql, mode="read").kind == StatementKind.SELECT
```

## Tests adversariales (lista mínima)

Ver `docs/architecture/security-model.md` § "Casos adversariales que el guard DEBE bloquear". Cada caso debe estar en `tests/unit/test_sql_guard_adversarial.py` con expectativa `pytest.raises(GuardRejectedError)`.

## Tests de contrato MCP

- Levantar el server en proceso, cliente fake JSON-RPC, verificar:
  - `tools/list` devuelve exactamente las 16 tools de [tools-contract.md](../architecture/tools-contract.md).
  - Cada tool tiene `inputSchema`, `outputSchema`, `description`, `annotations`.
  - Errores siguen el formato del contrato.

## Cobertura

- `pytest --cov=src/nz_mcp --cov-report=term-missing --cov-fail-under=85`.
- `coveragerc`:
  ```ini
  [run]
  branch = True
  source = src/nz_mcp
  
  [report]
  exclude_lines =
      pragma: no cover
      raise NotImplementedError
      if TYPE_CHECKING:
  ```
- Módulos con cobertura **100 %** obligatoria: `sql_guard.py`, `auth.py`, `i18n.py` (mensajes).

## Anti-patrones

- ❌ `pytest.skip()` para silenciar test que falla.
- ❌ Tests que dependen de orden.
- ❌ Mock del driver en tests `@pytest.mark.integration`.
- ❌ `assert True` o tests sin assertion.
- ❌ Tests que tardan > 5 s sin marcar `@pytest.mark.slow`.
- ❌ Compartir estado entre tests vía variables globales.
- ❌ `@pytest.mark.skipif(...)` con condición vaga ("flaky en CI").

## Checklist antes de PR

- [ ] Tests nuevos para todo comportamiento nuevo.
- [ ] `pytest -m "not integration"` verde.
- [ ] Cobertura ≥ 85 %, 100 % en módulos de seguridad.
- [ ] No silencié warnings con `pytest.filterwarnings`.
- [ ] Si toqué `sql_guard`: añadí ≥ 3 tests adversariales.
- [ ] Si añadí integration test: documenté que se corre local con VPN.
