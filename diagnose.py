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
    --xray           investigate a patch's mechanism on the same seed: (1) every step
                     where agent.patch() directly rewrote the action, (2) every step
                     where the old and new games diverge (tagged PATCH-DIRECT vs
                     cascade), (3) day-by-day money curves. Use with --pa/--seed/--batch.
    --graph          render dashboards from SAVED replays: (a) a 1×2 side-by-side
                     PNG, LEFT = our agent / RIGHT = the opponent, each a vertical
                     stack (shed vs 100-cap + weeds, market prices with
                     shop ticks AND realised-sale dots, per-day defect swimlane, end-of-day
                     money) on a shared day axis; (b) an animated farm-board GIF
                     (`_board.gif`) — one frame per day showing BOTH farms' 10×10
                     maps (crops/animals/weeds/structures) plus farmer/hand position
                     dots and a money-race panel, so you can WATCH when a defect
                     appears instead of reading a static PNG. Uses
                     --replay-dir, or the most recent run dir. Per-game, never averaged.
                     Headless Agg.
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
import copy
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


_TAPE_SELECTED = "v1"  # "v1" -> route_tape.py, "v2" -> route_tape_v2.py


def _tape_module():
    return "route_tape" if _TAPE_SELECTED == "v1" else "route_tape_v2"


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
                    "discard_items": defaultdict(int),
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
    def _inv_totals(private):
        tot = {}
        for inv in (private["inventories"] or []):
            for item, n in (inv or {}).items():
                tot[item] = tot.get(item, 0) + n
        return tot

    @staticmethod
    def _discard_items(private, before_inv, before_shed):
        """Per-item units that left inventory but were not deposited into the shed.

        The env's DROP / deposit paths discard anything that does not fit in the
        shed; this isolates WHICH item overflowed (e.g. all-fertilizer gluts),
        not just a scalar count.
        """
        after_inv = _MarketAudit._inv_totals(private)
        after_shed = dict(private["shed"])
        items = set(before_inv) | set(before_shed) | set(after_inv) | set(after_shed)
        out = {}
        for it in items:
            inv_dec = before_inv.get(it, 0) - after_inv.get(it, 0)
            shed_inc = after_shed.get(it, 0) - before_shed.get(it, 0)
            d = max(0, inv_dec - shed_inc)
            if d:
                out[it] = d
        return out

    def _apply_unit_action(self, farm, private, idx, action, board_size, day, turns_per_day, shed_capacity=100):
        op = action[0] if isinstance(action, list) and action else None
        # Only deposit paths can overflow: DROP, and PLACE of a non-animal via
        # the shed-adjacent branch.  FEED/FERTILIZE/PLACE-animal also consume
        # inventory but are legitimate uses, not discards.
        deposit = op == "DROP" or (
            op == "PLACE" and len(action) > 1 and action[1] not in ANIMALS
        )
        before_inv = self._inv_totals(private)
        before_shed = dict(private["shed"])
        self._orig_ua(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity)
        if not deposit:
            return
        discarded = self._discard_items(private, before_inv, before_shed)
        if discarded:
            step = self._ctx.get("step")
            seat = self._seat(private=private)
            if step is not None and seat is not None:
                self.events[step][seat]["discards"] += sum(discarded.values())
                for it, n in discarded.items():
                    self.events[step][seat]["discard_items"][it] += n

    def _drop_inventories_to_shed(self, private, capacity):
        before_inv = self._inv_totals(private)
        before_shed = dict(private["shed"])
        self._orig_drop(private, capacity)
        discarded = self._discard_items(private, before_inv, before_shed)
        if discarded:
            step = self._ctx.get("step")
            seat = self._seat(private=private)
            if step is not None and seat is not None:
                self.events[step][seat]["discards"] += sum(discarded.values())
                for it, n in discarded.items():
                    self.events[step][seat]["discard_items"][it] += n


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
        "animals_escaped_by": defaultdict(int),
        "weeds_start": 0,
        "weeds_end": 0,
        "weeds_max": 0,
        "idle_turns": 0,
        "idle_units": 0,
        "idle_units_ready": 0,
        "unit_turns": 0,
        "floor_sales": defaultdict(int),
        "below_base_sales": defaultdict(int),
        "sell_qty": defaultdict(int),
        "revenue_per_item": defaultdict(float),
        "avg_price_per_item": {},
        "sell_qty_source": "requested",
        "discarded_units": 0,
        "discarded_items": defaultdict(int),
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

        # Every live work-unit is one turn of (potential) labour; PASS = idle.
        day["unit_turns"] += f["n_hands"] + 1
        # Idle = every unit passes and no market orders (a whole idle turn; rare)
        all_pass = all(_op_name(ua) == "PASS" for _, ua in _unit_actions({"farmer": f["farmer"], "hands": f["hands"]}))
        if all_pass and not f["market_orders"]:
            day["idle_turns"] += 1

        # Unit-level idle: PASS on any tile (idle_units), plus PASS while standing
        # on ready produce / animal (idle_units_ready). idle_share = idle/unit-turns
        # is the real labour-efficiency signal; idle_turns understates it badly.
        for pos, cmd in zip([f["farmer_pos"], *f["hand_positions"]], [f["farmer"], *f["hands"]]):
            if _op_name(cmd) == "PASS":
                day["idle_units"] += 1
                if _tile_ready(f["tiles"][pos[1]][pos[0]], f["day"]):
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
            for it, n in (step_audit.get("discard_items") or {}).items():
                day["discarded_items"][it] += n
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
                day["animals_escaped_by"][fr.get("animal")] += 1
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
        day["discarded_items"] = dict(day["discarded_items"])
        day["animals_escaped_by"] = dict(day["animals_escaped_by"])
        # Real labour efficiency: idle share (idle_turns is a rare whole-turn idle).
        day["idle_share_pct"] = round(100.0 * day["idle_units"] / day["unit_turns"], 1) if day["unit_turns"] else 0.0
        # Feed self-sufficiency. Harvest attribution is unreliable (see
        # _crop_at_actor -> harvests_unknown), so wheat produced is ESTIMATED from
        # the reliable audit flows: produced = sold + fed - bought.
        day["wheat_sold"] = day["sell_qty"].get("WHEAT", 0)
        day["wheat_bought"] = day["buy_qty"].get("WHEAT", 0)
        day["wheat_fed"] = day["animals_fed"]
        # Daily wheat net (sold+fed-bought); can be negative on buy-heavy days.
        # The authoritative produced total is computed in summarize() from the
        # game totals, because harvest attribution is unreliable.
        day["feed_surplus"] = day["wheat_sold"] + day["wheat_fed"] - day["wheat_bought"]
        # Premium-good below-base realisation fraction (glut-crash detection).
        _prem = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
        _prem_sold = sum(day["sell_qty"].get(p, 0) for p in _prem)
        _prem_below = sum(day["below_base_sales"].get(p, 0) for p in _prem)
        day["premium_below_base_frac"] = round(_prem_below / _prem_sold, 3) if _prem_sold else 0.0
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
    at_risk_escape = 0
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
            # Near-escape (>=2 consecutive unfed) counted once regardless of hour.
            for a in f["animals"]:
                if a.get("consecutive_unfed", 0) >= 2:
                    at_risk_escape += 1

    # Endgame hygiene: dollars stranded at the bell (destbreso's x-ray "stranded
    # $" macro indicator). Unsold inventory does NOT count toward the score, so
    # shed + unit inventories still holding sellable product at FINAL prices is
    # money that died in the shed. Animals are structures, not sellable stock, so
    # they are excluded (they also live in the shed slot).
    stranded = 0
    locked_steps = 0
    locked_units_at_bell = 0
    if frames:
        lp = frames[-1].get("prices", {})
        _shed = frames[-1].get("shed", {}) or {}
        for k, v in _shed.items():
            if k not in ANIMALS:
                stranded += v * lp.get(k, 0)
        for inv in (frames[-1].get("inventories", []) or []):
            for k, v in (inv or {}).items():
                if k not in ANIMALS:
                    stranded += v * lp.get(k, 0)
        # Locked-tile check: any farmer/hand step that stands on unbought (LOCKED)
        # land wastes a worker-turn (since 1.32.3 units can walk across unbought
        # tiles, a bot that routes through them leaves hands standing on locked tiles).
        for f in frames:
            tiles = f.get("tiles") or []
            for (x, y) in [f.get("farmer_pos")] + list(f.get("hand_positions") or []):
                try:
                    if tiles[y][x] == "LOCKED":
                        locked_steps += 1
                except (IndexError, TypeError):
                    pass
        lt = frames[-1].get("tiles") or []
        for (x, y) in [frames[-1].get("farmer_pos")] + list(frames[-1].get("hand_positions") or []):
            try:
                if lt[y][x] == "LOCKED":
                    locked_units_at_bell += 1
            except (IndexError, TypeError):
                pass

    out = OrderedDict()
    out["days"] = len(days)
    out["final_money"] = round(days[-1]["end_money"], 1)
    out["stranded_at_bell"] = round(stranded)
    out["locked_steps"] = locked_steps          # farmer/hand worker-turns standing on unbought land
    out["locked_units_at_bell"] = locked_units_at_bell  # workers still on unbought land at the bell
    out["avg_daily_delta"] = round(sum(d["money_delta"] for d in days) / len(days), 1)
    idle_units_total = sum(d.get("idle_units", 0) for d in days)
    unit_turns_total = sum(d.get("unit_turns", 0) for d in days)
    idle_share = (100.0 * idle_units_total / unit_turns_total) if unit_turns_total else 0.0
    out["idle_steps"] = idle_steps           # whole-turn idle (rare; low-signal)
    out["idle_share_pct"] = round(idle_share, 1)
    out["idle_pct"] = f"{idle_share:.1f}%"   # unit-level idle share (the real signal)
    out["idle_by_day"] = {d["day"]: d["idle_units"] for d in days if d.get("idle_units")}
    out["idle_units_total"] = idle_units_total
    out["idle_units_ready_total"] = sum(d.get("idle_units_ready", 0) for d in days)
    out["unit_turns_total"] = unit_turns_total
    out["shed_pressure_days"] = shed_pressure_days
    out["shed_overflow_days"] = shed_overflow_days
    out["discarded_units_total"] = sum(d.get("discarded_units", 0) for d in days)
    _di = defaultdict(int)
    for d in days:
        for it, n in d.get("discarded_items", {}).items():
            _di[it] += n
    out["discarded_items"] = dict(sorted(_di.items()))
    out["max_shed_total"] = max((d["max_shed_total"] for d in days), default=0)
    out["floor_sales"] = dict(sorted(floor_sales.items()))
    out["below_base_sales"] = dict(sorted(below_base.items()))
    out["sell_qty"] = dict(sorted(sell_qty.items()))
    out["animal_escapes"] = animal_escapes
    _eb = defaultdict(int)
    for d in days:
        for a, n in d.get("animals_escaped_by", {}).items():
            _eb[a] += n
    out["animals_escaped_by"] = dict(sorted(_eb.items()))
    out["plants_died_to_weeds"] = plants_died
    out["harvests_total"] = sum(sum(d["plants_harvested"].values()) for d in days) + sum(d["harvests_unknown"] for d in days)
    out["weeds_peak"] = weeds_max
    out["unfed_animal_signals"] = unfed_eod        # >=1 unfed at end-of-day
    out["unfed_at_eod"] = unfed_eod
    out["at_risk_of_escape"] = at_risk_escape       # >=2 consecutive unfed (no double count)
    out["unwatered_crop_eod"] = unwatered_eod
    out["missed_harvest_eod"] = missed_harvest_eod
    out["hires_total"] = sum(d["hires"] for d in days)
    out["land_unlocks_total"] = sum(d["land_unlocks"] for d in days)
    # Feed self-sufficiency (wheat cycle is the #1 lever). wheat_produced is an
    # estimate from reliable audit flows (sold+fed-bought); harvest attribution is
    # unreliable (see _crop_at_actor -> harvests_unknown).
    out["wheat_sold_total"] = sum(d.get("wheat_sold", 0) for d in days)
    out["wheat_fed_total"] = sum(d.get("wheat_fed", 0) for d in days)
    out["wheat_bought_total"] = sum(d.get("wheat_bought", 0) for d in days)
    wheat_produced = max(0, out["wheat_sold_total"] + out["wheat_fed_total"] - out["wheat_bought_total"])
    out["wheat_produced_total"] = wheat_produced
    out["feed_surplus_total"] = wheat_produced - out["wheat_fed_total"]
    out["wheat_market_dependence"] = out["wheat_bought_total"]
    # Economics: revenue from committed sells, expenses from itemized costs.
    # (The sign-split of money_delta mislabels both when a step both buys & sells.)
    sell_revenue = sum(sum(d.get(f"revenue_{p}", 0) for p in PRODUCTS) for d in days)
    item_costs = sum(
        d.get("seed_cost", 0) + d.get("animal_cost", 0) + d.get("product_cost", 0)
        + d.get("hire_cost", 0) + d.get("land_cost", 0)
        for d in days)
    out["sell_revenue_total"] = round(sell_revenue, 1)
    out["itemized_costs_total"] = round(item_costs, 1)
    out["seed_cost_total"] = round(sum(d.get("seed_cost", 0) for d in days), 1)
    out["animal_cost_total"] = round(sum(d.get("animal_cost", 0) for d in days), 1)
    out["product_cost_total"] = round(sum(d.get("product_cost", 0) for d in days), 1)
    out["hire_cost_total"] = round(sum(d.get("hire_cost", 0) for d in days), 1)
    out["land_cost_total"] = round(sum(d.get("land_cost", 0) for d in days), 1)
    out["revenue_total"] = round(sell_revenue, 1) if sell_revenue > 0 else round(sum(d["revenue"] for d in days), 1)
    out["expenses_total"] = round(item_costs, 1) if item_costs > 0 else round(sum(d["expenses"] for d in days), 1)
    # Premium-good below-base realisation fraction (glut-crash on strawberry/melon/milk/wool).
    _prem = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
    _prem_sold = sum(sum(d.get("sell_qty", {}).get(p, 0) for p in _prem) for d in days)
    _prem_below = sum(sum(d.get("below_base_sales", {}).get(p, 0) for p in _prem) for d in days)
    out["premium_below_base_frac"] = round(_prem_below / _prem_sold, 3) if _prem_sold else 0.0
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


