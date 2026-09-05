# nz-mcp

Servidor MCP (Model Context Protocol) para **IBM Netezza Performance Server**. Permite que asistentes IA (Claude Desktop, Claude Code, Cursor, etc.) consulten Netezza con tools de responsabilidad única y permisos granulares por perfil.

🇬🇧 English version: [README.en.md](README.en.md)

> **Estado**: v0.1 en construcción. Desarrollo 100 % asistido por IA siguiendo [`AGENTS.md`](AGENTS.md).

## ¿Qué hace?

- Expone herramientas seguras para **listar bases de datos, schemas, tablas, vistas y procedimientos**.
- Ejecuta **`SELECT`** controlados con `LIMIT` forzado y `timeout`.
- Habilita **`INSERT`/`UPDATE`/`DELETE`** y DDL **solo si el perfil lo autoriza**.
- Permite **clonar procedimientos almacenados** entre bases.
- Tres barreras defensivas: tools single-purpose → `sql_guard` (sqlglot) → grants Netezza.

## Requisitos

- Python **3.11+**
- Acceso a Netezza NPS 11.x (probado con `Release 11.2.1.11-IF1`)
- Conectividad a Netezza (VPN si aplica — el MCP corre en tu máquina local)
- Cliente MCP: Claude Desktop, Claude Code, Cursor, Windsurf, VS Code MCP, etc.

## Instalación

