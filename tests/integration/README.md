# Integration tests

Tests marcados con `@pytest.mark.integration`: requieren **Netezza real** y VPN.
La guía completa está en [`docs/standards/testing.md`](../../docs/standards/testing.md).

## Cómo correrlos

1. Conecta la VPN.
2. Configura un perfil de desarrollo y guarda su password en el keyring:
   ```bash
   nz-mcp add-profile dev --active
   nz-mcp set-password dev
   ```
3. Ejecuta:
   ```bash
   NZ_MCP_RUN_INTEGRATION=1 uv run --extra dev pytest -q -m integration
   ```

Sin `NZ_MCP_RUN_INTEGRATION=1` la suite entera se salta (fixture autouse
`require_live_netezza` en `conftest.py`): no abre socket ni lee el keyring.

## Variables de entorno

| Variable | Default |
|---|---|
| `NZ_MCP_RUN_INTEGRATION` | sin default; `1` habilita la suite |
| `NZ_MCP_INTEGRATION_PROFILE` | perfil activo |
| `NZ_MCP_INTEGRATION_PROFILES` | `~/.nz-mcp/profiles.toml` |
| `NZ_MCP_TEST_DATABASE` | base del perfil |
| `NZ_MCP_TEST_SCHEMA` | `DBO` |
| `NZ_MCP_TEST_TABLE` / `NZ_MCP_TEST_PROCEDURE` | objetos del smoke de #71 |

## Reglas

- **No mockear el driver** en estos tests.
- No hardcodear base ni esquema: usar `integration_database` / `integration_schema`.
- Los tests de DDL/write borran su objeto en `finally`; nada debe quedar en Netezza.
- Ninguno escribe en el keyring: `set_password` y `delete_password` están bloqueados.

## CI

Estos tests **no corren en CI** (Netezza está detrás de VPN — ver ADR 0004).
El humano confirma que pasaron antes de cada release (ver `docs/actions/release.md`).