def render_legend():
    """Print the legend for the 10×10 board grid and the per-day lines once, so a
    long --render report can be read without re-opening this file."""
    print("BOARD GRID LEGEND  (one char per tile; the 10×10 map is row 0 = top)")
    print("  '.' = open/owned tile     '#' = LOCKED (unbought)     'x' = WEED")
    print("  lowercase crop letter:  w wheat · c carrot · t tomato · s strawberry · m melon")
    print("  UPPERCASE animal letter: G goose · C cow · S sheep    C/P = empty COOP / PASTURE")
    print("  ? = unknown tile")
    print("DAY LINE FIELDS")
    print("  money start->end delta (rev/exp)   shed total   weeds   planted/harvested")
    print("  hands hired · land unlocked · shops unlocked   (! = a defect on that day)")



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
    render_legend()
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
        "idle_turns", "n_pass", "n_move", "idle_units", "unit_turns", "idle_share_pct",
        "plants_watered", "plants_fertilized", "plants_died", "harvests_unknown",
        "animals_fed", "animals_cared", "animals_escaped", "fertilizer_collected",
        "shop_unlocks", "market_orders",
        "sell_qty_source", "discarded_units", "idle_units_ready",
        "wheat_sold", "wheat_fed", "wheat_bought", "feed_surplus",
        "premium_below_base_frac",
    ]
    for p in PRODUCTS:
        cols += [f"sell_qty_{p}", f"floor_sales_{p}", f"below_base_sales_{p}",
                 f"revenue_{p}", f"avg_price_{p}"]
    shed_items = sorted(set(PRODUCTS) | set(ANIMALS))  # animals live in the shed
    for it in shed_items:
        cols += [f"shed_items_start_{it}", f"shed_items_end_{it}", f"shed_deltas_{it}",
                 f"discarded_items_{it}"]
    buy_items = sorted(set(PRODUCTS) | set(CROPS) | set(ANIMALS))
    for it in buy_items:
        cols += [f"buy_qty_{it}"]
    for c in CROPS:
        cols += [f"seed_deltas_{c}", f"plants_planted_{c}", f"plants_harvested_{c}"]
    for a in ANIMALS:
        cols += [f"animals_placed_{a}", f"animals_escaped_by_{a}"]
    return cols


def _game_columns() -> List[str]:
    return ["agent", "opponent", "seed",
            "final_money", "opponent_final", "result",
            "idle_steps", "idle_units_total", "idle_share_pct",
            "idle_units_ready_total", "shed_pressure_days", "shed_overflow_days",
            "discarded_units_total", "discarded_items", "floor_sales", "stranded_at_bell",
            "locked_steps", "locked_units_at_bell",
            "animal_escapes", "escaped_by_type", "plants_died", "harvests",
            "weeds_peak", "unfed_signals", "at_risk_of_escape", "unwatered_eod",
            "missed_harvest_eod",
            "seed_cost_total", "animal_cost_total", "product_cost_total",
            "hire_cost_total", "land_cost_total", "sell_revenue_total",
            "wheat_fed", "feed_surplus", "premium_below_base_frac"]

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
        "idle_units_total": summary.get("idle_units_total", 0),
        "idle_share_pct": summary.get("idle_share_pct", 0.0),
        "idle_units_ready_total": summary.get("idle_units_ready_total", 0),
        "shed_pressure_days": summary.get("shed_pressure_days", 0),
        "shed_overflow_days": summary.get("shed_overflow_days", 0),
        "discarded_units_total": summary.get("discarded_units_total", 0),
        "discarded_items": json.dumps(summary.get("discarded_items", {}), sort_keys=True),
        "floor_sales": sum(summary.get("floor_sales", {}).values()),
        "stranded_at_bell": summary.get("stranded_at_bell", 0),
        "locked_steps": summary.get("locked_steps", 0),
        "locked_units_at_bell": summary.get("locked_units_at_bell", 0),
        "animal_escapes": summary.get("animal_escapes", 0),
        "escaped_by_type": " ".join(f"{k}:{v}" for k, v in summary.get("animals_escaped_by", {}).items()),
        "plants_died": summary.get("plants_died_to_weeds", 0),
        "harvests": summary.get("harvests_total", 0),
        "weeds_peak": summary.get("weeds_peak", 0),
        "unfed_signals": summary.get("unfed_at_eod", 0),
        "at_risk_of_escape": summary.get("at_risk_of_escape", 0),
        "unwatered_eod": summary.get("unwatered_crop_eod", 0),
        "missed_harvest_eod": summary.get("missed_harvest_eod", 0),
        "seed_cost_total": summary.get("seed_cost_total", 0),
        "animal_cost_total": summary.get("animal_cost_total", 0),
        "product_cost_total": summary.get("product_cost_total", 0),
        "hire_cost_total": summary.get("hire_cost_total", 0),
        "land_cost_total": summary.get("land_cost_total", 0),
        "sell_revenue_total": summary.get("sell_revenue_total", 0),
        "wheat_fed": summary.get("wheat_fed_total", 0),
        "feed_surplus": summary.get("feed_surplus_total", 0),
        "premium_below_base_frac": summary.get("premium_below_base_frac", 0.0),
    }


