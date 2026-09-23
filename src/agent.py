"""Patch layer for the new agent candidate.

The new agent is NOT a standalone replacement for main.py. It is the full
production agent from main.py with this patch layered *on top*: the harness
(diagnose.py) runs the production agent (``main._original_agent``) and then
hands the produced action to ``patch()``, which may alter it.

So `python diagnose.py --new` runs **everything in main.py + this patch**, and
the ``--new`` side of ``python diagnose.py --compare`` does the same.

THIS FILE IS CLEARED — it is an identity passthrough. patch() returns the
main-agent action unchanged. Experiments go here (or, now allowed, into
main.py's own layers). The module ``E1_PARAMS`` is kept so the ``--grid``
injection surface (diagnose/cli.py, diagnose/config.py) still works, but by
default nothing is changed.

Only edit ``patch()`` (returning ``action`` unchanged is a no-op).
"""
from __future__ import annotations

import main as _main

# Param namespace read live by patch() each call. ``--grid`` overwrites this per
# combination. Default is an identity no-op (see comments below).
E1_PARAMS = {}


def patch(action, observation, configuration=None):
    """Post-process the action produced by the full main.py agent.

    Cleared / identity: returns ``action`` unchanged. Add experiment logic here
    (or in src/main.py's own layers) when a concrete, measured defect warrants it.
    """
    if not isinstance(action, dict):
        return {}
    return action


# Keep a plain `agent(observation, configuration)` entry point so main.py's own
# agent-toggle resolves to the same behaviour: full main agent, then this patch.
# diagnose.py uses patch() directly.
def agent(observation, configuration=None):
    base = getattr(_main, "_original_agent", None)
    if base is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    return patch(base(observation, configuration), observation, configuration)
