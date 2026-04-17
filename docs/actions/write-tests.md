# Playbook — Escribir tests

> Lee primero [testing.md](../standards/testing.md) y [qa-engineer.md](../roles/qa-engineer.md).

## Cuándo añadir tests

- **Siempre que** cambies comportamiento.
- **Siempre que** descubras un bug (test de regresión primero, fix después).
- **Siempre que** el coverage de un módulo baje.
- Tras añadir tool nueva: contract + unit + (idealmente) integration local.

## Pirámide a respetar

1. **Unit con mocks** (rápidos, muchos).
2. **Contract MCP** (medios, en CI).
3. **Adversarial** (en CI; obligatorios al tocar `sql_guard`).
4. **Property-based** con `hypothesis` (parsers, sanitizers).
5. **Integration** (lentos, locales, contra Netezza real).

## Marks

```python
import pytest

# unit (sin mark)
def test_x(): ...

@pytest.mark.contract
def test_mcp_lists_all_tools(): ...

@pytest.mark.adversarial
def test_guard_rejects_stacked(): ...

@pytest.mark.integration
def test_real_select_against_netezza(): ...

@pytest.mark.slow
def test_benchmark(): ...
```

## Estructura recomendada

```
tests/
├── conftest.py
├── unit/
│   └── test_<modulo>.py
├── contract/
│   └── test_<aspecto>.py
├── adversarial/        ← opcional, también vale en unit/ con mark
│   └── test_<vector>.py
├── property/
│   └── test_<modulo>_props.py
└── integration/
    ├── README.md
    └── test_real_<flujo>.py
```

## Patrón: test unitario de tool con driver mockeado

```python
import pytest
from nz_mcp.tools.query_select import nz_query_select, QuerySelectInput
from nz_mcp.errors import GuardRejectedError

def test_select_happy_path(fake_profile, fake_connection, monkeypatch):
    monkeypatch.setattr("nz_mcp.connection.get_connection",
                        lambda profile: fake_connection)
    out = nz_query_select(fake_profile, QuerySelectInput(sql="SELECT 1"))
    assert out.row_count >= 0
    assert out.truncated is False

def test_select_rejects_delete(fake_profile):
    with pytest.raises(GuardRejectedError) as e:
        nz_query_select(fake_profile, QuerySelectInput(sql="DELETE FROM t WHERE 1=1"))
    assert e.value.code == "WRONG_STATEMENT_FOR_TOOL"
```

## Patrón: test adversarial

```python
import pytest
from nz_mcp.sql_guard import validate
from nz_mcp.errors import GuardRejectedError

@pytest.mark.adversarial
@pytest.mark.parametrize("sql,code", [
    ("SELECT 1; DROP TABLE t;",                  "STACKED_NOT_ALLOWED"),
    ("SELECT /*; DROP TABLE t; */ 1;",           "STACKED_NOT_ALLOWED"),
    ("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x;",
                                                  "STATEMENT_NOT_ALLOWED"),
    ("UPDATE t SET a=1",                          "UPDATE_REQUIRES_WHERE"),
    ("DELETE FROM t",                             "DELETE_REQUIRES_WHERE"),
    ("BEGIN; DELETE FROM t; COMMIT;",             "STACKED_NOT_ALLOWED"),
])
def test_guard_blocks(sql, code):
    with pytest.raises(GuardRejectedError) as e:
        validate(sql, mode="read")
    assert e.value.code == code
```

## Patrón: property-based

```python
from hypothesis import given, strategies as st
from nz_mcp.logging_utils import sanitize

@given(st.text(min_size=8, max_size=64))
def test_sanitize_masks_known_secret(secret):
    line = f"connecting password={secret} to host"
    assert secret not in sanitize(line, known_secrets={secret})
```

## Patrón: contract MCP

```python
import pytest
from nz_mcp.server import build_server

EXPECTED_TOOLS = {
    "nz_query_select", "nz_explain", "nz_list_databases", "nz_list_schemas",
    "nz_list_tables", "nz_describe_table", "nz_table_sample", "nz_table_stats",
    "nz_get_table_ddl", "nz_list_views", "nz_get_view_ddl",
    "nz_list_procedures", "nz_describe_procedure", "nz_get_procedure_ddl",
    "nz_get_procedure_section",
    "nz_insert", "nz_update", "nz_delete",
    "nz_create_table", "nz_truncate", "nz_drop_table",
    "nz_clone_procedure",
    "nz_current_profile", "nz_switch_profile",
}

@pytest.mark.contract
def test_all_tools_registered():
    server = build_server()
    names = {t.name for t in server.list_tools()}
    assert names == EXPECTED_TOOLS

@pytest.mark.contract
def test_all_tools_have_schemas():
    server = build_server()
    for tool in server.list_tools():
        assert tool.input_schema, f"{tool.name} missing input_schema"
        assert tool.output_schema, f"{tool.name} missing output_schema"
        assert tool.description, f"{tool.name} missing description"
```

## Cobertura

- Global ≥ 85 % (CI rojo si baja).
- `sql_guard.py`, `auth.py`, `i18n.py` (mensajes): 100 %.
- Excluir solo: `if TYPE_CHECKING`, `raise NotImplementedError`, `pragma: no cover`.

## Anti-patrones

- ❌ `pytest.skip()` para silenciar test que falla.
- ❌ `time.sleep()`.
- ❌ Mock del driver en integration.
- ❌ Tests que dependen del orden.
- ❌ Tests que tocan `~/.nz-mcp/` real (usar `tmp_path`).
- ❌ `assert True` o tests sin assertion.
- ❌ Mockear lo que estás probando.

## Checklist

- [ ] Test cubre el comportamiento, no la implementación.
- [ ] Marks correctos.
- [ ] Cobertura global y por módulo no baja.
- [ ] Si toqué `sql_guard`: ≥ 3 tests adversariales nuevos.
- [ ] Sin `skip`, `xfail` injustificados.
