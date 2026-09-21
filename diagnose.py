"""Diagnostic harness / A-B tester for the Kaggriculture agent.

What it is
----------
``main.py`` is the production agent (~6,400 lines, 45 layers). ``agent.py`` is the
experiment workspace: a *patch layer* that runs on top of ``main.py``. ``--new``
runs the full ``main.py`` agent and then hands its action to ``agent.patch()``,
so any improvement/regression is measured against real production behavior
rather than an isolated stub.

The harness runs the agent under test against the public agents in
``public_agents/``, saves every replay as JSON under ``diag-replays/run-N/``, and
emits per-day / per-opponent / per-game CSVs, optional narrative summaries, and
a same-seed A/B delta report.

Anti-goal — NEVER trust averages across games
---------------------------------------------
This environment is dynamic: random-seeded games across the whole public
leaderboard with live, moving prices. Averaging a score is NOT signal; it
regresses our score. Which public agent we face and any one seed's price action
can swing any run, so optimizing for a mean only chases noise and misdirection.
Always aim for *inefficiencies* in the system and tackle *system-level* issues:
idle steps, shed overflow, plants dying, missed harvests, unfed/unwatered
animals, floor-price / below-base sales, animal escapes, market timing — things
that hurt every game regardless of seed or opponent. Judge a patch on a concrete
defect you can point at in a specific game, never on an averaged-out misdirection.

Seating
-------
The public agents in ``public_agents/`` are single-seat "cloning" agents and only
act at **seat 0**. So the harness seats the **public opponent at seat 0** and the
**agent under test at seat 1** (``TEST_SEAT = 1``); the per-seed day files
(``days_seed<S>.csv``) read that seat. Never silence opponent output: these
agents depend on real stdout/stderr and quietly return PASS if their output is
redirected.

CLI
---
    python diagnose.py --old  --pa 1 --batch 5 --seed 42    # production agent only
    python diagnose.py --new  --pa 1 --batch 3 --seed 42    # main.py + agent.patch()
    python diagnose.py --compare --pa 1 --batch 5 --seed 42  # A/B old vs new (same seeds)
    python diagnose.py --replay-dir diag-replays/run-1 --render  # re-diagnose saved replays

Flags:
    --old / --new    which agent runs: old = main.py; new = main.py + agent.patch()
    --compare        run old and new on the identical seed set and print an A/B delta table
    --pa N[,M,...]   public agent indices (1-13), e.g. 1,2,3 or 1-6
    --batch N        number of seeds per opponent
    --seed S         deterministic: seeds S, S+1, ... S+(N-1) verbatim (omit = random)
    --run-dir DIR    where to save; default: next diag-replays/run-N
    --replay-dir     re-read saved replays (rewrites CSVs; --render prints a day report)
    --render         full day-by-day report for the last replay; with --compare also
                     the per-day old-vs-new money curves
    --llm            write one <replay>.md narrative summary per replay

Outputs (per run dir)
---------------------
    <agent>_vs_<opponent>_seed<S>.json   the full Kaggle replay — the authoritative
                                         step-level source (positions, tiles, crops,
                                         animals, prices, market orders, transitions)
    games.csv         one compact row per replay for the agent under test: its metrics
                      plus the opponent's final revenue and a WIN / LOSS / TIE tag
    days_seed<S>.csv  per-day view of the agent under test (its seat), one file per
                      distinct seed so each game's daily data stays separated
    <replay>.md       optional narrative summary (--llm)

Context columns are ``agent, opponent, seed`` (there is deliberately no ``file``
column). There is also no ``steps.csv``: per-step detail lives in the JSON
replays, which the per-seed day files and games.csv summarize.

Reproducibility: ``--seed`` makes a run fully deterministic; ``--compare`` always
shares one seed set between old and new, so the A/B deltas are meaningful. The
CSV schemas are stable across every run (all item columns present, zero-filled)
so runs can be diffed directly.

Related docs: the operating rules and patch workflow live in ``AGENTS.md``; the
project overview in ``README.md``.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import random
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from kaggle_environments import make
from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS,
    CROPS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
    SHOPS,
)
import kaggle_environments.envs.kaggriculture.kaggriculture as _ENV

EPISODE_STEPS = 720
TURNS_PER_DAY = 24
SHED_CAPACITY = 100
# The public opponents in public_agents/ are single-seat "cloning" agents: they
# only act when seated at seat 0. So the harness seats the public opponent at
# seat 0 and the agent under test (main.py / agent.py) at seat 1. days.csv
# tracks TEST_SEAT (the agent under test).
TEST_SEAT = 1
PUBLIC_AGENTS_DIR = Path(__file__).parent / "public_agents"
REPLAY_ROOT = Path(__file__).parent / "diag-replays"

# ---------------------------------------------------------------------------
# Public agent discovery
# ---------------------------------------------------------------------------

PUBLIC_AGENT_MAP: Dict[int, Tuple[str, Path]] = {}


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


def _reload_main_if_needed(fresh: bool = False):
    import main
    if fresh:
        import importlib
        importlib.reload(main)
    return main


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


def run_game(
    agent: Callable,
    opponent: Callable,
    seed: Optional[int] = None,
    episode_steps: int = EPISODE_STEPS,
    seat: int = 0,
    audit: bool = False,
):
    """Run a seeded game and return the Kaggle env object.

    If ``audit`` is True, wrap the env to record committed market sells and
    shed overflow discards.  The audit is attached to ``env._diagnose_audit``
    and merged into replay metadata by ``save_replay``."""
    conf = {"episodeSteps": episode_steps, "seed": seed}
    env = make("kaggriculture", configuration=conf)
    ctx = _MarketAudit() if audit else None
    if ctx is not None:
        ctx.wrap_env(env)
    with ctx or _NoOpContext():
        if seat == 0:
            env.run([agent, opponent])
        else:
            env.run([opponent, agent])
    if audit and ctx is not None:
        env._diagnose_audit = dict(ctx.events)
    return env


class _NoOpContext:
    def __enter__(self): return self
    def __exit__(self, *exc): return False

def save_replay(env, path: Path, metadata: Optional[Dict[str, Any]] = None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    replay = env.toJSON()
    if metadata:
        replay["_diagnose_meta"] = dict(metadata)
    audit = getattr(env, "_diagnose_audit", None)
    if audit:
        replay["_diagnose_meta"]["audit"] = audit
    with open(path, "w") as f:
        json.dump(replay, f, indent=2)
    return path


class _MarketAudit:
    """Record *committed* market sells and inventory discards during a game.

    The env's tape uses sentinel quantities (e.g. SELL WHEAT 1000) meaning
    "dump everything".  This audit patches the env's interpreter so every
    step is annotated with the current step/player state, then wraps
    _commit_unit and the inventory drop paths to count the units that
    actually left the shed and what overflowed."""

    def __init__(self):
        self.events: Dict[int, Dict[int, Dict[str, Any]]] = defaultdict(
            lambda: defaultdict(
                lambda: {
                    "sells": defaultdict(lambda: {"qty": 0, "revenue": 0.0, "floor": 0, "below": 0, "above": 0}),
                    "discards": 0,
                }
            )
        )
        self._ctx: Dict[str, Any] = {}
        self._orig_commit: Optional[Callable] = None
        self._orig_drop: Optional[Callable] = None
        self._orig_ua: Optional[Callable] = None
        self._wrapped_interpreter: Optional[Callable] = None

    def __enter__(self):
        self._orig_commit = _ENV._commit_unit
        self._orig_drop = _ENV._drop_inventories_to_shed
        self._orig_ua = _ENV._apply_unit_action
        _ENV._commit_unit = self._commit_unit
        _ENV._drop_inventories_to_shed = self._drop_inventories_to_shed
        _ENV._apply_unit_action = self._apply_unit_action
        return self

    def __exit__(self, *exc):
        _ENV._commit_unit = self._orig_commit
        _ENV._drop_inventories_to_shed = self._orig_drop
        _ENV._apply_unit_action = self._orig_ua

    def wrap_env(self, env):
        """Wrap the env instance's interpreter to record step/player context."""
        orig = env.interpreter

        def wrapped(state, env_):
            try:
                self._ctx["step"] = int(state[0].observation.get("step", 0))
                self._ctx["farms"] = [s.observation.farms[i] for i, s in enumerate(state)]
                self._ctx["privates"] = [s.observation.private for s in state]
            except Exception:
                self._ctx.clear()
            return orig(state, env_)

        self._wrapped_interpreter = wrapped
        env.interpreter = wrapped

    def _seat(self, farm=None, private=None) -> Optional[int]:
        if farm is not None:
            for i, f in enumerate(self._ctx.get("farms", ())):
                if f is farm:
                    return i
        if private is not None:
            for i, p in enumerate(self._ctx.get("privates", ())):
                if p is private:
                    return i
        return None

    def _commit_unit(self, op, item, price, farm, private, market, shed_capacity=100):
        ok = self._orig_commit(op, item, price, farm, private, market, shed_capacity)
        step = self._ctx.get("step")
        if step is None:
            return ok
        seat = self._seat(farm=farm, private=private)
        if seat is None:
            return ok
        if ok and op == "SELL" and item in PRODUCTS:
            rec = self.events[step][seat]["sells"][item]
            rec["qty"] += 1
            rec["revenue"] += price
            if price <= PRICE_FLOOR:
                rec["floor"] += 1
            if price < MARKET_PARAMS[item]["base"]:
                rec["below"] += 1
            else:
                rec["above"] += 1
        return ok

    @staticmethod
    def _discard_delta(private, before_inv, before_shed):
        after_inv = sum(sum(i.values()) for i in private["inventories"])
        after_shed = sum(private["shed"].values())
        return max(0.0, (before_inv - after_inv) - (after_shed - before_shed))

    def _apply_unit_action(self, farm, private, idx, action, board_size, day, turns_per_day, shed_capacity=100):
        op = action[0] if isinstance(action, list) and action else None
        # Only deposit paths can overflow: DROP, and PLACE of a non-animal via
        # the shed-adjacent branch.  FEED/FERTILIZE/PLACE-animal also consume
        # inventory but are legitimate uses, not discards.
        deposit = op == "DROP" or (
            op == "PLACE" and len(action) > 1 and action[1] not in ANIMALS
        )
        before_inv = sum(sum(i.values()) for i in private["inventories"])
        before_shed = sum(private["shed"].values())
        self._orig_ua(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity)
        if not deposit:
            return
        discarded = self._discard_delta(private, before_inv, before_shed)
        if discarded > 0:
            step = self._ctx.get("step")
            seat = self._seat(private=private)
            if step is not None and seat is not None:
                self.events[step][seat]["discards"] += discarded

    def _drop_inventories_to_shed(self, private, capacity):
        before_inv = sum(sum(i.values()) for i in private["inventories"])
        before_shed = sum(private["shed"].values())
        self._orig_drop(private, capacity)
        discarded = self._discard_delta(private, before_inv, before_shed)
        if discarded > 0:
            step = self._ctx.get("step")
            seat = self._seat(private=private)
            if step is not None and seat is not None:
                self.events[step][seat]["discards"] += discarded


