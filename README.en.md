# nz-mcp

MCP (Model Context Protocol) server for **IBM Netezza Performance Server**. Lets AI assistants (Claude Desktop, Claude Code, Cursor, etc.) query Netezza through single-responsibility tools with profile-scoped permissions.

🇪🇸 Versión en español: [README.md](README.md)

> **Status**: v0.1 in progress. 100 % AI-assisted development following [`AGENTS.md`](AGENTS.md).

## What it does

- Exposes safe tools to **list databases, schemas, tables, views, procedures**.
- Runs **`SELECT`** with forced `LIMIT` and `timeout`.
- Allows **`INSERT`/`UPDATE`/`DELETE`** and DDL **only if the profile authorizes**.
- Supports **cloning stored procedures** across databases.
- Three defense layers: single-purpose tools → `sql_guard` (sqlglot) → Netezza grants.

## Requirements

- Python **3.11+**
- IBM Netezza NPS 11.x access (tested with `Release 11.2.1.11-IF1`)
- Network reachability to Netezza (VPN if needed — the MCP runs on your local machine)
- MCP client: Claude Desktop, Claude Code, Cursor, Windsurf, VS Code MCP, etc.

## Install

`nz-mcp` runs on **your machine**, not on the Netezza server. All you strictly need is Python 3.11 or newer.

### Automated path (three commands)

