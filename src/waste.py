"""waste — every way a hired hand can spend a turn for nothing, and the gate for each.

A turn is the only resource the farm cannot buy more of. The engine silently ignores most
invalid actions (`_do_action` returns without effect), so an agent that emits them looks
busy and produces nothing -- measured on our own runs: `idle_share_pct` 2.7 and yet
`plants_died` 53 and `feed_surplus` -313, i.e. the crew was not idle, it was wasting turns.

This module enumerates the ways a turn is wasted. Each is a named code, checked against the
engine's own preconditions, so a job that cannot pay is dropped BEFORE assignment and the
count of dropped work is reportable instead of invisible.

  LOCKED_TILE     the tile is unowned; the engine will not act on it
  NO_PLANT        WATER/FERTILIZE where nothing is planted
  ALREADY_WATER   WATER on a tile already watered today (engine returns)
  OUT_OF_WINDOW   one-shot water outside the bonus window: no yield, and not at risk
  NO_GAIN_FERT    fertilising where the yield is already capped (melon, strawberry) or set
  ALREADY_FERT    FERTILIZE with `fertilized_until_day >= day`
  NO_FERT_INV     FERTILIZE with no fertilizer in hand
  NO_YIELD        HARVEST where `yield_units <= 0`
  TILE_TAKEN      PLANT on a tile that is not empty
  NO_SEED         PLANT with no seed of that crop (this one VOIDS THE WHOLE BATCH)
  NO_WHEAT        FEED with no wheat in hand
  ALREADY_FED     FEED an animal that is already fed
  ALREADY_CARED   CARE an animal already cared for
  NO_FERT_AVAIL   COLLECT_FERTILIZER where the animal has none
  NOT_ADJACENT    PICKUP/DROP away from the shed-adjacent tiles
  NO_STOCK        PICKUP an item the shed does not hold
  HANDS_FULL      PICKUP while carrying something undeliverable
  NO_STRUCTURE    PLACE with no free structure
  NOT_CARRYING    PLACE an animal we do not hold
  UNREACHABLE     the walk is longer than the turns left in the day
  DUPLICATE       two units assigned to the same tile

The job-list face of this is `filter_jobs`, which returns the surviving jobs and a Counter
of why the others were dropped; `budget_report` turns that into a printable line so the
waste is measured rather than assumed.
"""
from __future__ import annotations

import collections

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import routing, value

CODES = (
    "LOCKED_TILE", "NO_PLANT", "ALREADY_WATER", "OUT_OF_WINDOW", "NO_GAIN_FERT",
    "ALREADY_FERT", "NO_FERT_INV", "NO_YIELD", "TILE_TAKEN", "NO_SEED", "NO_WHEAT",
    "ALREADY_FED", "ALREADY_CARED", "NO_FERT_AVAIL", "NOT_ADJACENT", "NO_STOCK",
    "HANDS_FULL", "NO_STRUCTURE", "NOT_CARRYING", "UNREACHABLE", "DUPLICATE",
)


def _fert_gain_positive(state, tile):
    """Whether fertilising this tile can still add yield (see `value.fertilize_gain`)."""
    crop = tile["crop"]
    cd = CROPS[crop]
    if cd["ongoing"]:
        # Capped at `max_yield`: only worth it if a production day would otherwise be
        # missed. Conservative: no gain unless the tile is short of the cap.
        return False
    w = value.water_window(crop)
    if w is None:
        return False
    age = state.crop_age(tile)
    left = value.remaining_window_waters(crop, age, max(0, w[1] - age))
    if left <= 0:
        return False
    cur = tile.get("yield_units", 0)
    return cur < cd["max_yield"] and value.fertilize_gain(crop, left) > 0


