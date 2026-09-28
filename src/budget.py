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


def _fill_capital(state):
    """Working capital to FILL a quadrant: 25 seeds of the best recipe crop.

    THE ROOT FIX. MEASURED (`round 25`): the reference's EMPTY share is **0.0 % every day** and
    ours was **40 % at d8 and 35 % at d10** -- we bought quadrants and left them bare for 8-10
    days. At d8 our bank was $98 having just paid $2,000 for the ground, so there was no cash
    for seed. Buying land without seed is buying weeds: `_spawn_weeds` rolls once per `None`
    tile, so the empty quadrant IS the weed farm (his `weeds_max` 0, ours 23), it scatters the
    crops so every trip is longer (moves 41 % vs 60 %), and it starves revenue.

    An asset you cannot make productive is a liability. This makes the land buy carry the
    capital to fill it, so the quadrant is only bought when it can be worked.
    """
    if not params.at("LAND_FILL_CAPITAL", state.day):
        return 0.0
    try:
        from . import crew, recipes
        from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
        crop, _rate = recipes.best_crop_per_tile_day(crew.prices(state), state.day)
        if crop is None:
            return 0.0
        return 25.0 * float(CROPS[crop]["seed"])
    except Exception:                                     # noqa: BLE001
        return 0.0


def market_intents(state):
    """Land + hiring orders. Land first (structural), then hires up to the day's target."""
    out = []
    owned = set(state.unlocked)
    # During the opening the bank is meant to be committed, not reserved (see
    # params.CASH_RESERVE_OPENING); the season reserve is unchanged.
    reserve = (params.CASH_RESERVE_OPENING
               if state.day <= params.OPENING_HERD_UNTIL_DAY else params.CASH_RESERVE)
    # Land may use a DIFFERENT reserve (see params.LAND_CASH_RESERVE). The default is the
    # same value, so this is inert until asked; `None` means "unchanged".
    land_reserve = params.at("LAND_CASH_RESERVE", state.day)
    if land_reserve is None:
        land_reserve = reserve
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
                and state.money >= params.LAND_COST[q] + land_reserve + _fill_capital(state)):
            out.append(["BUY_LAND"])
        break  # one BUY_LAND per turn; the engine fills quadrants in order anyway

    # hands+ground lockstep: hire only up to the ground we own (actions are the
    # scarce resource; a hand with no tiles idles expensively).
    owned_tiles = sum(1 for row in state.tiles for t in row if t != "LOCKED")
    if params.at("HIRE_FROM_WORKLOAD", state.day):
        # WORKLOAD, NOT GROUND. `owned_tiles // TILES_PER_HAND` = 6 on the opening quadrant
        # against the reference's 9.6, which is a ~40 % shortfall in the land-burst window.
        from . import plan as plan_mod
        wl_target = 1 + plan_mod.hand_target(state)
        # REPLACE THE LEGACY SCHEDULE, DO NOT `min` WITH IT. This was the third instance of the
        # same failure class: the derived target was CORRECT (6/7/10/11 at d2/d4/d6/d8 against
        # the legacy 5/5/8/8) and `min(schedule, derived)` silently threw it away, so the crew
        # stayed flat at 129 unit-turns for d1-d5 while the reference ramped 91 -> 161. A
        # structural fix clamped by a legacy param cap is not a fix.
        target = wl_target
    else:
        target = min(params.target_hands(state.day),
                     max(2, owned_tiles // params.TILES_PER_HAND))
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
