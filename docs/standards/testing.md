# Estándares de testing

## Pirámide

```
                  ┌──────────────┐
                  │ integration  │  pocos, locales con VPN
                  └──────────────┘
              ┌──────────────────────┐
              │     contract MCP     │  algunos, en CI
              └──────────────────────┘
        ┌──────────────────────────────────┐
        │   unit + adversarial + property   │  muchos, en CI
        └──────────────────────────────────┘
```

## Marks (`pytest.mark`)

| Mark | Significado | CI |
|---|---|---|
| (sin) | Unit con mocks | ✅ |
| `contract` | Conformidad MCP JSON-RPC | ✅ |
| `adversarial` | Intentos de bypass de seguridad | ✅ |
| `property` | Property-based con `hypothesis` | ✅ |
| `integration` | Requiere Netezza real (con VPN) | ❌ (v0.1) |
| `slow` | > 5 s | opt-in (`pytest -m slow`) |

Definidos en `pyproject.toml` con `--strict-markers`.

## Cobertura

- **Global**: ≥ 85 %.
- **`sql_guard.py`**: 100 %.
- **`auth.py`**: 100 %.
- **`i18n.py`** (mensajes): 100 % (cada clave tiene test).
- Falla CI si cae bajo umbral.

`pytest --cov=src/nz_mcp --cov-branch --cov-report=term-missing --cov-fail-under=85`

## Mocks: regla

- Mockear el **driver** (`nzpy`), no la lógica.
- Mockear `keyring` con backend de test (`keyring.backends.fail.Keyring` o un dummy).
- En tests `@pytest.mark.integration`: **prohibido** mockear el driver.

## Fixtures comunes (en `conftest.py`)

```python
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def fake_profile():
    return Profile(name="test", host="x", port=5480, database="DB",
                   user="u", mode="read", max_rows_default=100, timeout_s_default=30)

@pytest.fixture
def fake_cursor():
    cur = MagicMock()
    cur.description = [("ID","INTEGER"),("NAME","VARCHAR")]
    cur.fetchmany.side_effect = [[(1,"a"),(2,"b")], []]
    return cur

@pytest.fixture
def fake_connection(fake_cursor):
    conn = MagicMock()
    conn.cursor.return_value = fake_cursor
    return conn

@pytest.fixture(autouse=True)
def isolated_keyring(monkeypatch):
    """Cada test usa un keyring vacío en memoria."""
    store = {}
    monkeypatch.setattr("keyring.get_password", lambda s,u: store.get((s,u)))
    monkeypatch.setattr("keyring.set_password", lambda s,u,p: store.update({(s,u):p}))
    monkeypatch.setattr("keyring.delete_password", lambda s,u: store.pop((s,u), None))
```

## Property-based con hypothesis

Aplicar a parsers, validators, sanitizers. Ejemplos en [qa-engineer.md](../roles/qa-engineer.md).

## Tests adversariales (sql_guard)

Lista mínima en [security-model.md](../architecture/security-model.md). Cada caso:

```python
import pytest
from nz_mcp.sql_guard import validate
from nz_mcp.errors import GuardRejectedError

@pytest.mark.adversarial
@pytest.mark.parametrize("sql,code", [
    ("SELECT 1; DROP TABLE t;", "STACKED_NOT_ALLOWED"),
    ("UPDATE t SET a=1", "UPDATE_REQUIRES_WHERE"),
    ("DELETE FROM t", "DELETE_REQUIRES_WHERE"),
    ("DROP DATABASE x", "STATEMENT_NOT_ALLOWED"),
    ("BEGIN; DELETE FROM t; COMMIT;", "STACKED_NOT_ALLOWED"),
])
def test_guard_rejects(sql, code):
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="read")
    assert exc.value.code == code
```

## Tests de contrato MCP

- Levantar el server in-process.
- Cliente fake que envía `initialize`, `tools/list`, `tools/call`.
- Verifica:
  - 16 tools exactas en `tools/list`.
  - Cada tool tiene `inputSchema`, `outputSchema`, `description`, `annotations`.
  - Errores con la estructura del contrato (campo `code`, mensajes ES/EN).

## Tests de integración (local con VPN)

- Carpeta `tests/integration/`.
- Marcar **todos** con `@pytest.mark.integration`.
- Variables de entorno necesarias documentadas en `tests/integration/README.md`.
- Usar perfil `test` (no `prod`) — requisito documentado.
- Limpieza: tests de write/DDL crean objetos con sufijo `_nzmcp_test_<uuid>` y los borran al final (fixture `tmp_table`).

## Tests determinísticos

- Sin dependencia de tiempo real (`freezegun` o congelar tiempo).
- Sin dependencia de orden (`pytest-randomly` recomendado).
- Sin red salvo `@pytest.mark.integration`.

## CI

- `pytest -m "not integration" -n auto` con `pytest-xdist` para paralelizar.
- Cross-OS: Ubuntu, Windows, macOS.
- Cross-Python: 3.11, 3.12.
- Coverage report subido a artifacts; sin servicios externos en v0.1.

## Anti-patrones

- ❌ `pytest.skip()` para evitar tests que fallan.
- ❌ `time.sleep()` en tests.
- ❌ Mock del driver en integration.
- ❌ Tests sin assertion.
- ❌ Compartir estado entre tests.
- ❌ Tests que tocan `~/.nz-mcp/` real (usar `tmp_path`).
- ❌ `try/except` que silencia fallos del test.

## Checklist

- [ ] Tests para todo comportamiento nuevo.
- [ ] Marks correctos.
- [ ] Cobertura cumple los umbrales.
- [ ] No introduje flakiness.
- [ ] Si añadí integration: doc actualizado, cleanup garantizado.
