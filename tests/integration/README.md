# Integration tests

Tests marcados con `@pytest.mark.integration` requieren **Netezza real**.

## Cómo correrlos

1. Conecta tu VPN.
2. Configura un perfil `test` apuntando a una BD de pruebas (no producción):
   ```bash
   nz-mcp add-profile test --active
   ```
3. Ejecuta:
   ```bash
   pytest -m integration -v
   ```

## Reglas

- **No mockear el driver** en estos tests.
- Crear objetos con sufijo `_nzmcp_test_<uuid>` y limpiarlos en `finally`.
- Usar perfil `test`, jamás `prod`.
- Si añades un test, documenta qué objetos crea.

## CI

Estos tests **no corren en CI** (Netezza está detrás de VPN — ver ADR 0004).
El humano confirma que pasaron antes de cada release (ver `docs/actions/release.md`).

## v0.1.0a0

Ningún test de integration aún. Llegan junto con la primera tool de lectura
real (issue #1).
