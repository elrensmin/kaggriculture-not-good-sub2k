"""Patch layer for the new agent candidate.

The new agent is NOT a standalone replacement for main.py. It is the full
production agent from main.py with this patch layered *on top*: the harness
(diagnose.py) runs the production agent (``main._original_agent``) and then
hands the produced action to ``patch()``, which may alter it.

So `python diagnose.py --new` runs **everything in main.py + this patch**, and
the ``--new`` side of ``python diagnose.py --compare`` does the same, so every
improvement/regression is measured relative to the exact production behavior.

Edit ``patch()`` for your experiment. Returning ``action`` unchanged is a no-op.
This is currently a clean baseline: ``patch()`` returns the action untouched, so
``--new`` is identical to ``--old`` until the next experiment is written here.

--------------------------------------------------------------------------------
NEVER TRUST AVERAGES ACROSS GAMES.
This environment is dynamic: random-seeded games across the whole public
leaderboard, with live, moving prices. Averaging a score is NOT signal --- it
regresses our score. Judge on concrete system-level defects you can point at
in a specific game / day / step, never on a mean.
--------------------------------------------------------------------------------
"""
from __future__ import annotations

import main as _main


def patch(action, observation, configuration=None):
    """Post-process the action produced by the full main.py agent.

    This is the experiment hook. Write your idea here. You may inspect
    ``observation`` (the full per-step state: farms, private, market prices,
    shops, unlocked quadrants, step/day/hour) and the ``action`` main.py just
    produced, then return a possibly-modified action dict.

    Returning ``action`` unchanged is a no-op (the current clean baseline).
    """
    return action


# Keep a plain `agent(observation, configuration)` entry point so main.py's own
# is_new_agent toggle (in case anyone flips it manually) resolves to the same
# behaviour: full main agent, then this patch. diagnose.py uses patch() directly.
def agent(observation, configuration=None):
    base = getattr(_main, "_original_agent", None)
    if base is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    return patch(base(observation, configuration), observation, configuration)
