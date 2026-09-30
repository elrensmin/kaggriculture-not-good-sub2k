"""Herd: species mix, buy/place, FEED/CARE/COLLECT. Structural layer (R4).

Shop-aware species mix (YARN -> 10 sheep + 6 geese, no-YARN -> 3 sheep + 8 geese),
ring placement, and the daily FEED+CARE cycle (care economics: SHEEP > COW > GOOSE).
Animals also print 1 free fertilizer/day -> the FERTILIZE path doubles crop yield.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS

from . import endgame, params
from .job import (
    P_BUILD, P_CARE, P_COLLECT_FERT, P_FEED, P_HARVEST, P_PICKUP_ANIMAL,
    P_PICKUP_WHEAT, P_PLACE, Job,
)

_STRUCT = {"GOOSE": "COOP", "COW": "PASTURE", "SHEEP": "PASTURE"}


def _targets(state):
    """Standing animal targets: the opening SCRIPT during d0-d5, else the season ramp.

    The season `HERD` targets are a ramp, and ramping a herd from 0 with a
    1-animal-per-turn buy over 24 market phases leaves the opening decided by cash
    gates instead of by a plan. The #1's herd through d5 is a constant (2 COW +
    3 SHEEP, 40/40 games), so during the opening the target is that constant.
    """
    if params.HERD_ENABLED and state.day <= params.OPENING_HERD_UNTIL_DAY:
        return {a: int(params.OPENING_HERD.get(a, 0)) for a in ("COW", "SHEEP", "GOOSE")}
    yarn = state.has_yarn()
    base = {
        "COW": params.HERD["COW"]["target"],
        "SHEEP": params.HERD["SHEEP"]["target_yarn" if yarn else "target_noyarn"],
        "GOOSE": params.HERD["GOOSE"]["target_yarn" if yarn else "target_noyarn"],
    }
    # SHOP-RESPONSIVE (see params.HERD_SHOP_RESPONSIVE): produce what the town actually buys.
    # The reference's own medians say a cow shop lifts COW 4->7-8, a goose shop GOOSE 3->7, and
    # YARN lifts SHEEP 2->9 -- but the season ramp here fixes COW at 9 with no regard for the
    # draw, so a no-cow-shop game over-breeds milk into the 1/day town centre.
    if params.at("HERD_SHOP_RESPONSIVE", state.day):
        from . import priors as _priors
        shops = set(state.shops)
        for sp in ("COW", "SHEEP", "GOOSE"):
            withs, without = [], None
            for shop, (species, w, wo) in _priors.HERD_BY_SHOP.items():
                if species != sp:
                    continue
                without = wo if without is None else max(without, wo)
                if shop in shops:
                    withs.append(w)
            if withs:
                base[sp] = int(max(withs))
            elif without is not None:
                base[sp] = int(without)
    return base


def _animal_counts(state):
    counts = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict) and "animal" in t:
                counts[t["animal"]] += 1
    for a in counts:
        counts[a] += int(state.shed.get(a, 0))
    for inv in state.inventories:
        for a in counts:
            counts[a] += int(inv.get(a, 0))
    return counts


def _on_board_counts(state):
    """Animals actually PLACED on the board, by species."""
    counts = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict) and "animal" in t:
                counts[t["animal"]] += 1
    return counts


def _structure_counts(state):
    coops = pastures = 0
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict):
                if t.get("kind") == "COOP":
                    coops += 1
                elif t.get("kind") == "PASTURE":
                    pastures += 1
    return coops, pastures


def _shed_order_empties(state):
    tiles = [
        (x, y)
        for y in range(params.BOARD)
        for x in range(params.BOARD)
        if state.is_empty_owned((x, y))
    ]
    tiles.sort(key=lambda p: min(abs(p[0] - s[0]) + abs(p[1] - s[1]) for s in params.SHED_ACCESS))
    return tiles


def _unfed_count(state):
    """Animals still needing today's feed (the day's wheat demand while feeding
    daily; with the old every-other-day feed this was the escape-risk subset)."""
    return sum(
        1
        for row in state.tiles
        for t in row
        if isinstance(t, dict) and "animal" in t
        and not t.get("fed_today", False)
    )


def _wheat_tiles(state):
    return sum(
        1
        for row in state.tiles
        for t in row
        if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop") == "WHEAT"
    )


def feed_reserve(state):
    """Cash to hold back for bought feed until our own wheat lands.

    The purchase gate alone is not enough: it leaves the money on the table and then
    the seed buys spend it, so the herd starves. Measured on the herd-on arm, money
    went $27 -> $10 -> $3 -> $1 across d0-d3 and all five animals escaped on d3.
    ``crop_plan.market_intents`` subtracts this before buying seed.
    """
    if not params.HERD_ENABLED:
        return 0.0
    herd = sum(_animal_counts(state).values())
    if herd <= 0:
        return 0.0
    if params.OPENING_BUY_FEED and state.day <= params.OPENING_HERD_UNTIL_DAY:
        # Opening package: the herd eats BOUGHT wheat (Boey buys ~3.5k/game), so a
        # 5-day `WHEAT_LANDS_DAY` reserve for a 10-animal herd is $1,500 of a $3,000
        # bank. Cover = OPENING_FEED_DAYS instead.
        days = max(0, params.OPENING_FEED_DAYS)
    else:
        days = max(0, params.WHEAT_LANDS_DAY - state.day)
    return herd * days * params.FEED_PRICE_GUESS



def _standing(state, crop):
    """Standing tiles of `crop` (local copy: crop_plan imports herd_plan, so the
    dependency cannot run the other way without a cycle)."""
    n = 0
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop") == crop:
                n += 1
    return n


def _script_seed_need(state):
    """Cash the OPENING script still needs to buy TODAY's seed for.

    Why not a flat reserve: a fixed `OPENING_SEED_FLOOR` is either too small to fund
    the day's crop top-up or big enough to block the 5th animal for the whole of d0.
    MEASURED (`tools/labour/unit_trace.py` + an instrumented gate): with $500 reserved
    we own only 4 animals all day; with $0 reserved the 5th animal buys on d0 and then
    takes the cash the d1 MELON top-up needs, so MELON stalls at 6/10 and the whole
    melon block (first_yield_day 10, max_yield_day 12, single harvest) is lost. Reserving
    the *exact* remaining seed cost lets both happen: the animal buys only with what is
    left after today's crop plan is funded.
    """
    if not params.OPENING_SCRIPT:
        return 0.0
    if params.OPENING_TAPE:
        # The tape (src/opening.py) owns the opening seed purchase, so the generic
        # script reserve must NOT also hold cash back -- it was reserving against the
        # DSM 10-strawberry table while the tape plants 4, and that over-reserve is why
        # the herd stalled at 4 animals (idle 63 %).
        return 0.0
    if params.OPENING_SEED_RESERVE_HORIZON:
        # Reserve seed only for crops whose planting window CLOSES inside the opening
        # (MELON: end=2) -- those are the ones the script cannot buy later. Reserving the
        # whole script (wheat/strawberry too) over-held cash: measured cash_commit 0.99 ->
        # 0.73, animals/feed down, idle +7 pp, margin -$3,324 (docs/v0/sc-horizon.txt).
        crops = {c for t in params.OPENING_STANDING.values() for c in t
                 if params.CROP_PLAN[c]["end"] <= params.OPENING_HERD_UNTIL_DAY}
        total = 0.0
        for crop in crops:
            target = max((int((params.OPENING_STANDING.get(d) or {}).get(crop, 0))
                          for d in range(state.day, params.OPENING_HERD_UNTIL_DAY + 1)),
                         default=0)
            have = _standing(state, crop) + int(state.seeds.get(crop, 0))
            total += max(0, target - have) * params.CROPS[crop]["seed"]
        return float(total)
    table = params.OPENING_STANDING.get(state.day)
    if not table:
        return 0.0
    total = 0.0
    for crop, target in table.items():
        have = _standing(state, crop) + int(state.seeds.get(crop, 0))
        total += max(0, int(target) - have) * params.CROPS[crop]["seed"]
    return float(total)


def market_intents(state):
    out = []
    # buy animals to reach the shop-aware targets, cash-gated and batched so the
    # opening crop ramp is never bankrupted before animal revenue starts.
    if params.HERD_BUY_FROM_DAY <= state.day <= params.HERD_BUY_UNTIL:
        targets = _targets(state)
        counts = _animal_counts(state)
        herd = sum(counts.values())
        # Post-opening expansion may be gated on the shop reveal: the season targets are
        # unconditional (9 COW + 3 SHEEP + 8 GOOSE) and measured -$16,775 from an
        # identical d5 state, but the #1 IS shop-responsive after d5 (YARN worlds end
        # with SHEEP 7.5 / GOOSE 2, no-YARN with SHEEP 0 / GOOSE 6). See the param.
        expanding = state.day > params.OPENING_HERD_UNTIL_DAY
        may_buy = not (expanding and params.HERD_EXPAND_ON_YARN and not state.has_yarn())
        # Crop modality GATES the herd modality: a wheat tile turns over ~4 units
        # per 5 days = 0.8 units/day and an animal eats 1/day, so the farm needs
        # ~1.7 standing wheat tiles per animal (DSM: 32 wheat / 19 animals). Buying
        # past that point is how the herd was measured to destroy the farm -- the
        # herd arm ran feed_surplus -240/game (it BOUGHT feed at retail) and lost
        # $20-30k a game while every labour defect improved. A tile we have already
        # SOWN counts: it will yield, and during day 0 the count climbs 0 -> 15, so
        # the gate opens exactly as the wheat base is established.
        need = params.at("WHEAT_TILES_PER_ANIMAL", state.day) * (herd + 1)
        # In the opening, cash is the feed capacity: we commit the bank before any
        # crop can feed the herd, and the feed_cover term below prices that. From
        # HERD_OPENING_DAYS on, the wheat base is the gate -- UNLESS OPENING_BUY_FEED,
        # which lets the opening herd eat bought wheat (Boey's behaviour) so the herd
        # is not capped at ~5 animals by our own not-yet-standing wheat.
        # HERD_SHED_WHEAT_CREDIT: a wheat unit already IN THE SHED is feed the farm owns.
        # MEASURED (tools/phases/herd_gate.py, 16 games): from d11 to d17 `can_feed` fails
        # EVERY single day with the herd at 16, wheatT at 22-26 and **$18.5k of idle cash**
        # -- the gate is a standing-TILE count while the constraint it is proxying for is
        # feed. The credit converts shed wheat into tile-equivalents (a wheat tile turns
        # over ~3 units per cycle), so a stocked shed opens the gate without pretending the
        # farm can out-produce its own herd. 0 = off (the old behaviour).
        _credit = params.at("HERD_SHED_WHEAT_CREDIT", state.day)
        _have = _wheat_tiles(state)
        if _credit:
            _have += int(state.shed.get("WHEAT", 0)) / float(_credit)
        # PRESSURE-AWARE VETO. When the graph says we are holding capital the reference already
        # deployed (`state_graph.deploy_pressure > 1`), the standing-tile gate yields: the herd
        # may be fed from bought wheat, which is the reference's own behaviour ("he does not gate
        # on standing wheat at all -- he gates on CASH and buys the feed"). Without this the graph
        # could compute the deployment deficiency and nothing could act on it (measured: graded
        # DEPLOY_NODE was byte-identical, +$0).
        try:
            from . import state_graph as _sg
            _deploy = _sg.deploy_pressure(state) > 1.0
        except Exception:                                      # noqa: BLE001
            _deploy = False
        can_feed = (_have >= need
                    or _deploy
                    or state.day <= params.HERD_OPENING_DAYS
                    or (params.OPENING_BUY_FEED
                        and state.day <= params.OPENING_HERD_UNTIL_DAY))
        # Cover the bought-feed gap until our own wheat ripens -- for the WHOLE
        # herd, not just the animal being bought. Per-animal cover let us buy six
        # animals on day 0 and leave $600 for six mouths: measured, FEED ops went to
        # 0 in the opening (the animals had nothing to eat) while the farm planted
        # half as much because the seed money was gone too.
        #
        # MATURE wheat base = the cover is double-counting. `can_feed` already says the
        # standing wheat covers the herd at the ration the farm runs; holding 5 more days
        # of bought-feed cash on top of that is what froze the midgame herd at 10 while
        # money grew to $7,792 (see tools/phases/herd_gate.py). Measured blocked days:
        # d10-d12 had 22 wheat tiles, `can_feed` True, and money $691-1,345 against a
        # $1,650-1,725 cover -- the animal was affordable and the reserve refused it.
        if state.day <= params.OPENING_HERD_UNTIL_DAY:
            feed_days = params.OPENING_FEED_DAYS
        elif _wheat_tiles(state) >= need:
            feed_days = params.at("ANIMAL_FEED_RESERVE_DAYS_MATURE", state.day)
        else:
            feed_days = params.at("ANIMAL_FEED_RESERVE_DAYS", state.day)
        feed_cover = feed_days * params.FEED_PRICE_GUESS * (herd + 1)
        for a in params.HERD_SPECIES_ORDER:
            deficit = targets[a] - counts[a]
            if deficit > 0 and can_feed and may_buy:
                n = min(deficit, 1)
                # keep the herd's feed AND the opening planting funded
                # script-aware, not a flat floor: reserve exactly what TODAY's
                # crop plan still needs to buy, so the animal buys with the rest
                seed_floor = _script_seed_need(state)
                # `ANIMAL_SHED_LIMIT`: the 95 was a "don't overflow the shed" proxy, but an
                # animal bought into the shed is PLACED and vacates it, and MEASURED the
                # guard binds exactly when the gate finally opens -- the same turns the
                # shed holds 60-94 items (mostly 59 WHEAT, which is 3.7 days of feed for
                # 16 animals). At d14 in a live game: shed 94, wheat tiles 28, need 32.3.
                if (state.money >= ANIMALS[a]["cost"] * n + params.ANIMAL_CASH_RESERVE
                        + feed_cover + seed_floor
                        and state.shed_total() + n <= params.at("ANIMAL_SHED_LIMIT", state.day)):
                    out.append(["BUY_ANIMAL", a, n])
    # feed top-up: buy the shortfall to cover every unfed animal (no hoarding).
    # From day 0, not day 4: an opening herd bought before its own wheat ripens
    # must be fed from the market or it escapes on day 3.
    unfed = _unfed_count(state)
    wheat = int(state.shed.get("WHEAT", 0))
    # FEED_STOCK_DAYS lets the herd run on a bought buffer rather than on today's
    # shortfall -- the reference's behaviour (see params.FEED_STOCK_DAYS). 0 = unchanged.
    days = params.at("FEED_STOCK_DAYS", state.day)
    target = unfed
    if days:
        # COUNT WHAT THE UNITS ARE CARRYING TOO. The shed alone looks empty while feeders
        # hold wheat in hand, so the layer rebought the same units every turn:
        # MEASURED 2026-09-29, `FEED_STOCK_DAYS_P2=2` bought **+$45,029 of product** and fed
        # only 24 more units -- the churn was the whole season cost.
        wheat += sum(int(inv.get("WHEAT", 0)) for inv in state.inventories)
        target = max(target, int(sum(_animal_counts(state).values()) * days))
    short = max(0, target - wheat)
    if short > 0 and state.money >= 100:
        out.append(["BUY_PRODUCT", "WHEAT", min(int(params.at("FEED_BUY_CHUNK", state.day)), short)])
    return out


def jobs(state):
    out = []
    active = (not endgame.herd_retiring(state)) and state.day < params.HERD_ACTIVE_UNTIL_DAY

    # animal-tile jobs: harvest product, feed, care, collect fertilizer
    for y in range(params.BOARD):
        for x in range(params.BOARD):
            pos = (x, y)
            t = state.animal_at(pos)
            if t is None:
                continue
            # harvest once at max_held where possible (the cap discards the rest)
            if state.animal_ready(t):
                out.append(Job(P_HARVEST, pos, "HARVEST", None))
            if active:
                # Feed DAILY: the engine pays the banked CARE bonus only on a fed
                # production day (and resets it otherwise), so a "feed every other
                # day" saving silently halves herd output. DSM feeds ~20/day.
                if state.animal_needs_feed(t):
                    at_risk = t.get("consecutive_unfed", 0) >= 1  # escapes tonight
                    out.append(Job(P_FEED, pos, "FEED", None, None, at_risk))
                if state.animal_needs_care(t):
                    out.append(Job(P_CARE, pos, "CARE", None))
                if state.animal_has_fert(t):
                    out.append(Job(P_COLLECT_FERT, pos, "COLLECT_FERTILIZER", None))

    # Build structures shed-outward -- but only to house animals we ALREADY own
    # (placed + carried + in the shed), never toward the season target. Building
    # toward the target front-loads the whole season's housing onto day 0:
    # measured, it erected 16 structures for 3 animals, ate the held-back tiles AND
    # the crop tiles, and left the farm with 8 planted tiles instead of 25.
    coops, pastures = _structure_counts(state)
    owned = _animal_counts(state)              # board + shed + carried
    placed = _on_board_counts(state)
    pending = {a: owned[a] - placed[a] for a in owned}
    free_coops = coops - placed["GOOSE"]
    free_pastures = pastures - placed["COW"] - placed["SHEEP"]
    need_coops = max(0, pending["GOOSE"] - free_coops)
    need_pastures = max(0, pending["COW"] + pending["SHEEP"] - free_pastures)
    empties = _shed_order_empties(state)
    for _ in range(min(need_coops, len(empties), params.BUILD_PER_TURN)):
        out.append(Job(P_BUILD, empties.pop(0), "BUILD_COOP", None))
    for _ in range(min(need_pastures, len(empties), params.BUILD_PER_TURN)):
        out.append(Job(P_BUILD, empties.pop(0), "BUILD_PASTURE", None))

    # place jobs: empty structures where a carried animal can be placed
    for y in range(params.BOARD):
        for x in range(params.BOARD):
            pos = (x, y)
            t = state.structure_at(pos)
            if t is None or "animal" in t:
                continue
            if t["kind"] == "COOP":
                out.append(Job(P_PLACE, pos, "PLACE", "GOOSE"))
            else:
                out.append(Job(P_PLACE, pos, "PLACE", "COW"))
                out.append(Job(P_PLACE, pos, "PLACE", "SHEEP"))

    # pickup jobs: animals sitting in the shed (place them), wheat (feed it)
    for a in ("GOOSE", "COW", "SHEEP"):
        if int(state.shed.get(a, 0)) <= 0:
            continue
        # No free structure of the right kind -> the only possible end of this carry is
        # a DROP back into the shed. MEASURED (tools/labour/unit_trace.py): emitting it
        # anyway produced an endless PICKUP COW / DROP COW loop that consumed 2 of 5
        # units for all of d0 and starved BUILD of the crew that would have freed them.
        free = free_coops if a == "GOOSE" else free_pastures
        if free <= 0:
            continue
        out.append(Job(P_PICKUP_ANIMAL, params.SHED_ACCESS[0], "PICKUP", a, 1))
        break
    wheat = int(state.shed.get("WHEAT", 0))
    unfed = _unfed_count(state)
    if active and unfed > 0 and wheat > 0:
        # one feeder per ~WHEAT_PICKUP_QTY animals, spread across the shed-access
        # tiles, so the feed chain scales with the herd instead of starving it.
        pick_qty = int(params.at("WHEAT_PICKUP_QTY", state.day))
        n_pickups = max(1, (unfed + pick_qty - 1) // pick_qty)
        for k in range(n_pickups):
            qty = min(pick_qty, max(1, unfed - k * pick_qty), wheat)
            if qty <= 0:
                break
            out.append(Job(P_PICKUP_WHEAT, params.SHED_ACCESS[k % 4], "PICKUP", "WHEAT", qty))

    return out
