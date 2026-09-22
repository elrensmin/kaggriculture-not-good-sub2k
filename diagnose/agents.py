"""diagnose.agents — agent loading (public opponents + the old/new main.py pair).

Loads the public "cloning" opponents from ``public_agents/`` and rebuilds the
old/new ``main.py``(+ ``agent.py``) pair under test.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
from typing import Callable, Tuple

from diagnose import config as _cfg
from diagnose.config import PUBLIC_AGENTS_DIR, PUBLIC_AGENT_MAP

def _refresh_public_agent_map():
    PUBLIC_AGENT_MAP.clear()
    if not PUBLIC_AGENTS_DIR.exists():
        return
    py_files = sorted(p for p in PUBLIC_AGENTS_DIR.iterdir() if p.suffix == ".py")
    for i, path in enumerate(py_files, 1):
        PUBLIC_AGENT_MAP[i] = (path.stem, path)


_refresh_public_agent_map()



def public_agent_names() -> str:
    return "\n".join(f"  {i}: {name}" for i, (name, _) in PUBLIC_AGENT_MAP.items())



def load_public_agent(idx: int) -> Callable:
    if idx not in PUBLIC_AGENT_MAP:
        raise ValueError(f"Unknown public agent #{idx}. Available:\n{public_agent_names()}")
    name, path = PUBLIC_AGENT_MAP[idx]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "agent") or not callable(mod.agent):
        raise RuntimeError(f"{path} does not expose a callable 'agent'")
    return mod.agent


# ---------------------------------------------------------------------------
# main.py / agent.py toggle
# ---------------------------------------------------------------------------



def _tape_module():
    return "route_tape"



def _reload_main_if_needed(fresh: bool = False):
    import importlib
    import os
    # main reads the tape source from KAGGICULTURE_TAPE at import; set it before
    # any (re)load so --tape selects which tape the freshly built chassis uses.
    os.environ["KAGGICULTURE_TAPE"] = _tape_module()
    import main  # noqa: F401
    if fresh:
        importlib.reload(main)
    else:
        # Enforce the tape even if main was imported earlier without the env set.
        if os.environ.get("KAGGICULTURE_TAPE") != _tape_module():
            importlib.reload(main)
    import main as _main2
    return _main2



def load_old_agent(fresh: bool = False) -> Callable:
    """Return the production agent built into main.py (no agent.py patch)."""
    return _reload_main_if_needed(fresh)._original_agent



def load_new_agent(fresh: bool = False) -> Callable:
    """Return the 'new' agent: main.py's full agent with agent.py's patch layered on top.

    Never a standalone replacement for main.py — the candidate hook in
    agent.patch() tweaks the action produced by the full main agent, so
    ``--new`` and the ``--new`` side of ``--compare`` run everything in main.py
    plus the patch (each improvement/regression is relative to production).
    """
    main = _reload_main_if_needed(fresh)
    base = main._original_agent
    import agent as amod
    pfunc = getattr(amod, "patch", None)
    if pfunc is None:
        raise TypeError(
            "agent.py must expose 'patch(action, observation, configuration=None)'"
            " as the new-agent hook"
        )

    def new_agent(observation, configuration=None):
        action = base(observation, configuration)
        return pfunc(action, observation, configuration)

    return new_agent



def load_old_and_new(fresh: bool = False) -> Tuple[Callable, Callable]:
    """Load main.py ONCE and return (old_agent, new_agent) from the same instance.

    Reloading main a second time for the new agent corrupts the previously-loaded
    old agent (they share singleton chassis state), so a fresh reload happens at
    most once here and both agents derive from the identical base.
    """
    main = _reload_main_if_needed(fresh)
    base = main._original_agent
    import agent as amod
    pfunc = getattr(amod, "patch", None)
    if pfunc is None:
        raise TypeError(
            "agent.py must expose 'patch(action, observation, configuration=None)'"
            " as the new-agent hook"
        )

    def new_agent(observation, configuration=None):
        return pfunc(base(observation, configuration), observation, configuration)

    return base, new_agent


# ---------------------------------------------------------------------------
# Episode runner + replay persistence
# ---------------------------------------------------------------------------
