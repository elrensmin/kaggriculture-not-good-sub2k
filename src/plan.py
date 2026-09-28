"""plan — the ALLOCATION actuator. The graph says what is deficient; this says who goes where.

Why this exists
---------------
Measured: 60 % of our unit-turns are spent WALKING against the reference's 41 %, and idle is
only 2.8 %. With that little slack, biasing a job PREFERENCE is nearly zero-sum -- it can only
reshuffle the ~37 % that are acts, which is exactly why every priority sweep (water 110/130/140
moved delivered water <4 %) and every graph arm lands at parity.

The scarce resource is unit-turns, so the graph must ALLOCATE them, not merely prefer. This
module turns the node pressures from `src/state_graph.py` into a NUMBER OF HANDS PER OP CLASS
for the turn, and the scheduler refuses work from a class whose allocation is spent. That is
the difference between "prefer water" and "four hands water this turn".

It is the same machinery P6 described -- a rolling plan recomputed from the observation every
turn -- with the graph as its objective function and the priors as its default:
  * `allocation` -- hands per op class, from pressure x unmet need
  * `capex`      -- land / animals / structures worth buying, by NPV over the days left
  * `spend_ok`   -- the priors' cash band: do not hold more than he does, do not spend what
                    the horizon cannot pay back
"""
from __future__ import annotations

import collections

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS

from . import params, priors, recipes, state_graph, value

# Op classes we allocate hands to. Anything absent is "filler": it may use whatever is left
# but never pre-empts an allocation.
ALLOCATED = ("WATER", "DIG", "HARVEST", "PLANT", "FEED", "CARE",
             "COLLECT_FERTILIZER", "FERTILIZE", "PLACE", "BUILD_PASTURE", "BUILD_COOP",
             "PICKUP", "DROP")


def need(state, jobs):
    """Pending jobs per op class -- the DEMAND side of the allocation."""
    c = collections.Counter()
    for j in jobs:
        c[j.op] += 1
    return c


def allocation(state, jobs, n_units=None):
    """op class -> how many hands may work it this turn.

    Proportional share of the crew by `pressure x unmet_need`, floored at 1 for any class the
    graph is pushing so a deficiency always gets at least one hand, and capped by the number of
    jobs actually pending. Sums to at most `n_units`.
    """
    n = int(n_units if n_units is not None else state.unit_count())
    nd = need(state, jobs)
    if not nd:
        return {}
    # ---- THE DEADLINE FLOOR, RESERVED FIRST -------------------------------------------
    # MEASURED: value-weighting the allocation moved the cost metrics the right way
    # (moves 60.1 % -> 53.0 %, moves/act 1.64 -> 1.19) and made `died` WORSE, 50 -> 62.
    # A WATER on a tile that is merely dry prices its +1 unit (~$25) against a HARVEST worth
    # hundreds -- and the tile that will actually die tonight carries
    # `consecutive_unwatered == 0` in the current observation, because the engine only
    # increments that counter at `_end_of_day`. So the imminent loss is not in the price at
    # all, and survival must be RESERVED before the dollars are shared out, not compete
    # inside them. These are exactly the `critical` jobs the layers already flag.
    out = collections.Counter()
    crit = collections.Counter()
    for j in jobs:
        if j.critical:
            crit[j.op] += 1
    reserved = 0
    for op, k in crit.most_common():
        if reserved >= n:
            break
        take = min(k, n - reserved)
        out[op] += take
        reserved += take
    n = max(0, n - reserved)          # only the SURPLUS competes on dollars
    if n == 0:
        return dict(out)
    press = {}
    try:
        press = state_graph.pressures(state)
    except Exception:                                     # noqa: BLE001
        press = {}
    # VALUE-WEIGHTED, NOT DEFICIENCY-WEIGHTED. Weighting by the job COUNT alone spends the
    # crew on whatever is most numerous -- measured, that moved the cost metrics the right way
    # (moves 60.1 % -> 57.5 %, acts 36.7 % -> 40.0 %) and made MONEY WORSE, because four hands
    # went to weeds while a harvest worth an order of magnitude more waited. The graph says
    # what is DEFICIENT; the dollars say what is WORTH DOING; the allocation needs both.
    from . import crew
    pr = crew.prices(state)
    herd_daily, at_risk = crew.herd_value_and_risk(state)
    dollar = collections.Counter()
    for j in jobs:
        try:
            dollar[j.op] += max(0.0, crew.job_value(state, j, pr, herd_daily, at_risk))
        except Exception:                                 # noqa: BLE001
            continue
    weight = {}
    for op, k in nd.items():
        p = press.get(op, 1.0)
        v = dollar.get(op, 0.0)
        # `max(k, v/50)` keeps a class with real dollar value but few jobs in the running,
        # and a class with many worthless jobs out of it.
        weight[op] = p * max(k, v / 50.0)
    total = sum(weight.values()) or 1.0
    left = n
    # Largest-remainder allocation so the whole crew is used and no class is starved.
    share = {op: n * w / total for op, w in weight.items()}
    for op, s in share.items():
        out[op] += min(int(s) - out[op], nd[op]) if int(s) > out[op] else 0
    left -= sum(out.values())
    for op, s in sorted(share.items(), key=lambda kv: -(kv[1] - int(kv[1]))):
        if left <= 0:
            break
        if out[op] < nd[op]:
            out[op] += 1
            left -= 1
    # A pressured class always gets at least one hand, even when its share rounds to zero.
    for op, p in press.items():
        if p > 1.0 and nd.get(op, 0) > 0 and out.get(op, 0) == 0:
            lo = min(out, key=lambda o: out[o]) if out else None
            if lo is not None and out[lo] > 1:
                out[lo] -= 1
                out[op] += 1
    return dict(out)