def load_replay(path: Path) -> Dict[str, Any]:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Frame builder: per-step state + transitions
# ---------------------------------------------------------------------------


def _tile_copy(t):
    if t is None or t == "LOCKED":
        return t
    if isinstance(t, dict):
        return dict(t)
    return t


def _tile_brief(t):
    if t is None:
        return None
    if t == "LOCKED":
        return "LOCKED"
    k = t.get("kind")
    if k == "PLANT":
        return {
            "kind": "PLANT",
            "crop": t.get("crop"),
            "planted_day": t.get("planted_day"),
            "yield_units": t.get("yield_units"),
            "watered_today": t.get("watered_today"),
            "consecutive_unwatered": t.get("consecutive_unwatered"),
            "fertilized_until_day": t.get("fertilized_until_day"),
            "max_lifespan_step": t.get("max_lifespan_step"),
        }
    if k in ("COOP", "PASTURE"):
        return {
            "kind": k,
            "animal": t.get("animal"),
            "yield_units": t.get("yield_units"),
            "fed_today": t.get("fed_today"),
            "consecutive_unfed": t.get("consecutive_unfed"),
            "cared_today": t.get("cared_today"),
            "fertilizer_available": t.get("fertilizer_available"),
            "pending_care_bonus": t.get("pending_care_bonus"),
            "placed_day": t.get("placed_day"),
        }
    if k == "WEED":
        return {"kind": "WEED"}
    return {"kind": k}


def _copy_tiles(tiles):
    return [[_tile_copy(t) for t in row] for row in tiles]


def _unit_actions(action: Dict[str, Any]) -> List[Tuple[int, List[str]]]:
    """Return list of (unit_index, action_list). Unit 0 = farmer."""
    out = [(0, list(action.get("farmer") or ["PASS"]))]
    for i, h in enumerate(action.get("hands") or [], 1):
        out.append((i, list(h or ["PASS"])))
    return out


def _op_name(a: List[str]) -> str:
    if not a:
        return "PASS"
    return a[0]


def _op_arg(a: List[str], idx: int, default=None):
    if a and len(a) > idx:
        return a[idx]
    return default


def _tile_ready(tile, day: int) -> bool:
    """A tile has produce/animal output waiting to be harvested."""
    if not isinstance(tile, dict):
        return False
    if tile.get("kind") == "PLANT":
        cd = CROPS.get(tile.get("crop"))
        if not cd:
            return False
        if tile.get("yield_units", 0) <= 0:
            return False
        if cd["ongoing"]:
            return True
        age = day - tile.get("planted_day", 0)
        return age >= cd["max_yield_day"]
    if "animal" in tile:
        return tile.get("yield_units", 0) > 0
    return False


def _shed_total(private):
    return sum((private.get("shed") or {}).values())


def _crop_at_actor(me, unit_idx: int, tiles) -> Optional[str]:
    """Crop on the tile the given actor currently occupies, if any.

    Harvesting picks the crop on the tile the unit is standing on, so the actor's
    position -> tile -> crop gives us crop-level harvest attribution.
    """
    if unit_idx == 0:
        pos = me.get("farmer")
    else:
        hands = me.get("hands") or []
        i = unit_idx - 1
        if not (0 <= i < len(hands)):
            return None
        pos = hands[i]
    if not pos:
        return None
    x, y = int(pos[0]), int(pos[1])
    if not (0 <= y < len(tiles) and 0 <= x < len(tiles[y])):
        return None
    t = tiles[y][x]
    if isinstance(t, dict) and t.get("kind") == "PLANT":
        return t.get("crop")
    return None


