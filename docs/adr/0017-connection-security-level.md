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
4. **Exponer `security_level` en el wizard CLI `add-profile`** — se difirió aquí como fuera del alcance mínimo del issue (campo + propagación + doc + test), con la nota "follow-up si se pide". **Diferimiento retirado** por la enmienda 2026-09-04 (#168): el wizard pregunta `security_level` y `ca_certs`.

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

## Enmienda 2026-09-04 (#160): verificación de certificado opt-in vía `ca_certs`

### Contexto

nzpy **1.17.7** endureció el handshake SSL. Con `securityLevel` 2 o 3, si el cliente no aporta un
bundle CA ni pide explícitamente saltar la verificación, el driver aborta con
`No CA certificate provided. Supply a valid ca_certs path or set skipCertVerification=True`.
nzpy 1.17.4 (con el que se validó esta ADR) caía silenciosamente a `CERT_NONE`. `connection.py` no
pasaba ni `ssl` ni `skipCertVerification`, así que **toda instalación nueva** (`pip`/`pipx` resuelven
nzpy 1.17.7) fallaba contra appliances con SSL habilitado, incluso con el default `security_level = 2`.

### Verificado contra el código de nzpy 1.17.7 (no asumido)

- `nzpy/__init__.py:49-54` — firma de `connect(...)`: `ssl=None` y `skipCertVerification=None` son
  **kwargs top-level e independientes**. `skipCertVerification` **no** es una clave del dict `ssl`.
- `nzpy/__init__.py:60-61` — si `skipCertVerification is None`, se resuelve a
  `securityLevel not in (2, 3)`: con el default `2` de esta ADR queda `False` → verificación exigida.
- `nzpy/handshake.py:295` — el dict `ssl` se lee únicamente como `self.ssl_params.get('ca_certs')`.
- `nzpy/handshake.py:300-311` — sin `ca_certs`: si `skipCertVerification` es falso, warning y
  `return False` (handshake abortado); si es `True`, contexto con `CERT_NONE`.
- `nzpy/handshake.py:313-330` — con `ca_certs`: `ssl.create_default_context(cafile=ca_certs)` y
  `verify_mode = CERT_REQUIRED` (`check_hostname = False` lo fija el driver, no es configurable).

### Decisión

- `Profile` gana el campo opcional `ca_certs: str | None = None` (ruta a bundle CA en PEM).
  `extra="forbid"` se mantiene.
- `open_connection` pasa **siempre** una de dos combinaciones a `nzpy.connect`:
  - `ca_certs` definido → `ssl={"ca_certs": <ruta>}` + `skipCertVerification=False`
    (verificación obligatoria, `CERT_REQUIRED`).
  - `ca_certs` ausente → `skipCertVerification=True` (SSL cifrado, sin verificar certificado).
- La verificación de certificado es **opt-in**: el default no verifica para **no romper on-prem**,
  cuyos appliances rara vez exponen una CA confiable, y reproduce exactamente el comportamiento
  que este proyecto ya tenía con nzpy 1.17.4. El cifrado del canal (`security_level` 2/3) no cambia.
- El pin mínimo sube a `nzpy>=1.17.7` en `pyproject.toml`. Verificado contra los wheels de PyPI:
  `skipCertVerification` **no existe** en 1.17.4 (la firma de `connect` no acepta `**kwargs` →
  `TypeError`) ni en 1.17.5/1.17.6; aparece en 1.17.7. Sin tope superior.

### Alternativas descartadas

1. **Fijar `nzpy<1.17.7` en `pyproject.toml`** — rechazada: congela el driver, oculta el problema y
   la spec (`data-engineer.md`) exige soportar la última estable.
2. **Verificación obligatoria por defecto (sin `ca_certs` → error)** — rechazada como default:
   rompe on-prem igual que el bug que se corrige; queda disponible como opt-in vía `ca_certs`.
3. **Pasar `ssl={"skipCertVerification": True}`** (lo que sugería el issue) — rechazada: el driver
   ignora esa clave (`handshake.py:295` solo lee `ca_certs`) y el handshake seguiría abortando.

### Consecuencias

- Instalaciones nuevas vuelven a conectar con el default `security_level = 2`.
- Instalaciones existentes con nzpy 1.17.4 se actualizan a 1.17.7 al reinstalar (`pip install -e .`)
  porque el pin mínimo lo exige; sin ese pin el kwarg nuevo rompería el driver viejo.
- Quien disponga del certificado del appliance obtiene verificación real con una línea en
  `profiles.toml`. Sin `ca_certs`, el canal va cifrado pero es vulnerable a MITM con certificado
  falso (misma exposición que con nzpy 1.17.4); documentado en `security-model.md`.
- Exponer `ca_certs` en el wizard `add-profile` se resuelve en la enmienda siguiente (#168).

## Enmienda 2026-09-04 (#168): el wizard pregunta `security_level` y `ca_certs`

### Contexto

La alternativa 4 de esta ADR difirió exponer `security_level` en el asistente del CLI con un
"follow-up si se pide", y la enmienda de #160 arrastró el mismo diferimiento para `ca_certs`.
El issue #168 lo pide: configurar el nivel de seguridad exigía editar `profiles.toml` a mano,
justo el archivo que el asistente acaba de escribir.

### Decisión

- `nz-mcp init` / `nz-mcp add-profile` preguntan **`security_level`** (default `DEFAULT_SECURITY_LEVEL`
  = 2, el mismo de `Profile`) y **`ca_certs`** (opcional; Enter lo omite), tras una línea que explica
  qué significa cada uno. Ambos se persisten en el perfil.
- Los valores pasan a ser **propiedad del wizard**: al sobrescribir un perfil se reemplazan como
  host o puerto, con el valor actual ofrecido como default de la pregunta. Antes se preservaban a
  ciegas porque el wizard no los preguntaba (#167). Los campos que el wizard sigue sin preguntar
  (`catalog_overrides` y cualquiera que se añada después) se preservan igual que hasta ahora.
- Sin `ca_certs`, la clave no se escribe en el TOML: un valor vacío significa "no verificar",
  no "conservar el anterior".

### Consecuencias

- Los defaults del modelo (`DEFAULT_SECURITY_LEVEL`, `MIN/MAX_SECURITY_LEVEL`) son ahora
  constantes de `config.py` reutilizadas por el `Profile` y por el wizard: un solo sitio que
  cambiar si se revisan los niveles.
- El diferimiento de §4 queda **retirado**; esta ADR ya no tiene follow-ups pendientes.