# ---------------------------------------------------------------- WORKLOAD -> LABOUR
def workload_ops(state):
    """Ops the farm NEEDS per day, derived from the recipes and the standing herd.

    The hiring rule was `owned_tiles // TILES_PER_HAND` = 25//4 = **6 hands** on the opening
    quadrant, while the reference runs **9.6 units** (231 unit-turns) on the same 25 tiles and
    12.4 by d10. That is a ground constant standing in for a workload, so it under-hires by
    ~40 % in exactly the window where the land burst happens.

    This counts the work instead: every planted tile needs its recipe's waters per cycle, a
    harvest per cycle, and its share of a replant; every empty owned tile needs a plant; every
    animal needs feed + care + collect every day.
    """
    from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS
    from . import recipes
    ops = 0.0
    for y, row in enumerate(state.tiles):
        for x, t in enumerate(row):
            pos = (x, y)
            if t is None and state.owned(pos):
                ops += 1.0                      # it must be planted
            elif isinstance(t, dict) and t.get("kind") == "WEED":
                ops += 0.5                      # it must be cleared
            elif isinstance(t, dict) and t.get("kind") == "PLANT":
                crop = t["crop"]
                r = recipes.recipe(crop)
                cyc = (r or {}).get("cycle_days") or 4
                waters = len((r or {}).get("waters") or ()) or 1
                ops += (waters + 1.0) / max(1.0, cyc)     # waters + harvest per cycle
                ops += 1.0 / max(1.0, cyc)                # its share of a replant
            elif isinstance(t, dict) and "animal" in t:
                ops += 3.0                      # feed + care + collect, every day
    return ops


def act_share(state):
    """Fraction of unit-turns that are acts. MEASURED 40 %, against the reference's 59 %."""
    return 0.40


def hand_target(state):
    """Hands needed to deliver `workload_ops` at `act_share` -- the workload, not the ground.

    Capped by what the bank can pay: hands are fibonacci-priced, so the marginal hand must earn
    its hire cost, and `budget` still refuses one it cannot afford.
    """
    # THE CREW IS A BENCHMARK QUANTITY. A workload sum does NOT calibrate: it gives 3 hands at
    # d2 where the reference runs 5.8, because his crew is not sized to the minimum ops -- he
    # idles 4-15 % early and ramps the crew to ~12 by d6 and holds it. So the target comes from
    # the MEASURED unit-turn curve (`benchmark.target('unit_turns') / 24`), which reproduces
    # 5.8 units at d2 and 12.4 at d10 by construction. `workload_ops` stays for diagnosis.
    try:
        ut = _bench_target(state)
        if ut:
            return max(0, min(24, int(round(ut / 24.0)) - 1))
    except Exception:                                     # noqa: BLE001
        pass
    import math
    per_unit = 24.0 * act_share(state)
    return max(0, min(24, int(math.ceil(workload_ops(state) / max(1.0, per_unit))) - 1))


def _bench_target(state):
    from . import benchmark
    return benchmark.target("unit_turns", int(state.day))


