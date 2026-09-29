"""src/opening.py — opening tape executor (d0-d5). Single owner of opening execution."""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import herd_plan, params, sell_policy, trade
from .job import P_HARVEST, P_PLANT, Job

# ---------------------------------------------------------------------------
# BOEY'S MEASURED d0-d5 SCRIPT (medians, 40 replays from diag-replays/boey-lb, seat
# detected by team name). The tile budget is CLOSED on every day: crops + herd = 25.
#
#   day  crops (M/S/W)   herd (C/S/G)   structs   empty
#    0      7/0/13          3/2/0          5        0
#    1      7/0/13          3/2/0          5        0
#    2     10/0/8           3/2/2          7        0
#    3     10/3/4           4/2/2          8        0
#    4     10/4/1           4/3/2         10        0
#    5     10/4/0           4/3/2         10        0
#
# The PATH is the mechanism: a 13-tile WHEAT base on d0 (first yield d2, max d4) is the
# herd's feed, and as it is HARVESTED its tiles convert to MELON/STRAWBERRY and to the
# growing herd ring. Our old script planned only 20 tiles (12 crops + a static 8-tile
# ring) and built 4 structures, so 10 owned tiles sat empty on d0 and the odd days
# idled (PASS 45/66/44 on d2/d3/d5 against his 7/7/21).
#
# CROP_BY_DAY totals are owned(25) - herd(day). Do not add a crop without removing one:
# the d0 sow is what buys the tile budget, and the d0 seed ask ($690) is sized so the
# 5-animal basket ($2,200) still fits inside the $3,000 bank.
CROP_BY_DAY = {
    0: {"WHEAT": 13, "MELON": 7},
    1: {"WHEAT": 13, "MELON": 7},
    2: {"WHEAT": 8, "MELON": 10},
    3: {"MELON": 10, "STRAWBERRY": 4, "WHEAT": 3},
    4: {"MELON": 10, "STRAWBERRY": 4, "WHEAT": 2},
    5: {"MELON": 10, "STRAWBERRY": 4, "WHEAT": 2},
}
HERD_BY_DAY_SPECIES = {
    0: {"COW": 3, "SHEEP": 2, "GOOSE": 0},
    1: {"COW": 3, "SHEEP": 2, "GOOSE": 0},
    2: {"COW": 3, "SHEEP": 2, "GOOSE": 2},
    3: {"COW": 4, "SHEEP": 2, "GOOSE": 2},
    4: {"COW": 4, "SHEEP": 3, "GOOSE": 2},
    5: {"COW": 4, "SHEEP": 3, "GOOSE": 2},
}
# (The seed ask is derived from CROP_BY_DAY by `_seed_need`; there is no static basket.)

# ---- fallback script, kept so the measured script is A/B-able -----------------
# `OPENING_TAPER_BOEY=0` reproduces the old 12-crop plan + static 8-tile ring;
# `OPENING_HERD_BOEY=0` reproduces the old ratio ramp + cheapest-first buy order.
STRUCT_TILES = 8
CROP_BY_DAY_LEGACY = {
    0: {"WHEAT": 6, "MELON": 6},
    1: {"WHEAT": 6, "MELON": 10},
    2: {"MELON": 10, "STRAWBERRY": 4, "WHEAT": 3},
    3: {"MELON": 10, "STRAWBERRY": 4, "WHEAT": 3},
    4: {"MELON": 10, "STRAWBERRY": 4, "WHEAT": 3},
    5: {"MELON": 10, "STRAWBERRY": 4, "WHEAT": 3},
}
HERD_BY_DAY_LEGACY = {0: 3, 1: 5, 2: 6, 3: 8, 4: 8, 5: 8}
_HERD_LEGACY_RATIO = {"COW": 4, "SHEEP": 2, "GOOSE": 2}


def _last_day(table):
    return max(table)


def crop_target(day):
    table = CROP_BY_DAY if params.OPENING_TAPER_BOEY else CROP_BY_DAY_LEGACY
    return dict(table.get(day, table[_last_day(table)]))


def active(state) -> bool:
    return bool(params.OPENING_TAPE) and state.day <= params.OPENING_HERD_UNTIL_DAY


