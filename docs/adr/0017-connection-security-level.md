# 17. `security_level` configurable por perfil, seguro por defecto

Date: 2026-07-09

## Status

Accepted

## Context

`connection.py` abría **todas** las conexiones con `securityLevel=1` (only-unsecured) hardcodeado: la sesión y las credenciales viajaban **sin cifrar** y nunca se negociaba TLS. No era configurable (el modelo `Profile` usa `extra="forbid"`). Eso: (a) contradice a la instancia SaaS/nube, que exige SSL; (b) es un riesgo de sniffing/MITM en cualquier red no confiable.

El issue [#136](https://github.com/Oscarsp15/nz-mcp/issues/136) (auditoría multiagente, `type/security`, `priority/P1`) pide que `securityLevel` sea configurable por perfil, con **default seguro**, propagado a `nzpy.connect`, documentado, y con test de que el valor del perfil llega a la conexión.

## Decision

Añadimos el campo `security_level: int` al `Profile` (`ge=0, le=3`) y lo propagamos a `nzpy.connect(securityLevel=...)`. Valores (convención de nzpy):

| valor | significado |
|---|---|
| 0 | preferred-unsecured (intenta claro, sube a SSL si hace falta) |
| 1 | only-unsecured (claro, sin TLS) |
| **2** | **preferred-secured — negocia SSL, con fallback a claro (DEFAULT)** |
| 3 | only-secured (SSL requerido, sin fallback) |

### Default `2` (preferred-secured), no `1`

El default es **`2`**, no el `1` histórico. Razones:
- **Secure-by-default**: se negocia TLS siempre que el servidor lo ofrezca; las credenciales dejan de viajar en claro por defecto.
- **No rompe on-prem sin TLS**: `2` hace *fallback* a claro si el servidor no tiene SSL, así que los perfiles existentes que omiten el campo siguen conectando (con más seguridad cuando esté disponible), sin cambio de configuración.
- **`1` es opt-in explícito**: el tráfico en claro solo se permite si el humano lo pide a propósito (`security_level = 1`), pensado para una red de laboratorio confiable. El issue exige exactamente esto ("el valor 1 solo por opt-in explícito").
- **SaaS/nube usan `3`**: la instancia cloud (`nzsaas`) requiere SSL; su perfil declara `security_level = 3`.

### Cambio de comportamiento observable

Perfiles que **omiten** `security_level` pasan de `1` (claro) a `2` (SSL preferido con fallback). Es un cambio de default consciente y de seguridad: más seguro y compatible por el fallback. Documentado en `CHANGELOG` y `security-model.md`. Requiere **validación humana antes de release** (el issue lo marca como cambio sensible).

## Alternatives considered

1. **Default `3` (only-secured)** — rechazado como default: rompería cualquier on-prem sin SSL (sin fallback). Correcto como valor explícito para SaaS, no como default global.
2. **Mantener default `1` y solo hacerlo configurable** — rechazado: el issue exige default seguro; dejar `1` perpetúa el tráfico en claro por defecto.
3. **Campo `ssl: bool`** — rechazado: pierde la granularidad de los 4 niveles de nzpy (preferred vs only, secured vs unsecured); un entero mapeado 1:1 a `securityLevel` es más fiel al driver.
4. **Exponer `security_level` en el wizard CLI `add-profile`** — diferido: fuera del alcance mínimo del issue (que pide campo + propagación + doc + test). Por ahora se setea editando `profiles.toml`; follow-up si se pide.

## Consequences

### Positivas
- Credenciales cifradas por defecto; SaaS conecta con `security_level = 3`.
- Configurable por perfil sin tocar código.
- Witness E2E (`nzsaas`, `security_level = 3`): conexión SSL viva, `SELECT 1` → `[1]`.

### Costes / negativas
- Cambio de default observable (1 → 2) para perfiles que omiten el campo. Mitigación: fallback de `2` evita romper on-prem; documentado; validación humana antes de release.
- `security_level = 1` sigue disponible pero desaconsejado (solo lab).

### Qué monitorizar
- Reportes de on-prem que fallen la negociación `2` (improbable por el fallback); si ocurre, el usuario fija `security_level = 0/1` explícito.

## References

- Issue #136 (GitHub) — spec, criterios de aceptación, marca de cambio sensible.
- ADR 0003 — credenciales en keyring (contexto de seguridad de conexión).
- `docs/architecture/security-model.md` — sección SSL / `security_level`.
- `src/nz_mcp/connection.py`, `src/nz_mcp/config.py` — implementación.
