# Claude Desktop: rutas del ejecutable / executable paths

> Los pasos de integración (dónde vive `claude_desktop_config.json`, el JSON completo y cómo comprobar que conectó) están en el [README](../../README.md#integración-con-claude-desktop) y en el [README en inglés](../../README.en.md#claude-desktop-setup). Aquí solo queda el detalle que no cabe allí.
>
> The integration steps (where `claude_desktop_config.json` lives, the full JSON block and how to check it connected) are in the [README](../../README.md#integración-con-claude-desktop) and its [English version](../../README.en.md#claude-desktop-setup). Only the extra detail lives here.
>
> Esta guía es corta y va bilingüe **en un solo archivo**: son rutas y ejemplos idénticos en ambos idiomas, y partirla en dos ficheros solo garantizaría que uno se quede atrás. / This guide is short and bilingual **in a single file**: the paths and examples are identical in both languages, and splitting it would only guarantee that one copy drifts.

## Español

Usa siempre un entorno Python **aislado** para `nz-mcp`, para que ningún otro CLI global (`open-interpreter`, `sqlfluff`, …) fije la versión de `typer` / `click`.

### Dónde queda el ejecutable

| Instalación | Windows | macOS / Linux |
|---|---|---|
| pipx | `%USERPROFILE%\.local\bin\nz-mcp.exe` | `~/.local/bin/nz-mcp` |
| Entorno virtual | `<venv>\Scripts\nz-mcp.exe` | `<venv>/bin/nz-mcp` |

El layout de pipx puede variar según versión y sistema: la fuente de verdad es `pipx list`, o `where.exe nz-mcp` / `which nz-mcp`.

En `claude_desktop_config.json`, `command` apunta a **esa ruta completa**, no a un `nz-mcp` cualquiera del `PATH`: Claude Desktop no arranca con el `PATH` de tu terminal, y un `nz-mcp` instalado globalmente puede ser otro.

`nz-mcp init` y `nz-mcp add-profile` ya resuelven esa ruta y la escriben en el bloque que imprimen al terminar: si lo pegas tal cual, no tienes que buscarla. Solo cuando el asistente no puede determinarla deja un marcador en `command` y te dice con qué comando obtenerla.

### Export de DDL (`nz_export_ddl`)

La tool de lectura `nz_export_ddl` devuelve el DDL de Netezza como **content blocks** MCP: un **resource** embebido (`text/sql`) con URI estable `nz-mcp://ddl/...` más un **texto** de resumen corto. En Claude Desktop se ve como una tarjeta SQL copiable junto al resumen; úsala después de resolver los nombres de los objetos con las tools de listado y describe.

### `pip install` global (desaconsejado)

Instalar en el site-packages del sistema o del usuario puede romper otras herramientas que dependan de versiones viejas de `typer` / `click`. Usa pipx o un venv dedicado.

## English

Always use an **isolated** Python environment for `nz-mcp`, so no other global CLI (`open-interpreter`, `sqlfluff`, …) pins the `typer` / `click` version.

### Where the executable lands

| Install | Windows | macOS / Linux |
|---|---|---|
| pipx | `%USERPROFILE%\.local\bin\nz-mcp.exe` | `~/.local/bin/nz-mcp` |
| Virtual environment | `<venv>\Scripts\nz-mcp.exe` | `<venv>/bin/nz-mcp` |

The pipx layout varies across versions and systems: the source of truth is `pipx list`, or `where.exe nz-mcp` / `which nz-mcp`.

In `claude_desktop_config.json`, `command` points at **that full path**, not at whichever `nz-mcp` sits on `PATH`: Claude Desktop does not start with your terminal `PATH`, and a globally installed `nz-mcp` may be a different one.

`nz-mcp init` and `nz-mcp add-profile` already resolve that path and write it into the block they print at the end: paste it as it is and you never have to look it up. Only when the wizard cannot determine it does it leave a placeholder in `command` and tell you which command prints the real one.

### DDL export (`nz_export_ddl`)

The read tool `nz_export_ddl` returns Netezza DDL as MCP **content blocks**: an embedded **resource** (`text/sql`) with a stable `nz-mcp://ddl/...` URI plus a short **text** summary. In Claude Desktop this appears as a copyable SQL card alongside the summary — use it after resolving object names with the list/describe tools.

### Global `pip install` (discouraged)

Installing into the system or user site-packages can break other tools that depend on older `typer` / `click`. Prefer pipx or a dedicated venv.
