# 16. `nz_switch_database` — cambiar la BD de trabajo del perfil activo

Date: 2026-07-09

## Status

Accepted

## Context

La BD "activa" (contra la que resuelven las queries sin calificar) la fija `profile.database` al abrir cada conexión efímera. Cambiarla solo era posible creando **un perfil por BD** y usando `nz_switch_profile`. En el setup real del proyecto —un servidor, un usuario (`UAIPSCREA1`), muchas BDs (`DESA_MODELOS`, `DESA_MAESTROBI`, …)— eso obliga a provisionar un perfil (y un password de keyring) por cada BD, aunque las credenciales sean las mismas.

El issue [#153](https://github.com/Oscarsp15/nz-mcp/issues/153) pide que la IA pueda saltar entre BDs del mismo server —y volver— de forma autónoma, sin pre-crear perfiles, para trabajar con `SELECT * FROM DBO.EFE_MC_CREDITOS` en vez de `DESA_MAESTROBI..EFE_MC_CREDITOS`.

## Decision

Añadimos `nz_switch_database(database)`, `mode="read"`, que actualiza el campo `database` del **perfil activo** en `profiles.toml` (vía `update_profile_fields`, reutilizando las credenciales del keyring de ese perfil). La siguiente tool call lee `profiles.toml` fresco y opera contra la nueva BD.

### Por qué es seguro que la IA lo haga

- **La BD no es una frontera de seguridad.** La IA ya puede leer/escribir cualquier BD visible con la notación cross-DB `BD..objeto`; cambiar la BD por defecto solo mueve la resolución de nombres no calificados. No otorga acceso nuevo.
- **No toca el `mode`.** El `mode` sigue siendo lo único que la IA no puede cambiar (regla inviolable 2 de `AGENTS.md`); `nz_switch_database` solo altera `database`. Host/user/mode se cambian con `nz_switch_profile`.
- **Verifica existencia y visibilidad.** El target se valida con `validate_database_identifier` (patrón `[A-Z][A-Z0-9_]*`) y se comprueba contra `_v_database` (lo que el usuario del perfil ve); si no es visible → `OBJECT_NOT_FOUND` con la lista disponible. Falla rápido ante typos, sin dejar el perfil en un estado que rompa queries posteriores.

### Persistencia (consciente)

Igual que `nz_switch_profile` persiste `active` en `profiles.toml`, `nz_switch_database` persiste el `database` del perfil activo. El output incluye `previous_database` para que la IA sepa a qué volver, y la descripción de la tool le indica **"switch back when done"**. Es un cambio de estado de sesión que sobrevive entre procesos hasta que se revierte.

## Alternatives considered

1. **Un perfil por BD + `nz_switch_profile`** — funciona hoy pero exige provisionar N perfiles y N passwords de keyring para el mismo usuario; fricción alta para el caso "misma cuenta, muchas BDs".
2. **Override de BD por-llamada en `nz_query_select`** (`database=`) — rechazado: cada tool abre su propia conexión, así que habría que propagar el override a todas las tools; multiplica superficie y rompe el patrón "el contexto de sesión vive en el perfil".
3. **`SET CATALOG` en una conexión persistente de sesión** — rechazado: el server no mantiene una conexión viva entre tool calls; cada call es independiente y re-lee `profiles.toml`.
4. **No persistir (solo en memoria)** — inviable: no hay estado de sesión en memoria compartido entre tool calls; el único canal es `profiles.toml`.

## Consequences

### Positivas
- La IA salta a cualquier BD visible del server con una tool call, reutilizando credenciales; sin pre-crear perfiles.
- Witness E2E (`nzsaas`, 2026-07-09): `DESA_MODELOS` → `nz_switch_database('DESA_MAESTROBI')` → `SELECT COUNT(*) FROM DBO.EFE_MC_CREDITOS` = 39 943 sin prefijo de BD → restaurado a `DESA_MODELOS`.

### Costes / negativas
- Persiste en `profiles.toml`: si la IA cambia y no revierte, el default cambia entre sesiones. Mitigación: `previous_database` en el output + indicación explícita en la descripción de la tool.
- La verificación contra `_v_database` añade una query al cambiar (no en el no-op de misma BD).

### Qué monitorizar
- Si `_v_database` no lista alguna BD válida para ciertos grants (falso negativo), evaluar relajar el chequeo a advisory.

## References

- Issue #153 (GitHub) — spec y criterios de aceptación.
- `docs/architecture/security-model.md` — `mode` como única frontera que la IA no cambia; validación de identificadores de BD.
- `docs/architecture/tools-contract.md` § 35 — contrato de la tool.
- Tools relacionadas: `nz_switch_profile` (§ 28), `nz_current_profile` (§ 27), `nz_list_databases` (§ 3).
