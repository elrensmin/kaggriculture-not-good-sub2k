"""window — restrict a tool to a day range (``--days 0-10``).

The opening is what we are fixing, and the opening is 5 days of a 30-day game. A
whole-game readout of an opening change has terrible signal-to-noise (the whole of
d0-d8 is ~6.5% of the structure gap), so every analysis tool takes the same window
argument and reports ONLY inside it.

``--days 0-10``  a day range, inclusive
``--days 0-10,12-17``  several ranges
``--days all``  the whole game (the default, so nothing changes unless asked)
"""
from __future__ import annotations


def parse_days(spec):
    """'0-10' | '0-10,12-17' | 'all' | None -> tuple of (lo, hi) ranges, or None."""
    if not spec or spec.strip().lower() in ("all", "*"):
        return None
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            out.append((int(a), int(b)))
        else:
            out.append((int(part), int(part)))
    return tuple(out) or None


def in_window(day, ranges) -> bool:
    if ranges is None:
        return True
    return any(lo <= day <= hi for lo, hi in ranges)


def describe(ranges) -> str:
    if ranges is None:
        return "whole game"
    return ", ".join(f"d{lo}-d{hi}" if lo != hi else f"d{lo}" for lo, hi in ranges)