def _owned_shed_order(state):
    def d(p):
        return min(abs(p[0] - s[0]) + abs(p[1] - s[1]) for s in params.SHED_ACCESS)
    return sorted(((x, y) for y in range(params.BOARD) for x in range(params.BOARD)
                   if state.owned((x, y))), key=d)


def _structure_positions(state):
    """The herd ring: the nearest-to-shed tiles reserved for structures, never planted.

    The reservation GROWS with the day's herd target (5 -> 9) instead of the constant 8,
    so the tile budget closes every day (crops + ring = owned). The tiles it grows into
    are the WHEAT block -- planted shed-outward first and harvested from d2 -- which is
    exactly Boey's path: sow 20 tiles on d0, then convert the harvested wheat tiles to
    the herd ring and to MELON/STRAWBERRY.
    """
    if params.OPENING_TAPER_BOEY:
        built = sum(1 for row in state.tiles for t in row
                    if isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE"))
        want = max(built, sum(_herd_target(state.day).values()))
    else:
        want = STRUCT_TILES
    return set(_owned_shed_order(state)[:want])


def _standing(state, crop):
    return sum(1 for row in state.tiles for x in row
               if isinstance(x, dict) and x.get("kind") == "PLANT" and x.get("crop") == crop)


def _herd_target(day):
    """The day's standing herd, by species.

    Measured script: COW/SHEEP bought first (they are the productive animals and the
    d0 commitment), GOOSE only once coops arrive on d2. Fallback: the old 4/2/2 ratio
    ramp, kept so the measurement is A/B-able.
    """
    if params.OPENING_HERD_BOEY:
        table = HERD_BY_DAY_SPECIES
        return dict(table.get(day, table[_last_day(table)]))
    total = HERD_BY_DAY_LEGACY.get(day, 8)
    base = sum(_HERD_LEGACY_RATIO.values())
    out, used = {}, 0
    for a in ("GOOSE", "SHEEP", "COW"):
        n = int(round(total * _HERD_LEGACY_RATIO[a] / base))
        out[a] = n
        used += n
    out["GOOSE"] += max(0, total - used)
    return out


def _unfed(state):
    return sum(1 for row in state.tiles for x in row
               if isinstance(x, dict) and "animal" in x and not x.get("fed_today", False))


def _animal_counts(state):
    c = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    for row in state.tiles:
        for x in row:
            if isinstance(x, dict) and "animal" in x:
                c[x["animal"]] += 1
    for a in c:
        c[a] += int(state.shed.get(a, 0))
    for inv in state.inventories:
        for a in c:
            c[a] += int(inv.get(a, 0))
    return c


def _animal_budget(state):
    """Cash the day's un-bought herd still needs. Reserved before the seed ask so the
    seed block (which is funded FIRST on d0-d1) cannot crowd out the animals."""
    if not params.HERD_ENABLED:
        return 0
    counts = _animal_counts(state)
    target = _herd_target(state.day)
    return sum(max(0, int(target.get(a, 0)) - counts.get(a, 0)) * int(ANIMALS[a]["cost"])
               for a in ("COW", "SHEEP", "GOOSE"))


def _seed_need(state, crop):
    """Seed to buy today: the day's scripted standing target -- and, within the
    look-ahead window, a later day's larger target -- minus standing plants and seed in
    hand. Derived from the script instead of a static basket so the ask is exactly what
    the plan will sow, including the d1->d2 MELON top-up (7 -> 10) before MELON's window
    shuts at d2."""
    plan = params.CROP_PLAN.get(crop)
    if plan is not None and state.day > plan["end"]:
        return 0                     # window shut: the tile can never be sown
    want = int(crop_target(state.day).get(crop, 0))
    for k in range(1, int(params.OPENING_SEED_PREBUY_DAYS) + 1):
        want = max(want, int(crop_target(state.day + k).get(crop, 0)))
    return max(0, want - _standing(state, crop) - int(state.seeds.get(crop, 0)))


def _buy_herd(state, feed_days):
    """Bulk animal purchase + feed top-up.

    herd_plan buys at most ONE animal per species per turn, so the d4 cash spike
    (money $693) converted to only ~2 animals and the herd stalled at 6. Buy the whole
    affordable deficit per species in one order instead, keeping the same feed cover.
    """
    out = []
    unfed = _unfed(state)
    wheat = int(state.shed.get("WHEAT", 0))
    if unfed > 0 and wheat < unfed + 2 and state.money >= 100:
        out.append(["BUY_PRODUCT", "WHEAT", min(params.FEED_BUY_CHUNK, unfed + 2 - wheat)])
    counts = _animal_counts(state)
    target = _herd_target(state.day)
    money = state.money
    # VALUE order, not cheapest-first: COW ($400, milk $160) and SHEEP ($500, wool $200)
    # are the d0 commitment Boey actually makes (3 COW + 2 SHEEP), and GOOSE only joins
    # once coops exist on d2. The old GOOSE-first order spent the d0 bank on the cheapest
    # animal and still stalled at 5.
    for a in (("COW", "SHEEP", "GOOSE") if params.OPENING_HERD_BOEY
              else ("GOOSE", "SHEEP", "COW")):
        need = int(target.get(a, 0)) - counts.get(a, 0)
        if need <= 0:
            continue
        cost = int(ANIMALS[a]["cost"])
        # Cover the feed we do NOT already hold, not a flat (herd+2)-days of cash. The
        # flat reserve double-counted the wheat in the shed: on d4 with 7 animals it held
        # $270 of a $585 bank against a COW that costs $400, so the herd froze at 6 while
        # money sat idle -- exactly the $693-at-d4 hoard Boey never has (he holds 137
        # wheat instead). Cover = the cash value of the MISSING feed units.
        wheat_now = int(state.shed.get("WHEAT", 0)) + sum(int(i.get("WHEAT", 0))
                                                          for i in state.inventories)
        herd_now = sum(counts.values())
        missing = max(0, (herd_now + int(params.OPENING_HERD_COVER_BUFFER)) * feed_days - wheat_now)
        cover = params.FEED_PRICE_GUESS * missing
        afford = int((money - cover) // max(1, cost))
        n = max(0, min(need, afford))
        if n > 0:
            out.append(["BUY_ANIMAL", a, n])
            money -= n * cost
            counts[a] = counts.get(a, 0) + n
    return out


def seed_ask(state):
    """The OPENING tape's seed ask, as (crop, qty) pairs -- AN ASK, NOT AN ORDER.

    Returns tuples rather than BUY_SEED orders so this is not a second EMITTER of the
    op: `plan.seed_intents` is the single owner that turns asks into orders. See
    tools/audit/duplicate_owners.py -- the audit counts order lists, not asks.
    """
    # self-contained: these were locals of `market_intents` before the extraction
    unfed = _unfed(state)
    wheat = int(state.shed.get("WHEAT", 0))
    feed_days = max(1, 3 - state.day)
    seed_orders = []
    if state.day <= params.OPENING_HERD_UNTIL_DAY:
        urgent = [c for c in params.PLANT_ORDER
                  if params.CROP_PLAN[c]["end"] - state.day <= params.WINDOW_URGENT_DAYS]
        seq = list(crop_target(state.day).keys()) + urgent + list(params.PLANT_ORDER)
        seen, plan_order = set(), []
        for c in seq:
            if c not in seen:
                seen.add(c)
                plan_order.append(c)
        need_feed = max(0, unfed * feed_days - wheat)
        # Reserve the day's un-bought animals before the seed ask -- but ONLY on d0-d1,
        # where the seed block is funded FIRST (below, `if state.day <= 1`). From d2 the
        # animals are funded before the seeds positionally, so reserving again starved
        # the MELON top-up and the whole STRAWBERRY block (measured: STRAWBERRY 0 tiles
        # and empty tiles 3 -> 10 from d4 as the harvested wheat went unreplanted).
        reserve_animals = _animal_budget(state) if state.day <= 1 else 0
        budget = state.money - params.FEED_PRICE_GUESS * need_feed - reserve_animals
        for crop in plan_order:
            n = _seed_need(state, crop)
            if n > 0 and budget > 0:
                price = max(1, params.CROPS[crop]["seed"])
                k = min(n, int(budget // price))
                if k > 0:
                    seed_orders.append((crop, k))
                break

    return seed_orders


def market_intents(state):
    """Opening market list in FUNDING order.

    sells -> feed -> [seed on d0-d1] -> animals -> hire -> [seed d2+]

    On d0-d1 the seed comes first: the wheat/melon planting window is what the whole
    opening rests on. From d2 the ANIMALS come first -- they are the daily-work engine
    and the egg/fertilizer cash that funds the rest, and with the seed basket ahead of
    them the herd stalled at 5 animals (docs/v0/sc-p1-tape11.txt).
    """
    # 3->1 day reserve: zeroing it from d3 measured WORSE (animals 6->5.5, idle 13.3->15.5,
    # revenue $2,498->$2,427 -- docs/v0/sc-p1-tape20.txt): the gate's feed cover protects
    # production. Restored.
    from . import plan as _plan
    feed_days = max(1, 3 - state.day)
    params.OPENING_BUY_FEED = True
    params.OPENING_FEED_DAYS = feed_days
    params.OPENING_HERD = _herd_target(state.day)

    # SINGLE SELL OWNER during the tape. `sell_policy` and the tape's block below BOTH
    # emitted opening sells for the same goods (WHEAT/FERTILIZER/EGG), and with the herd,
    # seeds and hire orders the list ran past `MAX_ORDERS=10` -- the tail (the tape's bulk
    # sell) was dropped silently. Measured on d3: shed WHEAT 48, feed water fine, money
    # $226, and only ~7 wheat units sold in the whole day, so the last SHEEP ($500) was
    # never funded. The tape's own block covers WHEAT/FERTILIZER/EGG, which is the whole
    # d0-d5 sell surface (no MILK/WOOL/MELON/STRAWBERRY is harvested before d6).
    out = [] if params.OPENING_OWNS_SELLS else list(sell_policy.market_intents(state))

    # EARLY CASH ENGINE: the default sell policy HOLDS wheat for scarcity, so the opening
    # earns almost nothing until d4-5 and the herd cannot be funded past ~5 animals.
    # Boey sells wheat/fertilizer throughout (6,786 wheat/game). Sell the surplus above a
    # 2-day feed reserve during the opening -- never the feed itself.
    unfed_now = _unfed(state)
    # Round-6 balance (TAPE14): a 2-day feed reserve and TRICKLE-sized sells. Raising the
    # reserve to 3 days + 30-unit chunks bought +$120 revenue but cost 8 pp of idle
    # (13.3 -> 21.1, docs/v0/sc-p1-tape15.txt) -- a bad trade against an objective that
    # includes idle <= 12, so it is reverted.
    # TAPE14/17 balance: sell surplus wheat above a 2-day feed reserve, plus fertilizer
    # and eggs. Stopping wheat sales entirely cost liquidity and the herd fell back
    # (revenue $2,498 -> $2,101, animals 6 -> 5, idle 13.3 -> 23.2; docs/v0/sc-p1-tape19.txt).
    reserved = unfed_now * int(params.OPENING_WHEAT_KEEP_DAYS) + 2
    for item in ("WHEAT", "FERTILIZER", "EGG"):
        have = int(state.shed.get(item, 0))
        keep = reserved if item == "WHEAT" else 0
        if have > keep:
            # OPENING_SELL_CHUNK, not TRICKLE: the knob existed and was never wired, so
            # the opening trickled cash out at 6 units a turn and hoarded $693 by d4
            # while the herd stalled.
            out.append(["SELL", item, min(have - keep, params.OPENING_SELL_CHUNK)])

    # THE CARRY (src/trade.py): the old leg here bought only when the shared wheat
    # inventory ran 50 units into a glut, which never happens in d0-d5 -- measured
    # inert. The carry now gates on PRICE and its sell half is emitted HERE, with the
    # other inflows and BEFORE the animal order, because the engine funds the market list
    # positionally: cash raised by the sell is spendable by the herd in the SAME turn.
    #
    # FRONT-LOAD: the carry exists to fund the herd, so when this day's animal target is
    # unmet and unaffordable, the position is LIQUIDATED -- down to the unfed count, at any
    # price above base. A few dollars a unit is worth it against a $500 SHEEP that returns
    # ~$1,600 of wool. Without this the carry's +$615 arrived d3-d5, after the buying window.
    counts_now = _animal_counts(state)
    tgt_now = _herd_target(state.day)
    still_needed = [a for a in tgt_now
                    if int(tgt_now.get(a, 0)) - counts_now.get(a, 0) > 0]
    if (still_needed and state.day >= int(params.OPENING_HERD_LIQUIDATE_DAY)
            and state.money < min(ANIMALS[a]["cost"] for a in still_needed)):
        out += trade.sell_intents(state, keep_extra=0, floor_margin=1.0, keep_none=True)
    else:
        out += trade.sell_intents(state)

    # feed top-up first, covering unfed + a small buffer
    unfed = _unfed(state)
    wheat = int(state.shed.get("WHEAT", 0))
    if unfed > 0 and wheat < unfed + 2 and state.money >= 100:
        out.append(["BUY_PRODUCT", "WHEAT", min(params.FEED_BUY_CHUNK, unfed + 2 - wheat)])

    # SEED IS DELEGATED. `plan.seed_intents` is the ONE owner of every BUY_SEED order; the
    # opening decides only WHERE in the funding order its seeds sit.
    seed_orders = _plan.seed_intents(state)
    if state.day <= 1:
        out += seed_orders
    if params.HERD_ENABLED:
        out += _buy_herd(state, feed_days)
    if params.OPENING_HIRE_FROM_TAPE:
        # Hiring has ONE owner: `budget.market_intents` already hires to the same
        # `min(target_hands(day), owned // TILES_PER_HAND)` formula. Emitting it here too
        # hired past the target -- 7 hands where Boey runs 5, which is the idle share.
        owned = sum(1 for y in range(params.BOARD) for x in range(params.BOARD)
                    if state.owned((x, y)))
        target = min(params.target_hands(state.day), max(2, owned // params.TILES_PER_HAND))
        if len(state.hand_positions) < target:
            out.append(["HIRE"])
    if state.day >= 2:
        out += seed_orders
    # the carry's BUY half last, and only with cash the rest of the opening does not
    # need: the day's un-bought herd plus its feed are reserved before it may cycle.
    unfed_end = _unfed(state)
    wheat_end = int(state.shed.get("WHEAT", 0))
    feed_cash = params.FEED_PRICE_GUESS * max(0, unfed_end * feed_days - wheat_end)
    out += trade.buy_intents(state, reserve=_animal_budget(state) + feed_cash)
    return out


def _early_harvest(state):
    """Boey's wheat taper: take the one-shot crop at FIRST yield, not at peak.

    WHEAT yields from age 2 but `state.plant_ready` (ONESHOT_HARVEST_AT_PEAK) only
    calls it ripe at age 4, so our 13 d0 wheat tiles blocked the d1->d2 MELON top-up
    (MELON's window shuts at d2) and, worse, fed nothing until d4 -- we BOUGHT the
    herd's feed at ~$420/day for three days (BUY_PRODUCT WHEAT 7 twice a day) while
    13 wheat tiles stood in the ground. Boey harvests 5/5/3 on d2/d3/d4 and eats his
    own crop. Harvest only the surplus above the day's scripted standing count, oldest
    first, so the taper is exactly CROP_BY_DAY and the tiles convert on schedule.
    """
    want = int(crop_target(state.day).get("WHEAT", 0))
    tiles = []
    for y in range(params.BOARD):
        for x in range(params.BOARD):
            t = state.at((x, y))
            if (isinstance(t, dict) and t.get("kind") == "PLANT"
                    and t.get("crop") == "WHEAT" and t.get("yield_units", 0) > 0
                    and state.crop_age(t) >= CROPS["WHEAT"]["first_yield_day"]):
                tiles.append((state.crop_age(t), (x, y)))
    tiles.sort(key=lambda a: -a[0])              # oldest first
    surplus = max(0, len(tiles) - want)
    return [Job(P_HARVEST, pos, "HARVEST", "WHEAT") for _, pos in tiles[:surplus]]


def jobs(state):
    """The tape's job list: the herd's SETUP pipeline first, then field work + planting.

    The bonus is op-selective, and that is the whole point. Boosting the entire herd
    loop (measured) placed the 5 d0 animals but starved both crop work and HARVEST:
    FEED/CARE went to 140 against HARVEST's 100, so not one wheat tile was harvested
    before d4, the herd had nothing to eat and lost a SHEEP (animals 5 -> 4). Boey's d0
    is the other way round -- PLANT 21 / WATER 20 against FEED 2 / CARE 2.

    So only the SETUP pipeline (BUILD / PICKUP / PLACE) is lifted; it is the part that
    must happen on d0 for the herd to exist at all. The daily loop keeps its own
    priorities, and a FEED is dropped outright when there is no wheat to feed with --
    it would otherwise burn a unit-turn walking to a tile it cannot serve.
    """
    from . import crop_plan, endgame
    herd = herd_plan.jobs(state) if params.HERD_ENABLED else []
    wheat = int(state.shed.get("WHEAT", 0)) + sum(int(i.get("WHEAT", 0))
                                                 for i in state.inventories)
    setup = {"BUILD_COOP", "BUILD_PASTURE", "PLACE", "PICKUP"}
    out = []
    for j in herd:
        if j.op == "FEED" and wheat <= 0:
            continue
        if j.op in setup:
            j = j._replace(priority=j.priority + params.OPENING_HERD_PRIORITY_BONUS)
        out.append(j)
    early = _early_harvest(state) if params.OPENING_TAPER_BOEY else []
    # `plant_jobs` REMOVED. It was the dormant second owner of PLANT: a CROP_BY_DAY table
    # authored for a 25-tile farm and CLAMPED at d5, so from d6 it asked for 16 plants while we
    # owned 75 tiles and emitted ZERO jobs. Measured: changing it left the game BYTE-IDENTICAL,
    # which is how it was caught. `scheduler._plant_jobs` is the live owner.
    return out + early + crop_plan.jobs(state) + endgame.jobs(state)


def capacity_target(state):
    """The crop budget derived from OWNED LAND, not from a table clamped at day 5.

    `crop_target` is CROP_BY_DAY clamped to its last key (d5) and was authored for a
    25-tile farm. From d6 the farm owns 50/75/100 tiles while the plan still asks for 16
    plants, so `max(0, target - standing) == 0` and the planting layer emits NO jobs -- the
    fill leak. Here the budget is closed on land instead: `owned - reserved_ring`, exactly
    Boey's invariant (crops + ring = owned, empty = 0 at end of day).

    The mix keeps the opening table's ratios for whatever it already asks (the d0-d5 script
    is correct and must not be disturbed) and fills the remainder by value per tile-day,
    with a WHEAT floor so the value mix cannot starve the herd's feed.
    """
    base = crop_target(state.day)
    if not params.LAND_SCALED_TARGET:
        return base
    owned = sum(1 for y, row in enumerate(state.tiles) for x in range(len(row))
                if state.owned((x, y)))
    cap = max(0, owned - len(_structure_positions(state)))
    if cap <= sum(base.values()):
        return base

    from . import value
    try:
        from . import demand
        prices = {c: demand.unit_price(c, state.inventories) for c in CROPS}
    except Exception:
        prices = {}
    rank = sorted(CROPS, key=lambda c: value.tile_dollars_per_day(prices, state.day).get(c, 0.0)
                  if isinstance(value.tile_dollars_per_day(prices, state.day), dict) else 0.0,
                  reverse=True)
    open_ = [c for c in rank
             if params.CROP_PLAN.get(c) is None
             or params.CROP_PLAN[c]["start"] <= state.day <= params.CROP_PLAN[c]["end"]]
    out = dict(base)
    room = cap - sum(out.values())
    wheat_floor = int(cap * params.LAND_SCALED_WHEAT_FLOOR)
    out["WHEAT"] = max(out.get("WHEAT", 0), wheat_floor)
    room = cap - sum(out.values())
    i = 0
    while room > 0 and open_:
        c = open_[i % len(open_)]
        out[c] = out.get(c, 0) + 1
        room -= 1
        i += 1
    return out
