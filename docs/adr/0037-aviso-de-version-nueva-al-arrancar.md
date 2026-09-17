# ADR 0037 — Aviso de versión nueva al arrancar el servidor (update-notify)

- **Fecha**: 2026-09-17
- **Estado**: aceptado
- **Decidido por**: Oscar (owner), con diseño propuesto por god (orquestador) y ejecutado por Ryan
- **Issue**: [#349](https://github.com/Oscarsp15/nz-mcp/issues/349)
- **Alcance**: comportamiento nuevo al arrancar `nz-mcp serve`. No añade, quita ni cambia ninguna tool del catálogo.

## Contexto

### Comportamiento actual

`nz-mcp` se instala con `uv tool install nz-mcp` o `pip install nz-mcp` y publica en PyPI en canal alpha. `nz-mcp version` imprime la versión **instalada**, y nada en el producto dice qué versión hay publicada. Un usuario con una instalación de hace dos semanas no tiene forma de enterarse de que existen tools o fixes nuevos: el único camino es acordarse de mirar PyPI a mano.

### Qué se quiere

Que el servidor, al arrancar, avise **una sola vez** y de forma **best-effort** cuando PyPI tiene una versión más nueva, con el comando exacto de upgrade. Es un aviso de cortesía: no actualiza nada, no bloquea, no falla y no se convierte en un problema cuando la máquina está sin red.

## Decisión

### 1. Best-effort en hilo daemon, nunca en el camino de arranque

`start_update_check()` lanza `threading.Thread(daemon=True)` y devuelve el control de inmediato; el handshake MCP no espera. El hilo usa un timeout de **1,5 s**. Cualquier fallo —sin red, DNS, proxy, TLS, timeout, PyPI caído, cuerpo que no es JSON, JSON con forma inesperada— termina en **silencio total**: ni mensaje, ni traza, ni línea de log. Se capturan explícitamente `OSError` / `ValueError` / `KeyError` / `TypeError` en el borde, en vez de un `except Exception` a secas (coding.md).

El motivo es asimétrico: el coste de avisar de más cuando no hay red es mucho mayor que el de no avisar una vez. Convertir "PyPI no responde" en "el servidor MCP falla" sería un bug introducido por una comodidad.

### 2. Solo stderr, jamás stdout

`serve` habla JSON-RPC sobre stdout; un solo byte ajeno ahí rompe el protocolo y el cliente MCP muere sin error legible (ADR 0027, addendum 1). El aviso sale por `nz_mcp.cli_output.warn()`, que escribe en **stderr** y es el único escritor de terminal del proyecto. Un test unitario comprueba que stdout queda vacío, y el contract test de stdout de `serve` sigue cubriendo el proceso completo.

### 3. Cache de 24 h en el directorio de configuración

El resultado (`{"checked_at": <epoch>, "latest": <str|null>}`) se guarda en `~/.nz-mcp/update-check.json`, calculado con `config.config_dir()` para respetar `NZ_MCP_HOME` (los tests apuntan ahí). Dentro de la ventana de 24 h no hay llamada de red. Un cliente MCP que reinicia el servidor varias veces al día no golpea PyPI cada vez.

### 4. Opt-out: `NZ_MCP_NO_UPDATE_CHECK`

Sigue la convención de `NZ_MCP_NO_CONSOLE_PREP` (ADR 0033): cualquier valor cuenta como *sí* salvo los que convencionalmente significan *no* (`""`, `0`, `false`, `no`). Con la variable activa no se lanza ni el hilo ni la llamada de red.

### 5. Comparación con `packaging.version`: nueva dependencia directa

La comparación tiene que ordenar versiones **PEP 440 con pre-releases**: el proyecto publica `0.1.0aN`, y `0.1.0a10` es posterior a `0.1.0a4` (una comparación lexicográfica diría lo contrario). La implementación correcta de esa regla es `packaging.version.Version`, que ya viene instalada de forma transitiva pero pasa a ser **dependencia directa declarada** en `pyproject.toml` (regla 5 de AGENTS.md: dependencia nueva ⇒ ADR, que es este documento). `importlib.metadata.version("nz-mcp")` da la versión instalada; en un checkout sin metadatos de distribución cae a `nz_mcp.__version__`.

### 6. Módulo nuevo `src/nz_mcp/update_check.py`, no una tool

Vive al lado de las otras utilidades transversales (`diagnostic.py`, `profile_check.py`, `jobs.py`): no registra tool, no toca SQL, no es alcanzable por `tools/call` y por tanto **no aparece** en `tools-contract.md` ni en `EXPECTED_V010A0`. Solo importa `i18n`, `cli_output`, `config` y stdlib + `packaging`.

## Consecuencias

### Positivas

- Quien instala y se olvida se entera del upgrade sin hacer nada.
- El coste en el arranque es cero en la práctica: hilo daemon y 1,5 s de techo.
- Ningún cambio en el contrato de tools ni en el protocolo MCP.
- La lógica es testeable sin red y sin reloj real: `latest_version(now=..., cache_path=..., fetch=...)` inyecta las tres dependencias externas.

### Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Una escritura descuidada contamina stdout y rompe el protocolo | El aviso sale solo por `cli_output.warn` (stderr); test unitario + contract test de stdout |
| La comprobación ralentiza el arranque | Hilo daemon + timeout 1,5 s; el handshake no espera |
| PyPI caído o sin red genera errores en consola | Silencio total por diseño; `OSError`/`ValueError` capturados explícitamente |
| Golpear PyPI en cada reinicio | Cache de 24 h en `update-check.json` |
| Ruido en CI o en uso automatizado | `NZ_MCP_NO_UPDATE_CHECK=1` |
| Ordenar mal las pre-releases (`a10` vs `a4`) | `packaging.version.Version`, dependencia directa declarada |
| El archivo de cache queda a medias | Escritura best-effort: un `OSError` se traga y la próxima ejecución reintenta |

## Alternativas consideradas

### A. `httpx` en vez de `urllib`

`httpx` ya está en el árbol por `mcp`. Rechazada: añade una dependencia directa más para una única petición GET con timeout, cuando `urllib.request` de la stdlib cubre el caso. Menos superficie y menos deuda.

### B. Comprobación bloqueante en el arranque

Rechazada: sumaría hasta el timeout a cada arranque, y un arranque lento en un cliente MCP se lee como "el servidor no funciona".

### C. Sin cache

Rechazada: un cliente que reinicia el servidor varias veces al día multiplicaría las peticiones a PyPI sin ninguna ganancia.

### D. Comparación manual de versiones, sin `packaging`

Rechazada: reimplementar la comparación PEP 440 de pre-releases a mano es exactamente el tipo de código que se equivoca en silencio y que una dependencia ya resuelta evita.
