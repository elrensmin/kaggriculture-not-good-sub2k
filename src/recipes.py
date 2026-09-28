"""recipes — the engine's optimum for each crop, derived from the rules, not tuned.

The engine's per-crop arithmetic is fully known (`CROPS`, and `_do_action`'s WATER /
FERTILIZE / HARVEST branches). That means the best way to play one tile is a solved
sequence, not a policy to be searched: which days to water, whether to fertilise first, and
which day to harvest. This module derives that sequence per crop and exposes it as the
RECIPE the rest of the crew reads.

Why it matters, worked out from the engine rather than asserted:

  WHEAT  window ages 2-4, `max_yield` 6, plant starts at 1, each water adds 2 if the tile is
         fertilised that day else 1, capped at `max_yield`.
             age 2 unfert  2 units, 3-day cycle = 0.667 /tile-day
             age 3 unfert  3 units, 4-day cycle = 0.750
             age 3 FERT     5 units, 4-day cycle = **1.250**  <- the optimum
             age 4 FERT     6 units, 5-day cycle = 1.200
         So harvest at **age 3, fertilised**, not at age 4 for the bigger number: the extra
         unit costs a whole day of the tile. `HARVEST_AGE_WHEAT` ships 0 (off), which is why
         the crew waits to age 4 and then runs out of time -- measured, 78 of 179 deaths are
         wheat whose yield decayed to zero.
  CARROT window 2-3, optimum fertilised at age 2 -> 3 units, 1.000 /tile-day.
  MELON  window 6-12, optimum fertilised at age 8 -> 6 units, 0.667 /tile-day.

**ORDER MATTERS.** `WATER` reads `fertilized_until_day >= day`, so fertilising BEFORE watering
turns that day's +1 into +2. Every recipe therefore fertilises before its first water, and a
tile that is watered first has already lost a unit for that day.

FERTILIZER IS THE SCARCE INPUT, so the recipes must be STAGGERED: the herd makes ~1 unit per
animal per day, and `fert_urgency` ranks tiles by how much a fertilise would gain and how soon
the window closes, so the supply is spent on the tiles that lose most by waiting.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS

from . import value


def water_window(crop):
    return value.water_window(crop)


def _one_shot_recipe(crop):
    """The rate-optimal (harvest_age, waters, yield) for a one-shot crop, brute-forced.

    Brute force rather than algebra so the recipe is derived from `CROPS` and stays true if
    the spec changes: for every harvest age in the window, water on every window day up to
    it, with or without fertiliser, and take the best units per TILE-DAY.
    """
    cd = CROPS[crop]
    w = water_window(crop)
    best = None
    for age in range(w[0], cd["max_yield_day"] + 1):
        waters = tuple(range(w[0], age + 1))
        for fert in (True, False):
            y = 1
            for _a in waters:
                y = min(cd["max_yield"], y + (2 if fert else 1))
            cycle = age + 1                       # replant the day after harvest
            rate = y / cycle
            cand = {"harvest_age": age, "waters": waters, "fertilize": fert,
                    "yield": y, "cycle_days": cycle, "units_per_day": rate,
                    "seed": cd["seed"], "ongoing": False}
            if best is None or rate > best["units_per_day"]:
                best = cand
    return best


def _ongoing_recipe(crop):
    """An ongoing crop: water on production days AND any dry day, harvest at the cap."""
    cd = CROPS[crop]
    return {"harvest_age": None, "waters": (), "fertilize": True,
            "yield": cd["max_yield"], "cycle_days": None, "units_per_day": None,
            "seed": cd["seed"], "ongoing": True}


RECIPES = {c: (_ongoing_recipe(c) if cd["ongoing"] else _one_shot_recipe(c))
           for c, cd in CROPS.items()}


def recipe(crop):
    return RECIPES.get(crop)


def units_per_tile_day(crop):
    r = RECIPES.get(crop)
    return (r or {}).get("units_per_day") or 0.0


def best_crop_per_tile_day(prices, day=None):
    """(crop, rate) with the best recipe value per tile-day, honouring the planting window."""
    from . import params
    best, bestv = None, 0.0
    for crop in CROPS:
        if day is not None:
            plan = params.CROP_PLAN.get(crop)
            if plan and not (plan["start"] <= day <= plan["end"]):
                continue
        r = RECIPES[crop]
        if r["ongoing"]:
            # ongoing crops are harvested repeatedly, so rate to the FIRST harvest
            cyc = CROPS[crop]["first_yield_day"] + CROPS[crop]["interval"] * \
                max(1, CROPS[crop]["max_yield"] - 1)
            v = (r["yield"] * prices.get(crop, 0.0) - r["seed"]) / max(1, cyc)
        else:
            v = (r["yield"] * prices.get(crop, 0.0) - r["seed"]) / r["cycle_days"]
        if v > bestv:
            best, bestv = crop, v
    return best, bestv


def stake(state, tile, prices):
    """Dollars this tile realises if its recipe is completed from here."""
    crop = tile.get("crop")
    r = RECIPES.get(crop)
    if not r:
        return 0.0
    return max(0.0, r["yield"] * prices.get(crop, 0.0) - r["seed"])


def on_recipe_age(state, tile):
    """The day this tile should be harvested, or None for an ongoing crop."""
    r = RECIPES.get(tile.get("crop"))
    if not r or r["ongoing"]:
        return None
    return tile.get("planted_day", 0) + r["harvest_age"]


def harvest_now(state, tile):
    """True when harvesting TODAY is what the recipe asks for."""
    r = RECIPES.get(tile.get("crop"))
    if not r:
        return False
    if r["ongoing"]:
        return tile.get("yield_units", 0) >= CROPS[tile["crop"]]["max_yield"]
    target = on_recipe_age(state, tile)
    return target is not None and state.day >= target


def waters_remaining(state, tile):
    """Window waters still available inside the recipe, including today."""
    r = RECIPES.get(tile.get("crop"))
    if not r or r["ongoing"]:
        return 0
    age = state.day - tile.get("planted_day", 0)
    last = r["harvest_age"]
    return max(0, min(last, age + 0) - max(min(r["waters"]), age) + 1) \
        if age <= last else 0


def fert_urgency(state, tile):
    """How much this tile loses by NOT being fertilised now -- the stagger key.

    Fertiliser is ~1 unit per animal per day, so the supply has to be ordered. A tile loses a
    unit for every remaining window water it does not cover, and the loss is immediate: the
    next water today is +1 instead of +2. Tiles closest to the window closing go first.
    """
    crop = tile.get("crop")
    r = RECIPES.get(crop)
    if not r:
        return 0.0
    if tile.get("fertilized_until_day", -1) >= state.day:
        return 0.0
    left = waters_remaining(state, tile)
    if r["ongoing"]:
        return 1.0 if not tile.get("watered_today") else 0.0
    return float(max(0, left))


def next_step(state, tile):
    """What the recipe wants done on this tile next, or None.

    Order is the point: FERTILISE before watering, water every window day, harvest on the
    recipe age. Returning a single named step lets the crew value the RIGHT action instead
    of ranking whatever job happens to exist.
    """
    crop = tile.get("crop")
    r = RECIPES.get(crop)
    if not r:
        return None
    if harvest_now(state, tile) and tile.get("yield_units", 0) > 0:
        return "HARVEST"
    if not tile.get("watered_today"):
        if r["ongoing"]:
            return "WATER"
        age = state.day - tile.get("planted_day", 0)
        if age in r["waters"]:
            if recipe_fert_due(state, tile):
                return "FERTILIZE"
            return "WATER"
    return None


def recipe_fert_due(state, tile):
    """The recipe fertilises ONCE, before the first window water."""
    r = RECIPES.get(tile.get("crop"))
    if not r:
        return False
    if tile.get("fertilized_until_day", -1) >= state.day:
        return False
    if r["ongoing"]:
        return True
    age = state.day - tile.get("planted_day", 0)
    return age <= min(r["waters"])
