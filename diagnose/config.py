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

# ---------------------------------------------------------------------------
# Experiment registry for --grid. Each experiment names the agent.py param
# namespace it sweeps (injected live into agent.E1_PARAMS), the combo defaults,
# the optional default sweep space, the target metric + sign it must move
# (target_dir: -1 = must decrease, +1 = must increase) and the guard set.
# diagnose.grid reads defaults/target/guards from here for the chosen --exp.
# ---------------------------------------------------------------------------
EXPERIMENTS = {
    # E1: stop dumping below-base premium goods + fertilizer into a glut.
    "e1": {
        "defaults": _E1_DEFAULT,
        "space": {"min_sell_frac": [0.8, 1.0],
                  "shed_cap_frac": [0.85, 0.90, 0.95]},
        "target": "premium_waste_units",
        "target_dir": -1,
        "guards": _E1_GUARDS,
        "print_keys": ["min_sell_frac", "shed_cap_frac", "hold_cap", "use_fert", "shop_aware"],
    },
    # floor: don't liquidate WOOL/MILK at (near) floor prices / hoard them deep
    # into the game. Defaults to `bulk` mode: hold (accumulate) below `sell_frac`
    # of base, then dump the accumulated stash as ONE order when the price comes
    # back up — bounded by hold_cap, shed room and endgame_day. Sweeps the sell
    # threshold, the accumulation (hold) cap and the per-order bulk cap.
    "floor": {
        "defaults": {"_exp": "floor", "price_frac": 0.0, "hold_cap": 40,
                     "shed_cap_frac": 0.90, "endgame_day": 27,
                     "bulk": 1, "sell_frac": 0.5, "bulk_max": 40},
        "space": {"sell_frac": [0.3, 0.5, 0.8],
                  "hold_cap": [20, 40, 80],
                  "bulk_max": [24, 40, 999]},
        "target": "floor_sales",
        "target_dir": -1,
        "guards": {
            "shed_overflow_days": (0.5, +1),
            "discarded_units_total": (1.0, +1),
            "animal_escapes": (0.0, +1),
            "stranded_at_bell": (300.0, +1),
            "premium_below_base_frac": (0.03, +1),
            "sell_revenue_total": (-0.10, -1),
        },
        "print_keys": ["sell_frac", "hold_cap", "bulk", "bulk_max", "endgame_day"],
    },
    # grow: cap how many COW/SHEEP we place and whether we plant MELON. Sweeps
    # herd size directly (milk/wool are livestock by-products; fertilizer pays).
    "grow": {
        "defaults": {"_exp": "grow", "cap_cows": 99, "cap_sheep": 99, "no_melon": 0},
        "space": {"cap_cows": [0, 3, 6, 9], "cap_sheep": [0, 3, 6, 9],
                  "no_melon": [0, 1]},
        "target": "sell_revenue_total",
        "target_dir": +1,
        "guards": {
            "shed_overflow_days": (0.5, +1),
            "discarded_units_total": (1.0, +1),
            "animal_escapes": (0.0, +1),
            "stranded_at_bell": (300.0, +1),
            "premium_below_base_frac": (0.03, +1),
            "sell_revenue_total": (-0.10, -1),
        },
        "print_keys": ["cap_cows", "cap_sheep", "no_melon"],
    },
    # wool: stop producing/selling structurally-worthless wool. WOOL base $200 but
    # craters to $1 on a ~105-unit glut and its only buyer is the Yarn Store
    # (absent ~1/3 of seasons). This cuts sheep when the shop draw shows no wool
    # buyer (keeping the herd as a fertilizer appliance) and guards the floor-sell.
    "wool": {
        "defaults": {"_exp": "wool", "sheep_yarn": 8, "sheep_noyarn": 0,
                     "decide_day": 9, "wool_floor": 0.15, "wool_cap": 16,
                     "endgame_day": 27},
        "space": {"sheep_noyarn": [0, 2, 4],
                  "sheep_yarn": [6, 8],
                  "wool_floor": [0.0, 0.2],
                  "wool_cap": [16, 32]},
        "target": "floor_sales",
        "target_dir": -1,
        "guards": {
            "shed_overflow_days": (0.5, +1),
            "discarded_units_total": (1.0, +1),
            "animal_escapes": (0.0, +1),
            "stranded_at_bell": (300.0, +1),
            "premium_below_base_frac": (0.03, +1),
            "sell_revenue_total": (-0.10, -1),
        },
        "print_keys": ["sheep_noyarn", "sheep_yarn", "wool_floor", "wool_cap", "decide_day"],
    },
}


# Products whose above-base target > 1 (small glut craters them to the $1 floor),
# and humanised shop names — used by the graph dashboard.
_SPIKEY_PRODUCTS = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
_SHOP_TITLE = {k: " ".join(w.title() for w in k.split("_")) for k in SHOPS}
