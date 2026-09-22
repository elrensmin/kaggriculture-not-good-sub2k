"""diagnose.config — shared constants, engine data and cross-module state.

This module is the dependency base of the package (everything imports it) and the
single place that re-exports the Kaggriculture engine's product/market tables so
the rest of the package does not have to reach into ``kaggle_environments``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

# Engine game/product tables, re-exported for the whole package.
from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS,
    CROPS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
    SHOPS,
)

# Project layout: the importable modules were moved to a ``src/`` layer.
#   <root>/diagnose/        -> this package
#   <root>/src/             -> main.py, agent.py, route_tape.py, public_agents/,
#                              and the analyze/package/fetch/lb helper scripts
# Put BOTH the package parent (so the package itself resolves) and ``src/`` (so
# ``import main`` / ``import agent`` / ``import route_tape`` work) on sys.path,
# no matter how the harness is launched (python -m diagnose, uv run, or a forked
# parallel worker inheriting this process's sys.path).
_ROOT = Path(__file__).resolve().parent.parent          # <root>
_SRC = _ROOT / "src"                                    # <root>/src
for _d in (str(_ROOT), str(_SRC)):
    if _d and _d not in sys.path:
        sys.path.insert(0, _d)
del _d
PUBLIC_AGENTS_DIR = _ROOT / "public_agents"
REPLAY_ROOT = _ROOT / "diag-replays"

EPISODE_STEPS = 720
TURNS_PER_DAY = 24
SHED_CAPACITY = 100

# The public agents in public_agents/ are single-seat "cloning" agents and only
# act at seat 0; the agent under test sits at seat 1 (TEST_SEAT).
TEST_SEAT = 1

# E1 grid target: premium goods + fertilizer sold below base (= their worst sales).
_GATED_WASTE = ("STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER")
# The shed sits at the board centre, reachable from its four inner-corner access
# tiles (one per quadrant). "Near shed" = the ownable ring within Manhattan
# distance <= 2 of those access tiles — the shortest-round-trip land in the game.
_SHED_ACCESS = [(4, 4), (5, 4), (4, 5), (5, 5)]

# Public agent discovery: index -> (stem, path), refreshed by diagnose.agents.
PUBLIC_AGENT_MAP: Dict[int, Tuple[str, Path]] = {}

# ---------- E1 sell-gate grid state (see diagnose.grid / agent.E1_PARAMS) ----
# Defaults for the agent.py E1_PARAMS combo (injected live by agent.patch()).
_E1_DEFAULT = {"min_sell_frac": 1.0, "shed_cap_frac": 0.90, "hold_cap": 45,
               "use_fert": 0, "shop_aware": 0}
# Workers (--workers) for parallel game execution; None => all cores.
_GRID_WORKERS = None
# Guards that a grid combo must not regress (per opponent, same-seed paired delta).
#  key -> (limit, direction): +1 => delta must be <= limit; -1 => >= limit.
_E1_GUARDS = {
    "shed_overflow_days": (0.5, +1),
    "discarded_units_total": (1.0, +1),
    "animal_escapes": (0.0, +1),
    "stranded_at_bell": (300.0, +1),
    "sell_revenue_total": (-0.10, -1),  # relative limit handled in diagnose.grid
}

# Products whose above-base target > 1 (small glut craters them to the $1 floor),
# and humanised shop names — used by the graph dashboard.
_SPIKEY_PRODUCTS = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
_SHOP_TITLE = {k: " ".join(w.title() for w in k.split("_")) for k in SHOPS}
