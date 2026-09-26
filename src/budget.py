"""Hiring + land intents. Structural layer: hands and ground move in lockstep."""
from __future__ import annotations

from . import params


def _fib(n: int) -> int:
    """Indexed like the engine: _fib(0)=1, _fib(1)=1, _fib(2)=2, ..."""
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def hire_cost(n_already_today: int) -> int:
    return _fib(n_already_today)


def market_intents(state):
    """Land + hiring orders. Land first (structural), then hires up to the day's target."""
    out = []
    owned = set(state.unlocked)
    for q in ("NE", "SW", "SE"):
        if q in owned:
            continue
        # hands+ground lockstep: buy land only when we can keep working it after
        # the purchase (cash reserve guards against a pre-revenue bankruptcy).
        if (state.day >= params.LAND_TARGET_DAY[q]
                and state.money >= params.LAND_COST[q] + params.CASH_RESERVE):
            out.append(["BUY_LAND"])
        break  # one BUY_LAND per turn; the engine fills quadrants in order anyway

    # hands+ground lockstep: hire only up to the ground we own (actions are the
    # scarce resource; a hand with no tiles idles expensively).
    owned_tiles = sum(1 for row in state.tiles for t in row if t != "LOCKED")
    target = min(params.target_hands(state.day), max(2, owned_tiles // params.TILES_PER_HAND))
    have = len(state.hand_positions)
    n_hire = 0
    cost = 0
    while have + n_hire < target:
        c = _fib(state.hires_today + n_hire)
        if state.money < cost + c:
            break
        cost += c
        n_hire += 1
    for _ in range(min(n_hire, params.MAX_HIRE_PER_TURN)):
        out.append(["HIRE"])
    return out