def build_frames(record: List[Tuple[Dict, Dict]], seat: int = 0) -> List[Dict[str, Any]]:
    """Convert raw (obs, action) pairs into rich per-step frames."""
    frames = []
    prev_obs: Optional[Dict] = None
    for obs, act in record:
        step = obs.get("step", 0)
        day = step // TURNS_PER_DAY
        hour = step % TURNS_PER_DAY
        me = obs["farms"][seat]
        private = obs.get("private") or {}
        market = obs.get("market") or {}
        town = obs.get("town") or {}

        tiles = _copy_tiles(me.get("tiles", []))
        prev_tiles = _copy_tiles(prev_obs["farms"][seat]["tiles"]) if prev_obs else None

        # Per-tile crop/animal/weed inventory
        crops = []
        animals = []
        weeds = 0
        structures = {"COOP": 0, "PASTURE": 0}
        for y, row in enumerate(tiles):
            for x, t in enumerate(row):
                if t is None or t == "LOCKED":
                    continue
                b = _tile_brief(t)
                if b["kind"] == "PLANT":
                    crops.append({"pos": (x, y), **b})
                elif b["kind"] in ("COOP", "PASTURE"):
                    structures[b["kind"]] += 1
                    if b.get("animal"):
                        animals.append({"pos": (x, y), **b})
                elif b["kind"] == "WEED":
                    weeds += 1

        # Transition detection vs previous step
        transitions = defaultdict(list)
        money_delta = 0.0
        if prev_obs is not None:
            prev_me = prev_obs["farms"][seat]
            prev_priv = prev_obs.get("private") or {}
            money_delta = me.get("money", 0.0) - prev_me.get("money", 0.0)

            # Tile diffs
            for y, row in enumerate(tiles):
                for x, t in enumerate(row):
                    pt = prev_tiles[y][x] if prev_tiles else None
                    if t == pt:
                        continue
                    transitions["tile_change"].append({"pos": (x, y), "from": _tile_brief(pt), "to": _tile_brief(t)})

            # Shed / seed / inventory diffs
            for item in PRODUCTS:
                d = (private.get("shed") or {}).get(item, 0) - (prev_priv.get("shed") or {}).get(item, 0)
                if d != 0:
                    transitions["shed_delta"].append({"item": item, "delta": d})
            for crop in CROPS:
                d = (private.get("seeds") or {}).get(crop, 0) - (prev_priv.get("seeds") or {}).get(crop, 0)
                if d != 0:
                    transitions["seed_delta"].append({"crop": crop, "delta": d})

            # Worker / land / shop diffs
            dh = len(me.get("hands", [])) - len(prev_me.get("hands", []))
            if dh > 0:
                transitions["hired"].append({"delta": dh})
            dl = len(me.get("unlocked_quadrants", [])) - len(prev_me.get("unlocked_quadrants", []))
            if dl > 0:
                transitions["bought_land"].append({"delta": dl})
            ds = len(town.get("unlocked_shops", [])) - len((prev_obs.get("town") or {}).get("unlocked_shops", []))
            if ds > 0:
                transitions["shop_unlock"].append({"shops": list(town.get("unlocked_shops", []))[-ds:]})

        # Action-based transitions
        for unit_idx, ua in _unit_actions(act):
            op = _op_name(ua)
            if op == "PASS":
                transitions["pass"].append({"unit": unit_idx})
            elif op in ("NORTH", "SOUTH", "EAST", "WEST"):
                transitions["move"].append({"unit": unit_idx, "dir": op})
            elif op == "PLANT":
                transitions["plant"].append({"unit": unit_idx, "crop": _op_arg(ua, 1)})
            elif op == "WATER":
                transitions["water"].append({"unit": unit_idx})
            elif op == "HARVEST":
                transitions["harvest"].append({"unit": unit_idx, "crop": _crop_at_actor(me, unit_idx, tiles)})
            elif op == "FERTILIZE":
                transitions["fertilize"].append({"unit": unit_idx})
            elif op == "DIG":
                transitions["dig"].append({"unit": unit_idx})
            elif op in ("BUILD_COOP", "BUILD_PASTURE"):
                transitions["build"].append({"unit": unit_idx, "kind": op})
            elif op == "PLACE":
                transitions["place"].append({"unit": unit_idx, "item": _op_arg(ua, 1)})
            elif op == "FEED":
                transitions["feed"].append({"unit": unit_idx})
            elif op == "CARE":
                transitions["care"].append({"unit": unit_idx})
            elif op == "COLLECT_FERTILIZER":
                transitions["collect_fertilizer"].append({"unit": unit_idx})
            elif op == "DROP":
                transitions["drop"].append({"unit": unit_idx})
            elif op == "PICKUP":
                transitions["pickup"].append({"unit": unit_idx, "item": _op_arg(ua, 1), "qty": int(_op_arg(ua, 2, 1))})
            else:
                transitions["other"].append({"unit": unit_idx, "op": op, "args": ua[1:]})

        for o in act.get("market") or []:
            if not o:
                continue
            transitions["market_order"].append({"order": list(o)})

        # Derived signals
        shed = dict(private.get("shed") or {})
        seeds = dict(private.get("seeds") or {})
        shed_total = sum(shed.values())
        prices = dict(market.get("prices") or {})
        inventory = dict(market.get("inventory") or {})
        hands = [list(h) for h in me.get("hands", [])]
        farmer_pos = tuple(me.get("farmer", [0, 0]))
        hand_positions = [tuple(h) for h in hands]

        frames.append({
            "step": step,
            "day": day,
            "hour": hour,
            "seat": seat,
            "money": me.get("money"),
            "money_delta": money_delta,
            "farmer": list(act.get("farmer") or ["PASS"]),
            "hands": [list(h) for h in act.get("hands") or []],
            "market_orders": [list(o) for o in act.get("market") or []],
            "shed": shed,
            "shed_total": shed_total,
            "seeds": seeds,
            "inventories": [dict(i or {}) for i in private.get("inventories") or []],
            "prices": prices,
            "market_inventory": inventory,
            "crops": crops,
            "animals": animals,
            "weeds": weeds,
            "structures": structures,
            "n_hands": len(hands),
            "farmer_pos": farmer_pos,
            "hand_positions": hand_positions,
            "tiles": tiles,
            "unlocked_quadrants": list(me.get("unlocked_quadrants", [])),
            "unlocked_shops": list(town.get("unlocked_shops", [])),
            "transitions": dict(transitions),
        })
        prev_obs = obs
    return frames


# ---------------------------------------------------------------------------
# Day rollup
# ---------------------------------------------------------------------------


