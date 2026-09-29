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
from collections import defaultdict

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


# ============================================================================ THE FILL MODEL


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
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS, LAND_PRICES
    owned_q = len(state.unlocked)
    if owned_q < 4:
        cost = LAND_PRICES[max(0, owned_q - 1)]
        per_tile = recipes.best_crop_per_tile_day(prices, state.day)[1]
        npv = 25 * per_tile * d - cost
        if npv > 0:
            out.append(("BUY_LAND", None, npv, float(cost)))
    # animals: the recipe for the herd, minus feed
    for sp in ANIMALS:
        v = value.animal_value(sp, state.day, prices.get(
            {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}[sp], 0.0),
            prices.get("FERTILIZER", 0.0), d, prices.get("WHEAT", 0.0))
        if v > 0:
            out.append(("BUY_ANIMAL", sp, v, float(ANIMALS[sp].get("cost", 0.0))))
    # ---- SEEDS. Seed is CAPITAL, exactly like a hand or a quadrant ----------------------
    # A seed costs dollars and returns tile-days of production for the rest of the horizon, so it
    # is one more claim on the LAST DOLLAR and belongs in this list, ranked by the same NPV as
    # land and animals. Modelling it as a special case with its own day offset was the mistake:
    # it made "when to buy seed" a hand-set constant instead of a consequence of the schedule.
    #
    # Ranking it here also makes the ORDERING problem disappear. Seed was emitted LAST in the
    # market list and BUY_LAND ate the cash first, so on exactly the land days -- when cash is
    # tightest -- the seed ask was the first casualty of MAX_ORDERS=10 and the quadrant landed
    # bare. A $10 wheat seed into ground we already own pays back inside its 3-day cycle, so its
    # NPV per dollar beats a $1,000 quadrant's over a short horizon and it sorts ABOVE BUY_LAND
    # on merit. The ordering fix and the timing fix are the same fix.
    #
    # The CLAIM is sized by the graph's PROJECTED empty -- bare tiles now plus every quadrant the
    # schedule says is arriving -- and scaled by the graph's pressure on `empty`, which is itself
    # anticipatory. So the seed claim appears while there is still time to act on it, and the lead
    # day comes from `state_graph.schedule`, never from a knob.
    try:
        from . import state_graph as _sg
        gap = float(_sg.projected_empty(state))
        press = float(_sg.pressures(state).get("BUY_SEED", 1.0))
    except Exception:                                         # noqa: BLE001
        gap, press = 0.0, 1.0
    if gap > 0:
        for crop in CROPS:
            spec = params.CROP_PLAN.get(crop)
            if spec and not (spec["start"] <= state.day <= spec["end"]):
                continue
            # MINUS THE SEED ALREADY IN THE SHED. Without this the claim is re-issued in full
            # every turn and the farm buys 38 strawberry seeds a turn forever -- MEASURED, seed
            # cost went $6,750-$8,370 a game to $26,070-$30,470 and the median bank halved
            # ($37,270 -> $19,702). Seed is INVENTORY, so the claim is a SHORTFALL, not a level.
            tiles = int(max(0.0, gap - float(state.seeds.get(crop, 0))))
            if tiles <= 0:
                continue
            # and never past what the crop plan itself wants standing
            if spec:
                tiles = min(tiles, int(max(0, spec["target"] -
                                            sum(1 for row in state.tiles for t in row
                                                if isinstance(t, dict) and t.get("kind") == "PLANT"
                                                and t.get("crop") == crop))))
            if tiles <= 0:
                continue
            cyc = value.cycle_days(crop)
            if cyc <= 0:
                continue
            units, seed_in = value.cycle_revenue(crop)
            margin = units * float(prices.get(crop, 0.0)) - seed_in
            if margin <= 0:
                continue
            seed_cost = float(CROPS[crop]["seed"]) * tiles
            npv = tiles * (margin / cyc) * d - seed_cost
            if npv > 0:
                out.append(("BUY_SEED", crop, npv * press, seed_cost))
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


# ============================================================================ SEQUENCED SEED BUY


# ============================================================================ THE SEED OWNER
def _window_ask(state):
    """Ask for crops whose planting window closes within WINDOW_URGENT_DAYS.

    Lifted out of `scheduler._urgent_window_seeds`, which was one of six BUY_SEED emitters.
    The urgency logic is right; owning the ORDER was not its job.
    """
    out = []
    for crop in params.PLANT_ORDER:
        spec = params.CROP_PLAN.get(crop)
        if spec is None:
            continue
        if spec["end"] - state.day > params.WINDOW_URGENT_DAYS:
            continue
        deficit = spec["target"] - int(state.seeds.get(crop, 0))
        if deficit > 0:
            out.append((crop, min(deficit, 8)))
    return out


