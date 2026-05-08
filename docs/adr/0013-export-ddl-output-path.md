# 13. `nz_export_ddl` admite `output_path` para escribir el DDL a disco

Date: 2026-05-08

## Status

Accepted

## Context

`nz_export_ddl` devuelve el DDL como un bloque MCP `EmbeddedResource` (`mimeType: text/sql`, URI `nz-mcp://ddl/...`) más un `TextContent` con resumen. En clientes con UI rica (Claude Desktop) el usuario puede copiar/guardar el resource desde la propia interfaz. En clientes terminal (Claude Code, Cursor sobre stdio) **no hay** ese affordance: el LLM tiene que tomar el `text` del resource, llamar a una tool externa de escritura (`Write`, `bash > path`, etc.), y rezar para que no haya BOM, CRLF u otros artefactos al pasar por capas intermedias.

El issue [#127](https://github.com/Oscarsp15/nz-mcp/issues/127) pide cerrar ese gap: que `nz_export_ddl` pueda persistir el DDL directamente al filesystem **del servidor MCP**, byte-idéntico al que devuelve hoy en el resource block.

Discutimos dos formas:

1. **Tool nueva** `nz_save_ddl_to_file` (intent separado).
2. **Parámetro opcional** `output_path` sobre la tool existente.

## Decision

**Adoptamos la opción 2: parámetro opcional sobre la tool existente.** El intent ya está cubierto por `nz_export_ddl` ("saca este DDL de MCP"); cambia el sink (resource → archivo), no la operación. Hay precedente en CLIs serios (`aws s3api get-object --output-file`, `gcloud sql export --destination`). API surface menor para el LLM, back-compat trivial: `output_path=None` (default) preserva el comportamiento actual.

### Firma resultante

```python
nz_export_ddl(
    object_type: Literal["table", "view", "procedure"],
    database: str,
    schema: str,
    name: str,
    signature: str | None = None,
    include_constraints: bool = True,
    output_path: str | None = None,   # NEW
    overwrite: bool = False,           # NEW
)
```

### Política de paths (validada antes de tocar Netezza)

La validación corre en `nz_mcp/io/safe_write.py::validate_output_path` y se invoca **antes** de la query al catálogo, vía `_validate_output_path_eager` en la tool. Reglas:

- Solo path **absoluto** (`pure.is_absolute()`).
- Sin segmentos `..` (path traversal).
- Sin `~` (no expandimos home; si el usuario lo quiere, que lo expanda él en cliente).
- Sin caracteres de control ASCII (`\x00`-`\x1f`, `\x7f`).
- La carpeta padre debe **existir**; nunca se crea automáticamente.
- Archivo no existe **a menos que** `overwrite=True`.

Las violaciones de path-policy levantan `ValueError`; las de filesystem-state, `FileNotFoundError` / `FileExistsError`. Todas se traducen en la capa de tool a `InvalidInputError` (código estable `INVALID_INPUT`) para mantener el envelope MCP de errores y la UX i18n. El detalle original viaja en `error.context.detail`.

### Permisos del archivo

- **POSIX**: el archivo se crea con permisos `0600` (solo el dueño lee/escribe). El DDL puede contener nombres de columnas y lógica sensible.
- **Windows (NT)**: `Path.chmod(0o600)` solo toggle-a el read-only bit, no setea ACLs POSIX. Heredamos la ACL del directorio padre. La tool no intenta emular `0600` con `pywin32` ni manipula DACLs porque (a) introduciría una dependencia, (b) está fuera del alcance v1, (c) en práctica los runners Windows del codebase corren como cuenta dedicada con HOMEDIR ya restringido. Documentamos la diferencia explícitamente y la convertimos en follow-up si aparece un caso de uso real.

Tests anclan la diferencia: el test POSIX (`stat.S_IMODE == 0o600`) está marcado `skipif(sys.platform == "win32")`; un segundo test fuerza la rama POSIX vía monkeypatch sobre `_is_posix` para garantizar 100 % cobertura en runners Windows.

### Resource + path o solo path

**Devolvemos los dos.** Cuando `output_path` está presente y la escritura tiene éxito:

- El bloque `EmbeddedResource` sigue presente con el `text` del DDL (back-compat estricta con clientes que ya lo consumen).
- `meta` se enriquece con `output_path`, `bytes_written`, `sha256` (hex SHA-256 de los bytes UTF-8 escritos).

Razones:

1. **Auditoría**: el LLM puede comparar el `sha256` reportado con uno calculado sobre el `text` del resource si necesita verificar que no hubo manipulación intermedia.
2. **Inspección barata**: el LLM puede razonar sobre el contenido (resource) sin volver a leer el archivo.
3. **El cap del resource block sigue siendo el mismo**: si el DDL es enorme, el cliente puede consumir el archivo por path y descartar el resource.

El `meta` cuando `output_path` no se pasa preserva los nuevos campos como `null`, no rompe la forma esperada por clientes existentes.

### Byte-identidad (acceptance crítico)

Lo escrito al archivo debe ser **byte-idéntico** al `text` del resource:

- UTF-8 sin BOM.
- Sin reformateo, sin header añadido, sin trailing newline insertado.
- Sin traducción CRLF (abrimos `wb` y volcamos `content.encode("utf-8")`).

Hay un test (`test_nz_export_ddl_byte_identical_with_and_without_output_path`) que ejerce las dos rutas (con y sin `output_path`) sobre el mismo DDL y compara `target.read_bytes() == ddl.encode("utf-8")` y `resource_text == ddl`.

### `allowed_export_paths` (diferido)

El issue mencionó la opción de un allowlist configurable por perfil (`profiles.toml::allowed_export_paths`). **Lo dejamos fuera del alcance de este PR** por:

- No hay caso de uso urgente reportado.
- Aumenta complejidad de configuración sin un beneficio claro vs. la política dura ya implementada (no traversal, no `~`, parent dir debe existir).
- Cuando aparezca el caso, se abre issue propio + ADR follow-up; la introducción es aditiva (campo opcional ignorado si está vacío).

## Alternatives considered

1. **Tool separada `nz_save_ddl_to_file`** — rechazada: dos tools con intents superpuestos, más superficie para que el LLM se confunda, y la lógica de filesystem se aísla igual sin necesidad de un nuevo entry point.
2. **Devolver solo `path` (sin resource cuando se persiste)** — rechazada: rompe back-compat con clientes que parsean `content[0].resource.text`, y obliga al LLM a re-leer el archivo para razonar sobre el DDL.
3. **Validar path después de fetch** — rechazada: el issue exige rechazo *antes* de tocar Netezza para paths inválidos. Validamos eagerly en `_validate_output_path_eager` justo después de `monotonic_start()`.
4. **Auto-crear el directorio padre** — rechazada: enmascara errores de tipeo y multiplica los lugares donde un MCP server puede materializar archivos inesperados.
5. **Setear ACLs Windows manualmente con `pywin32`** — rechazada: dependencia nueva sin caso de uso justificado, scope creep.

## Consequences

### Positivas

- Clientes terminal (Claude Code, Cursor stdio) ahora pueden persistir DDL en una sola tool call.
- `safe_write.py` queda como módulo aislado, 100 % cobertura, reusable si en el futuro otra tool necesita escribir a disco bajo la misma policy.
- Auditoría reforzada: `sha256` reportado en `meta` permite verificar integridad.

### Costes / negativas

- +1 módulo (`nz_mcp/io/safe_write.py`) y +9 tests adversariales que mantener.
- La tool ahora condiciona dos sinks (resource cuando `output_path=None`, resource+archivo cuando se especifica). Mitigación: la lógica de filesystem está completamente aislada en `safe_write.py` y la tool solo orquesta.
- Riesgo nuevo de seguridad: escritura a disco en el host del MCP server. Mitigación: política dura (no traversal, no `~`, parent dir debe existir, permisos `0600` en POSIX), validada por unit tests.

### Qué monitorizar

- Reportes de fricción con `output_path` (paths que la política rechaza pero deberían ser válidos).
- Si aparecen ≥ 3 issues pidiendo `allowed_export_paths`, reactivar el follow-up.
- Si Windows aparece como blocker para alguien que quiere `0600` real, abrir issue para evaluar `pywin32` o documento explícito de operación con HOMEDIR restringido.

## References

- Issue #127 (GitHub) — spec original con criterios de aceptación.
- Issue #129 (GitHub) — follow-up: cap collision + header `SET CATALOG`.
- ADR 0006 — Tools de responsabilidad única (justifica preferencia por extensión vs. tool nueva en este caso).
- ADR 0011 — `nz_get_procedure_table_logic` (precedente de aislar lógica en módulos reusables).
- `docs/architecture/tools-contract.md` § 29 — contrato actualizado.
- `docs/standards/i18n.md` — convención de mensajes ES/EN.

---

## Revisión 2026-05-08 (issue #129)

Después del merge de #128 aparecieron dos problemas reales que esta revisión documenta y resuelve **sin cambiar la firma básica `output_path` / `overwrite`**, sólo añadiendo dos parámetros opcionales con defaults seguros.

### Problemas observados

1. **Cap collision en respuestas grandes.** Reproducción E2E (perfil `uaipscrea1`, 2026-05-08): `nz_export_ddl(procedure, PROD_ANALITICA, DBO, PI_CLIENTESTCM, output_path=...)` con un DDL de ~67 KB hace que el response del MCP server (resource block + summary + meta + envoltorios JSON) supere el cap de ~100 KB / 25k tokens y el cliente recibe un error `result … exceeds maximum allowed tokens`, **aunque el archivo en disco se escribió correctamente**. La decisión "Resource + path o solo path" del ADR original (devolver ambos) chocó con la spec congelada del cap.
2. **Archivo sin contexto de BD.** El archivo escrito por #128 era el DDL crudo: si lo abres una semana después no sabes a qué BD pertenece y, si lo intentas re-ejecutar, falla por referencias no calificadas. No hay forma de auto-contener el archivo sólo con el cuerpo del DDL.

### Decisiones nuevas

#### D1. Por defecto, omitir el `EmbeddedResource` cuando hay `output_path`

Se añade el parámetro `include_resource_in_response: bool = False`. El comportamiento queda:

| Escenario | Resource block en response | Archivo en disco |
|---|---|---|
| `output_path is None` | sí (sin cambios) | no aplica |
| `output_path != None`, `include_resource_in_response=False` (default) | **omitido** — sólo `TextContent` summary + `meta.preview` (10 primeras líneas) | sí |
| `output_path != None`, `include_resource_in_response=True` | sí (el caller asume el riesgo de cap collision) | sí |

Justificación: el archivo en disco es la fuente de verdad cuando el caller eligió persistir; el resource block era valioso para clientes con UI rica que siempre vieron el archivo + texto, pero esos clientes ya rompen con DDLs grandes por el cap. El default seguro es omitirlo. El parámetro `include_resource_in_response` permite recuperar la forma anterior bajo riesgo conocido (auditorías que comparen el `text` del resource con el sha256 del archivo, por ejemplo).

`meta.preview` (10 primeras líneas del archivo en disco) reemplaza al resource como indicador barato para que el LLM razone sobre el contenido sin volver a abrir el archivo. Es un campo bounded — no crece con el tamaño del DDL.

**Cambio de default explícito**: callers de #128 que pasaban `output_path` y dependían de leer `content[0].resource.text` ahora no lo encontrarán. La back-compat estricta del ADR original se relaja en este punto y se documenta aquí. Para preservar el comportamiento previo: `include_resource_in_response=True`.

#### D2. Header con metadata + `SET CATALOG <db>;` en el archivo

Se añade el parámetro `include_header: bool = True`. Cuando es `True` (default) y hay `output_path`, el archivo escrito empieza con un bloque tipo:

```sql
-- Database: PROD_ANALITICA
-- Schema:   DBO
-- Object:   procedure DBO.PI_CLIENTESTCM
-- Exported: 2026-05-08T05:30:00Z by uaipscrea1 (nz-mcp v0.1.0a0)
SET CATALOG PROD_ANALITICA;

```

seguido del DDL. La función generadora `build_header_block` está aislada en `tools/export_ddl.py`, es **pura** (no toca tiempo, no abre el perfil, no hace I/O — los inputs se inyectan) y tiene tests adversariales.

Reglas:

- Timestamp en UTC ISO-8601 con sufijo `Z` (sin microsegundos) — comparable entre máquinas.
- Versión de nz-mcp obtenida de `nz_mcp.__version__` (importlib not necesario; ya está en el package).
- **Sólo el nombre del perfil** entra en el header. Nunca host, user, password ni connection string (regla inviolable 1 de `AGENTS.md`). Hay un test adversarial que verifica que las cadenas `password`, `host=`, `user=`, `secret`, `Authorization` no aparecen en el header.

Cuando `include_header=False`, el archivo es **byte-idéntico** al `text` del resource (preserva el invariante original del ADR para los pocos casos que lo necesiten — por ejemplo, hashing comparativo entre el resource block y el archivo).

#### D3. `sha256` reportado es el del archivo en disco

Antes del #129 la garantía era "byte-identidad: archivo == resource" y por tanto los dos sha256 coincidían. Ahora:

- Si `include_header=True` (default), el archivo es `header + DDL` y `meta.sha256` es el digest de **ese** payload.
- Si `include_header=False`, el archivo es el DDL crudo y `meta.sha256` coincide con el digest del `text` del resource.

Regla nueva: **el archivo en disco es la fuente de verdad para `sha256`**. Esto se documenta en `safe_write.py` y en `tools-contract.md`, y queda anclado en tests (`test_nz_export_ddl_sha256_reflects_file_on_disk_when_header_present`, `test_nz_export_ddl_include_header_false_keeps_byte_identity`).

### Compatibilidad con #128

- Callers que **no pasan** `output_path`: comportamiento idéntico al previo (resource + text summary, `meta.{output_path,bytes_written,sha256,preview,resource_in_response,header_included}` todos `null`).
- Callers que **sí** pasaron `output_path` en #128:
  - El archivo se sigue escribiendo en la misma ruta y con la misma policy de paths.
  - El response **ya no incluye** el resource block por default (D1). Esto es el cambio de default consciente; está documentado aquí y en el `CHANGELOG.md`.
  - El archivo escrito **incluye un header** por default (D2). Si el caller necesita exactamente el byte-stream que tenía antes, debe pasar `include_header=False`.
- Las tres decisiones son **aditivas**: ningún schema input requirió breaking change; sólo se añadieron dos campos opcionales con defaults.

### Tests añadidos / actualizados

- `safe_write.py` — header con valores normales, header con caracteres no-ASCII (Ñ, comillas), header `None` que preserva byte-identidad (regresión), header vacío como caso degenerado.
- `tools/export_ddl.py` — resource omitido por default con `output_path`, resource presente sólo con `include_resource_in_response=True`, header con SET CATALOG y validación adversarial de no-leak de credenciales, sha256 del archivo cuando hay header, `include_header=False` mantiene byte-identidad, `build_header_block` puro con timestamp UTC normalizado.

### Hallazgos laterales

- La policy de paths del #128 (no `..`, no `~`, no relativo, no control chars, parent dir existe, permisos POSIX) **no se tocó**. La validación eager sigue corriendo antes de la query al catálogo.
- `safe_write.py` sigue siendo módulo aislado y sin dependencias nuevas; el parámetro `header` fue una adición keyword-only para no romper callers existentes.
