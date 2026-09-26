"""Kaggriculture agent — onion architecture. Single entry point: ``src.agent``.

This package IS the agent. There is no route tape, no ``main.py`` chassis and no
patch layer: the whole strategy lives here as a stack of layers, and the harness
loads ``src.agent`` directly (``tools/diagnose/agents.py::load_agent``).

Layers (inside -> out):
  core         params / market / state / routing
  structural   budget / crop_plan / herd_plan / layout
  execution    sell_policy / endgame / scheduler / emit

``action(t) = f(state(t))`` only — every layer reads an immutable per-turn
``State`` snapshot, so a bug is a local fix and never a corrupted trajectory.
"""
from __future__ import annotations

from . import emit, scheduler
from .state import State


def agent(observation, configuration=None):
    try:
        return scheduler.plan(State(observation))
    except Exception:
        # A bug must degrade to idle, never to a crash or an illegal action.
        return emit.fallback(observation)
