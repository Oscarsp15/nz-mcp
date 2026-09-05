# Estándares de testing

## Pirámide

```
                  ┌──────────────┐
                  │ integration  │  pocos, locales con VPN
                  └──────────────┘
              ┌──────────────────────┐
              │  scenarios por rol   │  uno por rol, en CI
              └──────────────────────┘
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
| `scenario` | Recorrido por rol encadenando tools sobre el doble del driver | ✅ |
| `integration` | Requiere Netezza real (con VPN) | ❌ (v0.1) |
| `slow` | > 5 s | opt-in (`pytest -m slow`) |

Definidos en `pyproject.toml` con `--strict-markers`.

## Escenarios por rol (`tests/scenarios/`)

Nivel nuevo entre contract e integration. Un archivo por rol de usuario (analista,
data engineer, mantenedor de procedimientos, operador). Correr solo estos:
`pytest -m scenario`.

**Qué prueba un escenario y un unitario no**: el **encadenamiento**. Un escenario llama
a `server.call_tool` como lo hace un cliente y usa la salida de una tool como entrada de
la siguiente, **sin reformatear el identificador**. Fija cosas que ninguna tool puede
comprobar sola:

- que el nombre que devuelve un listado es válido como argumento de la tool siguiente;
- que el `hint` de una tool truncada apunta a la línea exacta donde continuar
  (numeraciones distintas entre el DDL reconstruido y `PROCEDURESOURCE`);
- que el `dry_run` describe lo que hace la ejecución real;
- que el objeto que crea una tool es el que encuentra la siguiente;
- que cambiar de perfil o de base afecta ya a la llamada siguiente.

**Cuándo basta un unitario**: una tool aislada, una rama de error, un parser, un límite.
Si el aserto no habla de **dos tools**, es un unitario.

**Reglas**:

- El único doble es `nzpy.connect`, sustituido por `tests/scenarios/netezza_double.py`.
  Ninguna tool ni función de catálogo se mockea: si el escenario pasa, pasó por
  `sql_guard`, por la puerta de permisos y por la capa de catálogo de verdad.
- El doble vive en **un solo sitio**; los archivos de escenario no definen el suyo.
- El doble **falla ruidosamente** (`FakeNetezzaError`) ante SQL que no entiende: un
  escenario nunca debe pasar porque el doble devolvió vacío en silencio.
- Cada rol incluye al menos un caso negativo: el mismo recorrido con un modo
  insuficiente se detiene donde debe y **no llega SQL al driver**.
- Sin red, sin `sleep`, sin dependencia de orden entre escenarios.
- Si un escenario destapa un bug real, se abre issue aparte; el test queda marcado con
  la referencia a ese issue, no se arregla la tool en el mismo PR.

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
  - Cada tool tiene `inputSchema`, `description`, `annotations`. `outputSchema` NO se declara (ADR 0019).
  - Errores con la estructura del contrato (campo `code`, mensajes ES/EN).

## Tests de integración (local con VPN)

- Carpeta `tests/integration/`.
- Marcar **todos** con `@pytest.mark.integration`.
- Variables de entorno necesarias documentadas en `tests/integration/README.md`.
- Usar un perfil de desarrollo (jamás uno que apunte a datos de producción).
- Limpieza: los tests de write/DDL crean su objeto y lo borran en `finally`; al terminar la
  suite no debe quedar nada en Netezza.

### Cómo correrlos de verdad

Requisitos, los tres a la vez:

1. **VPN conectada** y el host del perfil alcanzable. Sin VPN los tests fallan en la
   conexión, no se saltan.
2. Un perfil configurado en `~/.nz-mcp/profiles.toml` con su password **ya guardada en el
   keyring** (`nz-mcp set-password <perfil>`). La suite nunca escribe la credencial.
3. La variable `NZ_MCP_RUN_INTEGRATION=1`.

Comando exacto (bash / Git Bash):

```bash
NZ_MCP_RUN_INTEGRATION=1 uv run --extra dev pytest -q -m integration
```

PowerShell:

```powershell
$env:NZ_MCP_RUN_INTEGRATION = "1"; uv run --extra dev pytest -q -m integration
```

`--extra dev` no es opcional: sin él `uv run` puede resolver un `pytest` de fuera del
entorno del proyecto y ejecutar los tests contra otra copia del código y otra versión de
`nzpy`.

> **La password ya no sale en la traza de un fallo** (issue #191, ADR 0026). La credencial
> viaja como `Secret`: en la salida de pytest aparece `password = Secret(***)`, en
> `open_connection` y en los frames de `nzpy`, con cualquier `--tb` y también con
> `--showlocals`. Host, puerto, base y usuario siguen visibles para diagnosticar.
>
> Lo que la traza sí puede seguir mostrando: host, usuario y nombre de base del perfil, y
> el mensaje del servidor. No son secretos, pero antes de pegar una salida en un sitio
> público conviene mirarla. Y si escribes un helper propio que reciba la password **como
> argumento**, ese frame es tuyo: pásale lo que devuelve `get_password`, que ya es un
> `Secret`, en vez de fabricar una `str`.

Sin `NZ_MCP_RUN_INTEGRATION=1` los 13 tests se **saltan** (fixture autouse
`require_live_netezza` en `tests/integration/conftest.py`): no abren socket ni leen el
keyring. La suite normal (`uv run --extra dev pytest -q`) los deselecciona igual que antes.

### Coordenadas: nunca hardcodeadas

Las fixtures `integration_database` / `integration_schema` toman por defecto la base del
perfil activo y el esquema `DBO`. Overrides opcionales:

| Variable | Para qué |
|---|---|
| `NZ_MCP_RUN_INTEGRATION=1` | Habilita la suite (obligatoria). |
| `NZ_MCP_INTEGRATION_PROFILE` | Perfil a usar; por defecto, el activo. |
| `NZ_MCP_INTEGRATION_PROFILES` | Ruta alternativa a `profiles.toml`. |
| `NZ_MCP_TEST_DATABASE` | Base a consultar; por defecto, la del perfil. |
| `NZ_MCP_TEST_SCHEMA` | Esquema; por defecto `DBO`. |
| `NZ_MCP_TEST_TABLE`, `NZ_MCP_TEST_PROCEDURE` | Objetos concretos del smoke de #71. |

Las tools DDL rechazan cualquier base distinta a la del perfil activo, así que el default
"la base del perfil" es lo único que deja correr lectura y DDL con las mismas coordenadas.

### Keyring: la única excepción a `isolated_keyring`

El fixture autouse `isolated_keyring` (`tests/conftest.py`) sustituye el keyring por uno en
memoria para **toda** la suite. Los tests de integración necesitan la credencial real, así
que se exceptúan solo si se cumplen las tres condiciones a la vez: `NZ_MCP_RUN_INTEGRATION=1`,
marca `integration` y módulo dentro de `tests/integration/`. Aun exceptuados, `set_password`
y `delete_password` quedan bloqueados: un test de integración **lee** la credencial, nunca la
escribe ni la borra. Cubierto por `tests/unit/test_keyring_isolation.py`.

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
