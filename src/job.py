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
P_HARVEST = 100
P_PICKUP_WHEAT = 101  # feed-critical: start the pickup->feed chain before harvesting
P_FEED = params.P_FEED          # feeding ties harvesting (an escaped animal is a total loss)
P_WATER_SURVIVAL = params.P_WATER_SURVIVAL
P_PICKUP = 88         # generic pickup (fertilizer)
P_PLANT = 85
P_CARE = params.P_CARE
P_PICKUP_ANIMAL = 60  # placing animals is not urgent
P_PLACE = 60
P_COLLECT_FERT = params.P_COLLECT_FERT
P_FERTILIZE = params.P_FERTILIZE
# Window watering ("bonus" water: the +1/+2 yield watering at ages 2-4 for wheat,
# 6-12 for melon). This was a bare constant (50) until it was moved into params --
# an A/B of `P_WATER_BONUS` therefore silently measured nothing. It is the op the
# WATER-coverage root is short of: survival water (90) fires only when the plant is
# about to die, so a wheat tile watered only by survival yields 1-2 units instead of
# 4-6 and the opening buys its feed (see docs/DSM-vs-us(v0).md §2).
P_WATER_BONUS = params.P_WATER_BONUS
P_BUILD = params.P_BUILD
P_DIG = 20
