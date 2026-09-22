"""Patch layer for the new agent candidate (CLEAN template).

The new agent is NOT a standalone replacement for main.py. It is the full
production agent from main.py with this patch layered *on top*: the harness
(diagnose.py) runs the production agent (``main._original_agent``) and then
hands the produced action to ``patch()``, which may alter it.

So `python diagnose.py --new` runs **everything in main.py + this patch**, and
the ``--new`` side of ``python diagnose.py --compare`` does the same, so every
improvement/regression is measured relative to the exact production behavior.

NOTE: the previous experiment (_ASTRA_I1 opening extension) was promoted into
``main.py`` as the production baseline (see the "NEW PATCH ... [BASELINE]"
block at the end of main.py). This file was reset for the next iteration.
Until a new patch is written, ``--new`` == ``--old`` == the promoted baseline.

Edit ``patch()`` for your experiment. Returning ``action`` unchanged is a no-op.

------------------------------------------------------------------------------
NEVER TRUST AVERAGES ACROSS GAMES.
This environment is dynamic: random-seeded games across the whole public
leaderboard, with live, moving prices. Averaging a score is NOT signal — it
regresses our score. The matchup (which public agent) and any single seed's
price action can inflate or crush any run, so optimizing for any mean just
chases noise and misdirection.

Always look for what actually costs money in EVERY game:
  * system-level / structural defects — scheduling, routing, stock/inventory,
    market entry-exit, crop/animal lifecycle handling that is wrong regardless
    of seed or opponent;
  * concrete per-game / per-day / per-step inefficiencies — idle steps, shed
    overflow, plants dying, missed harvests, unfed/unwatered animals,
    floor-price or below-base sales, escaped animals, suboptimal market timing.

Judge a patch on whether it removes a concrete inefficiency or fixes a systemic
defect you can point at in a specific game — never on whether some average went
up.
------------------------------------------------------------------------------
"""
from __future__ import annotations

import main as _main


def patch(action, observation, configuration=None):
    """Post-process the action produced by the full main.py agent.

    This is the experiment hook. Write your idea here. You may inspect
    ``observation`` (the full per-step state: farms, private, market prices,
    shops, unlocked quadrants, step/day/hour) and the ``action`` main.py just
    produced, then return a possibly-modified action dict.

    Returning ``action`` unchanged is a no-op.
    """
    if isinstance(observation, dict):
        step = int(observation.get('step', 0))
        _ = step  # placeholder for the next experiment
    return action


# Keep a plain `agent(observation, configuration)` entry point so main.py's own
# is_new_agent toggle (in case anyone flips it manually) resolves to the same
# behaviour: full main agent (already the promoted baseline), then this patch.
# diagnose.py uses patch() directly.
def agent(observation, configuration=None):
    base = getattr(_main, "_original_agent", None)
    if base is None:
        # Fallback when not running inside the harness: nothing to patch.
        return {"farmer": ["PASS"], "hands": [], "market": []}
    return patch(base(observation, configuration), observation, configuration)
