"""tools/team.py — which opponent/team a leaderboard replay arm is.

Historically every tool hardcoded the #1's team name ("DSM") to (a) find the arm's
seat inside a replay's ``info.TeamNames`` and (b) label/filter the arm's rows in a
leaderboard ``games.csv``. This module is the single place that resolves the name so
the same tool can analyse any leaderboard arm (DSM, Boey, ...).

Resolution order: an explicit value (``--team``) > ``$KAGG_OPPONENT`` > ``"DSM"``.

Typical wiring in a tool's ``main()``::

    from tools import team as team_mod
    ap.add_argument("--team", default=None, help="leaderboard team name (default: DSM / $KAGG_OPPONENT)")
    ...
    args = ap.parse_args()
    team_mod.set_team(args.team)

then any detector uses ``team_mod.matches(name)`` / ``team_mod.seat_of_names(names)``.
"""
from __future__ import annotations

import os

_DEFAULT = "DSM"
_team: str | None = None


def get() -> str:
    """The current team name: explicit > ``$KAGG_OPPONENT`` > ``"DSM"``."""
    return _team or os.environ.get("KAGG_OPPONENT") or _DEFAULT


def set_team(name: str | None) -> None:
    """Pin the team for this process (called from a tool's ``main`` after parsing)."""
    global _team
    if name:
        _team = str(name)


def matches(name, team: str | None = None) -> bool:
    """Case-insensitive substring match: does ``name`` belong to the team?"""
    target = team or get()
    return bool(name) and target.upper() in str(name).upper()


def seat_of_names(names, team: str | None = None, fallback: int = 1) -> int:
    """Seat index whose ``TeamNames`` entry matches the team, else ``fallback``."""
    target = team or get()
    for i, n in enumerate(names or []):
        if matches(n, target):
            return i
    return fallback


def seats_of_names(names, team: str | None = None) -> list[int]:
    """Every seat whose ``TeamNames`` entry matches the team (may be empty)."""
    target = team or get()
    return [i for i, n in enumerate(names or []) if matches(n, target)]


def team_of(replay, team: str | None = None) -> str:
    """The team name at the arm's seat inside one replay, or the resolved team."""
    names = (replay.get("info") or {}).get("TeamNames") or []
    seat = seat_of_names(names, team)
    return names[seat] if 0 <= seat < len(names) and names[seat] else (team or get())
