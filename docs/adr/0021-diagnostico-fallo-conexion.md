# 21. Diagnóstico real del fallo de conexión: capturar el logger de nzpy

Date: 2026-09-05

## Status

Accepted

## Context

`open_connection` envolvía la excepción de `nzpy.connect` en `ConnectionError` usando `str(exc)` como `detail`. Para **todos** los fallos de handshake nzpy levanta el mismo texto genérico: `Error in handshake` (`core.py:1528`). Password incorrecta y base de datos inexistente daban un `detail` idéntico, verificado contra un Netezza real (issue #175, detectado validando el PR #174).

El motivo real sí existe, pero nzpy **lo loggea**, no lo propaga: `handshake.py:646` hace `self.log.warning("Error occured, server response:%s", error)` sobre el logger `nzpy.Connection[<database>}]`, creado en `core.py:1171` sin tocar `propagate`. Sin ningún handler en la jerarquía, esos registros acaban en `logging.lastResort` → **stderr**, donde ni el servidor MCP ni el CLI los leen.

## Decision

`open_connection` envuelve la llamada a `nzpy.connect` en un context manager que **añade un handler propio al logger `nzpy`** (ancestro del logger por conexión) mientras dura la conexión, y lo retira siempre en el `finally`. Al fallar, los mensajes capturados se normalizan (se quita el prefijo `Error occured, server response:`, el terminador NUL y las migas de control `Error in conn_*`), se concatenan con el texto de la excepción y se pasan **una sola vez** por `sanitize(known_secrets={password})` antes de llegar a ningún mensaje, log o hint.

Ese texto se clasifica en una causa estable mediante una **tabla de reglas ordenadas** (`_CAUSE_RULES`): `TLS_FAILED`, `AUTH_REJECTED`, `DATABASE_UNAVAILABLE`, `HOST_UNREACHABLE` y `UNKNOWN` como último recurso. Añadir un mensaje nuevo del driver cuesta una entrada en la tupla, no una rama nueva.

El `ConnectionError` resultante lleva en su `context` la `cause` y los hints accionables `hint_es` / `hint_en` (catálogo i18n `CONNECTION_FAILED.HINT.<cause>`, con test de paridad). El servidor MCP ya expone el `context` entero en el payload de error, así que la mejora llega a la vez a `nz-mcp test-connection`, al asistente de perfiles y a todas las tools sin tocar ninguna de ellas.

La firma pública de `open_connection` y el comportamiento de conexión no cambian.

## Alternatives considered

1. **`logOptions=LogOptions.Logfile`** — rechazada: nzpy escribiría un `nzpy.log` rotatorio en el cwd del proceso (basura en el directorio del usuario) y habría que leer un fichero para saber qué pasó.
2. **Bajar `logLevel` a DEBUG y leer stderr** — rechazada: inunda stderr con tráfico por paquete y rompe las UIs de cliente que lo renderizan (motivo por el que ya se fijó WARNING).
3. **Redirigir `sys.stderr` durante `connect`** — rechazada: es global al proceso, corre en el mismo proceso que el transporte stdio del MCP y se traga logs de terceros; el handler de `logging` obtiene el mismo texto sin efectos colaterales.
4. **`logging.basicConfig` o tocar la configuración global de logging** — rechazada: el servidor configura su propio pipeline (`logging_config.py`); una librería no debe reconfigurar el logging del proceso anfitrión.
5. **Parchear nzpy para que la excepción lleve el motivo** — rechazada: implicaría fork o monkeypatch de un driver de terceros por una mejora de mensaje.
6. **Reescribir el texto del servidor** (nzpy recorta los primeros bytes y emite `hentication failed for user 'X'`) — rechazada: el `detail` reproduce lo que dijo el driver; la legibilidad la aporta el hint, no una reconstrucción inventada.

## Consequences

- El `detail` distingue las cuatro causas del issue. Medido contra Netezza real (perfil `uaipscrea1`, NPS 11.2.1.11): password incorrecta → `Error in handshake: hentication failed for user 'UAIPSCREA1'`; BD inexistente → `Error in handshake: FATAL 1: Database "NO_EXISTE_XYZ" does not exist.`; host inalcanzable → `('communication error', TimeoutError('timed out'))`; CA equivocada → `Error in handshake: Problem establishing secured session`.
- Mientras el handler está puesto, `logging.lastResort` ya no dispara: los warnings de nzpy dejan de ensuciar stderr durante la conexión. Efecto secundario deseado para el transporte stdio.
- El handler es local y siempre se retira; si el proceso anfitrión ya tenía handlers en `nzpy` o en la raíz, siguen recibiendo los mismos registros (no se toca `propagate` ni los niveles).
- Un mensaje del driver no visto antes cae en `UNKNOWN` con un hint genérico, nunca en una causa equivocada de forma silenciosa.
- Si nzpy cambiara el nombre de su logger o dejara de loggear el motivo, el `detail` volvería al texto de la excepción: degradación al comportamiento anterior, sin excepción nueva.