def build_days(frames: List[Dict[str, Any]], audit: Optional[Dict[int, Dict[int, Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    days: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
        "day": 0,
        "start_money": 0.0,
        "end_money": 0.0,
        "money_delta": 0.0,
        "revenue": 0.0,
        "expenses": 0.0,
        "start_shed_total": 0,
        "end_shed_total": 0,
        "max_shed_total": 0,
        "shed_items_start": {},
        "shed_items_end": {},
        "shed_deltas": defaultdict(int),
        "seed_deltas": defaultdict(int),
        "seed_cost": 0.0,
        "animal_cost": 0.0,
        "product_cost": 0.0,
        "hire_cost": 0.0,
        "land_cost": 0.0,
        "plants_planted": defaultdict(int),
        "plants_watered": 0,
        "plants_harvested": defaultdict(int),
        "harvests_unknown": 0,
        "plants_fertilized": 0,
        "plants_died": 0,
        "animals_placed": defaultdict(int),
        "animals_fed": 0,
        "animals_cared": 0,
        "fertilizer_collected": 0,
        "animals_escaped": 0,
        "weeds_start": 0,
        "weeds_end": 0,
        "weeds_max": 0,
        "idle_turns": 0,
        "idle_units_ready": 0,
        "floor_sales": defaultdict(int),
        "below_base_sales": defaultdict(int),
        "sell_qty": defaultdict(int),
        "revenue_per_item": defaultdict(float),
        "avg_price_per_item": {},
        "sell_qty_source": "requested",
        "discarded_units": 0,
        "buy_qty": defaultdict(int),
        "hires": 0,
        "land_unlocks": 0,
        "shop_unlocks": [],
        "hands_start": 0,
        "hands_end": 0,
        "n_pass": 0,
        "n_move": 0,
        "market_orders": [],
        "first_step": None,
        "last_step": 0,
    })

    if not frames:
        return []

    for f in frames:
        d = f["day"]
        day = days[d]
        day["day"] = d
        if day["first_step"] is None:
            day["first_step"] = f["step"]
        day["last_step"] = f["step"]
        if day["start_money"] == 0.0 and f["step"] % TURNS_PER_DAY == 0:
            day["start_money"] = f["money"]
        day["end_money"] = f["money"]
        day["end_shed_total"] = f["shed_total"]
        day["max_shed_total"] = max(day["max_shed_total"], f["shed_total"])
        day["weeds_end"] = f["weeds"]
        day["weeds_max"] = max(day["weeds_max"], f["weeds"])
        day["hands_end"] = f["n_hands"]
        if f["step"] % TURNS_PER_DAY == 0:
            day["hands_start"] = f["n_hands"]
            day["start_shed_total"] = f["shed_total"]
            day["weeds_start"] = f["weeds"]
            day["shed_items_start"] = dict(f["shed"])
        day["shed_items_end"] = dict(f["shed"])

        # Transitions aggregation
        tr = f.get("transitions", {})
        for p in tr.get("plant", []):
            day["plants_planted"][p["crop"]] += 1
        day["plants_watered"] += len(tr.get("water", []))
        day["plants_fertilized"] += len(tr.get("fertilize", []))
        for h in tr.get("harvest", []):
            # Crop-level attribution when the harvested tile is known.
            crop = h.get("crop")
            if crop:
                day["plants_harvested"][crop] += 1
            else:
                day["harvests_unknown"] += 1
        day["animals_fed"] += len(tr.get("feed", []))
        day["animals_cared"] += len(tr.get("care", []))
        day["fertilizer_collected"] += len(tr.get("collect_fertilizer", []))
        day["n_pass"] += len(tr.get("pass", []))
        day["n_move"] += len(tr.get("move", []))
        for p in tr.get("place", []):
            item = p["item"]
            if item in ANIMALS:
                day["animals_placed"][item] += 1
        for h in tr.get("hired", []):
            day["hires"] += h["delta"]
        for l in tr.get("bought_land", []):
            day["land_unlocks"] += l["delta"]
        for s in tr.get("shop_unlock", []):
            day["shop_unlocks"].extend(s["shops"])
        day["market_orders"].extend(tr.get("market_order", []))

        # Idle = every unit passes and no market orders
        all_pass = all(_op_name(ua) == "PASS" for _, ua in _unit_actions({"farmer": f["farmer"], "hands": f["hands"]}))
        if all_pass and not f["market_orders"]:
            day["idle_turns"] += 1

        # Unit-level idle: PASS while standing on a ready tile / animal
        for pos, cmd in zip([f["farmer_pos"], *f["hand_positions"]], [f["farmer"], *f["hands"]]):
            if _op_name(cmd) == "PASS" and _tile_ready(f["tiles"][pos[1]][pos[0]], f["day"]):
                day["idle_units_ready"] += 1

        # Shed/seed deltas from state diff
        for sd in tr.get("shed_delta", []):
            day["shed_deltas"][sd["item"]] += sd["delta"]
        for sd in tr.get("seed_delta", []):
            day["seed_deltas"][sd["crop"]] += sd["delta"]

        # Money attribution: crude but useful
        if f["money_delta"] > 0:
            day["revenue"] += f["money_delta"]
        else:
            day["expenses"] += -f["money_delta"]

        # Market order classification: use committed audit data when available
        seat = f["seat"]
        use_audit = audit is not None
        step_audit = audit.get(f["step"], {}).get(seat, {}) if use_audit else {}
        if use_audit:
            day["sell_qty_source"] = "committed"
            for item, rec in (step_audit.get("sells") or {}).items():
                day["sell_qty"][item] += rec["qty"]
                day["floor_sales"][item] += rec["floor"]
                day["below_base_sales"][item] += rec["below"]
                day["revenue_per_item"][item] += rec["revenue"]
            day["discarded_units"] += step_audit.get("discards", 0)
        else:
            day["sell_qty_source"] = day.get("sell_qty_source") or "requested"
            for o in f["market_orders"]:
                op = o[0] if o else None
                item = o[1] if len(o) > 1 else None
                qty = int(o[2]) if len(o) > 2 else 1
                if op == "SELL" and item in PRODUCTS:
                    day["sell_qty"][item] += qty
                    price = f["prices"].get(item, MARKET_PARAMS[item]["base"])
                    if price <= PRICE_FLOOR:
                        day["floor_sales"][item] += qty
                    if price < MARKET_PARAMS[item]["base"]:
                        day["below_base_sales"][item] += qty

        # BUY orders and atomic orders (raw qty is still informative)
        for o in f["market_orders"]:
            op = o[0] if o else None
            item = o[1] if len(o) > 1 else None
            qty = int(o[2]) if len(o) > 2 else 1
            if op == "BUY_SEED" and item in CROPS:
                day["buy_qty"][item] += qty
                day["seed_cost"] += qty * CROPS[item]["seed"]
            elif op == "BUY_ANIMAL" and item in ANIMALS:
                day["buy_qty"][item] += qty
                day["animal_cost"] += qty * ANIMALS[item]["cost"]
            elif op == "BUY_PRODUCT" and item in PRODUCTS:
                day["buy_qty"][item] += qty
                price = f["prices"].get(item, MARKET_PARAMS[item]["base"])
                day["product_cost"] += qty * price
            elif op == "HIRE":
                # Hires are counted once, from the actual hand-count increase
                # (the "hired" transition above). The HIRE order is only a
                # request; it can fail, so it is not an authoritative count.
                pass
            elif op == "BUY_LAND":
                # Land prices: 1000, 2000, 4000 for the three extra quadrants
                n = len(f["unlocked_quadrants"])
                price = [0, 1000, 2000, 4000][min(n, 3)]
                day["land_cost"] += price
                day["land_unlocks"] += 1

        # Detect animal escapes from tile changes
        for tc in tr.get("tile_change", []):
            fr = tc["from"]
            to = tc["to"]
            if fr and isinstance(fr, dict) and fr.get("animal") and (to is None or to == "LOCKED" or (isinstance(to, dict) and not to.get("animal") and to.get("kind") in ("COOP", "PASTURE"))):
                day["animals_escaped"] += 1
            if fr and isinstance(fr, dict) and fr.get("kind") == "WEED" and to is None:
                pass  # weed removed
            if fr and isinstance(fr, dict) and fr.get("kind") == "PLANT" and isinstance(to, dict) and to.get("kind") == "WEED":
                day["plants_died"] += 1

    # Convert defaultdicts to plain dicts and compute hire/land cost more accurately
    result = []
    for d in sorted(days.keys()):
        day = days[d]
        # Hire cost: Fibonacci sequence for cumulative hires within the day.
        if day["hires"] > 0:
            # Sum fib(0..hires-1) where fib = 1,1,2,3,5,...
            a, b = 1, 1
            cost = 0
            for _ in range(day["hires"]):
                cost += a
                a, b = b, a + b
            day["hire_cost"] = cost
        day["money_delta"] = day["end_money"] - day["start_money"]
        day["plants_planted"] = dict(day["plants_planted"])
        day["plants_harvested"] = dict(day["plants_harvested"])
        day["animals_placed"] = dict(day["animals_placed"])
        day["shed_deltas"] = dict(day["shed_deltas"])
        day["seed_deltas"] = dict(day["seed_deltas"])
        day["sell_qty"] = dict(day["sell_qty"])
        day["buy_qty"] = dict(day["buy_qty"])
        day["floor_sales"] = dict(day["floor_sales"])
        day["below_base_sales"] = dict(day["below_base_sales"])
        day["revenue_per_item"] = dict(day["revenue_per_item"])
        # Average realised price per item (only where something was sold)
        day["avg_price_per_item"] = {
            p: round(day["revenue_per_item"].get(p, 0.0) / day["sell_qty"].get(p, 1), 2)
            if day["sell_qty"].get(p, 0) else 0.0
            for p in PRODUCTS
        }
        # Zero-fill every known item so the CSV schema is stable across runs.
        shed_items = sorted(set(PRODUCTS) | set(ANIMALS))   # animals live in the shed too
        for it in shed_items:
            day["shed_items_start"].setdefault(it, 0)
            day["shed_items_end"].setdefault(it, 0)
            day["shed_deltas"].setdefault(it, 0)
        buy_items = sorted(set(PRODUCTS) | set(CROPS) | set(ANIMALS))
        for it in buy_items:
            day["buy_qty"].setdefault(it, 0)
        for p in PRODUCTS:
            day["sell_qty"].setdefault(p, 0)
            day["floor_sales"].setdefault(p, 0)
            day["below_base_sales"].setdefault(p, 0)
            day["revenue_per_item"].setdefault(p, 0.0)
            day["avg_price_per_item"].setdefault(p, 0.0)
        # Flatten per-item revenue/price for stable CSV schema
        for p in PRODUCTS:
            day[f"revenue_{p}"] = day["revenue_per_item"].get(p, 0.0)
            day[f"avg_price_{p}"] = day["avg_price_per_item"].get(p, 0.0)
        del day["revenue_per_item"]
        del day["avg_price_per_item"]
        for c in CROPS:
            day["seed_deltas"].setdefault(c, 0)
            day["plants_planted"].setdefault(c, 0)
            day["plants_harvested"].setdefault(c, 0)
        for a in ANIMALS:
            day["animals_placed"].setdefault(a, 0)
        day["shop_unlocks"] = list(day["shop_unlocks"])
        result.append(day)
    return result


# ---------------------------------------------------------------------------
# Inefficiency / summary engine
# ---------------------------------------------------------------------------


def summarize(days: List[Dict[str, Any]], frames: Optional[List[Dict[str, Any]]] = None) -> OrderedDict:
    if not days:
        return OrderedDict()

    total_steps = sum(1 for _ in frames) if frames else days[-1]["last_step"] + 1
    idle_steps = sum(d["idle_turns"] for d in days)
    shed_pressure_days = sum(1 for d in days if d["max_shed_total"] >= SHED_CAPACITY - 5)
    shed_overflow_days = sum(1 for d in days if d["max_shed_total"] >= SHED_CAPACITY)
    floor_sales = defaultdict(int)
    below_base = defaultdict(int)
    sell_qty = defaultdict(int)
    for d in days:
        for item, n in d["floor_sales"].items():
            floor_sales[item] += n
        for item, n in d["below_base_sales"].items():
            below_base[item] += n
        for item, n in d["sell_qty"].items():
            sell_qty[item] += n

    animal_escapes = sum(d["animals_escaped"] for d in days)
    plants_died = sum(d["plants_died"] for d in days)
    weeds_max = max((d["weeds_max"] for d in days), default=0)

    # Per-frame animal/crop trouble, but only flag at end-of-day or near escape.
    unfed_eod = 0
    unwatered_eod = 0
    missed_harvest_eod = 0
    if frames:
        for f in frames:
            if f["hour"] == TURNS_PER_DAY - 1:
                for a in f["animals"]:
                    if a.get("consecutive_unfed", 0) >= 1:
                        unfed_eod += 1
                for c in f["crops"]:
                    if not c.get("watered_today"):
                        unwatered_eod += 1
                    cd = CROPS.get(c["crop"])
                    if cd and not cd["ongoing"]:
                        age = f["day"] - c.get("planted_day", 0)
                        if age >= cd["max_yield_day"] and c.get("yield_units", 0) > 0:
                            missed_harvest_eod += 1
            # Also flag any animal near escape regardless of hour
            for a in f["animals"]:
                if a.get("consecutive_unfed", 0) >= 2:
                    unfed_eod += 1

    out = OrderedDict()
    out["days"] = len(days)
    out["final_money"] = round(days[-1]["end_money"], 1)
    out["avg_daily_delta"] = round(sum(d["money_delta"] for d in days) / len(days), 1)
    out["idle_steps"] = idle_steps
    out["idle_pct"] = f"{100.0 * idle_steps / total_steps:.1f}%" if total_steps else "n/a"
    out["idle_by_day"] = {d["day"]: d["idle_turns"] for d in days if d["idle_turns"]}
    out["idle_units_ready_total"] = sum(d.get("idle_units_ready", 0) for d in days)
    out["shed_pressure_days"] = shed_pressure_days
    out["shed_overflow_days"] = shed_overflow_days
    out["discarded_units_total"] = sum(d.get("discarded_units", 0) for d in days)
    out["max_shed_total"] = max((d["max_shed_total"] for d in days), default=0)
    out["floor_sales"] = dict(sorted(floor_sales.items()))
    out["below_base_sales"] = dict(sorted(below_base.items()))
    out["sell_qty"] = dict(sorted(sell_qty.items()))
    out["animal_escapes"] = animal_escapes
    out["plants_died_to_weeds"] = plants_died
    out["harvests_total"] = sum(sum(d["plants_harvested"].values()) for d in days) + sum(d["harvests_unknown"] for d in days)
    out["weeds_peak"] = weeds_max
    out["unfed_animal_signals"] = unfed_eod
    out["unwatered_crop_eod"] = unwatered_eod
    out["missed_harvest_eod"] = missed_harvest_eod
    out["hires_total"] = sum(d["hires"] for d in days)
    out["land_unlocks_total"] = sum(d["land_unlocks"] for d in days)
    out["revenue_total"] = round(sum(d["revenue"] for d in days), 1)
    out["expenses_total"] = round(sum(d["expenses"] for d in days), 1)
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_money(v: float) -> str:
    return f"{v:,.0f}"


def _tile_char(t):
    if t is None:
        return "."
    if t == "LOCKED":
        return "#"
    if isinstance(t, dict):
        k = t.get("kind")
        if k == "WEED":
            return "x"
        if k == "PLANT":
            return t["crop"][0].lower()
        if "animal" in t:
            return t["animal"][0]
        if k == "COOP":
            return "C"
        if k == "PASTURE":
            return "P"
    return "?"


def render_map(tiles: List[List[Any]], title: str = ""):
    if title:
        print(title)
    header = "    " + " ".join(str(i % 10) for i in range(len(tiles[0])))
    print(header)
    for y, row in enumerate(tiles):
        print(f" {y:2d}  " + " ".join(_tile_char(t) for t in row))


def render_day(day: Dict[str, Any], frames: Optional[List[Dict[str, Any]]] = None):
    print(f"\n=== Day {day['day']:2d}  steps {day['first_step']}-{day['last_step']} ===")
    print(f"  money  ${_fmt_money(day['start_money'])} -> {_fmt_money(day['end_money'])}  "
          f"delta {_fmt_money(day['money_delta'])}  (rev {_fmt_money(day['revenue'])}  exp {_fmt_money(day['expenses'])})")
    print(f"  shed   {day['start_shed_total']} -> {day['end_shed_total']}  max {day['max_shed_total']}")
    print(f"  weeds  {day['weeds_start']} -> {day['weeds_end']}  max {day['weeds_max']}")
    print(f"  hands  {day['hands_start']} -> {day['hands_end']}  hires {day['hires']}  land {day['land_unlocks']}  "
          f"shops {day['shop_unlocks']}")
    if day["plants_planted"]:
        print(f"  planted {dict(day['plants_planted'])}")
    if day["plants_harvested"]:
        print(f"  harvested {dict(day['plants_harvested'])}")
    if day["animals_placed"]:
        print(f"  placed {dict(day['animals_placed'])}")
    if day["market_orders"]:
        print(f"  market orders {len(day['market_orders'])}")
    if day["idle_turns"]:
        print(f"  !!! idle turns: {day['idle_turns']}")
    if day["floor_sales"]:
        print(f"  !!! floor sales: {dict(day['floor_sales'])}")
    if day["animals_escaped"]:
        print(f"  !!! animal escapes: {day['animals_escaped']}")
    if day["plants_died"]:
        print(f"  !!! plants died to weeds: {day['plants_died']}")
    if frames:
        # End-of-day map
        last = [f for f in frames if f["day"] == day["day"]][-1]
        render_map(last["tiles"], title=f"  end-of-day map (crops={len(last['crops'])}, animals={len(last['animals'])}, weeds={last['weeds']})")


def render(days: List[Dict[str, Any]], frames: Optional[List[Dict[str, Any]]] = None, span: Optional[slice] = None):
    if frames is None:
        frames = []
    if span is not None:
        days = days[span]
    for day in days:
        render_day(day, frames)
    print("\n--- summary ---")
    for k, v in summarize(days, frames).items():
        print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key + "_"))
        elif isinstance(v, list):
            out[key] = json.dumps(v)
        else:
            out[key] = v
    return out


