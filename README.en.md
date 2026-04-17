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

```bash
pipx install nz-mcp
nz-mcp init        # interactive wizard
```

> v0.1 not on PyPI yet. Meanwhile: `pipx install git+https://github.com/Oscarsp15/nz-mcp.git`

## Quick setup in Claude Desktop

`claude_desktop_config.json`:

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

Restart Claude Desktop and ask: *"list the databases on my Netezza"*.

### Diagnostics

To inspect your local environment (Python version, config paths, profile names without credentials, keyring) **without connecting to Netezza**:

```bash
nz-mcp doctor
```

Sample output (abbreviated):

```text
Local diagnostics (nz-mcp doctor)

nz-mcp version: 0.1.0a0
Python version: 3.11.x
...
Profile names: dev, prod
Active profile: dev
...
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

## Available tools (24)

Full contract: [`docs/architecture/tools-contract.md`](docs/architecture/tools-contract.md).

## Security

Threat model: [`docs/architecture/security-model.md`](docs/architecture/security-model.md). Vulnerability reports: [`SECURITY.md`](SECURITY.md).

## Development

This repository is developed **primarily by AI agents**. To contribute (human or AI), read:

- [`AGENTS.md`](AGENTS.md) — central router, inviolable rules.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, language, flow.
- [`docs/standards/`](docs/standards/) — coding, testing, git, i18n, pr-audit, issue-workflow, maintainability.

## License

[MIT](LICENSE)
