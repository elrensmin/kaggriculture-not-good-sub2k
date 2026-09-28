"""Immutable per-turn state snapshot + derived fields.

The single source of truth every policy layer reads. Rebuilt fresh each turn:
``action(t) = f(state(t))`` only, no cross-turn positional memory, so a movement
bug is a local fix, never a corrupted trajectory.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import params

# Unfertilized peak yield of one-shot crops (watering alone): harvest as soon as
# this is reached so decay never eats the yield.
_ONE_SHOT_PEAK = {"WHEAT": 4, "CARROT": 3, "MELON": 6}


class State:
    __slots__ = (
        "player", "step", "day", "hour", "farm", "rival", "private", "market",
        "town", "money", "tiles", "shed", "seeds", "inventories", "farmer_pos",
        "hand_positions", "positions", "unlocked", "hires_today", "shops",
        "prices", "inventory",
    )

    def __init__(self, obs):
        self.player = int(obs["player"])
        self.day = int(obs.get("day", 0))
        self.hour = int(obs.get("hour", 0))
        self.step = self.day * 24 + self.hour
        self.farm = obs["farms"][self.player]
        self.rival = obs["farms"][1 - self.player]
        self.private = obs["private"]
        self.market = obs["market"]
        self.town = obs["town"]
        self.money = self.farm["money"]
        self.tiles = self.farm["tiles"]
        self.shed = self.private["shed"]
        self.seeds = self.private["seeds"]
        self.inventories = self.private["inventories"]
        self.farmer_pos = tuple(self.farm["farmer"])
        self.hand_positions = [tuple(p) for p in self.farm["hands"]]
        self.positions = [self.farmer_pos] + self.hand_positions
        self.unlocked = list(self.farm["unlocked_quadrants"])
        self.hires_today = int(self.farm["hires_today"])
        self.shops = list(self.town["unlocked_shops"])
        self.prices = self.market["prices"]
        self.inventory = self.market["inventory"]

    # ---- raw tile access ------------------------------------------------------
    def at(self, pos):
        return self.tiles[pos[1]][pos[0]]

    def owned(self, pos) -> bool:
        return self.at(pos) != "LOCKED"

    # ---- unit access ----------------------------------------------------------
    def unit_count(self) -> int:
        return 1 + len(self.hand_positions)

    def unit_inv(self, i):
        return self.inventories[i] if i < len(self.inventories) else {}

    # ---- shed / seeds ---------------------------------------------------------
    def shed_total(self) -> int:
        return sum(v for v in self.shed.values() if v > 0)

    # ---- tile predicates ------------------------------------------------------
    def plant_at(self, pos):
        t = self.at(pos)
        return t if isinstance(t, dict) and t.get("kind") == "PLANT" else None

    def animal_at(self, pos):
        t = self.at(pos)
        return t if isinstance(t, dict) and "animal" in t else None

    def structure_at(self, pos):
        t = self.at(pos)
        if isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE"):
            return t
        return None

    # ---- animal helpers ------------------------------------------------------
    def herd_count(self) -> int:
        """Animals standing on our farm, any species."""
        return sum(1 for row in self.tiles for t in row
                   if isinstance(t, dict) and "animal" in t)

    def animal_ready(self, a) -> bool:
        return a.get("yield_units", 0) > 0

    def animal_needs_feed(self, a) -> bool:
        return not a.get("fed_today", False)

    def animal_needs_care(self, a) -> bool:
        return not a.get("cared_today", False)

    def animal_has_fert(self, a) -> bool:
        return bool(a.get("fertilizer_available", False))

    def is_empty_owned(self, pos) -> bool:
        return self.owned(pos) and self.at(pos) is None

    def is_weed(self, pos) -> bool:
        t = self.at(pos)
        return isinstance(t, dict) and t.get("kind") == "WEED"

    # ---- crop helpers ---------------------------------------------------------
    def crop_age(self, plant_tile) -> int:
        return self.day - plant_tile["planted_day"]

    def water_window(self, plant_tile):
        """(start, end) inclusive ages where watering adds yield, or None for ongoing."""
        cd = CROPS[plant_tile["crop"]]
        if cd["ongoing"]:
            return None
        start = (cd["max_yield_day"] + 1) // 2
        return (start, cd["max_yield_day"])

    def in_water_window(self, plant_tile) -> bool:
        w = self.water_window(plant_tile)
        if w is None:
            return False
        return w[0] <= self.crop_age(plant_tile) <= w[1]

    def fert_window_open(self, plant_tile) -> bool:
        """Whether fertilizing now can still pay for this tile.

        Ongoing crops: any day (the engine doubles the fruit on a watered production
        day). One-shot crops: inside the bonus window, and -- when
        ``params.FERTILIZE_PRE_WINDOW`` -- also on the day BEFORE it opens, because
        fertilize lasts ``day..day+2`` and ``WATER_BONUS`` outranks ``FERTILIZE``, so a
        fertilize landing after the window's first water only pays +2 from the second day.
        ``FERTILIZE_PRE_WINDOW`` is SHIPPED OFF: it measured negative (the crew does not
        reliably reach the pre-window tile, so the application lands late anyway).
        """
        cd = CROPS[plant_tile["crop"]]
        if cd.get("ongoing"):
            return True
        w = self.water_window(plant_tile)
        if w is None:
            return False
        age = self.crop_age(plant_tile)
        if not params.at("FERTILIZE_PRE_WINDOW", self.day):
            return w[0] <= age <= w[1]
        return (w[0] - 1) <= age <= w[1]

    def plant_ready(self, plant_tile) -> bool:
        """Harvestable now: one-shot at its unfertilized peak (before decay starts),
        ongoing when full."""
        cd = CROPS[plant_tile["crop"]]
        y = plant_tile.get("yield_units", 0)
        if y <= 0:
            return False
        if cd["ongoing"]:
            if params.at("ONGOING_HARVEST_ANY", self.day):
                return True
            if params.at("ONGOING_HARVEST_MIN", self.day) > 0:
                return y >= params.at("ONGOING_HARVEST_MIN", self.day)
            return y >= cd["max_yield"]
        # Early one-shot harvest age (see params.HARVEST_AGE_*). GUARDED ON
        # `watered_today`: the early day is only "ready" once that day's window water has
        # actually landed, otherwise the HARVEST job fires first and the tile turns over on
        # a SINGLE window water (MEASURED: water/cycle 1.93 -> 1.00 and wheat yield
        # 4.03 -> 2.53 when the guard was missing). Before the water lands, only the WATER
        # jobs exist and the bonus is banked, then this returns true later the same day.
        # READ THROUGH `at()`, not the bare attribute. These were read directly, so the
        # phase-scoped `_P2`/`_P3` overrides were DEAD: an arm setting
        # `HARVEST_AGE_WHEAT_P2=3` resolved to 3 at the params level and was then ignored
        # here, and the arm measured byte-identical. Same defect class as the missing `_P2`
        # declaration -- a knob is only live if BOTH the name exists AND the reader uses it.
        early = {"WHEAT": params.at("HARVEST_AGE_WHEAT", self.day),
                 "MELON": params.at("HARVEST_AGE_MELON", self.day)}.get(
                     plant_tile["crop"], 0)
        if (early and self.crop_age(plant_tile) >= early
                and plant_tile.get("watered_today")):
            return True
        if params.ONESHOT_HARVEST_AT_PEAK:
            # peak day is the day before `_decay_plants` starts eating the yield
            return y > 0 and self.crop_age(plant_tile) >= cd["max_yield_day"]
        return y >= _ONE_SHOT_PEAK[plant_tile["crop"]] or \
            self.crop_age(plant_tile) > cd["max_yield_day"]

    def needs_water(self, plant_tile) -> bool:
        if plant_tile["watered_today"]:
            return False
        return True

    def ongoing_produces_today(self, plant_tile) -> bool:
        """Whether today is a scheduled production day for an ongoing crop
        (mirrors the engine's _daily_refresh_plants). Watering + fertilizing on
        these days doubles the fruit."""
        cd = CROPS[plant_tile["crop"]]
        if not cd["ongoing"]:
            return False
        dsf = (self.day + 1) - plant_tile["planted_day"] - cd["first_yield_day"]
        if dsf < 0 or dsf % cd["interval"] != 0:
            return False
        return (dsf // cd["interval"] + 1) <= cd["max_yield"]

    # ---- town / market --------------------------------------------------------
    def has_yarn(self) -> bool:
        return any("YARN" in s for s in self.shops)

    def has_milk_shop(self) -> bool:
        return any(s in self.shops for s in ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP"))