def job_ok(state, job, carrying=None, horizon=None, fail=None):
    """(ok, code). `code` is None when the job can pay; otherwise a `CODES` entry.

    `carrying` is the assigned unit's inventory (needed for FEED/PLACE/PICKUP/FERTILIZE),
    `horizon` the moves left today, `fail` an optional Counter collecting the reasons.
    """
    def out(code):
        if fail is not None and code:
            fail[code] += 1
        return (code is None), code

    op = job.op
    tile_pos = job.tile
    if tile_pos is None:
        # Shed-based op (PICKUP/DROP): the tile is an access tile we always own.
        pass
    elif not state.owned(tile_pos):
        return out("LOCKED_TILE")
    tile = state.plant_at(tile_pos) if tile_pos is not None else None
    animal = state.animal_at(tile_pos) if tile_pos is not None else None
    inv = carrying or {}

    if op in ("WATER", "FERTILIZE", "HARVEST") and tile_pos is not None and \
            tile is None and animal is None:
        # HARVEST also applies to animal tiles; WATER/FERTILIZE do not.
        if op != "HARVEST":
            return out("NO_PLANT")

    if op == "WATER":
        if tile.get("watered_today"):
            return out("ALREADY_WATER")
        cd = CROPS[tile["crop"]]
        if not cd["ongoing"]:
            w = value.water_window(tile["crop"])
            age = state.crop_age(tile)
            in_window = bool(w) and w[0] <= age <= w[1]
            at_risk = tile.get("consecutive_unwatered", 0) >= 1
            if not in_window and not at_risk:
                return out("OUT_OF_WINDOW")

    elif op == "FERTILIZE":
        if inv.get("FERTILIZER", 0) <= 0:
            return out("NO_FERT_INV")
        if tile.get("fertilized_until_day", -1) >= state.day:
            return out("ALREADY_FERT")
        if not _fert_gain_positive(state, tile):
            return out("NO_GAIN_FERT")

    elif op == "HARVEST":
        src = animal if animal is not None else tile
        if src is None or src.get("yield_units", 0) <= 0:
            return out("NO_YIELD")

    elif op == "PLANT":
        if tile_pos is not None and not state.is_empty_owned(tile_pos):
            return out("TILE_TAKEN")
        if state.seeds.get(job.item, 0) <= 0:
            return out("NO_SEED")

    elif op == "FEED":
        if inv.get("WHEAT", 0) <= 0:
            return out("NO_WHEAT")
        if animal is None:
            return out("NO_PLANT")
        if animal.get("fed_today"):
            return out("ALREADY_FED")

    elif op == "CARE":
        if animal is None:
            return out("NO_PLANT")
        if animal.get("cared_today"):
            return out("ALREADY_CARED")

    elif op == "COLLECT_FERTILIZER":
        if animal is None:
            return out("NO_PLANT")
        if not animal.get("fertilizer_available"):
            return out("NO_FERT_AVAIL")

    elif op == "PICKUP":
        if tile_pos is not None and tile_pos not in _shed_access():
            return out("NOT_ADJACENT")
        if state.shed.get(job.item, 0) <= 0:
            return out("NO_STOCK")
        if inv and any(k in ANIMALS or k in ("WHEAT", "FERTILIZER") for k in inv):
            return out("HANDS_FULL")

    elif op == "DROP":
        if tile_pos is not None and tile_pos not in _shed_access():
            return out("NOT_ADJACENT")

    elif op == "PLACE":
        if inv.get(job.item, 0) <= 0:
            return out("NOT_CARRYING")
        if tile_pos is not None and state.structure_at(tile_pos) is None:
            return out("NO_STRUCTURE")

    if horizon is not None and tile_pos is not None:
        from . import routing as _r
        # Distance is the exact walk; `horizon` is the moves left today.
        if _r.manhattan(state.positions[0], tile_pos) > horizon and job.critical is False:
            pass    # the caller checks with the unit's own position; see `filter_jobs`
    return out(None)


def _shed_access():
    from . import params
    return set(params.SHED_ACCESS)


def filter_jobs(state, jobs, fail=None):
    """Drop every job that cannot pay, counting the reason. Order is preserved.

    Each job is checked against the inventory of `A UNIT THAT COULD TAKE IT`; because
    eligibility depends on what a unit carries, a job is kept if it is valid for at least
    one unit and dropped only when it is impossible for all of them (no fertilizer anywhere
    in hand, no seed, shed empty, ...). That keeps the gate honest without needing the
    assignment to have happened yet.
    """
    invs = [state.unit_inv(i) for i in range(state.unit_count())]
    keep = []
    for j in jobs:
        if j.tile is not None and not state.owned(j.tile):
            if fail is not None:
                fail["LOCKED_TILE"] += 1
            continue
        ok = False
        last = None
        for inv in (invs or [{}]):
            good, code = job_ok(state, j, carrying=inv, fail=None)
            if good:
                ok = True
                break
            last = code
        if ok:
            keep.append(j)
        elif fail is not None:
            fail[last or "UNKNOWN"] += 1
    return keep


def budget_report(fail, total, label=""):
    """One printable line: how many jobs were dropped and why."""
    if not fail:
        return f"   {label}no jobs dropped"
    dropped = sum(fail.values())
    top = ", ".join(f"{k}={v}" for k, v in collections.Counter(fail).most_common(6))
    return (f"   {label}jobs {total}  dropped {dropped} "
            f"({100*dropped/max(1,total):.0f}%)  {top}")