def _day_columns() -> List[str]:
    """Canonical, stable day column set — identical columns on every run so
    runs (old vs new, and across seeds) can be diffed directly."""
    cols = [
        "agent", "opponent", "seed",
        "day", "first_step", "last_step",
        "start_money", "end_money", "money_delta",
        "revenue", "expenses", "seed_cost", "animal_cost", "product_cost",
        "start_shed_total", "end_shed_total", "max_shed_total",
        "weeds_start", "weeds_end", "weeds_max",
        "hands_start", "hands_end", "hires", "hire_cost",
        "land_unlocks", "land_cost",
        "idle_turns", "n_pass", "n_move",
        "plants_watered", "plants_fertilized", "plants_died", "harvests_unknown",
        "animals_fed", "animals_cared", "animals_escaped", "fertilizer_collected",
        "shop_unlocks", "market_orders",
        "sell_qty_source", "discarded_units", "idle_units_ready",
    ]
    for p in PRODUCTS:
        cols += [f"sell_qty_{p}", f"floor_sales_{p}", f"below_base_sales_{p}",
                 f"revenue_{p}", f"avg_price_{p}"]
    shed_items = sorted(set(PRODUCTS) | set(ANIMALS))  # animals live in the shed
    for it in shed_items:
        cols += [f"shed_items_start_{it}", f"shed_items_end_{it}", f"shed_deltas_{it}"]
    buy_items = sorted(set(PRODUCTS) | set(CROPS) | set(ANIMALS))
    for it in buy_items:
        cols += [f"buy_qty_{it}"]
    for c in CROPS:
        cols += [f"seed_deltas_{c}", f"plants_planted_{c}", f"plants_harvested_{c}"]
    for a in ANIMALS:
        cols += [f"animals_placed_{a}"]
    return cols


