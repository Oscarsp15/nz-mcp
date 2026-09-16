# ADR 0036 — `nz_call_procedure` asíncrono: lanzar, sondear, cancelar

- **Fecha**: 2026-09-16
- **Estado**: aceptado
- **Decidido por**: Oscar (owner), con diseño propuesto por Toby (implementador de `call.py` / `connection.py` en #272)
- **Issue**: [#287](https://github.com/Oscarsp15/nz-mcp/issues/287) (absorbe [#275](https://github.com/Oscarsp15/nz-mcp/issues/275) — cancelación server-side)
- **Alcance**: nuevo conjunto de tools para lanzar un SP en segundo plano y sondear / cancelar su resultado. `nz_call_procedure` (síncrono) no cambia.

## Contexto

### Comportamiento actual

`nz_call_procedure` (PR #272) abre una conexión nzpy con `timeout=None` y bloquea hasta que el SP devuelve. Para SPs de producción de 10-20 minutos o más, el agente que llama queda inoperativo durante todo ese tiempo.

El servidor MCP corre bajo `anyio.run()` con handlers de tool **síncronos**: `_handle_call_tool` en `server.py` llama a `_dispatch_tool_call(...)` directamente, sin `await` ni `anyio.to_thread.run_sync()`. nzpy es I/O bloqueante. Consecuencia verificada leyendo `server.py`: **mientras un CALL corre, el event loop queda bloqueado y no puede atender ninguna otra llamada MCP**. Dos llamadas concurrentes se serializan; la segunda espera a que la primera termine. Un SP de 20 minutos bloquea la herramienta entera durante 20 minutos.

### Qué se quiere

Un patrón no bloqueante:
1. Una tool lanza el SP en segundo plano y devuelve un `job_id` de inmediato.
2. Una tool sondea el estado (`running` / `done` / `failed`) y recoge el resultado cuando termina.
3. Una tool cancela el job enviando `ABORT SESSION` a Netezza desde una segunda conexión admin (absorbe #275).

El `nz_call_procedure` síncrono existente no se toca: sigue disponible para SPs cortos o para callers que prefieran esperar.

## Decisión

### 1. Modelo de concurrencia: hilo daemon por job

Cada llamada a `nz_call_procedure_async` lanza un `threading.Thread(daemon=True)`. El hilo abre su propia conexión nzpy (con `timeout=None`), ejecuta el CALL, actualiza el job store y cierra la conexión. Daemon para que el proceso servidor no quede bloqueado esperando hilos al apagar.

No se usa `anyio.to_thread.run_sync()` porque los handlers de tool son síncronos (ver contexto); no hay event loop accesible desde ellos. `threading.Thread` es suficiente y no añade dependencias.

Se limita a **`MAX_CONCURRENT_JOBS = 5`** trabajos simultáneos. Un intento de lanzar un sexto mientras cinco ya corren devuelve error `JOB_LIMIT_REACHED` con hint accionable.

### 2. Captura del session ID de Netezza

Inmediatamente después de abrir la conexión, antes del CALL, el hilo ejecuta:

```sql
SELECT CURRENT_SESSION
```

El resultado (`int`) se almacena en el job store. Es el identificador que `nz_job_cancel` necesita para enviar `ABORT SESSION <session_id>`. Si esta consulta falla (raro: la conexión ya está abierta), el job continúa y `session_id` queda `null`; `nz_job_cancel` devuelve entonces `CANCEL_UNAVAILABLE` con una explicación.

### 3. Job store

Módulo `src/nz_mcp/jobs.py`. Estado por job como dataclass; acceso protegido por `threading.Lock()` (módulo-nivel, compartido por todos los jobs).

```
JobState:
  job_id       str            UUID4, generado al lanzar
  status       Literal["running", "done", "failed", "cancelling", "cancelled"]
  created_at   float          time.monotonic() al lanzar
  completed_at float | None   time.monotonic() al terminar
  session_id   int | None     CURRENT_SESSION capturado al inicio del hilo
  result       dict | None    payload de éxito (return_value, messages, duration_ms)
  error        dict | None    payload de fallo (code, detail, partial_notices)
```

**Expiración**: los jobs completados (`done` / `failed` / `cancelled`) se eliminan del store **1 hora** después de `completed_at`. La limpieza es *lazy*: se ejecuta al inicio de cada llamada a `nz_job_poll` y `nz_job_cancel`, sin hilo de fondo adicional.

No hay persistencia en disco. Si el servidor reinicia, los jobs en vuelo se pierden. El ciclo de vida del servidor MCP (proceso por sesión de cliente) hace que esto sea aceptable para MVP.

### 4. Cancelación: ABORT SESSION

`nz_job_cancel` abre una **segunda conexión admin** con el mismo perfil, ejecuta `ABORT SESSION <session_id>` y cierra esa conexión. Luego marca el job como `"cancelling"` (el hilo background termina con error al recibir la interrupción de la sesión).

Si la sesión ya terminó antes de que llegue el ABORT (`status == "done"` o `"failed"`), devuelve `status: "already_done"` sin error.

Si `session_id` es `null` (no pudo capturarse), devuelve `CANCEL_UNAVAILABLE`.

`ABORT SESSION` requiere privilegios admin en Netezza. Si falla por permisos, el error se devuelve en el campo `abort_error` de la respuesta y el job sigue como `"running"` — el caller puede esperar a que termine o pedirle a un DBA que lo cancele con `ABORT SESSION <session_id>` directamente.

### 5. Superficie de tools

Las tres tools siguen las convenciones del contrato (`docs/architecture/tools-contract.md`).

#### `nz_call_procedure_async`

**Modo**: `admin`

**Input** (igual que `nz_call_procedure` menos `timeout_s` y `dry_run`):

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `database` | `str` | sí | Debe coincidir con el perfil activo |
| `schema` | `str` | sí | Schema del SP |
| `procedure` | `str` | sí | Nombre del SP |
| `args` | `list[Any]` | no | Argumentos posicionales |
| `signature` | `str` | no | Firma `(TYPE,TYPE)` para validar el conteo de args |
| `confirm` | `bool` | sí | Debe ser `true` para ejecutar |

No hay `timeout_s`: el job corre sin límite hasta que termina o se cancela explícitamente.

**Output** (éxito):
```json
{
  "job_id": "3f2d…",
  "status": "running",
  "session_id": null,
  "hint_es": "Sondea con nz_job_poll(job_id) cada 30 s. Cancela con nz_job_cancel(job_id) si es necesario.",
  "hint_en": "Poll with nz_job_poll(job_id) every 30 s. Cancel with nz_job_cancel(job_id) if needed."
}
```

`session_id` es `null` en el output de lanzamiento porque el hilo puede no haber capturado aún `CURRENT_SESSION`; está disponible en `nz_job_poll` en cuanto el hilo lo registra.

#### `nz_job_poll`

**Modo**: `read`

**Input**:

| Campo | Tipo | Requerido |
|---|---|---|
| `job_id` | `str` | sí |

**Output** (job en ejecución):
```json
{
  "job_id": "3f2d…",
  "status": "running",
  "session_id": 2485636,
  "partial_notices": ["Procesando lote 1 de 10…"],
  "elapsed_ms": 45230
}
```

**Output** (job terminado con éxito):
```json
{
  "job_id": "3f2d…",
  "status": "done",
  "session_id": 2485636,
  "return_value": null,
  "messages": ["Procesando lote 1 de 10…", "OK"],
  "duration_ms": 920000
}
```

**Output** (job fallido):
```json
{
  "job_id": "3f2d…",
  "status": "failed",
  "session_id": 2485636,
  "error": {
    "code": "NETEZZA_ERROR",
    "detail": "…",
    "partial_notices": ["Procesando lote 1 de 10…"]
  }
}
```

#### `nz_job_cancel`

**Modo**: `admin`

**Input**:

| Campo | Tipo | Requerido |
|---|---|---|
| `job_id` | `str` | sí |

**Output**:
```json
{
  "job_id": "3f2d…",
  "status": "cancelling",
  "message_es": "ABORT SESSION enviado a la sesión 2485636. El job pasará a 'cancelled' cuando el hilo confirme la interrupción.",
  "message_en": "ABORT SESSION sent to session 2485636. The job will transition to 'cancelled' once the thread confirms the interruption."
}
```

### 6. `nz_call_procedure` síncrono no cambia

Su contrato, código y tests quedan exactamente como los dejó #272. Las dos tools coexisten; el caller elige cuál usar según su caso.

## Consecuencias

### Positivas

- El agente llamador vuelve a estar disponible mientras el SP corre.
- El session ID capturado cierra el pendiente de #275 (cancelación server-side).
- Ningún cambio en `nz_call_procedure` existente: cero riesgo de regresión en callers actuales.

### Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Jobs perdidos al reiniciar el servidor | Ciclo de vida del proceso MCP = sesión del cliente; documentado como limitación conocida |
| Proliferación de hilos si se lanzan muchos jobs | `MAX_CONCURRENT_JOBS = 5`; error claro si se supera |
| nzpy no documentada como thread-safe | Cada hilo tiene su propia conexión y cursor; `_DriverDiagnosticsHandler` ya filtra por thread ID; no hay estado compartido de driver |
| ABORT SESSION puede no tener permisos | `abort_error` en la respuesta; instrucción para que un DBA ejecute el ABORT manualmente con el `session_id` devuelto |
| `session_id` no capturado (raro) | `nz_job_cancel` devuelve `CANCEL_UNAVAILABLE`; el job sigue corriendo |
| Carrera entre `ABORT SESSION` y la finalización natural del SP | `nz_job_cancel` verifica el estado antes de enviar ABORT; si ya terminó, devuelve `already_done` |
| Expiración: el caller no recoge el resultado a tiempo | TTL de 1 hora post-completado; documentado en la descripción de `nz_job_poll` |

## Estimación de esfuerzo (FASE 2)

| Componente | LoC estimadas |
|---|---|
| `src/nz_mcp/jobs.py` (job store + `JobState`) | ~120 |
| `src/nz_mcp/catalog/call_async.py` (lógica del hilo, session capture) | ~130 |
| Registros de las 3 tools + input models | ~90 |
| `docs/architecture/tools-contract.md` (secciones nuevas) | ~60 |
| Tests unitarios (mock de thread, store, cancel) | ~200 |
| **Total** | **~600 LoC** |

Esfuerzo estimado: **medio** — comparable al alcance de nz-2 (#272). Bloqueante: aprobación de Oscar sobre este ADR antes de arrancar FASE 2.

## Alternativas consideradas

### A. `asyncio.create_task` en el handler async

`_handle_call_tool` ya es `async def`. Se podría crear una tarea asyncio y devolver el `job_id` de inmediato. Rechazado: los handlers de tool actuales son síncronos (`_dispatch_tool_call` no es async); refactorizarlos para ser awaitable requeriría cambios en todos los 24 tools y en `server.py`, un alcance mucho mayor que el de esta feature.

### B. Worker process separado (multiprocessing / subprocess)

Más aislamiento, pero comunicación entre procesos (pipes, sockets) añade complejidad y latencia. No aporta ventajas sobre un hilo daemon dado que ya manejamos el aislamiento de conexión y el GIL no es el cuello de botella (I/O bloqueante, no CPU).

### C. Cola de jobs persistente (SQLite / archivo)

Permitiría recuperar jobs tras un reinicio. Rechazado para MVP: añade una dependencia de almacenamiento, complica el ciclo de vida y el caso de uso (SPs en vuelo al reiniciar son inherentemente en estado desconocido). Puede añadirse como mejora posterior si el patrón de uso lo justifica.
