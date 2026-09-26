"""diagnose.config — shared constants, engine data and cross-module state.

This module is the dependency base of the package (everything imports it) and the
single place that re-exports the Kaggriculture engine's product/market tables so
the rest of the package does not have to reach into ``kaggle_environments``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Tuple

# Engine game/product tables, re-exported for the whole package.
from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS,
    CROPS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
    SHOPS,
)

# Project layout. Put the REPO ROOT on sys.path so ``import src`` (the agent under
# test) and ``import tools.diagnose`` resolve no matter how the harness is launched:
# ``python -m tools.diagnose``, ``uv run``, or a forked parallel worker that
# inherited this process's sys.path.
#
#   <root>/src/            -> the agent package (src/__init__.py exposes ``agent``)
#   <root>/tools/diagnose/ -> this harness
#   <root>/tools/          -> the read-only analysis tools
_ROOT = Path(__file__).resolve().parent.parent.parent      # <root>
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
PUBLIC_AGENTS_DIR = _ROOT / "public_agents"
REPLAY_ROOT = _ROOT / "diag-replays"

EPISODE_STEPS = 720
TURNS_PER_DAY = 24
SHED_CAPACITY = 100

# The public agents in public_agents/ are single-seat "cloning" agents and only
# act at seat 0; the agent under test sits at seat 1 (TEST_SEAT).
TEST_SEAT = 1

# Premium goods whose worst sales are the below-base ones (kept for the tools).
_GATED_WASTE = ("STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER")
# The shed sits at the board centre, reachable from its four inner-corner access
# tiles (one per quadrant). "Near shed" = the ownable ring within Manhattan
# distance <= 2 of those access tiles — the shortest-round-trip land in the game.
_SHED_ACCESS = [(4, 4), (5, 4), (4, 5), (5, 5)]

# Public agent discovery: index -> (stem, path), refreshed by tools.diagnose.agents.
PUBLIC_AGENT_MAP: Dict[int, Tuple[str, Path]] = {}

# Products whose above-base target > 1 (small glut craters them to the $1 floor),
# and humanised shop names — used by the graph dashboard.
_SPIKEY_PRODUCTS = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
_SHOP_TITLE = {k: " ".join(w.title() for w in k.split("_")) for k in SHOPS}
