"""Crop calendar + field jobs. Structural layer: which crops, where, when.

R2 scope: wheat/melon loop. R3 widens this into the full overlapped calendar
(melon -> strawberry -> tomato -> carrot, wheat continuous) with labour slicing.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS

from . import endgame, herd_plan, params
from .job import (
    P_DIG, P_FERTILIZE, P_HARVEST, P_PICKUP, P_WATER_BONUS, P_WATER_SURVIVAL, Job,
)


def _crop_count(state, crop: str) -> int:
    return sum(
        1
        for row in state.tiles
        for t in row
        if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop") == crop
    )


def _opening_target(state, crop):
    """The opening script's standing-tile target for `crop` today, or None.

    ``None`` means "the script does not cover today" and the caller keeps the ramp.
    A crop the script covers but does not list has target 0 -- the #1 plants nothing
    else in the opening, and a ramp that keeps sowing it is how we ended up with 9
    standing WHEAT tiles at d5 where he has 0.
    """
    if not params.OPENING_SCRIPT:
        return None
    table = params.OPENING_STANDING.get(state.day)
    if table is None:
        return None
    return int(table.get(crop, 0))


def plant_queue(state):
    """Interleaved planting queue weighted by each crop's *ramped* deficit.

    The deficit is measured against a scheduled standing count, not the final
    target, so a crop is sown steadily across its window instead of stacked into
    one day (see ``params.CROP_PLAN``). A crop whose seed can no longer pay back
    (window closing within 2 days) is front-loaded.

    During the opening (``params.OPENING_STANDING``) the schedule is the #1's
    *measured* standing count for the day rather than a ramp -- his d0-d5 is a fixed
    script, not a reaction (see the comment block in ``params.py``).

    ``PLANT_QUEUE_BY_NEED_FRACTION`` weights each crop by ``deficit / cap`` rather
    than by the raw deficit. Raw deficit lets one big-target crop monopolise the
    crew: at d10 WHEAT sits at 7 of its cap 29 (deficit 22) while STRAWBERRY sits at
    2 of its cap 18 (deficit 16), so a raw weighting hands ~58 % of the planters to
    wheat — and wheat is the *lowest* value per tile in the plan. Measured on the
    herd-on arm, strawberry was starved to 2 tiles at d10 against a cap of 18 while
    wheat ran 7. Fraction-of-need keeps the ramp as the plan and gives the tiles to
    whichever crop is furthest behind *relative to its own schedule*.
    """
    urgent = []
    rest = {}
    if endgame.retiring(state):
        return []
    for crop in params.CROP_PLAN:
        plan = params.CROP_PLAN[crop]
        if not (plan["start"] <= state.day <= plan["end"]):
            continue
        if state.seeds.get(crop, 0) <= 0:
            continue
        scripted = _opening_target(state, crop)
        if scripted is None:
            span = max(1, plan["peak"] - plan["start"] + 1)
            ramp = min(1.0, (state.day - plan["start"] + 1) / span) if params.PLANT_RAMP else 1.0
            cap = plan["target"] * ramp
            if crop == "WHEAT" and state.day <= params.WHEAT_OPENING_UNTIL_DAY:
                # the opening wheat burst: cheap feed for the herd before land arrives
                cap = max(cap, min(plan["target"], params.WHEAT_OPENING_TILES))
        else:
            cap = float(scripted)
        deficit = int(cap - _crop_count(state, crop))
        if deficit <= 0:
            continue
        if params.PLANT_QUEUE_BY_NEED_FRACTION:
            # slots proportional to how far behind the crop is against ITS OWN
            # schedule, floored at 1 so a nearly-satisfied crop still gets a look-in
            slots = max(1, int(round(params.PLANT_QUEUE_SCALE * deficit / max(1.0, cap))))
        else:
            slots = deficit
        # closing windows are urgent and front-loaded; everything else is
        # interleaved proportionally to need so the mix stays balanced.
        if plan["end"] - state.day <= 2:
            urgent.extend([crop] * slots)
        else:
            rest[crop] = slots

    queue = list(urgent)
    while rest:
        for crop in list(rest):
            queue.append(crop)
            rest[crop] -= 1
            if rest[crop] <= 0:
                del rest[crop]
    return queue


def jobs(state):
    """Harvest / water / dig field jobs (planting is handled by the scheduler)."""
    out = []
    retire = endgame.retiring(state)
    for y in range(params.BOARD):
        for x in range(params.BOARD):
            pos = (x, y)
            t = state.at(pos)
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                if state.plant_ready(t):
                    out.append(Job(P_HARVEST, pos, "HARVEST", t["crop"], None,
                               params.HARVEST_CRITICAL))
                    if (params.WATER_READY_FALLBACK
                            and t.get("consecutive_unwatered", 0) >= 1):
                        # Fallback so a missed harvest does not become a WEED. HARVEST
                        # outranks this, so it only fires when the harvest did not.
                        out.append(Job(P_WATER_SURVIVAL, pos, "WATER", t["crop"],
                                       None, True))
                elif state.needs_water(t):
                    if t.get("consecutive_unwatered", 0) >= 1:
                        # becomes a WEED tonight -> total loss, walk any distance
                        out.append(Job(P_WATER_SURVIVAL, pos, "WATER", t["crop"],
                                       None, True))
                    elif state.in_water_window(t):
                        out.append(Job(P_WATER_BONUS, pos, "WATER", t["crop"]))
                # fertilize: boosts one-shot in the water window, or doubles ongoing
                # fruit on a watered day. Eligibility (carrying FERTILIZER) is the
                # scheduler's job.
                if (not retire and state.day >= params.FERTILIZE_FROM_DAY
                        and (params.FERTILIZE_MIN_PRICE <= 0
                             or params.MARKET_PARAMS[t["crop"]]["base"] >= params.FERTILIZE_MIN_PRICE)
                        and t.get("fertilized_until_day", -1) < state.day
                        and (not params.FERTILIZE_ONGOING_ONLY
                             or CROPS[t["crop"]]["ongoing"])
                        and (not params.FERTILIZE_ONESHOT_ONLY
                             or not CROPS[t["crop"]]["ongoing"])
                        and (state.in_water_window(t) or CROPS[t["crop"]]["ongoing"])):
                    out.append(Job(P_FERTILIZE, pos, "FERTILIZE", None))
            elif state.is_weed(pos) and not retire:
                out.append(Job(P_DIG, pos, "DIG", None))

    # pickup fertilizer from the shed when there are plants worth fertilizing
    if not retire and int(state.shed.get("FERTILIZER", 0)) > 0 and _worth_fertilizing(state):
        out.append(Job(P_PICKUP, params.SHED_ACCESS[0], "PICKUP", "FERTILIZER", 6))
    return out


def fertilizer_buy_intent(state):
    """Buy fertilizer for the ongoing crops when the shed has run dry.

    Kept in `crop_plan` (the layer that owns fertilizing) and called from the scheduler's
    market list, so the gate and the pickup use the SAME `_worth_fertilizing`.
    """
    if not params.BUY_FERTILIZER:
        return []
    # STRICT: buy only for a tile that is ON A PRODUCTION DAY TODAY and unfertilised.
    # `_worth_fertilizing` is far too loose for this -- it is true whenever any ongoing
    # crop exists, which made the first version buy 1,583 units in 2 games and reduce
    # output everywhere by draining seed cash and turns.
    need = 0
    for row in state.tiles:
        for x in row:
            if not (isinstance(x, dict) and x.get("kind") == "PLANT"):
                continue
            if not CROPS[x["crop"]]["ongoing"]:
                continue
            if x.get("fertilized_until_day", -1) >= state.day:
                continue
            if state.ongoing_produces_today(x):
                need += 1
    if need <= 0:
        return []
    have = int(state.shed.get("FERTILIZER", 0))
    want = min(need, params.FERTILIZER_BUY_QTY) - have
    price = params.MARKET_PARAMS["FERTILIZER"]["base"]
    spendable = state.money - herd_plan.feed_reserve(state) - params.CASH_RESERVE
    n = min(want, int(spendable // max(1, price)))
    return [["BUY_PRODUCT", "FERTILIZER", n]] if n > 0 else []


def _worth_fertilizing(state):
    if state.day < params.FERTILIZE_FROM_DAY:
        return False
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                if params.FERTILIZE_ONGOING_ONLY and not CROPS[t["crop"]]["ongoing"]:
                    continue
                if params.FERTILIZE_ONESHOT_ONLY and CROPS[t["crop"]]["ongoing"]:
                    continue
                if t.get("fertilized_until_day", -1) < state.day and \
                        (state.in_water_window(t) or CROPS[t["crop"]]["ongoing"]):
                    return True
    return False


def _free_tiles(state):
    """Owned tiles with nothing on them: the only place a seed can go today."""
    return sum(
        1
        for y in range(params.BOARD)
        for x in range(params.BOARD)
        if state.is_empty_owned((x, y))
    )


def market_intents(state):
    """Buy seeds to keep a small in-hand buffer for every active calendar crop.

    The buffer is capped by the tiles we could actually plant right now, plus a
    small plant-now margin. Seed inventory is cash that cannot buy the next
    quadrant, and while the farm is tile-bound that cash buys nothing: measured on
    the baseline arm, ``empty`` owned tiles are **0 for the whole of d6-d10** (25
    tiles, all planted) yet we still bought $1,540 of seed over d4-d9. Holding that
    cash is what lets the next land purchase land on time -- the prerequisite the
    wheat curve depends on.
    """
    out = []
    # never spend the cash the herd needs for feed (see herd_plan.feed_reserve)
    spendable = state.money - herd_plan.feed_reserve(state)
    if params.SEED_BUFFER_BY_FREE:
        buffer = max(params.SEED_BUFFER_MIN, min(params.SEED_BUFFER, _free_tiles(state)))
    else:
        buffer = params.SEED_BUFFER
    if params.OPENING_SCRIPT and state.day in params.OPENING_STANDING:
        buffer = max(buffer, params.OPENING_SEED_BUFFER)
    for crop in params.PLANT_ORDER:
        plan = params.CROP_PLAN[crop]
        if not (plan["start"] <= state.day <= plan["end"]):
            continue
        in_hand = int(state.seeds.get(crop, 0))
        # During the opening the ask is the SCRIPT's need exactly. Taking the max
        # with the usual buffer was a real bug: at d2 the script wants 4 STRAWBERRY
        # ($400) but the buffer asked for 12 ($1,200), the all-or-nothing buy below
        # then bought nothing, and STRAWBERRY stayed at 0 until d5 -- the #1 has 10
        # tiles standing by d3.
        scripted = _opening_target(state, crop)
        if scripted is not None:
            want = scripted - _crop_count(state, crop) - in_hand
        else:
            want = buffer - in_hand
        if want <= 0:
            continue
        price = CROPS[crop]["seed"]
        # PARTIAL FILL. All-or-nothing was a real bug: it asked for the whole buffer
        # and bought nothing if the full cost was unaffordable. Strawberry seed is
        # $100, so a 6-seed top-up needs $600 and, with the herd's feed reserve held
        # back, it silently bought ZERO -- measured, STRAWBERRY tiles stayed at 0
        # through d5 while the ramp wanted 8. Gated because it was only ever measured
        # inside a net-negative package; SEE params.SEED_PARTIAL_FILL.
        if not params.SEED_PARTIAL_FILL:
            cost = price * want
            if spendable >= cost:
                out.append(["BUY_SEED", crop, want])
            continue
        n = min(want, int(spendable // price)) if price else want
        if n > 0:
            out.append(["BUY_SEED", crop, n])
    return out