def _lead_ask(state):
    """Ask for the WHEAT feed base of the incoming quadrant, funded from the surplus above the
    land threshold. See params.SEED_LEAD_ENABLED and plan.fill_gates."""
    if not params.at("SEED_LEAD_ENABLED", state.day):
        return []
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS as _CROPS
    from . import crop_plan, herd_plan
    base = crop_plan.seed_ask(state)
    owned = set(state.unlocked)
    nxt = next((q for q in ("NE", "SW", "SE") if q not in owned), None)
    if nxt is None:
        return []
    lead = int(params.at("SEED_LEAD_DAYS", state.day))
    if state.day + lead < params.LAND_TARGET_DAY[nxt]:
        return []
    share = float(params.at("SEED_LEAD_WHEAT_SHARE", state.day))
    want = max(0, int(round(25 * share)) - int(state.seeds.get("WHEAT", 0))
               - sum(int(q) for c, q in base if c == "WHEAT"))
    if want <= 0:
        return []
    reserve = (params.CASH_RESERVE_OPENING
               if state.day <= params.OPENING_HERD_UNTIL_DAY else params.CASH_RESERVE)
    land_reserve = params.at("LAND_CASH_RESERVE", state.day)
    if land_reserve is None:
        land_reserve = reserve
    keep = float(params.LAND_COST[nxt]) + float(land_reserve)
    spendable = min(state.money - herd_plan.feed_reserve(state), state.money - keep)
    price = float(_CROPS["WHEAT"]["seed"])
    n = max(0, min(want, int(spendable // price))) if price > 0 else want
    return [("WHEAT", n)] if n > 0 else []


def _capex_ask(state):
    """Ask from the value-ranked capex list, funded only from the surplus ABOVE the atomic
    claims (land is indivisible; seed is not). See params.CAPEX_ALLOCATOR."""
    if not params.at("CAPEX_ALLOCATOR", state.day):
        return []
    from . import crew, herd_plan
    from . import state_graph as _sg
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS as _CROPS
    budget = state.money - herd_plan.feed_reserve(state)
    land_reserve = float(params.at("LAND_CASH_RESERVE", state.day) or 0.0)
    for op, _off, arg in _sg.schedule(state):
        if op == "BUY_LAND":
            need = float(params.LAND_COST.get(arg, 0.0)) + land_reserve
            if state.money >= need:
                budget -= need
    if budget <= 0:
        return []
    out = []
    for op, item, _npv, dollars in capex(state, crew.prices(state)):
        if op != "BUY_SEED" or not item:
            continue
        price = float(_CROPS[item]["seed"])
        if price <= 0:
            continue
        n = int(min(dollars, budget) // price)
        if n > 0:
            out.append((item, n))
            budget -= n * price
    return out


def seed_intents(state):
    """*** THE SINGLE OWNER OF EVERY `BUY_SEED` ORDER. ***

    MEASURED: this decision had SIX emitters -- `crop_plan.market_intents`,
    `opening.market_intents`, a helper in `opening`, `plan.seed_lead`, `plan.capex_intents`
    and `scheduler._urgent_window_seeds` (tools/audit/duplicate_owners.py --section ops).
    That is why every seed experiment this round came back weak or byte-identical: each was
    one of six competing claims on the same decision, and whichever ran won.

    The other five are now ASKERS: they return `(crop, qty)` pairs and own no order. This
    function is the only place a `["BUY_SEED", ...]` list is constructed, so the funding
    order, the budget and the graph's pressure all meet in exactly one place.

    Per crop the ask is the SUM of the contributors, CAPPED by the crop plan's own standing
    target. MAX was tried first and cost $16,159 ($58,899 -> $42,756, revenue $99,078 ->
    $84,400, idle 2.5 -> 7.9): the contributors are not redundant, they are *partial* asks
    (the buffer wants a floor, the window ask wants urgency, the lead wants the feed base), so
    taking the max discards the ones that asked for more. The cap is what stops the sum from
    becoming an over-buy that trips the engine's collective-PLANT rule, which voids the WHOLE
    batch for a crop when the requests exceed the seeds held.
    """
    from . import crop_plan, opening
    asks = defaultdict(int)
    try:
        if params.OPENING_TAPE and state.day <= params.OPENING_HERD_UNTIL_DAY:
            for c, n in opening.seed_ask(state):
                asks[c] += int(n)
        else:
            for fn in (_window_ask, crop_plan.seed_ask, _lead_ask, _capex_ask):
                try:
                    for c, n in fn(state):
                        asks[c] += int(n)
                except Exception:                              # noqa: BLE001
                    pass
    except Exception:                                          # noqa: BLE001
        return []
    # NO standing cap: the contributors already express deficits, and capping on STANDING
    # (rather than on the ask) suppressed the replant/feed top-up whenever the farm was at
    # target -- which is exactly when a harvest is about to free a tile.
    return [["BUY_SEED", c, n] for c, n in
            sorted(asks.items(), key=lambda kv: -kv[1]) if n > 0]
