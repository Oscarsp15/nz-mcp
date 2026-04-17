"""Allow `python -m nz_mcp` to invoke the CLI."""

from __future__ import annotations

from nz_mcp.cli import app

if __name__ == "__main__":
    app()