If you already have [pipx](https://pypa.github.io/pipx/):

```bash
pipx install nz-mcp     # installs the CLI in an isolated environment and puts it on PATH
nz-mcp init             # wizard: creates the first profile and validates the connection
nz-mcp doctor           # checks the local environment (never touches Netezza)
```

**There is no install script, on purpose.** pipx already does what that script would do — create an isolated environment and publish the executable on PATH — and `nz-mcp init` already is the configuration wizard. A custom installer would be one more file to maintain per operating system, impossible to test in CI, and it would save no step.

> The published version is an alpha (`0.1.0a3`) and `pip` does not install prereleases by default. If `pipx install nz-mcp` reports that no version matches, use `pipx install nz-mcp --pip-args=--pre` or install from git: `pipx install git+https://github.com/Oscarsp15/nz-mcp.git`.

### Manual install, step by step

No pipx, one dedicated virtual environment. Every step has its own check: if the check fails, do not move on.

1. **Check Python.** It must print `3.11` or newer:

   ```bash
   python --version      # Windows
   python3 --version     # macOS / Linux
   ```

   If the command does not exist, install Python from [python.org](https://www.python.org/downloads/) and **open a new terminal** (PATH is only refreshed on a new one).

2. **Create a virtual environment just for `nz-mcp`.** That way no other package can pin old `typer`/`click` versions and break the CLI startup:

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

   The prompt now starts with `(nz-mcp)`: you are inside the environment.

3. **Install the package** with the environment activated (`pip install git+https://github.com/Oscarsp15/nz-mcp.git` for the latest `main`):

   ```bash
   pip install nz-mcp
   ```

4. **Check the install:**

   ```bash
   nz-mcp version     # prints the installed version, e.g. 0.1.0a3
   nz-mcp doctor      # local report; exit code 0 when the environment is usable
   ```

5. **Create the profile and validate it against Netezza:**

   ```bash
   nz-mcp init
   nz-mcp test-connection    # OK: connected to <version> as <user>
   ```

   If `test-connection` fails, the `HINT:` line says what to look at; see [Troubleshooting](#troubleshooting).

6. **Write down the executable path.** You need it for Claude Desktop, which starts without your terminal PATH:

   ```powershell
   where.exe nz-mcp    # Windows
   ```

   ```bash
   which nz-mcp        # macOS / Linux
   ```

### Development (from a clone)

```bash
git clone https://github.com/Oscarsp15/nz-mcp.git
cd nz-mcp
python -m venv .venv
.venv\Scripts\activate        # macOS / Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Installing with `pip` into the system Python (no pipx, no venv) works but is **discouraged**, because of the same `typer`/`click` clash.

## CLI commands

| Command | What it does |
|---|---|
| `nz-mcp init` | first-time wizard: creates the first profile |
| `nz-mcp add-profile <name> [--active]` | guided wizard for another profile: host, port, database, user, password, mode, security |
| `nz-mcp list-profiles` | names of the configured profiles |
| `nz-mcp switch-profile <name>` | change the active profile |
| `nz-mcp edit-profile <name>` | change single fields (`--mode`, `--database`, `--max-rows-default`, `--timeout-s-default`), password untouched |
| `nz-mcp remove-profile <name>` | delete the profile and its keyring password |
| `nz-mcp doctor` | local diagnostics, no Netezza connection |
| `nz-mcp test-connection [--profile <n>]` | open the profile connection and run `VERSION()`; exits `0` on success, `1` on failure |
| `nz-mcp probe-catalog [--profile <n>] [--json]` | run every catalog query with dummy parameters |
| `nz-mcp serve` | run the MCP server over stdio; **the client launches it**, not you |
| `nz-mcp version` | print the installed version |

## Profile management

Each profile lives in `~/.nz-mcp/profiles.toml`; the password goes to the OS keyring, never to the file. Fields the wizard asks for and you can also edit by hand: `security_level` (0-3, default `2` = negotiate SSL with cleartext fallback; `3` = SSL required) and `ca_certs` (path to a PEM CA bundle used to **verify** the server certificate; when omitted, the SSL connection is established without certificate verification). Details in [docs/architecture/security-model.md](docs/architecture/security-model.md).

`add-profile` with an existing name asks for confirmation (default `No`) and, when accepted, **replaces** the fields of that section instead of duplicating it; the current values are offered as the default of every question.

### The guided wizard step by step

`nz-mcp init` and `nz-mcp add-profile <name>` explain every non-obvious concept in one line before asking for it:

- **Mode**: `read` queries only, `write` adds data writes, `admin` adds DDL. The mode **grants** no Netezza privilege: it only narrows the ones your user already has.
- **Security level** (`security_level`, default `2`): whether the connection is encrypted and whether TLS is mandatory.
- **`ca_certs`**: optional, press Enter to skip; without it the channel is still encrypted but the certificate is not verified.

Before writing anything to `profiles.toml` or to the keyring, the wizard offers to **validate the profile in three levels**, each reported separately:

1. **Connection** — opens the session and reads `VERSION()`: credentials, network and TLS negotiation.
2. **Catalog read** — lists databases: the account really reads, it does not just authenticate.
3. **Visibility in the default database** — lists its schemas: catches the silent failure of connecting without holding any `GRANT`.

If a level fails **nothing you typed is lost**: you can retry, fix a single field (the rest is kept), save anyway — configuring a profile with the VPN down is a normal case — or cancel leaving no trace. On success it prints the JSON block ready to paste into `claude_desktop_config.json` with the profile name already substituted.

`remove-profile` asks for explicit confirmation before deleting the TOML section and the keyring password. If the deleted profile was the active one, the file is left without `active`: pick another one with the `NZ_MCP_PROFILE` variable or by editing the `active` field.

## Claude Desktop setup

1. **Open the configuration file** (create it if missing):

   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: Claude Desktop has no official Linux build. Community builds usually read `~/.config/Claude/claude_desktop_config.json`, but that path is not verified here; on Linux the supported route is Claude Code, below.

2. **Find the real executable path.** Claude Desktop starts the server without your terminal PATH, so `command` must be a full path:

   - **pipx**: `pipx list` shows the environment and the installed apps; `where.exe nz-mcp` (Windows) or `which nz-mcp` (macOS/Linux) prints the path. On Windows it is usually `C:\Users\<YOURUSER>\.local\bin\nz-mcp.exe`.
   - **Virtual environment**: `<venv_path>\Scripts\nz-mcp.exe` on Windows, `<venv_path>/bin/nz-mcp` on macOS/Linux.

3. **Paste the block** using that path. `env` pins the profile the server starts with:

   ```json
   {
     "mcpServers": {
       "netezza": {
         "command": "C:\\Users\\YOURUSER\\.local\\bin\\nz-mcp.exe",
         "args": ["serve"],
         "env": { "NZ_MCP_PROFILE": "prod" }
       }
     }
   }
   ```

   This is JSON: on Windows the backslashes are doubled. On macOS/Linux `command` is a POSIX path (`/Users/youruser/.local/bin/nz-mcp`). If you already have other servers, add the `netezza` key inside the existing `mcpServers`.

4. **Restart Claude Desktop completely**: closing the window is not enough, quit from the system tray (Windows) or the menu bar (macOS) too.

5. **Check it connected**: ask *"list the databases on my Netezza"*; it should call the `nz_list_databases` tool. If nothing happens, read the per-server log Claude Desktop writes — on Windows, `%APPDATA%\Claude\logs\mcp-server-netezza.log`, named after the server key you used in the config.

Paths per install method and `nz_export_ddl` notes: [docs/guides/claude-desktop-setup.md](docs/guides/claude-desktop-setup.md).

## Claude Code setup

Claude Code registers servers from its own CLI: `claude mcp add <name> <command> [args...]`. The `--` separates the server arguments from `claude`'s own:

```bash
claude mcp add netezza -- nz-mcp serve                                  # local scope (default)
claude mcp add -s user netezza -- nz-mcp serve                          # in all your projects
claude mcp add -s user -e NZ_MCP_PROFILE=prod netezza -- nz-mcp serve   # pinning the profile
```

If `nz-mcp` is not on PATH, use the full executable path, exactly as in Claude Desktop.

`-s` / `--scope` values:

| Scope | Where it lands | When |
|---|---|---|
| `local` (default) | your own private config, this project only | trying it out without affecting anyone |
| `project` | the repo's `.mcp.json`, shared with whoever clones it | teams; each person still needs their own profile and their own keyring password |
| `user` | your user config | day-to-day use, across all your projects |

Check it was registered:

```bash
claude mcp list          # configured servers and their status
claude mcp get netezza   # details for this server
claude mcp remove netezza
```

Inside a session, the `/mcp` command manages the connected MCP servers.

## Diagnostics

To inspect your local environment (Python version, config paths, profile names without credentials, keyring) **without connecting to Netezza**:

```bash
nz-mcp doctor
```

Sample literal output (reference Linux environment, Python 3.11; fictional paths and profiles ``demo`` / ``dev`` / ``prod`` — same shape as ``format_diagnostic_report`` in the package):

```text
Local diagnostics (nz-mcp doctor)

nz-mcp version: 0.1.0a0
Python version: 3.11.9
Platform: Linux-6.8.0-generic-x86_64-with-glibc2.39
Configuration directory: /home/demo/.nz-mcp
  Exists: yes
  Writable: yes
Profiles path: /home/demo/.nz-mcp/profiles.toml
  Exists: yes
Profiles load OK: yes
Profile count: 2
Profile names: dev, prod
Active profile: prod
Keyring backend: SecretService Keyring
  Available: yes
Locale: en
```

Exit code: `0` when the setup is OK; `1` on a critical issue (e.g. keyring unavailable).

### Catalog diagnostics

After you configure a profile and store the password in the OS keyring, you can verify that **every catalog query** (including `catalog_overrides` in `profiles.toml`) runs against your Netezza with safe dummy parameters:

```bash
nz-mcp probe-catalog
nz-mcp probe-catalog --profile my_profile
nz-mcp probe-catalog --json
```

The command reports duration and row counts per query. If a query only fails because a dummy table or object does not exist, it is reported as a warning rather than a hard failure. Exit code: `0` when there are no hard failures, `1` when any query fails definitively or the connection cannot be established.

## Troubleshooting

### The connection fails

`nz-mcp test-connection` prints `FAIL:` with the driver detail and `HINT:` with the lead. nz-mcp classifies the failure into one of these causes, and the AI gets the same lead in the error's `hint` field:

| Cause | What happened | What to do |
|---|---|---|
| `AUTH_REJECTED` | Netezza rejected the user's credentials | Store the password again with `nz-mcp add-profile <profile>` and check the account is not locked or expired |
| `DATABASE_UNAVAILABLE` | The database does not exist or the user has no permission on it | Review `database` in the profile and the user's grants |
| `HOST_UNREACHABLE` | No response from `host:port` | Bring up the VPN, check the host resolves via DNS and the port is open |
| `TLS_FAILED` | TLS negotiation failed | Review the profile's `ca_certs`, or lower `security_level` if the server does not offer SSL |
| `UNKNOWN` | The driver text matches no rule | Run `nz-mcp test-connection` and read the raw driver detail |

### The client does not see the server

- **`nz-mcp` not found / "command not found"**: the client does not inherit your PATH. Put the full executable path in `command` (`where.exe nz-mcp` / `which nz-mcp`).
- **Claude Desktop still does not list it**: restart the **whole** application (system tray or menu bar) and read `mcp-server-<name>.log` in the Claude Desktop `logs` folder.
- **The CLI starts in your terminal but not under the client**: make sure `command` points at the pipx or venv `nz-mcp`, not at some other one left on the system PATH.

### Other

- **`nz-mcp doctor` exits with code 1**: usually the keyring. With no keyring backend there is nowhere to store the password; on headless Linux you must install and unlock one.
- **A tool returns `PERMISSION_DENIED`**: the profile mode is not enough (`read` does not write, `write` does not do DDL). nz-mcp never raises the mode: you change it with `nz-mcp edit-profile <profile> --mode <mode>`, and Netezza grants still have the last word.
- **`WHERE_ALWAYS_TRUE` on an update or a delete**: that is intended, see [Security](#security).

## Available tools (24)

Full contract: [`docs/architecture/tools-contract.md`](docs/architecture/tools-contract.md).

## Security

Threat model: [`docs/architecture/security-model.md`](docs/architecture/security-model.md). Vulnerability reports: [`SECURITY.md`](SECURITY.md).

### Deleting or updating a whole table must be confirmed

`sql_guard` rejects with the `WHERE_ALWAYS_TRUE` code every `UPDATE` or `DELETE` whose `WHERE` is always true: `WHERE 1=1`, `WHERE TRUE`, `WHERE id = id`, `... OR 1=1` and the like. Requiring only the **presence** of a `WHERE` protected nothing, because `DELETE FROM T WHERE 1=1` wipes the table just the same.

When touching every row really is the intent, repeat the call with `confirm_full_table=true` on `nz_update` or `nz_delete`: the statement runs, and the declaration of intent stays written in the call arguments. `confirm_full_table` grants **no** privileges and does not waive writing a `WHERE`; `SELECT` statements are unaffected.

Explicit limit: deciding whether a predicate is a tautology is undecidable. Constants behind functions (`ABS(1)=1`), data-dependent predicates (`id IS NOT NULL`, `name LIKE '%'`) and cross-type comparisons (`'1' = 1`) are not detected.

## Development

This repository is developed **primarily by AI agents**. To contribute (human or AI), read:

- [`AGENTS.md`](AGENTS.md) — central router, inviolable rules.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, language, flow.
- [`docs/standards/`](docs/standards/) — coding, testing, git, i18n, pr-audit, issue-workflow, maintainability.

## License

[MIT](LICENSE)