def print_game_table(rows: List[Dict[str, Any]]):
    if not rows:
        return
    cols = ["agent", "opponent", "seed", "final_money", "opponent_final", "result",
            "idle_share_pct", "idle_units_total", "shed_pressure_days", "floor_sales",
            "animal_escapes", "at_risk_of_escape", "plants_died", "missed_harvest_eod",
            "feed_surplus", "sell_revenue_total", "premium_below_base_frac",
            "discarded_units_total", "unfed_signals", "unwatered_eod"]
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
    lines.append(f"- Sell revenue (committed): ${s['sell_revenue_total']:,.0f} | Itemized costs: ${s['itemized_costs_total']:,.0f}  (net ${s['sell_revenue_total'] - s['itemized_costs_total']:,.0f})")
    lines.append(f"- Costs: seeds ${s['seed_cost_total']:,.0f} | animals ${s['animal_cost_total']:,.0f} | product ${s['product_cost_total']:,.0f} | hiring ${s['hire_cost_total']:,.0f} | land ${s['land_cost_total']:,.0f}")
    lines.append(f"- Hires: {s['hires_total']} | Land unlocks: {s['land_unlocks_total']}")
    lines.append("")
    lines.append("## Inefficiency signals")
    lines.append(f"- Idle-labour share: {s['idle_pct']}  ({s['idle_units_total']} unit-PASS turns of {s['unit_turns_total']}, {s['idle_units_ready_total']} on ready produce)")
    lines.append(f"- Feed self-sufficiency: wheat produced* {s['wheat_produced_total']} | fed {s['wheat_fed_total']} | bought {s['wheat_bought_total']} | sold {s['wheat_sold_total']} | surplus {s['feed_surplus_total']:+.0f}   (*=net of audit flows; see AGENTS.md)")
    lines.append(f"- Shed pressure days (>=95): {s['shed_pressure_days']} | Overflow days (=100): {s['shed_overflow_days']} | Discarded items: {s['discarded_items']}")
    lines.append(f"- Floor-price sales: {s['floor_sales']} | Below-base sales: {s['below_base_sales']}")
    lines.append(f"- Premium below-base realized frac: {s['premium_below_base_frac']:.3f}")
    lines.append(f"- Animal escape events: {s['animal_escapes']} {s['animals_escaped_by']} | Unfed at EOD: {s['unfed_at_eod']} | At risk of escape: {s['at_risk_of_escape']}")
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