def _game_columns() -> List[str]:
    return ["agent", "opponent", "seed",
            "final_money", "opponent_final", "result",
            "idle_steps", "shed_pressure_days", "shed_overflow_days",
            "floor_sales", "animal_escapes", "plants_died", "harvests",
            "weeds_peak", "unfed_signals", "unwatered_eod", "missed_harvest_eod",
            "discarded_units_total", "idle_units_ready_total"]


def write_csv_days(days: List[Dict[str, Any]], path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not days:
        return
    rows = []
    for d in days:
        dd = dict(d)
        # Collapse the raw order list to a count so the column stays a scalar.
        dd["market_orders"] = len(d.get("market_orders") or [])
        rows.append(_flatten(dd))
    fieldnames = _day_columns()
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# Replay -> frames / days helper
# ---------------------------------------------------------------------------


def replay_to_record(replay: Dict[str, Any], seat: int = 0) -> List[Tuple[Dict, Dict]]:
    record = []
    for i, step_data in enumerate(replay.get("steps", [])):
        state = step_data[seat]
        obs = state.get("observation", {})
        act = state.get("action") or {}   # an opponent's action may be None
        if obs is None or not isinstance(obs, dict):
            obs = {}
        obs = dict(obs)
        # The observer's observation carries `step`/`day`/`hour`; the opponent's
        # stored observation may omit them. Fall back to the step index so day
        # attribution and hour work for every seat.
        obs.setdefault("step", i)
        record.append((obs, act))
    return record


def replay_to_summary(replay: Dict[str, Any], seat: int = 0) -> Tuple[List[Dict], List[Dict], OrderedDict]:
    record = replay_to_record(replay, seat)
    frames = build_frames(record, seat)
    audit = replay.get("_diagnose_meta", {}).get("audit")
    if audit:
        # JSON turns integer keys into strings; rebuild them.
        audit = {
            int(step): {int(s): v for s, v in (seats or {}).items()}
            for step, seats in audit.items()
        }
    days = build_days(frames, audit=audit)
    summary = summarize(days, frames)
    return frames, days, summary


# ---------------------------------------------------------------------------
# Per-game compact summary (for terminal tables, no cross-game aggregation)
# ---------------------------------------------------------------------------


def game_summary(path: Path, seat: Optional[int] = None) -> Dict[str, Any]:
    """Return a compact dict of key metrics for a single replay file.

    Analyzes the agent under test (meta seat, or seat 0 for legacy runs), and
    also reports the opponent's final revenue plus a WIN / LOSS / TIE tag."""
    replay = load_replay(path)
    meta = replay.get("_diagnose_meta", {})
    if seat is None:
        seat = _agent_seat(replay)
    opp_seat = 1 - seat
    _, days, summary = replay_to_summary(replay, seat)
    our_final = summary.get("final_money", 0)
    opp_final = None
    try:
        opp_final = replay["steps"][-1][opp_seat].get("reward")
        if opp_final is not None and isinstance(opp_final, (int, float)):
            opp_final = round(float(opp_final), 1)
    except Exception:
        opp_final = None
    if opp_final is None:
        result = "?"
    elif our_final > opp_final:
        result = "WIN"
    elif our_final < opp_final:
        result = "LOSS"
    else:
        result = "TIE"
    return {
        "agent": meta.get("agent", "unknown"),
        "opponent": meta.get("opponent", "unknown"),
        "seed": meta.get("seed", "unknown"),
        "final_money": our_final,
        "opponent_final": opp_final if opp_final is not None else "",
        "result": result,
        "idle_steps": summary.get("idle_steps", 0),
        "shed_pressure_days": summary.get("shed_pressure_days", 0),
        "shed_overflow_days": summary.get("shed_overflow_days", 0),
        "floor_sales": sum(summary.get("floor_sales", {}).values()),
        "animal_escapes": summary.get("animal_escapes", 0),
        "plants_died": summary.get("plants_died_to_weeds", 0),
        "harvests": summary.get("harvests_total", 0),
        "weeds_peak": summary.get("weeds_peak", 0),
        "unfed_signals": summary.get("unfed_animal_signals", 0),
        "unwatered_eod": summary.get("unwatered_crop_eod", 0),
        "missed_harvest_eod": summary.get("missed_harvest_eod", 0),
        "discarded_units_total": summary.get("discarded_units_total", 0),
        "idle_units_ready_total": summary.get("idle_units_ready_total", 0),
    }


def print_game_table(rows: List[Dict[str, Any]]):
    if not rows:
        return
    cols = ["agent", "opponent", "seed", "final_money", "opponent_final", "result",
            "idle_steps", "shed_pressure_days", "floor_sales", "animal_escapes",
            "plants_died", "weeds_peak", "unfed_signals", "unwatered_eod",
            "discarded_units_total", "idle_units_ready_total"]
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    header = "  ".join(c.rjust(widths[c]) for c in cols)
    print(header)
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).rjust(widths[c]) for c in cols))


