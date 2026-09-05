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

`nz-mcp` se instala en **tu máquina**, no en el servidor de Netezza. Lo único imprescindible es Python 3.11 o superior.

### Camino automático (tres comandos)

Si ya tienes [pipx](https://pypa.github.io/pipx/):

```bash
pipx install nz-mcp     # instala el CLI en un entorno aislado y lo deja en el PATH
nz-mcp init             # asistente: crea el primer perfil y valida la conexión
nz-mcp doctor           # comprueba el entorno local (no toca Netezza)
```

**No hay script de instalación y es deliberado.** pipx ya hace lo que haría ese script —crear un entorno aislado y publicar el ejecutable en el PATH— y `nz-mcp init` ya es el asistente de configuración. Un instalador propio sería un archivo más que mantener por sistema operativo, imposible de probar en CI, para no ahorrar ningún paso.

> La versión publicada es alfa (`0.1.0a2`) y `pip` no instala prereleases por defecto. Si `pipx install nz-mcp` responde que no encuentra ninguna versión, usa `pipx install nz-mcp --pip-args=--pre` o instala desde git: `pipx install git+https://github.com/Oscarsp15/nz-mcp.git`.

### Instalación manual paso a paso

Sin pipx, con un entorno virtual dedicado. Cada paso trae su comprobación: si la comprobación no sale, no sigas al siguiente.

1. **Comprueba Python.** Tiene que imprimir `3.11` o superior:

   ```bash
   python --version      # Windows
   python3 --version     # macOS / Linux
   ```

   Si el comando no existe, instala Python desde [python.org](https://www.python.org/downloads/) y **abre una terminal nueva** (el PATH solo se refresca al abrirla).

2. **Crea un entorno virtual solo para `nz-mcp`.** Así ningún otro paquete puede fijar versiones viejas de `typer`/`click` y romper el arranque del CLI:

   ```powershell
   # Windows (PowerShell)
   python -m venv $HOME\.venvs\nz-mcp
   & $HOME\.venvs\nz-mcp\Scripts\Activate.ps1
   ```

   ```bash
   # macOS / Linux
   python3 -m venv ~/.venvs/nz-mcp
   source ~/.venvs/nz-mcp/bin/activate
   ```

   El prompt pasa a empezar por `(nz-mcp)`: estás dentro del entorno.

3. **Instala el paquete** con el entorno activado (`pip install git+https://github.com/Oscarsp15/nz-mcp.git` para el último `main`):

   ```bash
   pip install nz-mcp
   ```

4. **Comprueba la instalación:**

   ```bash
   nz-mcp version     # imprime la versión instalada, p. ej. 0.1.0a2
   nz-mcp doctor      # informe local; código de salida 0 si el entorno es usable
   ```

5. **Crea el perfil y valídalo contra Netezza:**

   ```bash
   nz-mcp init
   nz-mcp test-connection    # OK: connected to <versión> as <usuario>
   ```

   Si `test-connection` falla, la línea `HINT:` dice qué mirar; ver [Problemas frecuentes](#problemas-frecuentes).

6. **Anota la ruta del ejecutable.** La necesitas para Claude Desktop, que arranca sin el PATH de tu terminal:

   ```powershell
   where.exe nz-mcp    # Windows
   ```

   ```bash
   which nz-mcp        # macOS / Linux
   ```

### Desarrollo (clonando el repo)

```bash
git clone https://github.com/Oscarsp15/nz-mcp.git
cd nz-mcp
python -m venv .venv
.venv\Scripts\activate        # macOS / Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Instalar con `pip` en el Python del sistema (ni pipx ni venv) es posible pero **desaconsejado**, por el mismo choque de `typer`/`click`.

## Comandos del CLI

| Comando | Qué hace |
|---|---|
| `nz-mcp init` | asistente inicial: crea el primer perfil |
| `nz-mcp add-profile <nombre> [--active]` | alta guiada de otro perfil: host, puerto, BD, usuario, password, modo, seguridad |
| `nz-mcp list-profiles` | nombres de los perfiles configurados |
| `nz-mcp switch-profile <nombre>` | cambia el perfil activo |
| `nz-mcp edit-profile <nombre>` | cambia campos sueltos (`--mode`, `--database`, `--max-rows-default`, `--timeout-s-default`) sin tocar la password |
| `nz-mcp remove-profile <nombre>` | borra el perfil y su password del keyring |
| `nz-mcp doctor` | diagnóstico local, sin conectar a Netezza |
| `nz-mcp test-connection [--profile <n>]` | abre la conexión del perfil y ejecuta `VERSION()`; sale con `0` si conecta, `1` si no |
| `nz-mcp probe-catalog [--profile <n>] [--json]` | ejecuta todas las queries del catálogo con parámetros dummy |
| `nz-mcp serve` | arranca el servidor MCP sobre stdio; **lo lanza el cliente**, no tú a mano |
| `nz-mcp version` | imprime la versión instalada |

## Gestión de perfiles

Cada perfil vive en `~/.nz-mcp/profiles.toml`; la password va al keyring del SO, nunca al archivo. Campos que el asistente pregunta y que puedes editar a mano: `security_level` (0-3, default `2` = negocia SSL con fallback a claro; `3` = SSL obligatorio) y `ca_certs` (ruta a un bundle CA en PEM para **verificar** el certificado del servidor; si se omite, la conexión SSL se establece sin verificar el certificado). Detalle en [docs/architecture/security-model.md](docs/architecture/security-model.md).

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

## Integración con Claude Desktop

1. **Abre el archivo de configuración** (créalo si no existe):

   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: Claude Desktop no tiene versión oficial para Linux. Si usas una compilación de la comunidad, la ruta suele ser `~/.config/Claude/claude_desktop_config.json`, pero no está verificada aquí; en Linux la vía soportada es Claude Code, más abajo.

2. **Averigua la ruta real del ejecutable.** Claude Desktop arranca el servidor sin el PATH de tu terminal, así que `command` tiene que ser una ruta completa:

   - **pipx**: `pipx list` muestra el entorno y las apps instaladas; `where.exe nz-mcp` (Windows) o `which nz-mcp` (macOS/Linux) imprime la ruta. En Windows suele ser `C:\Users\<TU_USUARIO>\.local\bin\nz-mcp.exe`.
   - **Entorno virtual**: `<ruta_del_venv>\Scripts\nz-mcp.exe` en Windows, `<ruta_del_venv>/bin/nz-mcp` en macOS/Linux.

3. **Pega el bloque** con esa ruta. `env` fija con qué perfil arranca el servidor:

   ```json
   {
     "mcpServers": {
       "netezza": {
         "command": "C:\\Users\\TU_USUARIO\\.local\\bin\\nz-mcp.exe",
         "args": ["serve"],
         "env": { "NZ_MCP_PROFILE": "prod" }
       }
     }
   }
   ```

   Es JSON: en Windows las barras invertidas van dobladas. En macOS/Linux el `command` es una ruta POSIX (`/Users/tu_usuario/.local/bin/nz-mcp`). Si ya tienes otros servidores, añade la clave `netezza` dentro del `mcpServers` que ya existe.

4. **Reinicia Claude Desktop por completo**: cerrar la ventana no basta, sal también desde el icono de la bandeja del sistema (Windows) o de la barra de menús (macOS).

5. **Comprueba que conectó**: pídele *"lista las bases de datos de mi Netezza"*; debe llamar a la tool `nz_list_databases`. Si no pasa nada, revisa el log que Claude Desktop escribe por servidor —en Windows, `%APPDATA%\Claude\logs\mcp-server-netezza.log`, con el nombre que le diste al servidor en el archivo.

Rutas por método de instalación y notas de `nz_export_ddl`: [docs/guides/claude-desktop-setup.md](docs/guides/claude-desktop-setup.md).

## Integración con Claude Code

Claude Code registra los servidores desde su propio CLI: `claude mcp add <nombre> <comando> [args...]`. El `--` separa los argumentos del servidor de los del propio `claude`:

```bash
claude mcp add netezza -- nz-mcp serve                                  # alcance local (default)
claude mcp add -s user netezza -- nz-mcp serve                          # en todos tus proyectos
claude mcp add -s user -e NZ_MCP_PROFILE=prod netezza -- nz-mcp serve   # fijando el perfil
```

Si `nz-mcp` no está en el PATH, pon la ruta completa al ejecutable, igual que en Claude Desktop.

Alcances de `-s` / `--scope`:

| Alcance | Dónde queda | Cuándo |
|---|---|---|
| `local` (default) | config privada tuya, solo en este proyecto | probar sin tocar nada de nadie |
| `project` | `.mcp.json` del repo, compartido con quien lo clone | equipo; cada persona sigue necesitando su propio perfil y su password en el keyring |
| `user` | tu config de usuario | uso habitual, en todos tus proyectos |

Comprueba que quedó registrado:

```bash
claude mcp list          # servidores configurados y su estado
claude mcp get netezza   # detalle de este servidor
claude mcp remove netezza
```

Dentro de una sesión, el comando `/mcp` gestiona los servidores MCP conectados.

## Diagnóstico

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

## Problemas frecuentes

### La conexión falla

`nz-mcp test-connection` imprime `FAIL:` con el detalle del driver y `HINT:` con la pista. nz-mcp clasifica el fallo en una de estas causas y la IA recibe la misma pista en el campo `hint` del error:

| Causa | Qué pasó | Qué hacer |
|---|---|---|
| `AUTH_REJECTED` | Netezza rechazó las credenciales del usuario | Vuelve a guardar la password con `nz-mcp add-profile <perfil>` y comprueba que la cuenta no esté bloqueada ni caducada |
| `DATABASE_UNAVAILABLE` | La base de datos no existe o el usuario no tiene permiso sobre ella | Revisa `database` en el perfil y los grants del usuario |
| `HOST_UNREACHABLE` | No hubo respuesta de `host:puerto` | Levanta la VPN, comprueba que el host resuelva por DNS y que el puerto esté abierto |
| `TLS_FAILED` | Falló la negociación TLS | Revisa `ca_certs` del perfil, o baja `security_level` si el servidor no ofrece SSL |
| `UNKNOWN` | El texto del driver no casa con ninguna regla | Ejecuta `nz-mcp test-connection` y lee el detalle crudo del driver |

### El cliente no ve el servidor

- **`nz-mcp` no aparece / "command not found"**: el cliente no hereda tu PATH. Pon la ruta completa al ejecutable en `command` (`where.exe nz-mcp` / `which nz-mcp`).
- **Claude Desktop sigue sin listarlo**: reinicia la aplicación **entera** (bandeja del sistema o barra de menús) y revisa `mcp-server-<nombre>.log` en la carpeta `logs` de Claude Desktop.
- **El CLI arranca en tu terminal pero no bajo el cliente**: comprueba que el `command` apunta al `nz-mcp` de pipx o del venv, no a otro que haya quedado en el PATH del sistema.

### Otros

- **`nz-mcp doctor` sale con código 1**: normalmente es el keyring. Sin backend de keyring no hay dónde guardar la password; en Linux headless hace falta instalar y desbloquear uno.
- **La tool devuelve `PERMISSION_DENIED`**: el modo del perfil no llega (`read` no escribe, `write` no hace DDL). nz-mcp nunca eleva el modo: lo cambias tú con `nz-mcp edit-profile <perfil> --mode <modo>`, y aun así Netezza sigue mandando sobre sus grants.
- **`WHERE_ALWAYS_TRUE` al actualizar o borrar**: es intencionado, ver [Seguridad](#seguridad).

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

### Borrar o actualizar la tabla entera exige confirmarlo

`sql_guard` rechaza con el código `WHERE_ALWAYS_TRUE` todo `UPDATE` o `DELETE` cuyo `WHERE` sea siempre verdadero: `WHERE 1=1`, `WHERE TRUE`, `WHERE id = id`, `... OR 1=1` y similares. Exigir solo la **presencia** de un `WHERE` no protegía de nada, porque `DELETE FROM T WHERE 1=1` borra la tabla igual.

Si la intención es de verdad tocar todas las filas, repite la llamada con `confirm_full_table=true` en `nz_update` o `nz_delete`: la sentencia se ejecuta, y la declaración de intención queda escrita en los argumentos de la llamada. `confirm_full_table` **no** eleva privilegios ni exime de escribir un `WHERE`; los `SELECT` no se ven afectados.

Límite explícito: decidir si un predicado es una tautología es indecidible. No se detectan constantes tras funciones (`ABS(1)=1`), predicados que dependen de los datos (`id IS NOT NULL`, `name LIKE '%'`) ni comparaciones entre tipos distintos (`'1' = 1`).

## Desarrollo

Este repositorio se desarrolla **principalmente con agentes IA**. Si quieres contribuir (humano o IA), lee:

- [`AGENTS.md`](AGENTS.md) — router central, reglas inviolables.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, idioma, flujo.
- [`docs/standards/`](docs/standards/) — coding, testing, git, i18n, pr-audit, issue-workflow, maintainability.

## Licencia

[MIT](LICENSE)
