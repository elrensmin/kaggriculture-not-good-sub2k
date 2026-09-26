"""Endgame retirement (d26-29). Execution layer (R6).

DSM rule #4: "Cut production at the end instead of selling at the end."

Measured on his replays, water ops fall 63 -> 24 (not -> 0) across days 26-29
while feed/care/fertilize fall 21 -> 1 and weeds climb 0 -> 10. So his endgame
has TWO separate parts, and they are not interchangeable:

  * **Stop investing**: no new PLANT, no FERTILIZE, no DIG of the abandoned
    ground. Weeds appearing on retired tiles is the plan, not neglect.
  * **Release the herd**: feed stops on day 28 so ~10 animals/game escape. That
    is the disposal mechanism for stock whose output the market can no longer
    absorb, and it frees the hands.
  * **Keep watering** the crops that are still in the ground and will still be
    harvested. Watering is what *delivers* the late-season revenue.

The last point was measured the hard way. A blanket "switch watering off at day
26" retirement was run on this agent and is unambiguously bad (16 paired games,
every seed down, days 26-29 go 0% -> 56/67/96/96% idle, watering 37 -> 0, and the
late harvest -- which is where most of this farm's revenue lands -- disappears
with it). The crops-only farm is *late*: its melon/strawberry/carrot liquidation
happens in exactly the days a blanket retirement switches off. So ``RETIRE_DAY``
gates only the *investment* ops, and watering is never gated.
"""
from __future__ import annotations

from . import params


def retiring(state) -> bool:
    """True once we stop *investing* (plant / fertilize / dig). Watering and
    harvesting continue to the bell."""
    return state.day >= params.RETIRE_DAY


def herd_retiring(state) -> bool:
    """True once the herd is released: feed and care stop, so animals escape."""
    return state.day >= params.HERD_RETIRE_DAY


def jobs(state):
    # Retirement is expressed in the policy layers (crop_plan/herd_plan consult
    # ``retiring``/``herd_retiring``), so there is no separate job stream here.
    return []


def market_intents(state):
    return []
