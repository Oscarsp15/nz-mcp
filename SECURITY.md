# Política de seguridad

## Reportar una vulnerabilidad

**No abras un issue público** para vulnerabilidades.

Usa **[GitHub Security Advisories](https://github.com/Oscarsp15/nz-mcp/security/advisories/new)** para reportar de forma privada.

Recibirás respuesta inicial en **≤ 5 días hábiles**.

## Versiones soportadas

| Versión | Soporte de seguridad |
|---|---|
| Última `MINOR` publicada | ✅ |
| `MINOR` anterior | ✅ durante 30 días tras nueva `MINOR` |
| Más antiguas | ❌ |

## Modelo de amenazas

Ver [`docs/architecture/security-model.md`](docs/architecture/security-model.md).

Resumen:
- **3 barreras defensivas**: tools de responsabilidad única → `sql_guard` (sqlglot) → grants Netezza.
- **Credenciales**: `keyring` OS-native, jamás en archivo plano.
- **Modos por perfil**: `read` / `write` / `admin`. La IA no puede elevar privilegios.
- **Logging**: queries y metadata sí; resultados y credenciales nunca.

## Qué SÍ es vulnerabilidad

- Bypass de `sql_guard` que permita ejecutar SQL fuera del modo del perfil.
- Filtración de credenciales en logs, errores o respuestas.
- SQL injection vía parámetros del usuario.
- Escalación de privilegios entre perfiles.
- Lectura/escritura no autorizada de `~/.nz-mcp/*`.

## Qué NO es vulnerabilidad

- Comportamiento documentado del modo `admin` (es por diseño).
- Errores informativos que no exponen secretos.
- Consumo alto de tokens del LLM por queries grandes (configurable por límites).

## Disclosure timeline

1. Recibimos report → confirmamos en 5 días.
2. Investigamos y desarrollamos fix.
3. Coordinamos disclosure con quien reportó.
4. Publicamos parche + CVE si aplica.
5. Disclosure público tras parche.

## Reconocimiento

Quienes reporten vulnerabilidades reales serán reconocidos en `SECURITY-CREDITS.md` (con su consentimiento).
