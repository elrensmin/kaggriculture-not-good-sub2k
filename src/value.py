"""value — dollars per tile, per animal, per op. The agent's price list.

Every function here is the engine's own arithmetic, not a heuristic: `src/demand.py` prices
the sale and this prices the production. Together they let the scheduler rank work by
dollars per unit-turn instead of by a hand-tuned priority constant.

The engine rules this encodes (read from `kaggriculture.py`, not assumed):

  PLANT      `_new_plant`: `yield_units = 0` for ongoing, else **1**;
             `consecutive_unwatered = 1` (planting day counts as unwatered, so a crop not
             watered ON the day it is planted becomes a WEED that night);
             `max_lifespan_step = (day + max_yield_day + 1) * 24` for one-shot.
  WATER      one-shot: only inside the bonus window `[(max_yield_day+1)//2, max_yield_day]`
             does it add yield, and it adds **2 if `fertilized_until_day >= day`, else 1**,
             capped at `max_yield`. Outside the window it only prevents death.
             ongoing: no per-water yield; production is credited at day end (below).
  FERTILIZE  `fertilized_until_day = max(existing, day + 2)` — active on day, day+1, day+2.
  ONGOING    `_daily_refresh_plants`: on a production day adds
             `2 if (watered_today and fertilized) else 1`, capped at `max_yield`.
  DECAY      one-shot from `max_lifespan_step` loses 1 unit every 2 steps; at <= 0 → WEED.

**THE EDGE THIS MAKES EXPLICIT: order matters.** `WATER` reads `fertilized_until_day >= day`,
so fertilising BEFORE watering turns a +1 water into +2. That is why the reference's visit
is FERTILIZE then WATER (measured: 65 of 67 of his fertilise events are followed by a WATER
on the same tile), and why our kernel -- which ranks WATER 120 above FERTILIZE 54 and waters
first -- collects the +1 and leaves the +1 on the table.

**AND A NEGATIVE RESULT: fertilising an ONGOING crop is capped at `max_yield`.** For
strawberry (4 production events, cap 4) it cannot raise the harvestable amount at all; its
only value is reaching the cap sooner, i.e. cycle time. The one-shot crops are where the
+1-per-water actually lands, and where the money is.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import demand, market
from .params import I0  # noqa: F401

STEPS_PER_DAY = 24


# --------------------------------------------------------------------------- crops
def water_window(crop):
    """(start, end) inclusive ages where one-shot watering adds yield, or None."""
    cd = CROPS[crop]
    if cd["ongoing"]:
        return None
    return ((cd["max_yield_day"] + 1) // 2, cd["max_yield_day"])


def order_matters_for(crop):
    """True when FERTILIZE-before-WATER buys an extra unit on this crop."""
    cd = CROPS[crop]
    return not cd["ongoing"]


def one_shot_yield(crop, waters_in_window, fertilized_waters):
    """Yield one unit of `crop` reaches after `waters_in_window` waters.

    `fertilized_waters` of them land while `fertilized_until_day >= day`. The plant starts
    at 1 (engine `_new_plant`), each water adds 2 or 1, and the total is capped at
    `max_yield` -- which is why the cap has to be applied as the engine does it, not at the
    end, or we would over-value late fertiliser.
    """
    cd = CROPS[crop]
    y = 1
    for k in range(int(waters_in_window)):
        bonus = 2 if k < int(fertilized_waters) else 1
        y = min(cd["max_yield"], y + bonus)
    return y


def max_one_shot_yield(crop):
    """Best possible yield: every window water fertilised."""
    w = water_window(crop)
    if w is None:
        return 0
    return one_shot_yield(crop, w[1] - w[0] + 1, w[1] - w[0] + 1)


def unfertilized_one_shot_yield(crop):
    w = water_window(crop)
    if w is None:
        return 0
    return one_shot_yield(crop, w[1] - w[0] + 1, 0)


def ongoing_production_days(crop, planted_day, through_day):
    """Days on which an ongoing crop is credited production."""
    cd = CROPS[crop]
    out = []
    for d in range(planted_day, through_day + 1):
        dsf = (d + 1) - planted_day - cd["first_yield_day"]
        if dsf < 0 or dsf % cd["interval"] != 0:
            continue
        if (dsf // cd["interval"] + 1) <= cd["max_yield"]:
            out.append(d)
    return out


def ongoing_yield(crop, planted_day, through_day, watered_days=(), fertilized_days=()):
    """Accumulated yield of an ongoing crop, exactly as `_daily_refresh_plants` credits it."""
    cd = CROPS[crop]
    w = set(watered_days)
    f = set(fertilized_days)
    y = 0
    for d in ongoing_production_days(crop, planted_day, through_day):
        plus = 2 if (d in w and d in f) else 1
        y = min(cd["max_yield"], y + plus)
    return y


def fertilize_gain(crop, remaining_waters, ongoing_events=0):
    """Extra units from fertilising now, for the rest of this tile's life.

    One-shot: `remaining_waters` window waters become +2 each instead of +1, capped.
    Ongoing: capped at `max_yield`, so this is usually **zero** and the value is cycle time.
    """
    cd = CROPS[crop]
    if cd["ongoing"]:
        w = min(ongoing_events, cd["max_yield"])
        return min(cd["max_yield"], w * 2) - min(cd["max_yield"], w * 1)
    return one_shot_yield(crop, remaining_waters, remaining_waters) - \
        one_shot_yield(crop, remaining_waters, 0)


def remaining_window_waters(crop, age, horizon_days):
    """Window-water events still available to this tile within the horizon."""
    w = water_window(crop)
    if w is None:
        return 0
    return max(0, min(w[1], age + horizon_days) - max(w[0], age) + 1)


def crop_margin(crop, price, waters, fertilized_waters, seed_cost=None):
    """Dollars from one tile: yield x price - seed."""
    y = one_shot_yield(crop, waters, fertilized_waters) \
        if not CROPS[crop]["ongoing"] else 0
    seed = CROPS[crop]["seed"] if seed_cost is None else seed_cost
    return y * price - seed, y


# ----------------------------------------------------------------- the tile itself
def cycle_days(crop):
    """Days one tile spends on a `crop` cycle, planting to harvestable."""
    cd = CROPS[crop]
    if cd["ongoing"]:
        return cd["first_yield_day"] + cd["interval"] * max(1, cd["max_yield"] - 1)
    return cd["max_yield_day"] + 1


def cycle_revenue(crop):
    """Units a full cycle yields, and the seed it costs."""
    cd = CROPS[crop]
    if cd["ongoing"]:
        return cd["max_yield"], cd["seed"]
    return unfertilized_one_shot_yield(crop), cd["seed"]


def tile_dollars_per_day(prices, day=None):
    """Best dollars per tile-day available to the farm right now.

    A tile is not worth the yield standing on it -- it is worth the best crop cycle it can
    still run. This is the term the crew was missing: pricing a dying wheat tile at its
    ~$25 of standing yield made watering lose to a $1,500 melon harvest, so the wheat died
    while the priority constants (WATER_SURVIVAL 90) would have saved it.

    `day` gates the crop by its PLANTING WINDOW (`params.CROP_PLAN`). Without it melon --
    closed after d2 but worth $109/tile-day -- dominates every late tile and inflates the
    option value to $2,075 at d10, which is nonsense.
    """
    from . import params
    best = 0.0
    for crop in CROPS:
        if day is not None:
            plan = params.CROP_PLAN.get(crop)
            if plan and not (plan["start"] <= day <= plan["end"]):
                continue
        cyc = cycle_days(crop)
        if cyc <= 0:
            continue
        units, seed = cycle_revenue(crop)
        margin = units * prices.get(crop, 0.0) - seed
        if margin <= 0:
            continue
        best = max(best, margin / cyc)
    return best


def tile_option_value(days_left, prices, day=None):
    """What a still-usable tile is worth for the rest of the season.

    Losing a tile to a weed forfeits every cycle it could have run, so this is the number a
    survival WATER or a DIG has to be judged against -- not the standing yield.
    """
    if days_left <= 0:
        return 0.0
    return max(0.0, tile_dollars_per_day(prices, day) * days_left)


# --------------------------------------------------------------------------- animals
def animal_output_per_day(species):
    """Units per production day for one animal (milk 2d, wool 3d, egg 1d)."""
    a = ANIMALS[species]
    return 1.0 / max(1, a["interval"])


def animal_value(species, day, price_units, price_fert, days_left, wheat_cost,
                 care_capture=1.0):
    """NPV of buying one animal today, in dollars.

    Output is `1/interval` units per day, doubled by the care bonus to the extent
    `care_capture` is achieved (the engine pays the banked bonus only on a FED production
    day). Feed is 1 wheat/day. Fertilizer is counted at its SALE price but is worth more as
    a crop input, so callers should pass the larger of the two.
    """
    a = ANIMALS[species]
    out = animal_output_per_day(species) * days_left * (1.0 + 0.0 * care_capture)
    revenue = out * price_units
    fert = 1.0 * days_left * price_fert
    feed = 1.0 * days_left * wheat_cost
    return revenue + fert - feed - a["cost"]


# --------------------------------------------------------------------------- ops
# Ops that produce something sellable, and the item they produce.
def op_turns(walk_tiles, extra=0):
    """Expected unit-turns an op costs: the walk plus the act itself."""
    return max(1, int(walk_tiles) + 1 + int(extra))


def op_value(kind, unit_value, units=1, extra=0.0):
    """Dollars an op is expected to add."""
    if kind == "yield":
        return unit_value * units + extra
    if kind == "cost":
        return extra
    return extra


def dollars_per_turn(value, turns):
    return value / max(1e-9, turns)


def sell_value(item, inventory, qty, floor=None):
    """Dollars from selling `qty` of `item` right now, honouring a price floor."""
    return demand.revenue_for(item, inventory, qty, floor=floor)


def hold_or_sell(item, inventory, qty, shops, steps_left, opp_rate=0.0, floor=1):
    """Units to sell now vs hold, from `demand.best_sell_now`."""
    return demand.best_sell_now(item, inventory, qty, shops, steps_left, floor, opp_rate)
