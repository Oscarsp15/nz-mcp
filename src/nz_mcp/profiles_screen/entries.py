"""What "Ver perfiles" offers, as data: rows, actions, a choice (ADR 0032, decision 3).

Same property the menu and the wizard hold to: **no terminal and no library.** Nothing
here imports ``textual`` or the output layer, so the shape of the screen can be exercised
without one and the confinement of ADR 0029 stays true.

This is the third and last screen the ADR authorises. It does not host anything: it shows
what is known about each profile and hands back which one was picked and what to do with
it. Running that choice is ``cli.py``'s job, on the ordinary terminal, exactly like the
six-task menu already does for its own choice (ADR 0030, decision 1, extended by ADR 0032
to a two-step pick).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

#: Smallest window this screen draws itself in. Five columns plus the padding of a frame
#: need more than the six-task menu's 60, but the screen still holds less than the wizard's
#: eight fields with their explanation panel (60x21), so the height stays at the menu's own
#: floor (ADR 0028, conditions 1 and 4).
MIN_WIDTH: Final[int] = 72
MIN_HEIGHT: Final[int] = 18

#: The reading of one profile the table shows, decided **without opening a connection**
#: (acceptance criterion 1 of issue #240): "ok" means the profile section parses and its
#: keyring entry is present; "warning" means it parses but has no stored password yet;
#: "error" means the section itself fails to load. None of the three levels of
#: :mod:`nz_mcp.profile_check` run here - those need a live socket, and only "probar"
#: (issue #240, acceptance criterion 3) is allowed to open one, on the ordinary terminal,
#: after this screen has already closed.
ProfileStatus = Literal["ok", "warning", "error"]

#: The four actions ``Enter`` on a row offers (ADR 0032, decision 3). Each one hands off to
#: the command already in ``cli.py``; none is reimplemented here.
ProfileAction = Literal["use", "test", "edit", "remove"]

#: How the screen ended.
#:
#: - ``chosen``: an action was picked for :attr:`ProfilesChoice.profile`.
#: - ``cancelled``: Escape from the table. Nothing runs; the caller reopens the six-task
#:   menu (issue #240, acceptance criterion 7 - unlike the menu itself, this screen is not
#:   the last step, so leaving it is not the end of the session).
#: - ``configure``: Escape has nothing to leave *to* here - the table was empty and the one
#:   offer it makes ("configurar") was taken.
#: - ``degraded``: the window dropped below the minimum mid-session, same fallback as the
#:   menu's own ninth trigger.
ProfilesStatus = Literal["chosen", "cancelled", "configure", "degraded"]


@dataclass(frozen=True, slots=True)
class ProfileRow:
    """One row of the table, resolved and ready to draw.

    ``host``, ``database`` and ``mode`` are ``None`` only when ``status`` is ``"error"``:
    the section failed to load, so there is nothing configuration-shaped left to show.
    ``mode`` is left exactly as configuration spells it, never as prose - the same rule
    the menu's context panel already follows (ADR 0032, decision 1).
    """

    name: str
    host: str | None
    database: str | None
    mode: str | None
    status: ProfileStatus
    #: Whether this is the profile ``switch-profile`` would find active today.
    active: bool


@dataclass(frozen=True, slots=True)
class ProfilesChoice:
    """What the screen hands back: an action, or the reason there is none.

    The border of the package, the same one :class:`~nz_mcp.menu.entries.MenuChoice` draws
    for the six-task menu: the rest of the CLI asks *what was chosen* and gets this, with no
    idea that an event loop was involved.
    """

    status: ProfilesStatus
    profile: str | None = None
    action: ProfileAction | None = None