1. **Recomendada — [pipx](https://pypa.github.io/pipx/)** (aisla dependencias; evita choques de `typer`/`click` con otros CLI globales):

   ```bash
   pipx install nz-mcp
   nz-mcp init
   ```

   > Versión de desarrollo (último `main`, sin pasar por PyPI): `pipx install git+https://github.com/Oscarsp15/nz-mcp.git`.

2. **Desarrollo** — clona el repo y usa un venv:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. **Global con `pip`** — posible pero **desaconsejada**: otros paquetes pueden fijar versiones viejas de `typer`/`click` y romper el arranque del CLI.

Rutas completas al ejecutable para Claude Desktop (pipx vs `.venv`) y ejemplos de `claude_desktop_config.json`: [docs/guides/claude-desktop-setup.md](docs/guides/claude-desktop-setup.md).

Campos por perfil en `~/.nz-mcp/profiles.toml` que el asistente ya pregunta: `security_level` (0-3, default `2` = negocia SSL con fallback a claro; `3` = SSL obligatorio) y `ca_certs` (ruta a un bundle CA en PEM para **verificar** el certificado del servidor; si se omite, la conexión SSL se establece sin verificar el certificado). Detalle en [docs/architecture/security-model.md](docs/architecture/security-model.md).

## Gestión de perfiles

Cada perfil vive en `~/.nz-mcp/profiles.toml`; la password va al keyring del SO, nunca al archivo.

```bash
nz-mcp add-profile prod --active      # alta guiada: host, puerto, BD, usuario, password, modo, seguridad
nz-mcp list-profiles                  # nombres configurados
nz-mcp switch-profile prod            # cambia el perfil activo
nz-mcp edit-profile prod --mode read  # cambia campos sueltos, sin tocar la password
nz-mcp remove-profile prod            # borra el perfil y su password del keyring
```

`add-profile` con un nombre que ya existe pide confirmación (default `No`) y, si aceptas, **reemplaza** los campos de esa sección en vez de duplicarla; los valores actuales se ofrecen como default de cada pregunta.

### El asistente guiado paso a paso

`nz-mcp init` y `nz-mcp add-profile <nombre>` explican en una línea cada concepto no obvio antes de preguntarlo:

- **Modo**: `read` solo consultas, `write` añade escritura de datos, `admin` añade DDL. El modo **no otorga** permisos en Netezza: solo recorta los que ya tenga tu usuario.
- **Nivel de seguridad** (`security_level`, default `2`): si la conexión viaja cifrada y si se exige TLS.
- **`ca_certs`**: opcional, Enter para omitir; sin él el canal sigue cifrado pero no se verifica el certificado.

Antes de escribir nada en `profiles.toml` ni en el keyring, el asistente ofrece **validar el perfil en tres niveles**, cada uno reportado por separado:

1. **Conexión** — abre la sesión y lee `VERSION()`: credenciales, red y negociación TLS.
2. **Lectura del catálogo** — lista bases de datos: la cuenta lee de verdad, no solo autentica.
3. **Visibilidad en la base por defecto** — lista sus esquemas: detecta el fallo silencioso de conectar sin tener ningún `GRANT`.

Si algún nivel falla **no se pierde nada de lo escrito**: puedes reintentar, corregir un solo campo (el resto se conserva), guardar de todos modos —configurar un perfil sin la VPN levantada es un caso normal— o cancelar sin dejar rastro. Al terminar imprime el bloque JSON listo para pegar en `claude_desktop_config.json` con el nombre del perfil ya sustituido.

`remove-profile` pide confirmación explícita antes de borrar la sección del TOML y la password del keyring. Si el perfil borrado era el activo, el archivo se queda sin `active`: elige otro con la variable `NZ_MCP_PROFILE` o editando el campo `active`.

## Configuración rápida en Claude Desktop

`claude_desktop_config.json` (ajusta `command` al `nz-mcp` de pipx o del venv, ver guía arriba):

```json
{
  "mcpServers": {
    "netezza": {
      "command": "nz-mcp",
      "args": ["serve"]
    }
  }
}
```

Reinicia Claude Desktop y pídele: *"lista las bases de datos de mi Netezza"*.

### Diagnóstico

Para revisar el entorno local (versión de Python, rutas de config, perfiles sin credenciales, keyring) **sin conectar a Netezza**:

```bash
nz-mcp doctor
```

Ejemplo de salida literal (referencia Linux, Python 3.11; rutas y perfiles ficticios ``demo`` / ``dev`` / ``prod`` — coincide con ``format_diagnostic_report`` del paquete):

```text
Diagnóstico local (nz-mcp doctor)

Versión nz-mcp: 0.1.0a0
Versión de Python: 3.11.9
Plataforma: Linux-6.8.0-generic-x86_64-with-glibc2.39
Directorio de configuración: /home/demo/.nz-mcp
  Existe: sí
  Escribible: sí
Ruta de perfiles: /home/demo/.nz-mcp/profiles.toml
  Existe: sí
Carga de perfiles OK: sí
Número de perfiles: 2
Nombres de perfiles: dev, prod
Perfil activo: prod
Backend de keyring: SecretService Keyring
  Disponible: sí
Idioma (locale): es
```

Código de salida: `0` si el entorno es usable; `1` si hay un problema crítico (p. ej. keyring no disponible).

### Diagnóstico de catálogo

Tras configurar un perfil y guardar la contraseña en el keyring, puedes validar que **todas las consultas del catálogo** (incluidas las de `catalog_overrides` en `profiles.toml`) se ejecutan contra tu Netezza con parámetros dummy seguros:

```bash
nz-mcp probe-catalog
nz-mcp probe-catalog --profile mi_perfil
nz-mcp probe-catalog --json
```

Mide duración y filas devueltas por query; si una consulta solo falla porque no existe un objeto de prueba (p. ej. tabla ficticia), se marca como advertencia, no como fallo duro. Código de salida: `0` si no hay errores graves, `1` si alguna query falla de forma definitiva o no se puede conectar.

## Tools disponibles (27)

Ver el contrato completo en [`docs/architecture/tools-contract.md`](docs/architecture/tools-contract.md).

| Categoría | Tools |
|---|---|
| Lectura | `nz_query_select`, `nz_explain`, `nz_list_databases`, `nz_list_schemas`, `nz_list_tables`, `nz_describe_table`, `nz_table_sample`, `nz_table_stats`, `nz_get_table_ddl`, `nz_list_views`, `nz_get_view_ddl`, `nz_list_procedures`, `nz_describe_procedure`, `nz_get_procedure_ddl`, `nz_export_ddl`, `nz_get_procedure_section` |
| Escritura | `nz_insert`, `nz_insert_select`, `nz_update`, `nz_delete` |
| DDL / SP | `nz_create_table`, `nz_create_table_as`, `nz_truncate`, `nz_drop_table`, `nz_clone_procedure` |
| Sesión | `nz_current_profile`, `nz_switch_profile` |

## Seguridad

Resumen del modelo en [`docs/architecture/security-model.md`](docs/architecture/security-model.md). Reportes de vulnerabilidad: [`SECURITY.md`](SECURITY.md).

## Desarrollo

Este repositorio se desarrolla **principalmente con agentes IA**. Si quieres contribuir (humano o IA), lee:

- [`AGENTS.md`](AGENTS.md) — router central, reglas inviolables.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, idioma, flujo.
- [`docs/standards/`](docs/standards/) — coding, testing, git, i18n, pr-audit, issue-workflow, maintainability.

## Licencia

[MIT](LICENSE)
