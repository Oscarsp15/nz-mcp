"""The shared visual layer of the level 2 surfaces: the sheet, the themes, the base app.

See :mod:`nz_mcp.tui.theme` for what lives here and why nothing else may hold a colour.
"""

from __future__ import annotations

from nz_mcp.tui.theme import NZ_DARK, NZ_LIGHT, STYLESHEET, THEMES, ThemedApp

__all__ = ["NZ_DARK", "NZ_LIGHT", "STYLESHEET", "THEMES", "ThemedApp"]
