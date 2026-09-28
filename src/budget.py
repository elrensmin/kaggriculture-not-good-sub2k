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
    # During the opening the bank is meant to be committed, not reserved (see
    # params.CASH_RESERVE_OPENING); the season reserve is unchanged.
    reserve = (params.CASH_RESERVE_OPENING
               if state.day <= params.OPENING_HERD_UNTIL_DAY else params.CASH_RESERVE)
    for q in ("NE", "SW", "SE"):
        if q in owned:
            continue
        # W2 geometry test: stop buying ground past this many quadrants. We own 100
        # tiles in the midgame and plant ~53; Boey owns 75 and plants 55. A bigger,
        # sparser farm costs walking on every water op (`WATER moves/op` 2.92 vs 1.17),
        # and coverage is the phase-2 root. 4 = the old behaviour.
        if len(owned) >= int(params.at("LAND_QUADRANT_MAX", state.day)):
            break
        # hands+ground lockstep: buy land only when we can keep working it after
        # the purchase (cash reserve guards against a pre-revenue bankruptcy).
        if (state.day >= params.LAND_TARGET_DAY[q]
                and state.money >= params.LAND_COST[q] + reserve):
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
    # PHASE-SCOPED, and the midgame needs it badly: `_end_of_day` wipes `hands` and
    # resets `hires_today` EVERY day, so the whole crew is rebuilt from scratch each
    # morning. At `MAX_HIRE_PER_TURN=1` (shipped in Phase 1 to stop 5-at-once HIREs
    # eating the opening's order list) that takes 12 turns, so the crew averages 8.8
    # units against a target of 10.8 -- and Boey runs 10.8. Measured: the phase-2
    # `move share`/act deficit traces back to this, not to routing.
    for _ in range(min(n_hire, int(params.at("MAX_HIRE_PER_TURN", state.day)))):
        out.append(["HIRE"])
    return out
