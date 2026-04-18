# Claude Desktop and nz-mcp

Use an **isolated** Python environment for `nz-mcp` so `typer` / `click` versions are not pinned by other global CLI tools (e.g. `open-interpreter`, `sqlfluff`).

## Recommended: pipx

Install [pipx](https://pypa.github.io/pipx/) and install from PyPI (when published) or from a git URL:

```bash
pipx install git+https://github.com/Oscarsp15/nz-mcp.git
pipx ensurepath
```

On Windows, the executable is typically `%USERPROFILE%\.local\bin\nz-mcp.exe` (pipx layout may vary).

## Development: virtualenv

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -e ".[dev]"
```

The CLI is `.venv\Scripts\nz-mcp.exe` (Windows) or `.venv/bin/nz-mcp`.

## `claude_desktop_config.json`

Point `command` at the **full path** to the `nz-mcp` binary from pipx or venv — not a conflicting global `nz-mcp` on `PATH`.

### pipx (Windows example)

```json
{
  "mcpServers": {
    "netezza": {
      "command": "C:\\Users\\YOURUSER\\.local\\bin\\nz-mcp.exe",
      "args": ["serve"]
    }
  }
}
```

### venv (Windows example)

```json
{
  "mcpServers": {
    "netezza": {
      "command": "C:\\path\\to\\nz-mcp\\.venv\\Scripts\\nz-mcp.exe",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop after editing the config.

## Global `pip install` (discouraged)

Installing into the system or user site-packages can break other tools that depend on older `typer`/`click`. Prefer pipx or a dedicated venv.
