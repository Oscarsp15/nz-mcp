"""The six curated onboarding tasks ``nz-mcp help`` lists.

There used to be a full-screen menu here (ADR 0030); ADR 0035 removed it along with the
other two full-screen surfaces the CLI had. What is left is exactly the plain-text listing
``nz-mcp help`` already showed as the non-interactive equivalent of the menu: nothing here
builds a screen, imports ``textual`` or runs anything. It returns data; ``cli.py`` decides
what to do with it.
"""

from __future__ import annotations

from typing import Final

from nz_mcp.menu.entries import TASKS, MenuEntry, MenuTask, command_line

__all__: Final[tuple[str, ...]] = (
    "TASKS",
    "MenuEntry",
    "MenuTask",
    "command_line",
)