def narrative_summary(days: List[Dict[str, Any]], frames: Optional[List[Dict[str, Any]]] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Return a concise, LLM-readable narrative of a single replay."""
    s = summarize(days, frames)
    lines = []
    meta = metadata or {}
    lines.append(f"# Kaggriculture replay summary")
    lines.append(f"- Agent: {meta.get('agent', 'unknown')} vs {meta.get('opponent', 'unknown')} (seat {meta.get('seat', 0)})")
    lines.append(f"- Seed: {meta.get('seed', 'unknown')}, Steps: {meta.get('episode_steps', EPISODE_STEPS)}")
    lines.append(f"- Final money: ${s['final_money']:,.0f} over {s['days']} days (avg daily delta ${s['avg_daily_delta']:+,.0f})")
    lines.append("")
    lines.append("## Economic performance")
    lines.append(f"- Total revenue: ${s['revenue_total']:,.0f}")
    lines.append(f"- Total expenses: ${s['expenses_total']:,.0f}")
    lines.append(f"- Hires: {s['hires_total']} | Land unlocks: {s['land_unlocks_total']}")
    lines.append("")
    lines.append("## Inefficiency signals")
    lines.append(f"- Idle steps: {s['idle_steps']} ({s['idle_pct']})")
    lines.append(f"- Shed pressure days (>=95): {s['shed_pressure_days']} | Overflow days (=100): {s['shed_overflow_days']} | Max shed: {s['max_shed_total']}")
    lines.append(f"- Floor-price sales: {s['floor_sales']}")
    lines.append(f"- Below-base sales: {s['below_base_sales']}")
    lines.append(f"- Animal escape events: {s['animal_escapes']} | Unfed-animal signals: {s['unfed_animal_signals']}")
    lines.append(f"- Plants died to weeds: {s['plants_died_to_weeds']} | Harvests: {s['harvests_total']} | Unwatered at end-of-day: {s['unwatered_crop_eod']} | Missed harvests at EOD: {s['missed_harvest_eod']}")
    lines.append(f"- Weed peak count: {s['weeds_peak']}")
    lines.append("")
    lines.append("## Day-by-day money curve")
    for d in days:
        delta = d['money_delta']
        delta_str = f"{delta:+,.0f}"
        lines.append(f"- Day {d['day']:2d}: ${d['end_money']:>9,.0f}  delta {delta_str:>10s}  "
                     f"shed {d['max_shed_total']:>3d}  weeds {d['weeds_max']:>2d}  "
                     f"idle {d['idle_turns']:>2d}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Batch runner + CLI
# ---------------------------------------------------------------------------


def _new_run_dir() -> Path:
    idx = 1
    while True:
        p = REPLAY_ROOT / f"run-{idx}"
        if not p.exists():
            return p
        idx += 1


def _parse_pa_arg(arg: str) -> List[int]:
    """Parse --pa '1' or '1,2,3' or '1-3'."""
    out = []
    for part in arg.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def _make_seeds(n_seeds: int, seed: Optional[int]) -> List[int]:
    """Seed set for a run.

    With --seed given: use seed, seed+1, ... seed+n-1 literally (deterministic,
    and the passed value is used verbatim). Without it: random seeds.
    """
    if seed is None:
        return [random.randint(0, 1_000_000_000) for _ in range(n_seeds)]
    return [seed + i for i in range(n_seeds)]


def batch_run(
    agent: Callable,
    agent_label: str,
    pa_indices: List[int],
    n_seeds: int,
    run_dir: Path,
    episode_steps: int = EPISODE_STEPS,
    seed: Optional[int] = None,
):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    seeds = _make_seeds(n_seeds, seed)
    saved = []
    for pa in pa_indices:
        opp = load_public_agent(pa)
        opp_name = PUBLIC_AGENT_MAP[pa][0]
        for s in seeds:
            env = run_game(agent, opp, seed=s, episode_steps=episode_steps, seat=TEST_SEAT, audit=True)
            meta = {
                "agent": agent_label,
                "opponent": opp_name,
                "opponent_idx": pa,
                "seed": s,
                "seat": TEST_SEAT,
                "episode_steps": episode_steps,
            }
            path = run_dir / f"{agent_label}_vs_{opp_name}_seed{s}.json"
            save_replay(env, path, meta)
            saved.append(path)
            reward = env.steps[-1][TEST_SEAT].reward
            print(f"  saved {path.name}  reward={reward:.0f}")
    return saved, seeds


def compare_batch(
    pa_indices: List[int],
    n_seeds: int,
    run_dir: Path,
    episode_steps: int = EPISODE_STEPS,
    seed: Optional[int] = None,
):
    """Run old and new agents against the same (shared) seeds and public agents."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    seeds = _make_seeds(n_seeds, seed)
    old_agent, new_agent = load_old_and_new(fresh=True)
    results = {"old": [], "new": []}
    for pa in pa_indices:
        opp = load_public_agent(pa)
        opp_name = PUBLIC_AGENT_MAP[pa][0]
        for label, agent in (("old", old_agent), ("new", new_agent)):
            for s in seeds:
                env = run_game(agent, opp, seed=s, episode_steps=episode_steps, seat=TEST_SEAT, audit=True)
                meta = {
                    "agent": label,
                    "opponent": opp_name,
                    "opponent_idx": pa,
                    "seed": s,
                    "seat": TEST_SEAT,
                    "episode_steps": episode_steps,
                }
                path = run_dir / f"{label}_vs_{opp_name}_seed{s}.json"
                save_replay(env, path, meta)
                results[label].append(path)
                reward = env.steps[-1][TEST_SEAT].reward
                print(f"  saved {path.name}  reward={reward:.0f}")
    return results, seeds


def _agent_seat(replay) -> int:
    """The seat occupied by the agent under test (defaults to TEST_SEAT)."""
    return int(replay.get("_diagnose_meta", {}).get("seat", TEST_SEAT))


def _money_curve(path: Path):
    replay = load_replay(path)
    _, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
    return {d["day"]: d["end_money"] for d in days}


def ab_delta_report(paths: List[Path], per_day: bool = False):
    """Print same-seed old-vs-new deltas for a compare run."""
    from collections import defaultdict
    pairs = defaultdict(lambda: {"old": None, "new": None})
    for p in paths:
        meta = load_replay(p).get("_diagnose_meta", {})
        pairs[(meta.get("opponent"), meta.get("seed"))][meta.get("agent")] = p

    print("\n--- A/B old vs new (same seeds) ---")
    cols = ["opponent", "seed", "old_final", "new_final", "delta",
            "idle_delta", "floor_delta", "unwatered_delta", "escapes_delta", "harvest_delta"]
    rows = []
    for key, d in sorted(pairs.items()):
        if not d["old"] or not d["new"]:
            continue
        o = game_summary(d["old"]); n = game_summary(d["new"])
        rows.append({
            "opponent": key[0], "seed": key[1],
            "old_final": o["final_money"], "new_final": n["final_money"],
            "delta": n["final_money"] - o["final_money"],
            "idle_delta": n["idle_steps"] - o["idle_steps"],
            "floor_delta": n["floor_sales"] - o["floor_sales"],
            "unwatered_delta": n["unwatered_eod"] - o["unwatered_eod"],
            "escapes_delta": n["animal_escapes"] - o["animal_escapes"],
            "harvest_delta": n["harvests"] - o["harvests"],
        })
    if rows:
        widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
        print("  ".join(c.rjust(widths[c]) for c in cols))
        print("  ".join("-" * widths[c] for c in cols))
        for r in rows:
            print("  ".join(str(r.get(c, "")).rjust(widths[c]) for c in cols))
    else:
        print("  (no paired old/new replays found)")

    if per_day:
        for key, d in sorted(pairs.items()):
            if not d["old"] or not d["new"]:
                continue
            om = _money_curve(d["old"]); nm = _money_curve(d["new"])
            print(f"\n  per-day money (opponent={key[0]}, seed={key[1]})")
            print("    day     old       new        Δ")
            for day in sorted(set(om) | set(nm)):
                o = om.get(day, 0); n = nm.get(day, 0)
                print(f"    {day:3d}  {o:>9,.0f}  {n:>9,.0f}  {n - o:>9,}")
    return rows


def write_run_csv(run_dir: Path, paths: List[Path]):
    """Write per-seed days CSVs and games.csv for the agent under test.

    - days_seed<S>.csv — per-day view of OUR agent (its stored seat, normally 1);
      one file per distinct seed, so each game's daily data stays separated.
    - games.csv         — one compact row per replay for OUR agent (includes the
      opponent's final revenue and a WIN / LOSS / TIE tag).

    Per-step detail stays in the JSON replays (no steps.csv).
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    days_by_seed: Dict[str, List[Dict[str, Any]]] = {}
    games_rows = []
    for path in paths:
        replay = load_replay(path)
        meta = replay.get("_diagnose_meta", {})
        agent_seat = _agent_seat(replay)
        _, days, _ = replay_to_summary(replay, seat=agent_seat)
        games_rows.append(game_summary(path))
        seed = str(meta.get("seed", "unknown"))
        base = {
            "agent": meta.get("agent", "unknown"),
            "opponent": meta.get("opponent", "unknown"),
            "seed": meta.get("seed", "unknown"),
        }
        seed_rows = days_by_seed.setdefault(seed, [])
        for d in days:
            row = dict(base)
            dd = dict(d)
            dd["market_orders"] = len(d.get("market_orders") or [])
            row.update(_flatten(dd))
            seed_rows.append(row)

    def _write(rows, name, cols):
        if not rows:
            return
        path = run_dir / name
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {path.name} ({len(rows)} rows)")

    for seed in sorted(days_by_seed):
        _write(days_by_seed[seed], f"days_seed{seed}.csv", _day_columns())
    _write(games_rows, "games.csv", _game_columns())


def cli():
    parser = argparse.ArgumentParser(description="Kaggriculture diagnostic harness")
    parser.add_argument("--old", action="store_true", help="Run the old/main.py agent")
    parser.add_argument("--new", action="store_true",
                        help="Run main.py patched with agent.py (runs everything in main + patch)")
    parser.add_argument("--compare", action="store_true", help="A/B old vs new on the same seeds")
    parser.add_argument("--pa", default="1", help="Public agent indices, e.g. 1,2,3 or 1-3")
    parser.add_argument("--batch", type=int, default=1, help="Number of seeds per opponent")
    parser.add_argument("--seed", type=int, default=None,
                        help="Fixed seed for a deterministic run (used verbatim: seed, seed+1, ...)")
    parser.add_argument("--run-dir", help="Directory to save replays (default: next diag-replays/run-N)")
    parser.add_argument("--replay-dir", help="Diagnose saved replays instead of running games")
    parser.add_argument("--render", action="store_true", help="Print full day-by-day report for the last replay")
    parser.add_argument("--llm", action="store_true", help="Write per-game narrative .md files")
    args = parser.parse_args()

    if args.replay_dir:
        run_dir = Path(args.replay_dir)
        paths = sorted(run_dir.glob("*.json"))
        if not paths:
            print(f"No replay JSONs found in {run_dir}")
            return
        write_run_csv(run_dir, paths)
        rows = [game_summary(p) for p in paths]
        print("\nPer-game summary:")
        print_game_table(rows)
        if args.render and paths:
            replay = load_replay(paths[-1])
            frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
            print(f"\n--- rendered: {paths[-1].name} ---")
            render(days, frames)
        return

    pa_indices = _parse_pa_arg(args.pa)
    for pa in pa_indices:
        if pa not in PUBLIC_AGENT_MAP:
            print(f"Unknown public agent #{pa}. Available:\n{public_agent_names()}")
            sys.exit(1)

    run_dir = Path(args.run_dir) if args.run_dir else _new_run_dir()
    print(f"Saving replays to {run_dir}")

    if args.compare:
        results, seeds = compare_batch(pa_indices, args.batch, run_dir, seed=args.seed)
        all_paths = results["old"] + results["new"]
        write_run_csv(run_dir, all_paths)
        print("\nPer-game summary:")
        rows = [game_summary(p) for p in all_paths]
        print_game_table(rows)
        ab_delta_report(all_paths, per_day=args.render)
        if args.render and all_paths:
            replay = load_replay(all_paths[-1])
            frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
            print(f"\n--- rendered: {all_paths[-1].name} ---")
            render(days, frames)
        if args.llm:
            for p in all_paths:
                replay = load_replay(p)
                frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
                md_path = p.with_suffix(".md")
                md_path.write_text(narrative_summary(days, frames, metadata=replay.get("_diagnose_meta", {})))
                print(f"  wrote {md_path.name}")
        return

    if args.new and args.old:
        print("Use --compare for both; use only --old or --new otherwise.")
        sys.exit(1)
    if args.new:
        agent = load_new_agent(fresh=True)
        label = "new"
    else:
        agent = load_old_agent(fresh=True)
        label = "old"

    saved, seeds = batch_run(agent, label, pa_indices, args.batch, run_dir, seed=args.seed)
    write_run_csv(run_dir, saved)
    print("\nPer-game summary:")
    rows = [game_summary(p) for p in saved]
    print_game_table(rows)

    if args.render and saved:
        sample = saved[-1]
        replay = load_replay(sample)
        frames, days, _ = replay_to_summary(replay, seat=0)
        print(f"\n--- rendered: {sample.name} ---")
        render(days, frames)

    if args.llm and saved:
        for p in saved:
            replay = load_replay(p)
            frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
            md_path = p.with_suffix(".md")
            md_path.write_text(narrative_summary(days, frames, metadata=replay.get("_diagnose_meta", {})))
            print(f"  wrote {md_path.name}")


if __name__ == "__main__":
    cli()
