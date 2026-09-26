"""diagnose.agents — agent loading (public opponents + the agent under test).

Loads the public "cloning" opponents from ``public_agents/`` and the agent under
test, which is the ``src`` package (``src/__init__.py`` exposes ``agent``).
"""
from __future__ import annotations

import importlib
import importlib.util
from typing import Callable

from .config import PUBLIC_AGENTS_DIR, PUBLIC_AGENT_MAP


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


def load_agent(fresh: bool = False) -> Callable:
    """Return the agent under test: the ``src`` package's ``agent`` entry point.

    ``src`` resolves because the repo root is on sys.path via ``diagnose.config``.
    The package is self-contained: no route tape, no chassis, no patch layer.
    """
    import src
    if fresh:
        importlib.reload(src)
    if not hasattr(src, "agent") or not callable(src.agent):
        raise TypeError("src must expose 'agent(observation, configuration=None)'")
    return src.agent
