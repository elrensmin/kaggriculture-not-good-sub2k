"""risk — P7: the sign of the variance we want, read from the live margin.

The leaderboard pays WINS, and money is only the tie-break, so the quantity to maximise is
Pr[win] ~ Phi(mu / sigma). Adding variance INCREASES Pr[win] when we expect to finish behind
and DECREASES it when we are ahead -- the sign flips at `l + mu = 0`, where `l` is the live
margin (both banks are public, so `l` is observable every turn).

That is the fallback, and it needs no separate plan: when we fall behind the objective rotates
toward the high-ceiling, high-variance lines (melons, a bigger herd, bought feed), and when we
lead it rotates back to the steady engine. A fixed sign would be wrong half the time, which is
why this is a sign and not a constant.

`src/plan.py` allocates the turns; this scales the VALUE of the lines it allocates to.
"""
from __future__ import annotations

from . import priors

# How much variance-appetite moves a line's value at the extremes.
RISK_SLOPE = 0.5

# Which ops ride the high-variance lines: long-cycle, high-price, capital-intensive.
HIGH_VARIANCE_OPS = ("PLANT", "PLACE", "BUILD_PASTURE", "BUILD_COOP", "BUY_ANIMAL")
STEADY_OPS = ("WATER", "DIG", "CARE", "FEED", "HARVEST", "COLLECT_FERTILIZER")


def margin(state):
    """Live dollars ahead (+) or behind (-) the opponent -- both banks are public."""
    try:
        us = float(state.money)
        them = float(state.rival.get("money") or 0.0)
        return us - them
    except Exception:                                     # noqa: BLE001
        return 0.0


def behind(state):
    """True when we expect to finish behind: margin below his own target for the day."""
    try:
        tgt = priors.cash_target(int(state.day))
    except Exception:                                     # noqa: BLE001
        tgt = 0.0
    return margin(state) < -max(1.0, 0.25 * tgt)


def lam(state):
    """+1 behind (buy variance), -1 ahead (protect the lead), 0 when level."""
    return 1.0 if behind(state) else -1.0


def weight(state, op):
    """Multiplier for an op's value, from the sign of the variance we want."""
    if op in HIGH_VARIANCE_OPS:
        return 1.0 + RISK_SLOPE * lam(state)
    if op in STEADY_OPS:
        return 1.0 - RISK_SLOPE * lam(state) * 0.5
    return 1.0
