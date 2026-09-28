"""crew — the crew is paid in dollars, and every hand has a budget.

The old kernel ranked work with hand-tuned constants (HARVEST 100, WATER_BONUS 120,
COLLECT_FERTILIZER 55). This replaces the ranking with money: every job is worth a number
of dollars and costs a number of unit-turns, and a unit takes the best
**dollars per unit-turn** on offer.

The second half of the idea is the BUDGET. A hand is not an infinite resource that must be
kept busy: it is allowed to decline work whose return per turn is below what a turn is
worth elsewhere. `turn_price()` is that opportunity cost -- the best dollars-per-turn
currently on offer -- and a hand refuses anything below `frac * turn_price`. That is what
stops a hand walking six tiles to dig a weed while a crop dies, without needing a band, a
reservation or a radius.

Values are the engine's own arithmetic (see `src/value.py`), priced at the CURRENT market
(`src/demand.py`), so a job's worth moves with the market rather than with a constant.

Known approximations, stated rather than hidden:
  * PICKUP->FEED and PLACE->BUILD are chains. The value of the feed or the animal is
    carried by the job that REALISES it (FEED, PLACE); the enabling job (PICKUP, BUILD)
    carries a share, so a chain can be counted slightly more than once in the ranking.
    The budget floor uses the same numbers, so the bias is small and always in the
    direction of doing the supporting work.
  * A tile's `yield_units` is read from the observation, so no production is estimated
    that the engine has not already credited.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import demand, market, recipes, value

try:                                        # generated constants; see tools/phases/bench_codegen
    from . import benchmark as _bench
except Exception:                           # noqa: BLE001
    _bench = None

# Which product each animal pays out.
ANIMAL_ITEM = {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}

# A turn must be worth at least this share of the best turn available before a hand
# will take it. 0 disables the budget rule entirely (every hand works whenever it can).
TURN_FLOOR_FRAC = 0.0


def prices(state):
    inv = state.market["inventory"]
    return {p: market.price(p, inv.get(p, market.I0))
            for p in set(list(CROPS) + list(ANIMAL_ITEM.values()) + ["FERTILIZER"])}


def animal_daily_value(species, pr):
    """Dollars per day one animal of `species` pays, care bonus included."""
    item = ANIMAL_ITEM.get(species)
    if item is None:
        return 0.0
    a = ANIMALS[species]
    # 1/interval units per production day; the care bonus doubles that day's payout.
    return (1.0 / max(1, a["interval"])) * pr.get(item, 0.0)


def herd_value_and_risk(state):
    """(total daily herd value, number of animals that escape tonight)."""
    pr = prices(state)
    total = 0.0
    at_risk = 0
    for row in state.tiles:
        for t in row:
            if not (isinstance(t, dict) and "animal" in t):
                continue
            total += animal_daily_value(t["animal"], pr)
            if t.get("consecutive_unfed", 0) >= 1:
                at_risk += 1
    return total, at_risk


def steer(state):
    """The in-game correction loop: turn the day-wise benchmark into pressure on the work.

    `src/benchmark.py` is a controller, not a report. For each signal we measure where we
    stand RIGHT NOW, compare it to the reference's target for the day, and scale the value
    of the work that closes the gap -- so a day drifting off his surface pushes harder on
    exactly the thing that is slipping, without anyone editing a constant.

    Only quantities comparable at ANY hour are used as the "ours" side. Deaths, escapes and
    the shed are DAY-END quantities, so the live proxies are the leading indicators: a plant
    that is dry tonight WILL become a weed, an animal unfed tonight WILL escape, and weeds
    and shed level are already exact mid-day.

    Widths: for metrics whose target is 0 the reference's p75-p25 is also 0, so the caller
    supplies a farm-relative width (5 % of planted tiles, 10 % of the herd, 10 % of the shed
    cap) -- otherwise the multiplier saturates on the first unit and carries no information.
    """
    # THE GRAPH IS THE STEERING SOURCE when it is available: it evaluates the causal DAG on
    # the live state, finds the deficient node's ROOT, and maps that root to the op classes
    # that close it -- with `money` in the same loop, so a survival push that costs revenue
    # raises the revenue pressure and the machine is pulled back toward his money curve.
    try:
        from . import state_graph as _sg
        g = _sg.pressures(state)
        if g:
            return g
    except Exception:                                     # noqa: BLE001
        pass
    if _bench is None:
        return {}
    day = int(state.day)
    planted = sum(1 for row in state.tiles for t in row
                  if isinstance(t, dict) and t.get("kind") == "PLANT")
    weeds = sum(1 for row in state.tiles for t in row
                if isinstance(t, dict) and t.get("kind") == "WEED")
    dry = sum(1 for row in state.tiles for t in row
              if isinstance(t, dict) and t.get("kind") == "PLANT"
              and not t.get("watered_today"))
    unfed = sum(1 for row in state.tiles for t in row
                if isinstance(t, dict) and "animal" in t
                and t.get("consecutive_unfed", 0) >= 1)
    shed = state.shed_total()
    return {
        "DIG": _bench.pressure("weeds_max", day, weeds,
                               width=max(1.0, 0.05 * planted)),
        "WATER": _bench.pressure("plants_died", day, dry,
                                 width=max(1.0, 0.05 * max(1, planted))),
        "FEED": _bench.pressure("animals_escaped", day, unfed,
                                width=max(1.0, 0.10 * max(1, state.herd_count()))),
        "DROP": _bench.pressure("max_shed_total", day, shed,
                                width=max(1.0, 0.10 * 100)),
    }


def deviation_report(state):
    """One line per steering signal: ours vs his target, and the pressure applied."""
    if _bench is None:
        return []
    day = int(state.day)
    planted = sum(1 for row in state.tiles for t in row
                  if isinstance(t, dict) and t.get("kind") == "PLANT")
    rows = [
        ("DIG", "weeds_max", sum(1 for row in state.tiles for t in row
                                 if isinstance(t, dict) and t.get("kind") == "WEED")),
        ("WATER", "plants_died", sum(1 for row in state.tiles for t in row
                                     if isinstance(t, dict) and t.get("kind") == "PLANT"
                                     and not t.get("watered_today"))),
        ("FEED", "animals_escaped", sum(1 for row in state.tiles for t in row
                                        if isinstance(t, dict) and "animal" in t
                                        and t.get("consecutive_unfed", 0) >= 1)),
        ("DROP", "max_shed_total", state.shed_total()),
    ]
    mul = steer(state)
    out = []
    for op, metric, ours in rows:
        tgt = _bench.target(metric, day)
        out.append((op, metric, ours, tgt, mul.get(op, 1.0), planted))
    return out


def job_value(state, job, pr=None, herd_daily=0.0, at_risk=0, steer_mul=None):
    """Dollars this job is expected to add. 0 means "worth nothing on its own"."""
    pr = pr if pr is not None else prices(state)
    if steer_mul:
        _m = steer_mul.get(job.op)
        if _m and _m > 1.0:
            return _m * _base_job_value(state, job, pr, herd_daily, at_risk)
    return _base_job_value(state, job, pr, herd_daily, at_risk)


def _base_job_value(state, job, pr, herd_daily, at_risk):
    """The intrinsic dollars a job adds, before any steering pressure."""
    op = job.op
    tile = state.plant_at(job.tile) if job.tile is not None else None
    animal = state.animal_at(job.tile) if job.tile is not None else None

    if op == "HARVEST":
        if animal is not None:
            item = ANIMAL_ITEM.get(animal["animal"])
            return animal.get("yield_units", 0) * pr.get(item, 0.0)
        if tile is not None:
            v = tile.get("yield_units", 0) * pr.get(tile["crop"], 0.0)
            # EARLY HARVEST FORFEITS THE REMAINING WATERS. The recipe for wheat is fertilise,
            # water on ages 2 and 3, harvest at 3 for 5 units. Cutting at age 2 takes 3 and
            # abandons the rest of the cycle, so the job is worth less than the yield says.
            if not recipes.harvest_now(state, tile):
                forf = recipes.units_per_tile_day(tile["crop"]) or 0.0
                v -= forf * pr.get(tile["crop"], 0.0)
            return max(0.0, v)
        return 0.0

    if op == "WATER":
        if tile is None:
            return 0.0
        crop = tile["crop"]
        price = pr.get(crop, 0.0)
        # `consecutive_unwatered >= 1` means tonight it becomes a WEED. What that costs is
        # NOT the standing yield -- it is every cycle the TILE could still have run, which
        # is what `tile_option_value` prices. Measured: with the standing yield the kernel
        # let 70 plants die against 48 for plain priority constants.
        risk = (value.tile_option_value(days_left(state), pr, state.day)
                if tile.get("consecutive_unwatered", 0) >= 1 else 0.0)
        gain_units = 0
        if not CROPS[crop]["ongoing"] and not tile.get("watered_today"):
            w = value.water_window(crop)
            age = state.crop_age(tile)
            if w and w[0] <= age <= w[1]:
                # ORDER MATTERS: fertilised first means +2 instead of +1.
                gain_units = 2 if tile.get("fertilized_until_day", -1) >= state.day else 1
        return risk + gain_units * price

    if op == "FERTILIZE":
        if tile is None:
            return 0.0
        crop = tile["crop"]
        w = value.water_window(crop)
        if w is None:
            return 0.0
        left = value.remaining_window_waters(crop, state.crop_age(tile),
                                             max(0, w[1] - state.crop_age(tile)))
        gain = value.fertilize_gain(crop, left)
        if gain <= 0:
            return 0.0
        # Spending 1 fertilizer here forgoes selling it.
        v = gain * pr.get(crop, 0.0) - pr.get("FERTILIZER", 0.0)
        # STAGGER: the herd makes ~1 fertilizer per animal per day, so the supply is scare
        # and must be ordered. `fert_urgency` is how many window waters this tile would
        # still lose by waiting, so the tiles closest to the window closing go first.
        urg = recipes.fert_urgency(state, tile)
        if urg:
            v *= 1.0 + 0.25 * min(urg, 4.0)
        return v

    if op == "PLANT":
        crop = job.item
        if crop not in CROPS:
            return 0.0
        cd = CROPS[crop]
        # The recipe yield, not the unfertilised one: the tile is going to be played to the
        # recipe, so valuing it at the unfertilised yield undervalues planting wheat by a
        # unit (4 vs 5) and by the cycle time (5 days vs 4).
        y = (recipes.recipe(crop) or {}).get("yield") or cd["max_yield"]
        if cd["ongoing"]:
            y = cd["max_yield"]
        return y * pr.get(crop, 0.0) - cd["seed"]

    if op == "FEED":
        if animal is None:
            return 0.0
        if animal.get("consecutive_unfed", 0) >= 1:
            # Escapes tonight: the animal and its whole future.
            return ANIMALS[animal["animal"]]["cost"] + herd_daily
        return animal_daily_value(animal["animal"], pr)

    if op == "CARE":
        if animal is None:
            return 0.0
        return animal_daily_value(animal["animal"], pr)

    if op == "COLLECT_FERTILIZER":
        # Worth its sale price, and far more as a crop input -- but the crop-input value
        # is claimed by the FERTILIZE job, so this carries the sale price only.
        return pr.get("FERTILIZER", 0.0)

    if op == "PICKUP" and job.item == "WHEAT":
        # Enables `qty` feeds; the FEED job carries the realised value, so this carries a
        # share -- enough to compete with a marginal field op.
        return 0.5 * int(job.qty or 1) * max(0.0, herd_daily / max(1, state.herd_count()))

    if op == "DIG":
        # A weed blocks the tile until it is cleared, so clearing it is worth the tile's
        # option value -- not a fraction of one crop margin. MEASURED gap this targets:
        # `weeds_max` 37 for us against **0** for the reference at d20.
        return value.tile_option_value(days_left(state), pr, state.day)

    # ---- THE ENABLING OPS -------------------------------------------------------
    # These were priced at 0.0, and the value kernel skips anything worth nothing, so the
    # crew could not build a structure, place an animal, fetch one from the shed, or
    # deposit produce. MEASURED consequence (Gate A, 8 games): `idle_share_pct` 2.4 -> 3.6
    # and the farm lost its animals. Each is now priced by the OUTCOME IT SERVES.
    if op == "PLACE":
        # The animal is already bought, so the marginal value is its output over the
        # remaining days -- `animal_value` minus the purchase cost it has already paid.
        if job.item in ANIMALS:
            return animal_on_board_value(state, job.item, pr)
        return 0.0

    if op in ("BUILD_COOP", "BUILD_PASTURE"):
        # Housing is worth the animal that will fill it; the animal itself is bought
        # separately, so this carries a share rather than the whole NPV.
        best = max((animal_on_board_value(state, sp, pr) for sp in ANIMALS), default=0.0)
        return 0.5 * best

    if op == "PICKUP" and job.item in ANIMALS:
        # The inbound half of the same chain: the animal cannot be placed without it.
        return animal_on_board_value(state, job.item, pr)

    if op == "PICKUP" and job.item == "FERTILIZER":
        # Worth the crop yield it unlocks, which the FERTILIZE job also claims -- both are
        # needed in sequence, so both carry it and the ranking stays honest.
        return best_fert_gain(state, pr)

    if op == "DROP":
        # Banks carried produce for a same-day sale; `_end_of_day` would clear it for free,
        # so the value is the marginal revenue of what is in hand right now.
        return carried_sale_value(state, inv, pr)

    return 0.0


def days_left(state):
    """Days remaining to the bell (the game runs d0-d29)."""
    return max(0, 29 - int(state.day))


def animal_on_board_value(state, species, pr):
    """Dollars an animal already owned is worth over the remaining days.

    Output at `1/interval` units per production day, care-bonused, minus its feed, but NOT
    minus the purchase price -- that has already been paid, which is what makes this the
    right number for PLACE/PICKUP/BUILD rather than `value.animal_value`.
    """
    item = ANIMAL_ITEM.get(species)
    if item is None:
        return 0.0
    d = days_left(state)
    a = ANIMALS[species]
    out = (1.0 / max(1, a["interval"])) * d
    return out * pr.get(item, 0.0) + 1.0 * d * pr.get("FERTILIZER", 0.0) \
        - 1.0 * d * pr.get("WHEAT", 0.0)


def best_fert_gain(state, pr):
    """Largest crop-yield gain available from one fertilizer right now."""
    best = 0.0
    for row in state.tiles:
        for t in row:
            if not (isinstance(t, dict) and t.get("kind") == "PLANT"):
                continue
            crop = t["crop"]
            if CROPS[crop]["ongoing"]:
                continue
            w = value.water_window(crop)
            if w is None or t.get("fertilized_until_day", -1) >= state.day:
                continue
            age = state.crop_age(t)
            left = value.remaining_window_waters(crop, age, max(0, w[1] - age))
            gain = value.fertilize_gain(crop, left)
            if gain > 0:
                best = max(best, gain * pr.get(crop, 0.0) - pr.get("FERTILIZER", 0.0))
    return max(0.0, best)


def best_replant_margin(pr):
    """Best gross margin available from planting a tile."""
    return max((value.unfertilized_one_shot_yield(c) * pr.get(c, 0.0) - CROPS[c]["seed"])
               for c in CROPS)


def carried_sale_value(state, inv, pr):
    """Marginal revenue of the produce a unit is holding."""
    if not inv:
        return 0.0
    total = 0.0
    for item, n in inv.items():
        if item in ANIMALS or n <= 0:
            continue
        inv_shelf = state.market["inventory"].get(item, market.I0)
        total += demand.marginal_revenue(item, inv_shelf, 1) * min(int(n), 4)
    return total


def job_turns(state, pos, job):
    """Unit-turns the job costs: the walk plus the act. See `value.op_turns`."""
    from . import routing
    if job.tile is None:
        return 1
    return value.op_turns(routing.manhattan(pos, job.tile))


def score(state, pos, job, pr=None, herd_daily=0.0, at_risk=0):
    """Dollars per unit-turn -- the whole basis of the ranking."""
    v = job_value(state, job, pr, herd_daily, at_risk)
    if v <= 0:
        return 0.0
    return v / job_turns(state, pos, job)


def turn_price(state, jobs, pr=None, herd_daily=0.0, at_risk=0):
    """Opportunity cost of a turn: the best dollars-per-turn currently on offer.

    This is what makes the budget rule work without a global constant -- when the farm is
    rich in high-value work a hand will not walk for a weed, and when little is left the
    same weed becomes worth doing.
    """
    best = 0.0
    for j in jobs:
        if j.tile is None:
            continue
        v = job_value(state, j, pr, herd_daily, at_risk)
        if v <= 0:
            continue
        best = max(best, v)  # per-turn is distance-dependent; use value at d=0 as the cap
    return best


def worth_doing(state, pos, job, floor, pr=None, herd_daily=0.0, at_risk=0):
    """Budget rule: does this job clear `floor` dollars per turn?"""
    if floor <= 0:
        return True
    return score(state, pos, job, pr, herd_daily, at_risk) >= floor


def hand_budget(state, frac=None):
    """Dollars-per-turn a hand must clear before it will move at all.

    `frac * turn_price`, where `turn_price` is the best value on offer this turn. With
    `frac = 0` the budget is disabled and behaviour matches the old kernel.
    """
    f = TURN_FLOOR_FRAC if frac is None else frac
    if f <= 0:
        return 0.0
    return f
