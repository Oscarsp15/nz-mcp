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
- ADR 0006 — Tools de responsabilidad única (justifica preferencia por extensión vs. tool nueva en este caso).
- ADR 0011 — `nz_get_procedure_table_logic` (precedente de aislar lógica en módulos reusables).
- `docs/architecture/tools-contract.md` § 29 — contrato actualizado.
- `docs/standards/i18n.md` — convención de mensajes ES/EN.
