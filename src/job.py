"""Job: a unit of work the scheduler assigns to a worker."""
from __future__ import annotations

from collections import namedtuple

from . import params

# priority: higher runs first. tile: (x, y) the unit must stand on, or None for a
# shed-based op (PICKUP/DROP). op: the unit op token. item: crop/product/animal.
# qty: optional third op argument (e.g. PICKUP wheat 5).
# critical: the op prevents an *irreversible* loss (tonight's weed / tonight's
# escape). The assignment kernel lets a critical job beat any walk cost, so a
# local low-value job can never starve a tile that is about to die.
Job = namedtuple("Job", "priority tile op item qty critical", defaults=(None, False))


# Priority bands (edit in one place). Planting ranks ABOVE bonus-watering because
# a new wheat tile (~$90) outweighs one +1-yield water (~$25); survival watering
# still beats both (a dead plant yields nothing).
# EVERY band now reads `params` -- the comment above claimed "edit in one place" while
# seven of them (P_HARVEST, P_PICKUP_WHEAT, P_PICKUP, P_PLANT, P_PICKUP_ANIMAL, P_PLACE,
# P_DIG) were bare constants here, so an A/B of any of them silently measured nothing.
# P_WATER_BONUS was the same defect and cost a full round of phantom screens.
P_HARVEST = params.P_HARVEST
P_PICKUP_WHEAT = params.P_PICKUP_WHEAT  # feed-critical: pickup->feed before harvesting
P_FEED = params.P_FEED          # feeding ties harvesting (an escaped animal is a total loss)
P_WATER_SURVIVAL = params.P_WATER_SURVIVAL
P_PICKUP = params.P_PICKUP      # generic pickup (fertilizer)
P_PLANT = params.P_PLANT
P_CARE = params.P_CARE
P_PICKUP_ANIMAL = params.P_PICKUP_ANIMAL  # placing animals is not urgent
P_PLACE = params.P_PLACE
P_COLLECT_FERT = params.P_COLLECT_FERT
P_FERTILIZE = params.P_FERTILIZE
# Window watering ("bonus" water: the +1/+2 yield watering at ages 2-4 for wheat,
# 6-12 for melon). This was a bare constant (50) until it was moved into params --
# an A/B of `P_WATER_BONUS` therefore silently measured nothing. It is the op the
# WATER-coverage root is short of: survival water (90) fires only when the plant is
# about to die, so a wheat tile watered only by survival yields 1-2 units instead of
# 4-6 and the opening buys its feed (see docs/DSM-vs-us(v0).md §2).
P_WATER_PRODUCE = params.P_WATER_PRODUCE  # water an ONGOING crop on a production day
P_WATER_BONUS = params.P_WATER_BONUS
P_BUILD = params.P_BUILD
P_DIG = params.P_DIG

# ---------------------------------------------------------------------------
# PHASE-SCOPED PRIORITY BANDS. The scheduler calls `phase_band` for every job before
# sorting, so a band can be re-tuned for the midgame (`params.P_*_P2`) without moving
# the opening. The op -> band mapping lives HERE, next to the bands themselves, so a
# new job constructor only has to be added once.
# ---------------------------------------------------------------------------
_ANIMAL_ITEMS = ("COW", "SHEEP", "GOOSE")
_BUILD_OPS = ("BUILD_COOP", "BUILD_PASTURE")
_BY_OP = {
    "HARVEST": "P_HARVEST", "FEED": "P_FEED", "PLANT": "P_PLANT", "CARE": "P_CARE",
    "PLACE": "P_PLACE", "COLLECT_FERTILIZER": "P_COLLECT_FERT",
    "FERTILIZE": "P_FERTILIZE", "DIG": "P_DIG",
}


def band_name(j):
    """Which priority band a job was constructed with, or None if it has no band.

    WARNING -- THIS FUNCTION NORMALISES AWAY OUT-OF-BAND PRIORITIES IN PHASE 2.
    `scheduler.plan` remaps every job's priority through `phase_band` for day >= 6, and
    `phase_band` asks THIS function which band the job belongs to. A job built with a
    priority that does not match its own (op, critical) signature is therefore silently
    rewritten back to the declared band and the change is a no-op. MEASURED 2026-09-28:
    constructing a *critical* `WATER` at `P_WATER_BONUS` produced a **byte-identical** arm,
    because `band_name` said `P_WATER_SURVIVAL` and the remap restored it. If a phase-2
    change needs an out-of-band priority, either teach this function the new signature or
    emit a SECOND, non-critical job on the same tile (`crop_plan.jobs` does the latter for
    `WATER_WINDOW_PRIORITY`).
    """
    if j.op == "WATER":
        return "P_WATER_SURVIVAL" if j.critical else "P_WATER_BONUS"
    if j.op == "PICKUP":
        if j.item in _ANIMAL_ITEMS:
            return "P_PICKUP_ANIMAL"
        if j.item == "WHEAT":
            return "P_PICKUP_WHEAT"
        return "P_PICKUP"
    if j.op in _BUILD_OPS:
        return "P_BUILD"
    return _BY_OP.get(j.op)


def phase_band(j, day):
    """The phase-scoped band for this job.

    Returns the base band unchanged when no `_P2`/`_P3` override is set, so phase 1 and
    the season default are bit-identical until someone asks otherwise.
    """
    name = band_name(j)
    return None if name is None else params.at(name, day)