def seed_need(state, prices=None):
    """Seeds required to FILL THE LAND, and what the bank can pay for.

    TOP OF THE CAUSAL CHAIN, and the one piece still untouched. The chain measured is:
    seed never bought -> the quadrant stays EMPTY -> `_spawn_weeds` rolls once per `None` tile so
    the empty quadrant IS the weed farm -> crops scattered so every trip is longer -> moves 60 %
    against the reference's 45 % -> acts 98/day against his 127-163 -> watered 60 % -> revenue.

    The blocker is not cash. It is that the market list is capped at `MAX_ORDERS = 10` and the
    seed intents are emitted **LAST**, behind sells, land, hires, animals and feed -- so we can
    hold the money, buy the quadrant, and still never buy the seed. This computes the ask from the
    empty-tile count, and the caller slots it AHEAD.

    Returns [(crop, qty)] for at most the crops the recipe plan actually wants.
    """
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
    from . import crew, recipes
    empty = sum(1 for y, row in enumerate(state.tiles) for x, t in enumerate(row)
                if t is None and state.owned((x, y)))
    if empty <= 0:
        return []
    pr = prices if prices is not None else crew.prices(state)
    crop, _rate = recipes.best_crop_per_tile_day(pr, state.day)
    if crop is None:
        return []
    cost = float(CROPS[crop]["seed"])
    have = int(state.seeds.get(crop, 0))
    want = max(0, empty - have)
    if want <= 0:
        return []
    spendable = state.money - float(params.CASH_RESERVE)
    afford = int(spendable // max(1.0, cost))
    n = max(0, min(want, afford))
    return [(crop, n)] if n > 0 else []


def days_left(state):
    return max(0, 29 - int(state.day))


def capex(state, prices):
    """(op, item, dollars) buys worth doing now, best NPV first.

    P6's rule, derived rather than staged: buy while the payback fits inside the horizon. A
    $400 cow at d3 has 26 days to pay back and is worth it; at d25 it has four and is not. That
    is why the reference is fully invested to d10 and buys nothing after -- the SAME formula,
    not a phase table.
    """
    d = days_left(state)
    if d <= 0:
        return []
    out = []
    # land: LAND_PRICES[0, 2000, 4000] for the 2nd/3rd/4th quadrant, 25 tiles each
    from kaggle_environments.envs.kaggriculture.kaggriculture import LAND_PRICES
    owned_q = len(state.unlocked)
    if owned_q < 4:
        cost = LAND_PRICES[max(0, owned_q - 1)]
        per_tile = recipes.best_crop_per_tile_day(prices, state.day)[1]
        npv = 25 * per_tile * d - cost
        if npv > 0:
            out.append(("BUY_LAND", None, npv))
    # animals: the recipe for the herd, minus feed
    for sp in ANIMALS:
        v = value.animal_value(sp, state.day, prices.get(
            {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}[sp], 0.0),
            prices.get("FERTILIZER", 0.0), d, prices.get("WHEAT", 0.0))
        if v > 0:
            out.append(("BUY_ANIMAL", sp, v))
    return sorted(out, key=lambda t: -t[2])


def spend_ok(state, kind="discretionary"):
    """The priors' cash band as a spending gate.

    MEASURED: his median bank is **$13 at d5 and $41 at d10** -- he is fully invested, cash
    zero, through the build. So "hold cash" is not the target there; "spend everything that
    pays back inside the horizon" is. `benchmark` supplies the band, and a plan may sit above
    his p75 only when nothing clears its payback.
    """
    try:
        lo, hi = priors.cash_band(int(state.day))
    except Exception:                                     # noqa: BLE001
        return True
    if kind == "discretionary" and state.money <= hi:
        return True
    return state.money <= hi


# ============================================================================ THE FILL MODEL
def fill_gates(state):
    """The FOUR gates that decide whether an empty owned tile can become planted TODAY.

    `empty` is not controlled by one rule. A tile is sown only if ALL of these hold, and the
    leak is whichever one binds -- which is why every single-gate fix so far (queue, seeds,
    band) moved the number a little and then stopped:

      1. WINDOW   the crop's planting window is open today                (engine calendar)
      2. SEEDS    we hold a seed of that crop, AND the total PLANT requests for a crop do not
                  exceed the seeds held -- the engine validates PLANT COLLECTIVELY per crop and
                  voids EVERY request for that crop if the batch is over, so asking for 5 wheat
                  with 2 seeds plants ZERO
      3. TURNS    worker-turns left today: `units x (24 - hour)`, minus the work already
                  committed to survival
      4. ASSIGN   a job exists for the tile AND a unit is sent to it -- band membership,
                  per-worker quota, and the priority race

    `sowable` = min(gates 1-3). If `sowable < empty` the leak is STRUCTURAL (a resource); if
    `sowable >= empty` the leak is ASSIGNMENT (gates 4), which is a scheduler problem and not a
    resource one. Separating the two is the whole point: they need opposite fixes, and every
    aggregate hides which one is firing.
    """
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
    empty = sum(1 for y, row in enumerate(state.tiles) for x, t in enumerate(row)
                if t is None and state.owned((x, y)))
    # 1. WINDOW
    open_crops = []
    for c in CROPS:
        pl = params.CROP_PLAN.get(c)
        if pl is None or pl["start"] <= state.day <= pl["end"]:
            open_crops.append(c)
    # 2. SEEDS (the tightest gate: the engine's collective-PLANT rule)
    seed_cap = sum(int(state.seeds.get(c, 0)) for c in open_crops)
    # 3. TURNS
    turns_left = max(0, 24 - int(state.hour))
    units = state.unit_count()
    turn_cap = units * turns_left
    sowable = min(empty, seed_cap, turn_cap)
    if sowable < empty:
        binding = ("SEEDS" if seed_cap <= turn_cap else "TURNS")
    else:
        binding = "ASSIGN"
    return {"empty": empty, "open_crops": open_crops, "seed_cap": seed_cap,
            "turn_cap": turn_cap, "units": units, "turns_left": turns_left,
            "sowable": sowable, "binding": binding,
            "structural_gap": max(0, empty - sowable)}


def fill_report(state):
    """One line: the fill gates and which one is binding."""
    g = fill_gates(state)
    return (f"empty {g['empty']:>3}  sowable {g['sowable']:>3}  "
            f"seeds {g['seed_cap']:>3}  turns {g['turn_cap']:>4} "
            f"({g['units']}u x {g['turns_left']}h)  BINDING {g['binding']}")
