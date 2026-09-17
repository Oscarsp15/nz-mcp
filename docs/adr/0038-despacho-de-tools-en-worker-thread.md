# ADR 0038 — Despachar los tools síncronos en worker threads (`anyio.to_thread`)

- **Fecha**: 2026-09-17
- **Estado**: aceptado
- **Decidido por**: Oscar (owner), con diagnóstico de Dwight y ejecución de Toby
- **Issue**: [#360](https://github.com/Oscarsp15/nz-mcp/issues/360)
- **Alcance**: cambia el modelo de ejecución del servidor (`server.py`). No añade, quita ni renombra ninguna tool del catálogo.

## Contexto

### Comportamiento actual

`build_mcp_server` registra un handler `async def _handle_call_tool` que llama a `_dispatch_tool_call(...)` **directamente**, sin `await anyio.to_thread.run_sync()` ni `await` de ningún tipo. Todos los handlers de tool son **síncronos** y nzpy es I/O bloqueante, así que el handler async pasa la duración completa del tool ocupando el hilo del event loop.

Consecuencia: mientras un tool corre, el loop no procesa nada más. Los **pings** no contestan, las `CancelledNotification` no llegan, y cualquier otra petición se **encola** detrás. Si el tool tarda más que el timeout del cliente MCP (~120 s), el cliente cierra stdio, el server sale por EOF (`rc=0`) y la persona interpreta que "se murió el MCP". No es un crash: es **falta de responsividad**. Un `nz_find_table` sin acotar o un `nz_call_procedure` legítimo de 10–20 min bastan para dispararlo.

Este límite ya estaba descrito como consecuencia conocida en [ADR 0036](0036-nz-call-procedure-asincrono.md), que lo esquivó **solo para `nz_call_procedure_async`** con un `threading.Thread` propio. Las demás tools síncronas quedaron fuera.

### Qué se quiere

Que un tool lento **no bloquee el loop**: el server debe seguir leyendo stdio (pings, cancelaciones, otras peticiones) mientras un tool corre, de modo que una segunda tool no se serialice detrás de la primera y el cliente siga vivo.

## Decisión

### 1. `anyio.to_thread.run_sync` en el handler, no handlers async

Se añade `_dispatch_tool_call_offloaded(...)`, que envuelve el dispatcher síncrono con `anyio.to_thread.run_sync(partial(_dispatch_tool_call, ...), limiter=limiter)`. El handler async hace `await` de esa corrutina y nada más: el trabajo bloqueante vive en un worker thread del pool de anyio.

El dispatcher sigue siendo **síncrono** y no se toca la firma de ningún handler. Convertir los 51 tools a `async`/`await` (o a un driver async) sería una reescritura de todo el catálogo; el objetivo —no bloquear el loop— se logra con un solo `await` en el borde. `run_sync` no acepta kwargs, de ahí el `functools.partial`.

### 2. Tope de concurrencia explícito: `anyio.CapacityLimiter(MAX_CONCURRENT_TOOLS)`

Cada tool abre **su propia** conexión nzpy, así que el número de tools concurrentes es también el número de sesiones Netezza simultáneas. El `limiter` de anyio se pasa a `run_sync`, que lo usa como límite de hilos para esa llamada.

`MAX_CONCURRENT_TOOLS = 8`: deliberadamente por debajo del límite por defecto de anyio (40), para que una ráfaga de tools lentos no se convierta en una ráfaga de conexiones. El valor es un parámetro de `build_mcp_server`, inyectable en tests. Superar el tope **no falla**: la petición espera un hueco (a diferencia del `JOB_LIMIT_REACHED` de [ADR 0036](0036-nz-call-procedure-asincrono.md), aquí encolar es el comportamiento correcto porque el cliente espera una respuesta).

### 3. Cancelación: diferida, nunca huérfana

Se deja el default `abandon_on_cancel=False`. Si el cliente manda `CancelledNotification`, la corrutina **no** abandona el hilo: espera a que el tool termine y entonces propaga la cancelación. No se fuerza porque **nzpy no expone `cancel()`** (ver #275 y #291): abandonar el hilo dejaría una sesión Netezza corriendo de gancho, que es exactamente el P0 que se quiere evitar. El beneficio real de este ADR no es cancelar antes, sino que **el loop siga atendiendo todo lo demás** mientras el tool corre.

### 4. La API síncrona `call_tool` no cambia

`call_tool` (usada por el CLI y por tests unitarios) sigue siendo síncrona y llama al dispatcher directo. El cambio vive solo en el camino async del transporte stdio, que es donde existe el event loop.

### 5. Auditoría de estado global compartido

Pasar a multi-hilo obliga a revisar el estado de proceso:

| Estado | Veredicto |
|---|---|
| Job store (`jobs.py`) | Ya protegido por `threading.Lock`; sin cambios. |
| `i18n.MESSAGES` | Solo lectura; sin cambios. |
| `config.get_active_profile` / `load_profiles_file` | Solo lectura; sin cambios. |
| **Escritores de `profiles.toml`** (`set_active_profile`, `upsert_profile`, `remove_profile`, `update_profile_fields`) | **Riesgo real**: read-modify-write sin lock y `.tmp` de nombre fijo compartido. Se serializan con `_WRITE_LOCK` (un `threading.Lock` de módulo). |
| `_DriverDiagnosticsHandler` (`connection.py`) | Ya filtra por `record.thread == self._thread_id`; su propio docstring lo describe como *"a guard against a future thread pool"*. Sin cambios: el guard se vuelve efectivo ahora. |

## Consecuencias

### Positivas

- Un tool lento ya no bloquea pings, cancelaciones ni otras peticiones; dos tools no se serializan.
- El cliente deja de ver "el MCP se murió" por un tool largo.
- Cambio de superficie mínima: un helper nuevo, un parámetro y una constante; ni un handler tocado.
- Testeable sin Netezza: un tool de prueba que se bloquea en un `threading.Event` demuestra el no-bloqueo de forma determinista.

### Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Ráfaga de conexiones nzpy | `CapacityLimiter(8)`, por debajo del default 40 de anyio |
| Carrera al escribir `profiles.toml` | `_WRITE_LOCK` en los cuatro escritores |
| Hilo huérfano tras cancelación | `abandon_on_cancel=False`; nzpy sin `cancel()` documentado como límite |
| Regresión del contrato MCP (handshake, nº de tools) | El handler solo cambia `_dispatch_tool_call` por `await ..._offloaded`; contract tests de wire y de esquemas siguen verdes |
| Contaminación de diagnósticos entre conexiones concurrentes | El handler de `connection.py` ya filtra por hilo |

## Alternativas consideradas

### A. Hacer todos los handlers `async` (o driver async)

Rechazada: reescribir 51 tools y el acceso a nzpy para un problema que se resuelve con un `await` en el borde. Alcance desproporcionado y de riesgo alto.

### B. `asyncio.to_thread` en vez de `anyio`

Rechazada: el servidor ya corre sobre `anyio.run()` y usa `anyio` para el transporte. `anyio` aporta además el `CapacityLimiter` que se necesita; `asyncio.to_thread` obligaría a un semáforo propio y ataría el código a un backend concreto.

### C. Sin límite (usar el limiter por defecto de anyio, 40)

Rechazada: 40 tools lentos serían hasta 40 conexiones Netezza simultáneas desde un único cliente stdio, sin control. El tope explícito es más barato que descubrirlo en producción.

### D. `abandon_on_cancel=True`

Rechazada: honraría la cancelación al instante, pero dejaría el hilo y la sesión Netezza corriendo sin forma de abortarlos (nzpy sin `cancel()`), reintroduciendo el problema de sesiones huérfanas de #275/#291.

### E. Confiar en `nz_call_procedure_async` para todo

Rechazada: ese camino solo cubre procedimientos. Las tools de catálogo (`nz_find_table`, `nz_query_select`, etc.) no tienen variante asíncrona y son justo las que bloquean el loop en el uso normal.