def _most_recent_run_dir() -> Optional[Path]:
    """Newest diag-replays/run-N holding replay JSONs (for --graph without --replay-dir)."""
    if not REPLAY_ROOT.exists():
        return None
    cands = sorted((p for p in REPLAY_ROOT.iterdir()
                    if p.is_dir() and (p / "*.json").glob and list(p.glob("*.json"))),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


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


def _paired_verdict(diffs):
    """Statistical verdict on paired per-seed deltas, following wins-not-money.

    Rule: keep the change iff (1) the mean delta is more than 2 standard errors
    from zero (|t| = |mean|/SE > 2) AND (2) a majority of seeds lean the same way
    as the mean. Aggregating per opponent first (never pooled) keeps the spread
    honest; pairing old/new on the SAME seed cancels that seed's luck.
    """
    import statistics as st
    import math
    diffs = [float(d) for d in diffs if d is not None]
    n = len(diffs)
    base = {"n": n, "mean": 0.0, "sd": 0.0, "se": 0.0, "t": 0.0,
            "frac_same_sign": 0.0, "keep": False, "note": ""}
    if n == 0:
        base["note"] = "no paired seeds"
        return base
    mean = sum(diffs) / n
    base["mean"] = mean
    if n == 1:
        base["mean"] = mean
        base["se"] = float("inf")
        base["note"] = "single paired seed — cannot estimate SE; re-run with more seeds (--batch 12)"
        return base
    sd = st.stdev(diffs)
    base["sd"] = sd
    se = sd / math.sqrt(n)
    base["se"] = se
    base["t"] = mean / se if se > 0 else float("inf") if mean != 0 else 0.0
    sign = 1 if mean > 0 else (-1 if mean < 0 else 0)
    if sign == 0:
        base["note"] = "zero mean — a change, not an effect"
        return base
    same = sum(1 for d in diffs if (d > 0) == (sign == 1))
    base["frac_same_sign"] = same / n
    mag_signif = abs(base["t"]) > 2.0 if base["t"] != float("inf") else (mean != 0)
    consensus = base["frac_same_sign"] > 0.5
    base["keep"] = bool(mag_signif and consensus)
    if not mag_signif:
        base["note"] = "mean within 2 SE of zero — no reliable effect"
    elif not consensus:
        base["note"] = "mean > 2 SE but seeds disagree in sign — treat with caution"
    else:
        base["note"] = "clear — mean > 2 SE and majority of seeds agree in sign"
    return base


def _print_verdict(lines, label):
    v = _paired_verdict([r["delta"] for r in lines])
    win_n = sum(1 for r in lines if r.get("result_new") == "WIN")
    tie_n = sum(1 for r in lines if r.get("result_new") == "TIE")
    loss_n = v["n"] - win_n - tie_n
    verdict = "KEEP" if v["keep"] else "REJECT"
    print(f"\n  {label}: n={v['n']}  mean Δ=${v['mean']:+,.0f}  "
          f"SE=${v['se']:,.0f}  t={v['t']:+.2f}  same-sign {v['frac_same_sign']:.0%}")
    print(f"            win {win_n} / tie {tie_n} / loss {loss_n}  →  {verdict} ({v['note']})")
    return v


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
            "result_old": o["result"], "result_new": n["result"],
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

    # Paired verdict across seeds — wins-not-money decision rule.
    from collections import defaultdict
    if rows:
        by_opp = defaultdict(list)
        for r in rows:
            by_opp[r["opponent"]].append(r)
        print("\n--- paired verdict (KEEP iff |mean Δ| > 2·SE AND majority of seeds agree in sign) ---")
        for opp in sorted(by_opp):
            _print_verdict(by_opp[opp], f"{opp}")
        print()
        _print_verdict(rows, "ALL OPPONENTS")
    return rows


# ---------------------------------------------------------------------------
# --xray — per-move / per-step / per-day investigation of what a patch changes
# ---------------------------------------------------------------------------


def _action_diff(day, step, old, new):
    """Return a human-readable diff between two actions, or None if equal."""
    if old == new:
        return None
    lines = []
    keys = set(old) | set(new)
    for k in sorted(keys, key=lambda x: {"farmer": 0, "hands": 1, "market": 2}.get(x, 9)):
        ov, nv = old.get(k), new.get(k)
        if ov != nv:
            lines.append(f"      {k}: old={ov if k != 'market' else _succinct_market(ov)}"
                         f" | new={nv if k != 'market' else _succinct_market(nv)}")
    return "\n".join(lines)


def _succinct_market(market):
    m = market or []
    return ";".join("".join(str(x) for x in o) if o else "_" for o in m)


def xray_game(pa: int, seed: int):
    """Run old (main.py) and new (main.py + agent.patch) on the same seed.

    Returns a dict with per-step action traces + the patch's before/after ledger
    so callers can print what changed (and where that first breaks).
    """
    main = _reload_main_if_needed(fresh=True)
    import agent as amod
    base = main._original_agent
    orig_patch = getattr(amod, "patch", None)
    if orig_patch is None:
        raise TypeError("agent.py must expose patch(action, observation, configuration=None)")

    opp = load_public_agent(pa)
    opp_name = PUBLIC_AGENT_MAP[pa][0]

    # --- old trace (every step's final action) ---
    old_acts = []

    def old_agent(obs, configuration=None):
        a = base(obs, configuration)
        old_acts.append(copy.deepcopy(a))
        return a

    # --- new trace + patch after/before ledger ---
    new_acts = []
    new_prices = []          # live market prices (new game) at each step
    patch_ledger = []        # list of (step, day, before, after)

    def rec_patch(action, observation, configuration=None):
        out = orig_patch(action, observation, configuration)
        return out

    def _mkt_prices(obs):
        try:
            return {k: int(v) for k, v in (obs.get("market", {}).get("prices", {}) or {}).items()}
        except Exception:
            return {}

    def new_agent(obs, configuration=None):
        raw = base(obs, configuration)
        new_prices.append(_mkt_prices(obs))
        patched = rec_patch(raw, obs, configuration)
        new_acts.append(copy.deepcopy(patched))
        patch_ledger.append(copy.deepcopy((raw, patched)))
        return patched

    env_old = run_game(old_agent, opp, seed=seed, episode_steps=EPISODE_STEPS, seat=TEST_SEAT, audit=True)
    env_new = run_game(new_agent, opp, seed=seed, episode_steps=EPISODE_STEPS, seat=TEST_SEAT, audit=True)

    # Build the patch "direct" ledger: steps where patch() returned something != input.
    # (raw, patched) rows are aligned to new_acts by step.
    direct = []
    for i, (raw, patched) in enumerate(patch_ledger):
        if raw != patched:
            direct.append(i)

    # Divergence: compare final old vs new action streams (both length 719).
    n = min(len(old_acts), len(new_acts))
    diverged = []
    for i in range(n):
        if old_acts[i] != new_acts[i]:
            diverged.append(i)

    return {
        "pa": pa, "opponent": opp_name, "seed": seed,
        "n": n,
        "old_final": env_old.steps[-1][TEST_SEAT].reward,
        "new_final": env_new.steps[-1][TEST_SEAT].reward,
        "old_acts": old_acts, "new_acts": new_acts, "new_prices": new_prices,
        "patch_ledger": patch_ledger,
        "direct_steps": direct,
        "divergence": diverged,
        "env_old": env_old, "env_new": env_new,
    }


def xray_report(x):
    """Print the xray investigation report for one game."""
    print(f"=== xray: {x['opponent']} seed {x['seed']} ===")
    print(f"  old final ${x['old_final']:.0f}  |  new final ${x['new_final']:.0f}  "
          f"|  delta {x['new_final'] - x['old_final']:+.0f}")

    # 1) patch ledger — steps where patch() itself changed the action.
    print("\n[1] patch() direct changes (agent.py moves), %d step(s):"
          % len(x["direct_steps"]))
    for i in x["direct_steps"]:
        raw, patched = x["patch_ledger"][i]
        diff = _action_diff(i // 24, i, raw, patched)
        stepno = i  # ledger index == step (agent called once/step for our seat)
        print(f"  step {stepno:3d} (day {stepno // 24:2d}):")
        print(diff or "      (structure equal: no visible diff)")
    # A patch may mutate state/tape at step 0 (returning the action unchanged)
    # rather than rewriting actions per-step — that shows up only as cascades.
    if not x["direct_steps"] and x.get("divergence"):
        print("  (no per-step action rewrites: the patch likely installs "
              "state/tape at step 0 and the effect surfaces as the cascade steps "
              "in [2])")

    # 2) old-vs-new divergence — where the two games first break apart.
    div = x["divergence"]
    first = div[0] if div else None
    print(f"\n[2] old-vs-new final action divergence: {len(div)} of {x['n']} steps differ"
          f"{' (first at step %d / day %d)' % (first, first // 24) if first is not None else ', identical'}")

    show = div[:40]
    if first is not None:
        direct_set = set(x["direct_steps"])
        for i in show:
            tag = "PATCH-DIRECT" if i in direct_set else "cascade"
            day = i // 24
            print(f"\n  step {i:3d} (day {day:2d}) [{tag}]")
            d = _action_diff(day, i, x["old_acts"][i], x["new_acts"][i])
            print(d)
            # If the market order set changed, show live prices for the items in play.
            om = x["old_acts"][i].get("market") or []
            nm = x["new_acts"][i].get("market") or []
            if d and (om != nm):
                prices = x["new_prices"][i] if i < len(x["new_prices"]) else {}
                sell_items = list(dict.fromkeys(o[1] for o in nm if o and o[0] == "SELL"))
                if sell_items:
                    shown = ", ".join(f"{it}:${prices.get(it, '?')}" for it in sell_items)
                    print(f"      [market prices] {shown}")
    if len(div) > len(show):
        print(f"  ... and {len(div) - len(show)} more changed steps (see --run-dir replays).")

    # 3) daily money curves.
    print("\n[3] day-by-day money (old vs new):")
    od = _money_curve_from_env(x["env_old"])
    nd = _money_curve_from_env(x["env_new"])
    first_day = (first // 24) if first is not None else None
    # Find the day where the money delta first becomes nonzero (or changes sign)
    # so the user can spot the day the patch's economic impact truly lands.
    print("    day     old       new        Δ")
    for day in sorted(set(od) | set(nd)):
        o = od.get(day, 0); n = nd.get(day, 0)
        mark = ""
        if first_day is not None and day == first_day:
            mark = "  <- first action divergence day"
        print(f"    {day:3d}  {o:>9,.0f}  {n:>9,.0f}  {n - o:>9,}{mark}")
    return x


def env_to_replay(env):
    """Return a replay (JSON-able dict) from a live env object."""
    try:
        return env.toJSON()
    except Exception:
        return {"steps": env.steps}


def _money_curve_from_env(env):
    """Return {day: end-of-day money} for TEST_SEAT from an env object via its replay."""
    try:
        _, days, _ = replay_to_summary(env_to_replay(env), seat=TEST_SEAT)
        return {d["day"]: d["end_money"] for d in days}
    except Exception:
        return {}


def xray_batch(pa_indices, seeds, run_dir):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for pa in pa_indices:
        if pa not in PUBLIC_AGENT_MAP:
            continue
        opp_name = PUBLIC_AGENT_MAP[pa][0]
        for seed in seeds:
            x = xray_game(pa, seed)
            meta_o = {"agent": "old", "opponent": opp_name, "opponent_idx": pa, "seed": seed,
                      "seat": TEST_SEAT, "episode_steps": EPISODE_STEPS}
            meta_n = {"agent": "new", "opponent": opp_name, "opponent_idx": pa, "seed": seed,
                      "seat": TEST_SEAT, "episode_steps": EPISODE_STEPS}
            po = run_dir / f"old_vs_{opp_name}_seed{seed}.json"
            pn = run_dir / f"new_vs_{opp_name}_seed{seed}.json"
            save_replay(x["env_old"], po, meta_o)
            save_replay(x["env_new"], pn, meta_n)
            xray_report(x)
            saved.extend([po, pn])
    return saved


# ---------------------------------------------------------------------------
# --graph — matplotlib per-game dashboards from saved replays
# ---------------------------------------------------------------------------
# Goal: turn a single saved replay into PNG figures that surface SYSTEM-LEVEL
# defects you can *see* at a specific step/day (per AGENTS.md anti-goal: never
# trust cross-game averages). Reads the exact replay JSON `--old/--new/--compare`
# writes, so no extra logging is required — every series below already exists in
# each step's observation.

# Products that crash straight to the $1 floor on oversupply (above_target > 1).
# Highlighting them + shop-unlock ticks makes glut/scarcity timing visible at a glance.
_SPIKEY_PRODUCTS = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
_SHOP_TITLE = {k: " ".join(w.title() for w in k.split("_")) for k in SHOPS}


def _tile_count_weeds(tiles):
    n = 0
    for row in tiles or []:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "WEED":
                n += 1
    return n


def _collect_step_series(replay):
    """One pass over a replay → per-step curves for BOTH seats + shared market.

    Returns dict (plain lists, index = step number 0..n-1):
      xs            step numbers              n_steps       number of steps
      money[seat]   money per step, per seat  shed[seat]    shed total per seat
      weeds[seat]   WEED count per seat       prices[p]     market price/step
      shop_steps    [(step, frozenset)] where the unlocked-shop set grew
    Prices/shops are shared by both players, so they are captured once (from the
    seat-0 observation). Money/shed/weeds are captured per seat.
    """
    steps = replay["steps"]
    xs = []
    money, shed, weeds = {0: [], 1: []}, {0: [], 1: []}, {0: [], 1: []}
    prices = {p: [] for p in PRODUCTS}
    shop_sets = []
    for idx, s in enumerate(steps):
        for seat in (0, 1):
            if seat >= len(s):
                money[seat].append(0.0); shed[seat].append(0); weeds[seat].append(0)
                if seat == 0:                      # keep axes length consistent
                    xs.append(idx)
                    for p in PRODUCTS:
                        prices[p].append(MARKET_PARAMS[p]["base"])
                    shop_sets.append(frozenset())
                continue
            o = s[seat].get("observation") or {}
            farms = o.get("farms") or []
            money[seat].append(farms[seat].get("money", 0.0) if seat < len(farms) else 0.0)
            shed[seat].append(_shed_total(o.get("private") or {}))
            me = farms[seat] if seat < len(farms) else {}
            weeds[seat].append(_tile_count_weeds(me.get("tiles", [])))
            if seat == 0:                          # shared market/town: read once
                px = (o.get("market") or {}).get("prices") or {}
                for p in PRODUCTS:
                    prices[p].append(px.get(p, MARKET_PARAMS[p]["base"]))
                town = o.get("town") or {}
                shop_sets.append(frozenset(town.get("unlocked_shops") or []))
                xs.append(idx)
    shop_steps, prev = [], frozenset()
    for i, ss in enumerate(shop_sets):
        new = ss - prev
        if new:
            shop_steps.append((xs[i], new))
        prev = ss
    return {"xs": xs, "money": money, "shed": shed, "weeds": weeds,
            "prices": prices, "shop_steps": shop_steps, "n_steps": len(steps)}


def _draw_day_grid(ax, n_steps):
    """Vertical gridlines + day labels along a step axis."""
    for st in range(0, n_steps, TURNS_PER_DAY):
        ax.axvline(st, color="0.75", lw=0.5, zorder=0)
    ax.set_xticks(list(range(0, n_steps + 1, TURNS_PER_DAY)))
    ax.set_xticklabels([d for d in range(n_steps // TURNS_PER_DAY + 1)])
    ax.set_xlabel("day")


def _plt():
    """Import matplotlib lazily with the Agg backend so graphing works headless."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _sell_series(replay, seat):
    """Derive per-(day, product) realised sales straight from a replay's SELL orders.

    The day-CSV pipeline's avg-price is only populated during a live run (it uses
    a market commit audit that does not exist for saved replays). So for --graph
    we re-quote every SELL order at the market price of the step it was submitted
    on — the pre-sell price the agent actually decided to sell at. Returns a list
    of {day, product, qty, avg, floor_qty, below_qty, base}.
    """
    from collections import defaultdict
    agg = defaultdict(lambda: {"qty": 0, "revenue": 0.0, "floor": 0, "below": 0})
    for idx, s in enumerate(replay["steps"]):
        if seat >= len(s):
            continue
        ent = s[seat]
        obs = ent.get("observation") or {}
        act = ent.get("action") or {}
        # The agent's own observation does NOT carry a "step" field (only seat 0's
        # does); use the replay list index, which IS the step.
        step = idx
        px = (obs.get("market") or {}).get("prices") or {}
        for order in act.get("market") or []:
            if not order or order[0] != "SELL" or len(order) < 2:
                continue
            item = order[1]
            if item not in PRODUCTS:
                continue
            qty = int(order[2]) if len(order) > 2 else 1
            price = px.get(item, MARKET_PARAMS[item]["base"])
            a = agg[(step // TURNS_PER_DAY, item)]
            a["qty"] += qty
            a["revenue"] += qty * price
            a["floor"] += qty if price <= PRICE_FLOOR else 0
            a["below"] += qty if price < MARKET_PARAMS[item]["base"] else 0
    out = []
    for (day, item), a in sorted(agg.items()):
        out.append({"day": day, "product": item, "qty": a["qty"],
                    "avg": a["revenue"] / max(a["qty"], 1),
                    "floor_qty": a["floor"], "below_qty": a["below"],
                    "base": MARKET_PARAMS[item]["base"]})
    return out


def _seat_sells(days: List[Dict[str, Any]], committed: bool, replay, seat: int):
    """Per-day realised-sale markers for one seat.

    Prefers committed per-day data from the replay's market audit (real units at
    realised price). Replays without an audit fall back to re-quoting the request's
    SELL orders (qty = requested, so it over-counts; the legend flags that).
    Returns list of {day, product, qty, avg, floor, below}.
    """
    if committed:
        sells = []
        for d in days:
            for p in PRODUCTS:
                q = (d.get("sell_qty") or {}).get(p, 0)
                if q <= 0:
                    continue
                sells.append({
                    "day": d["day"], "product": p, "qty": q,
                    "avg": d.get(f"avg_price_{p}", 0) or 0.0,
                    "floor": (d.get("floor_sales") or {}).get(p, 0) > 0,
                    "below": (d.get("below_base_sales") or {}).get(p, 0) > 0,
                })
        sells.sort(key=lambda r: (r["day"], r["product"]))
        return sells
    sells = _sell_series(replay, seat)
    for r in sells:
        r["floor"] = r["floor_qty"] > 0
        r["below"] = r["below_qty"] > 0
    return sells


def _draw_seat_dashboard(fig, gs, data, days, sells, seat, header, committed):
    """Draw the 4 stacked panels for ONE seat into a 4×1 GridSpec `gs`.

    Panels, on a shared day axis so a defect lines up with the market action it
    caused: (0) shed vs the 100-cap + weeds/overflow, (1) market prices with
    shop-unlock ticks AND this seat's realised-sale dots (green ≥ base / orange
    below-base / red floor, size ∝ qty), (2) a defect swimlane, (3) end-of-day
    money. `data` is the once-computed shared series, `days`/`sells` are per-seat.
    """
    from matplotlib.lines import Line2D
    plt = _plt()
    xs, n = data["xs"], data["n_steps"]
    by_day = {d["day"]: d for d in days}
    day_axis = sorted(by_day)

    # ---- Panel 0: shed vs cap + weeds (this seat) ----
    ax = fig.add_subplot(gs[0])
    ax.plot(xs, data["shed"][seat], color="#1f77b4", lw=1.1, label=f"shed total (seat {seat})")
    ax.axhline(SHED_CAPACITY, color="#d62728", ls="--", lw=1.2, label=f"shed cap {SHED_CAPACITY}")
    over = [i for i, v in enumerate(data["shed"][seat]) if v > SHED_CAPACITY]
    if over:
        ax.scatter([xs[i] for i in over], [data["shed"][seat][i] for i in over],
                   color="#d62728", s=16, zorder=3,
                   label=f"overflow days: {len(set(i // TURNS_PER_DAY for i in over))}")
    axw = ax.twinx()
    axw.fill_between(xs, data["weeds"][seat], 0, color="0.55", alpha=0.35)
    axw.plot(xs, data["weeds"][seat], color="0.4", lw=0.7)
    axw.set_ylabel("weeds (gray)"); axw.set_ylim(0, max(data["weeds"][seat] + [8]) * 1.2)
    ax.set_ylabel("shed items")
    ax.set_title(f"{header} — shed pressure vs cap + weeds", loc="left", fontsize=11)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.set_ylim(0, max(SHED_CAPACITY * 1.15, max(data["shed"][seat] + [0]) * 1.15, 1))
    _draw_day_grid(ax, n)

    # ---- Panel 1: market prices + shop ticks + this seat's realised-sale dots ----
    ax = fig.add_subplot(gs[1])
    # Distinct hue per product so every line is identifiable; spike-prone thicker.
    price_color = {p: plt.cm.tab20(i) for p, i in zip(PRODUCTS, [0, 2, 4, 6, 8, 10, 12, 14, 16])}
    for p in PRODUCTS:
        lw = 2.0 if p in _SPIKEY_PRODUCTS else 1.1
        ax.plot(xs, data["prices"][p], color=price_color[p], lw=lw, alpha=0.95, label=p.title())
    for st, new in data["shop_steps"]:
        ax.axvline(st, color="#2ca02c", lw=0.7, alpha=0.6, zorder=1)
        ax.annotate(",".join(sorted(_SHOP_TITLE[k] for k in new)),
                    (st, ax.get_ylim()[1]), xytext=(st + 1, ax.get_ylim()[1]),
                    ha="left", va="top", fontsize=7, rotation=90, color="#2ca02c")
    for rec in sells:
        c = "#d62728" if rec["floor"] else ("#ff7f0e" if rec["below"] else "#2ca02c")
        ax.scatter(rec["day"] * TURNS_PER_DAY + 12, rec["avg"],
                   s=24 + rec["qty"] * 6, color=c, alpha=0.85, zorder=4,
                   edgecolor="black", linewidth=0.4)
    handles = [
        Line2D([], [], marker="o", ls="none", color="#2ca02c", markersize=7, label="sold ≥ base"),
        Line2D([], [], marker="o", ls="none", color="#ff7f0e", markersize=7, label="sold below base"),
        Line2D([], [], marker="o", ls="none", color="#d62728", markersize=7, label=f"sold at floor ${PRICE_FLOOR}"),
    ]
    src = "committed units @ realised price" if committed else "requested units (no audit)"
    leg_sell = ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.9,
                         title=f"sales · {src} · size ∝ qty", title_fontsize=8)
    ax.add_artist(leg_sell)
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9, ncol=2,
              title="product (line colour)", title_fontsize=9)
    ax.set_ylabel("market price ($)")
    ax.set_title(f"{header} — market prices + shop ticks + realised-sale dots", loc="left", fontsize=11)
    _draw_day_grid(ax, n)

    # ---- Panel 2: defect swimlane (this seat) ----
    def totals(d, key):
        v = d.get(key)
        return sum(v.values()) if isinstance(v, dict) else (v or 0)
    rows = [
        ("idle", "#1f77b4", [by_day.get(dy, {}).get("idle_turns", 0) for dy in day_axis]),
        ("floor sales", "#d62728", [totals(by_day.get(dy, {}), "floor_sales") for dy in day_axis]),
        ("below-base", "#ff7f0e", [totals(by_day.get(dy, {}), "below_base_sales") for dy in day_axis]),
        ("escaped", "#8c564b", [by_day.get(dy, {}).get("animals_escaped", 0) for dy in day_axis]),
        ("plants died", "#9467bd", [by_day.get(dy, {}).get("plants_died", 0) for dy in day_axis]),
    ]
    ax = fig.add_subplot(gs[2])
    n_rows = len(rows)
    for r, (label, color, vals) in enumerate(rows):
        y = n_rows - 1 - r                     # idle on top, plants-died at bottom
        nz = [(dx, v) for dx, v in zip(day_axis, vals) if v > 0]
        if not nz:
            continue
        rowmax = max(v for _, v in nz)
        top = {dx for dx, _ in sorted(nz, key=lambda t: t[1], reverse=True)[:3]}
        for dx, v in nz:
            ax.scatter(dx * TURNS_PER_DAY + 12, y, s=40 + (v / rowmax) * 260,
                       color=color, alpha=0.35 + 0.6 * (v / rowmax), zorder=3)
            if dx in top:
                ax.text(dx * TURNS_PER_DAY + 12, y + 0.30, str(v), ha="center",
                        va="bottom", fontsize=7, zorder=4)
    ax.set_yticks([len(rows) - 1 - r for r in range(len(rows))])
    ax.set_yticklabels([lbl for lbl, _, _ in rows])
    ax.set_ylim(-0.6, n_rows + 0.15)
    for sep in range(n_rows):                 # faint row separators for readability
        ax.axhline(sep - 0.5, color="0.88", lw=0.6, zorder=1)
    ax.set_title(f"{header} — defects by day (marker size/alpha ∝ count; number = worst days)",
                 loc="left", fontsize=11)
    _draw_day_grid(ax, n)

    # ---- Panel 3: end-of-day money (this seat) ----
    ax = fig.add_subplot(gs[3])
    x = [dy * TURNS_PER_DAY for dy in day_axis]           # step axis, matches _draw_day_grid
    em = [by_day.get(dy, {}).get("end_money", 0) for dy in day_axis]
    ax.bar(x, em, width=TURNS_PER_DAY * 0.8, color="0.6")
    ax.set_ylabel("closing cash ($)")
    ax.set_ylim(0, max(em + [1]) * 1.15)
    ax.set_title(f"{header} — end-of-day money (dips = land / animals / build spend)",
                 loc="left", fontsize=9)
    _draw_day_grid(ax, n)


def plot_game(path: Path, out_dir: Optional[Path] = None):
    """Render a 1×2 side-by-side dashboard: LEFT = agent under test, RIGHT = opponent.

    Each side is the same 4-panel stack (shed, prices + realised-sale dots, defects,
    money), so identical rows let you see the difference in play at a glance. Writes
    `<stem>_graph.png` next to the JSON (or in `out_dir`); this is the --graph output.
    """
    plt = _plt()
    replay = load_replay(path)
    data = _collect_step_series(replay)
    if data["n_steps"] == 0:
        return None
    meta = replay.get("_diagnose_meta", {})
    agent_seat = _agent_seat(replay)
    opp_seat = 1 - agent_seat
    committed = bool(meta.get("audit"))
    _, days_a, _ = replay_to_summary(replay, seat=agent_seat)
    _, days_o, _ = replay_to_summary(replay, seat=opp_seat)
    sells_a = _seat_sells(days_a, committed, replay, agent_seat)
    sells_o = _seat_sells(days_o, committed, replay, opp_seat)
    try:
        final_us = data["money"][agent_seat][-1]
        final_opp = data["money"][opp_seat][-1]
    except IndexError:
        final_us = final_opp = float("nan")
    opp = meta.get("opponent", "opponent")
    seed = meta.get("seed", "?")
    tag = " (US WINS)" if final_us > final_opp else (" (OPP WINS)" if final_opp > final_us else " (TIE)")

    fig = plt.figure(figsize=(28, 12.5))
    outer = fig.add_gridspec(1, 2, wspace=0.33, top=0.92, bottom=0.05, left=0.05, right=0.98)
    ga = outer[0].subgridspec(4, 1, height_ratios=[2.0, 3.4, 2.2, 1.0], hspace=0.5)
    go = outer[1].subgridspec(4, 1, height_ratios=[2.0, 3.4, 2.2, 1.0], hspace=0.5)
    fig.suptitle(f"{meta.get('agent','?')} vs {opp} · seed {seed} · "
                 f"LEFT agent (seat {agent_seat}) · RIGHT opponent (seat {opp_seat}) · "
                 f"final ${final_us:,.0f} vs ${final_opp:,.0f}{tag}",
                 fontsize=13, fontweight="bold")
    _draw_seat_dashboard(fig, ga, data, days_a, sells_a, agent_seat, f"US · seat {agent_seat}", committed)
    _draw_seat_dashboard(fig, go, data, days_o, sells_o, opp_seat, f"OPPONENT · seat {opp_seat}", committed)

    out_path = (out_dir or path.parent) / (path.stem + "_graph.png")
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def graph_batch(paths: List[Path], run_dir: Path, gif_fps: int = 2) -> List[Path]:
    """Render per replay the 1×2 side-by-side dashboard AND an animated farm-board
    GIF (both farms + farmer/hand positions + money race, one frame per day),
    returning the paths written. `gif_fps` sets GIF playback speed. Also emits a
    season-constant animal-care payback chart once per run."""
    out = []
    try:
        rendered = plot_animal_care_payback(Path(run_dir) / "animal_care_payback.png")
        if rendered:
            out.append(rendered)
            print(f"  reference: {rendered.name}")
    except Exception as e:
        print(f"  animal-care chart FAILED: {e}")
    for p in paths:
        try:
            rendered = plot_game(p, out_dir=run_dir)
            if rendered:
                out.append(rendered)
                print(f"  graph: {rendered.name}")
        except Exception as e:  # keep one bad replay from killing the batch
            print(f"  graph FAILED {p.name}: {e}")
        try:
            rendered = plot_board_gif(p, out_dir=run_dir, fps=gif_fps)
            if rendered:
                out.append(rendered)
                print(f"  graph: {rendered.name}")
        except Exception as e:
            print(f"  board GIF FAILED {p.name}: {e}")
    return out


# ---------------------------------------------------------------------------
# --graph board montage — per-step state of the whole environment
# ---------------------------------------------------------------------------

_CROP_COLOR = {"WHEAT": "#e6b800", "CARROT": "#ff7f0e", "TOMATO": "#e03e36",
               "STRAWBERRY": "#f06292", "MELON": "#5cbb5c"}
_STRUCT_COLOR = {"COOP": "#b0bec5", "PASTURE": "#8d9aa6"}
_ANIMAL_COLOR = {"GOOSE": "#e0e0e0", "COW": "#5d4037", "SHEEP": "#c0a878"}
_ANIMAL_LETTER = {"GOOSE": "G", "COW": "C", "SHEEP": "S"}
_EMPTY, _LOCKED, _WEED = "#f5f5f5", "#3a3a3a", "#8b5a2b"


def _hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _tile_color_letter(t):
    """Return (rgb-as-floats, overlay-letter-or-None) for one tile."""
    if t is None:
        return _hex_rgb(_EMPTY), None
    if t == "LOCKED":
        return _hex_rgb(_LOCKED), None
    if isinstance(t, dict):
        k = t.get("kind")
        if k == "WEED":
            return _hex_rgb(_WEED), None
        if k == "PLANT":
            return _hex_rgb(_CROP_COLOR.get(t.get("crop"), "#66bb6a")), (t.get("crop") or "")[:1]
        if k in ("COOP", "PASTURE"):
            a = t.get("animal")
            if a:
                return _hex_rgb(_ANIMAL_COLOR.get(a, "#9e9e9e")), _ANIMAL_LETTER.get(a, "a")
            return _hex_rgb(_STRUCT_COLOR.get(k, "#9e9e9e")), ("⌑" if k == "COOP" else "◇")
    return _hex_rgb(_EMPTY), None


def _draw_mini_map(ax, tiles):
    """Colour-coded 10×10 farm map on `ax` (crops/animals get a single-letter mark)."""
    arr, marks = [], []
    for y, row in enumerate(tiles):
        arr_row = []
        for x, t in enumerate(row):
            c, l = _tile_color_letter(t)
            arr_row.append(c)
            if l:
                marks.append((x, y, l))
        arr.append(arr_row)
    ax.imshow(arr, origin="upper", interpolation="nearest", aspect="equal")
    for x, y, l in marks:
        ax.text(x, y, l, ha="center", va="center", fontsize=6,
                color="#111111", zorder=5, fontweight="bold")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.6)


def _tile_counts(tiles):
    crops, animals, weeds, struct = {}, {}, 0, {"COOP": 0, "PASTURE": 0}
    for row in tiles:
        for t in row:
            if isinstance(t, dict):
                k = t.get("kind")
                if k == "PLANT":
                    crops[t.get("crop")] = crops.get(t.get("crop"), 0) + 1
                elif k == "WEED":
                    weeds += 1
                elif k in ("COOP", "PASTURE"):
                    struct[k] += 1
                    if t.get("animal"):
                        animals[t.get("animal")] = animals.get(t.get("animal"), 0) + 1
    return crops, animals, weeds, struct


def _day_cell_readout(snap) -> str:
    shed = snap["shed"] or {}
    seeds = snap["seeds"] or {}
    crops, animals, weeds, struct = snap["counts"]
    sh = " ".join(f"{k[:1]}{v}" for k, v in shed.items() if v) or "empty"
    sd = " ".join(f"{k[:1]}{v}" for k, v in seeds.items() if v) or ""
    an = " ".join(f"{_ANIMAL_LETTER.get(k, k[:1])}{v}" for k, v in animals.items()) or "-"
    cr = " ".join(f"{k[:1]}{v}" for k, v in crops.items()) or "-"
    return (f"${snap['money']:,.0f}  shed[{sh}]  seeds[{sd}]",
            f"crops[{cr}]  animals[{an}]  weeds {weeds}  coop/past {struct['COOP']}/{struct['PASTURE']}")


def plot_board(path: Path, out_dir: Optional[Path] = None):
    """Render a per-game board montage: `_board.png`.

    Top: the shared market price curves with a marker per sampled day (so you can
    correlate state with the price action). Below: a 6×5 grid, one cell per day,
    each showing BOTH farmers' 10×10 maps (colour-coded crops / animals / weeds /
    structures / locked) plus a money · shed · seeds · weeds · crop/animals readout.
    Everything comes straight from each step's observation.
    """
    plt = _plt()
    replay = load_replay(path)
    data = _collect_step_series(replay)
    n = data["n_steps"]
    if n == 0:
        return None
    meta = replay.get("_diagnose_meta", {})
    agent_seat = _agent_seat(replay)
    opp_seat = 1 - agent_seat
    steps = replay["steps"]

    # Snapshot per day at its last step (state after that day's play).
    days = list(range(min(30, (n + TURNS_PER_DAY - 1) // TURNS_PER_DAY)))
    snap_steps = [min(d * TURNS_PER_DAY + TURNS_PER_DAY - 1, n - 1) for d in days]
    snaps = []
    for i in snap_steps:
        s = steps[i]
        row = []
        for seat in (agent_seat, opp_seat):
            if seat >= len(s):
                row.append(None)
                continue
            o = s[seat].get("observation") or {}
            me = (o.get("farms") or [])[seat] if seat < len(o.get("farms") or []) else {}
            pr = o.get("private") or {}
            tiles = list(me.get("tiles") or [])
            row.append({"money": me.get("money", 0.0),
                        "shed": pr.get("shed") or {},
                        "seeds": pr.get("seeds") or {},
                        "tiles": tiles,
                        "counts": _tile_counts(tiles)})
        snaps.append((i, row))

    ncols = 5
    nrows = (len(snaps) + ncols - 1) // ncols
    fig = plt.figure(figsize=(22, 4.6 + nrows * 3.4))
    outer = fig.add_gridspec(2, 1, height_ratios=[1.0, nrows * 3.4],
                             hspace=0.35, top=0.93, bottom=0.015, left=0.02, right=0.99)

    # ---- Top: shared market prices with per-day markers ----
    axp = fig.add_subplot(outer[0])
    price_color = {p: plt.cm.tab20(i) for p, i in zip(PRODUCTS, [0, 2, 4, 6, 8, 10, 12, 14, 16])}
    for p in PRODUCTS:
        axp.plot(data["xs"], data["prices"][p], color=price_color[p],
                 lw=1.1 if p in _SPIKEY_PRODUCTS else 0.7, alpha=0.9)
    for d, i in zip(days, snap_steps):
        axp.axvline(i, color="#d62728", lw=0.6, alpha=0.7)
        if d % 2 == 0:
            axp.text(i, axp.get_ylim()[1], str(d), fontsize=6, rotation=90,
                     ha="right", va="top", color="#d62728")
    axp.set_ylabel("market price ($)")
    axp.set_title(f"{meta.get('agent','?')} vs {meta.get('opponent','?')} · seed {meta.get('seed','?')}"
                  f" · market prices (red = sampled day)", loc="left", fontsize=11)
    _draw_day_grid(axp, n)
    axp.axhline(0, color="k", lw=0.5)

    # ---- Below: day cells, each with both maps + readout ----
    gs = outer[1].subgridspec(nrows, ncols, hspace=0.62, wspace=0.20)
    for k, (i, row) in enumerate(snaps):
        ax = fig.add_subplot(gs[k // ncols, k % ncols])
        ax.set_axis_off()
        ax.set_title(f"day {days[k]}", fontsize=10, fontweight="bold", pad=3)
        for seat_idx, seat in enumerate((agent_seat, opp_seat)):
            snap = row[seat_idx]
            if snap is None:
                continue
            lab = "US" if seat == agent_seat else "OPP"
            left = 0.02 + seat_idx * 0.50
            sub = ax.inset_axes([left, 0.34, 0.47, 0.62])
            _draw_mini_map(sub, snap["tiles"])
            sub.set_title(lab, fontsize=8, pad=1)
            l1, l2 = _day_cell_readout(snap)
            ax.text(left + 0.01, 0.24, l1, ha="left", va="top", fontsize=7,
                    transform=ax.transAxes, family="monospace")
            ax.text(left + 0.01, 0.11, l2, ha="left", va="top", fontsize=7,
                    transform=ax.transAxes, family="monospace")
        # day cell money diff
        a, o = row[0], row[1]
        if a and o:
            ax.text(0.02, 0.005, f"Δ ${o['money'] - a['money']:+,.0f}", fontsize=8,
                    transform=ax.transAxes, color="#d62728")

    out_path = (out_dir or path.parent) / (path.stem + "_board.png")
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return out_path


def _draw_farm_with_positions(ax, tiles, farmer, hands):
    """One farm on `ax`: colour-coded 10×10 tiles plus farmer / hand position dots.

    Mirrors the notebook's `draw_farm` idea: a ripe crop (yield_units > 0) gets a
    white dot, animals are drawn in their product colour, the shed is the centre
    cross, and each worker is a shaded circle (farmer bigger than hands)."""
    ax.imshow(_tiles_to_rgb(tiles), origin="upper", interpolation="nearest", aspect="equal")
    # ripe-crop dots
    for y, row in enumerate(tiles):
        for x, t in enumerate(row):
            if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("yield_units", 0) > 0:
                ax.plot(x, y, "o", ms=3.2, mfc="white", mec="none", zorder=6)
    ax.plot([0, 10], [5, 5], color="0.5", lw=1.4, alpha=0.8, zorder=4)
    ax.plot([5, 5], [0, 10], color="0.5", lw=1.4, alpha=0.8, zorder=4)
    ax.text(5, 5, "shed", ha="center", va="center", fontsize=6, color="#111111", zorder=5)
    if farmer is not None:
        ax.plot(farmer[0], farmer[1], "o", ms=9.0, mfc="#1e3a8a", mec="white", mew=1.2, zorder=7)
    for hx, hy in hands or []:
        ax.plot(hx, hy, "o", ms=5.5, mfc="#1e3a8a", mec="white", mew=1.0, zorder=7)
    ax.set_xlim(-0.5, 9.5); ax.set_ylim(9.5, -0.5)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.6)


def _tiles_to_rgb(tiles):
    arr = []
    for row in tiles:
        arr_row = []
        for t in row:
            c, _ = _tile_color_letter(t)
            arr_row.append(c)
        arr.append(arr_row)
    return arr


def plot_board_gif(path: Path, out_dir: Optional[Path] = None, fps: int = 2,
                   max_days: int = 30) -> Optional[Path]:
    """Render an animated farm-board GIF from a saved replay, `<stem>_board.gif`.

    One frame per in-game day (like the notebook's `season_gif`): BOTH farms side by
    side (tiles + ripe-crop dots + farmer/hand position markers), a money-race panel
    showing both banks through the season, and a fixed legend for what each colour /
    marker means. `fps` controls playback speed (default 2 frames/s = 0.5 s per day —
    raise it to 4-5 if you want a quicker skim). This is the `--graph` board output —
    an animation you can watch for *when* a defect appears, instead of a static PNG.
    """
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    plt = _plt()
    replay = load_replay(path)
    agent_seat = _agent_seat(replay)
    opp_seat = 1 - agent_seat
    meta = replay.get("_diagnose_meta", {})
    n = len(replay.get("steps", []))
    if n == 0:
        return None
    steps = replay["steps"]
    days = list(range(min(max_days, (n + TURNS_PER_DAY - 1) // TURNS_PER_DAY)))
    snap_steps = [min(d * TURNS_PER_DAY + TURNS_PER_DAY - 1, n - 1) for d in days]

    money = {seat: [] for seat in (agent_seat, opp_seat)}
    for s in steps:
        for seat in (agent_seat, opp_seat):
            if seat < len(s):
                o = s[seat].get("observation") or {}
                me = (o.get("farms") or [])[seat] if seat < len(o.get("farms") or []) else {}
                money[seat].append(me.get("money", 0.0) or 0.0)

    top = max([max(money[agent_seat] + [0])] + [max(money[opp_seat] + [0])]) * 1.08

    def _snapshot(seat, i):
        s = steps[i]
        if seat >= len(s):
            return None
        o = s[seat].get("observation") or {}
        me = (o.get("farms") or [])[seat] if seat < len(o.get("farms") or []) else {}
        if not me:
            return None
        hands = []
        for h in me.get("hands") or []:
            hp = h.get("pos") if isinstance(h, dict) else h
            if isinstance(hp, (list, tuple)) and len(hp) == 2:
                hands.append(hp)
        farmer = me.get("farmer")
        if not isinstance(farmer, (list, tuple)) or len(farmer) != 2:
            farmer = None
        return {
            "tiles": [list(r) for r in (me.get("tiles") or [])],
            "farmer": farmer,
            "hands": hands,
            "money": me.get("money", 0.0) or 0.0,
        }

    snaps = [(d, _snapshot(agent_seat, k), _snapshot(opp_seat, k)) for d, k in zip(days, snap_steps)]

    from matplotlib.animation import FuncAnimation, PillowWriter
    fig, (axA, axO, axM, axL) = plt.subplots(
        1, 4, figsize=(12.0, 3.7), gridspec_kw={"width_ratios": [1.0, 1.0, 1.2, 0.95]},
        sharey=False)

    # ---- Fixed legend (drawn once; not cleared by frame()) ----
    axL.axis("off")
    crop_handles = []
    for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
        crop_handles.append(Patch(facecolor=_hex_rgb(_CROP_COLOR[c]), label=c.title()))
    legend_handles = crop_handles + [
        Patch(facecolor=_hex_rgb(_WEED), label="weed"),
        Patch(facecolor=_hex_rgb(_LOCKED), label="locked (unbought)"),
        Patch(facecolor=_hex_rgb(_STRUCT_COLOR["COOP"]), label="coop / pasture"),
        Line2D([], [], marker="o", ls="none", ms=8, mfc="white", mew=0.5, mec="#555", label="ripened crop"),
        Line2D([], [], marker="o", ls="none", ms=12, mfc="#1e3a8a", mew=1.2, mec="white", label="farmer"),
        Line2D([], [], marker="o", ls="none", ms=8, mfc="#1e3a8a", mew=1.0, mec="white", label="hired hand"),
        Line2D([], [], marker="o", ls="none", color="#1e3a8a", lw=2, label="US bank ($)"),
        Line2D([], [], marker="o", ls="none", color="#d62728", lw=1.6, label="OPP bank ($)"),
    ]
    axL.legend(handles=legend_handles, loc="upper left", fontsize=7.5, ncol=1,
               handleheight=1.3, frameon=False, title="Legend")

    def frame(i):
        d, sa, so = snaps[i]
        for ax in (axA, axO, axM):
            ax.clear()
        if sa:
            _draw_farm_with_positions(axA, sa["tiles"], sa["farmer"], sa["hands"])
            axA.set_title(f"US · day {d} · ${sa['money']:,.0f}", fontsize=9, fontweight="bold")
        else:
            axA.set_title(f"US · day {d}", fontsize=9)
        if so:
            _draw_farm_with_positions(axO, so["tiles"], so["farmer"], so["hands"])
            axO.set_title(f"OPP · day {d} · ${so['money']:,.0f}", fontsize=9, fontweight="bold")
        else:
            axO.set_title(f"OPP · day {d}", fontsize=9)
        k = snap_steps[i]
        axM.plot([money[agent_seat][t] for t in range(k)], color="#1e3a8a", lw=2.0, label="US")
        axM.plot([money[opp_seat][t] for t in range(k)], color="#d62728", lw=1.6, label="OPP")
        axM.set_xlim(0, n); axM.set_ylim(0, top)
        axM.set_title("Coins in the bank", fontsize=9, fontweight="bold")
        axM.set_xlabel("turn", fontsize=8); axM.grid(alpha=0.2)
        axM.legend(fontsize=7.5, loc="upper left", frameon=False)
        fig.suptitle(f"{meta.get('agent','?')} vs {meta.get('opponent','?')} · seed {meta.get('seed','?')}",
                     fontsize=11, fontweight="bold")

    anim = FuncAnimation(fig, frame, frames=len(snaps), interval=200)
    out_path = (out_dir or path.parent) / (path.stem + "_board.gif")
    anim.save(out_path, writer=PillowWriter(fps=max(fps, 1)), dpi=90)
    plt.close(fig)
    return out_path


_PRODUCT_COLOR = {"EGG": "#d4a017", "MILK": "#8d9aa6", "WOOL": "#b08d57"}


def _animal_payback(a, prod, cared):
    """Mirror _daily_refresh_animals: a cared+fed day adds 1 to a pending counter,
    and a production day pays out 1 + whatever has accumulated, capped by max_held."""
    import numpy as np
    feed_cost = MARKET_PARAMS["WHEAT"]["base"]  # optimistic: base wheat; the market quotes higher as you buy
    cash, pending = [-a["cost"]], 0
    for d in range(1, 30):
        units = 0
        if d >= a["first_yield_day"] and (d - a["first_yield_day"]) % a["interval"] == 0:
            units, pending = min(a["max_held"], 1 + pending), 0
        if cared:
            pending += 1
        cash.append(cash[-1] + units * MARKET_PARAMS[prod]["base"] - feed_cost)
    return cash


def plot_animal_care_payback(out_path: Path) -> Path:
    """Season economics of animal CARE: for each animal, cumulative cash over the
    30-day season for FED-ONLY (dotted) vs FED+CARED (solid), against a FEED_COST of
    one wheat/day, with break-even-day markers on the cared lines. Season-constant —
    identical for every replay, so it is rendered once per `--graph` run / `--animals`.
    """
    import matplotlib.patheffects as pe
    plt = _plt()
    season = list(range(0, 30))
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    end_season = {}
    for animal in ("GOOSE", "COW", "SHEEP"):
        a = ANIMALS[animal]
        prod = a["product"]
        c = _PRODUCT_COLOR[prod]
        for cared, style, width, alpha in ((False, ":", 1.6, 0.55), (True, "-", 2.2, 1.0)):
            cash = _animal_payback(a, prod, cared)
            ax.plot(season, cash, style, lw=width, color=c, alpha=alpha,
                    label=(f"{animal.title()} cared — {prod.lower()} x{1 + a['interval']} per pickup"
                           if cared else None))
            be = next((int(d) for d, cv in zip(season, cash) if cv >= 0), None)
            if be and cared:
                dx, dy, ha = {"GOOSE": (-0.4, -560, "right"), "COW": (0.4, -560, "left"),
                              "SHEEP": (0, 320, "center")}[animal]
                ax.plot(be, cash[be], "o", ms=9, color=c, mec="white", zorder=5)
                ax.text(be + dx, cash[be] + dy, f"day {be}", fontsize=9.5, color=c,
                        weight="bold", ha=ha,
                        path_effects=[pe.withStroke(linewidth=2.6, foreground="white")])
            end_season[(animal, cared)] = cash[-1]
    ax.axhline(0, color="#4A3F35", lw=1)
    ax.set_xlabel("season day (animal bought on day 0)")
    ax.set_ylabel("cumulative coins")
    ax.set_title("Care changes the ranking: solid = fed + cared, dotted = fed only")
    ax.legend(fontsize=9.5, frameon=False, loc="upper left")
    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    for animal in ("GOOSE", "COW", "SHEEP"):
        print(f"  {animal.title():6s} end of season: "
              f"{end_season[(animal, True)]:+8,.0f} cared   {end_season[(animal, False)]:+8,.0f} fed only")
    return out_path


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
    parser.add_argument("--xray", action="store_true",
                        help="Investigate a patch: per-step patch() moves, old-vs-new action "
                             "divergence, and day-by-day money for the same seed")
    parser.add_argument("--graph", action="store_true",
                        help="Render per-game dashboard PNG + animated farm-board GIF from saved replays")
    parser.add_argument("--animals", action="store_true",
                        help="Render the season-constant animal CARE payback chart "
                             "(fed-only vs fed+cared cumulative cash) as animal_care_payback.png")
    parser.add_argument("--gif-fps", type=int, default=2,
                        help="Farm-board GIF playback speed in frames/sec (default 2 = 0.5s/day; "
                             "raise to 4-5 for a quicker skim)")
    parser.add_argument("--tape", choices=["v1", "v2"], default="v1",
                        help="Tape module to build main.py against: v1=route_tape.py "
                             "(production), v2=route_tape_v2.py (experimental)")
    args = parser.parse_args()

    global _TAPE_SELECTED
    _TAPE_SELECTED = args.tape

    if args.replay_dir or (args.graph and not args.old and not args.new and not args.compare
                           and not args.xray):
        auto_picked = not args.replay_dir
        run_dir = Path(args.replay_dir) if args.replay_dir else _most_recent_run_dir()
        if run_dir is None:
            print("No replay dir found; pass --replay-dir <dir>.")
            return
        paths = sorted(run_dir.glob("*.json"))
        if not paths:
            print(f"No replay JSONs found in {run_dir}")
            return
        # Bare `--graph` must not silently render a huge default dir (e.g. a full
        # 39-replay sweep) — ask for an explicit --replay-dir instead.
        if args.graph and auto_picked and len(paths) > 8:
            print(f"auto-picked {run_dir} has {len(paths)} replays; pass --replay-dir "
                  f"{run_dir} explicitly to graph them (or cap it).")
            return
        write_run_csv(run_dir, paths)
        rows = [game_summary(p) for p in paths]
        print("\nPer-game summary:")
        print_game_table(rows)
        if args.compare and paths:
            ab_delta_report(paths, per_day=args.render)
        if args.render and paths:
            replay = load_replay(paths[-1])
            frames, days, _ = replay_to_summary(replay, seat=_agent_seat(replay))
            print(f"\n--- rendered: {paths[-1].name} ---")
            render(days, frames)
        if args.graph and paths:
            print(f"\nRendering PNG dashboards + farm GIFs into {run_dir}:")
            graph_batch(paths, run_dir, gif_fps=args.gif_fps)
        return

    if args.animals and not (args.old or args.new or args.compare):
        out_dir = Path(args.run_dir) if args.run_dir else Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)
        chart = plot_animal_care_payback(out_dir / "animal_care_payback.png")
        if chart:
            print(f"  wrote {chart.name}")
        return

    pa_indices = _parse_pa_arg(args.pa)
    for pa in pa_indices:
        if pa not in PUBLIC_AGENT_MAP:
            print(f"Unknown public agent #{pa}. Available:\n{public_agent_names()}")
            sys.exit(1)

    run_dir = Path(args.run_dir) if args.run_dir else _new_run_dir()
    print(f"Saving replays to {run_dir}")

    if args.xray:
        seeds = _make_seeds(args.batch, args.seed)
        saved = xray_batch(pa_indices, seeds, run_dir)
        write_run_csv(run_dir, saved)
        return

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
