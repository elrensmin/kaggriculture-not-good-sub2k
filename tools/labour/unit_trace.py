#!/usr/bin/env python
"""unit_trace — per-unit, per-turn op + inventory timeline, ours or the #1's.

Why this exists
---------------
`op_patterns` gives op *counts*; it cannot say **which unit did what, while holding
what**. Every remaining phase-1 hypothesis is of the form "a unit picks up X, cannot
use it, and carries/drops it back" -- and that is invisible in an aggregate. This
prints the actual timeline so the shuttle, if it exists, is visible turn by turn.

What it prints
--------------
  * one line per (turn, unit): position, inventory BEFORE acting, and the op;
  * a per-unit tally of `(op, item)` and of PICKUP->DROP round trips;
  * a "wasted carry" count: turns a unit spent holding something it could not use.

Modes
-----
  live   (default) run a fresh game with the CURRENT src/ and seed
  replay --dir/--glob  read saved replays instead (works on the #1's games too)

Usage
-----
  PYTHONPATH=. python -m tools.labour.unit_trace --days 0-2 --max-turns 24
  PYTHONPATH=. python -m tools.labour.unit_trace --days 0-5 --pa 1 --seed 4362837462
  PYTHONPATH=. python -m tools.labour.unit_trace --dir replays/DSM/v1 --glob '*.json'
  SCRATCH_PARAMS='...' PYTHONPATH=. python -m tools.labour.unit_trace --days 0-2
"""
from __future__ import annotations

try:
    from tools import team as team_mod
except ImportError:  # bare-script execution: add the repo root to sys.path
    import pathlib as _pl
    import sys as _sys
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))
    from tools import team as team_mod

import argparse
import collections
import glob as globmod
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.diagnose.window import parse_days, in_window, describe   # noqa: E402

_WINDOW = None
DAY = 24


def _in(day):
    return in_window(day, _WINDOW)


# ---------------------------------------------------------------------------
def _steps_of(obj):
    return obj.steps if hasattr(obj, "steps") else obj.get("steps", [])


def _load_live(pa, seed, steps):
    from tools.diagnose.agents import load_agent, load_public_agent
    from tools.diagnose.games import run_game
    env = run_game(load_agent(fresh=True), load_public_agent(pa),
                   seed=seed, episode_steps=steps, seat=1, audit=False)
    return env, 1, f"live vs pa#{pa} seed {seed}"


def _load_replay(path, seat_spec):
    from tools.diagnose.games import load_replay
    from tools.phases.phase_map import _seat_of
    rep = load_replay(Path(path))
    return rep, _seat_of(rep, seat_spec), Path(path).name


def _inv_map(obs):
    """[(item, qty)] held by each unit, farmer first. The engine keys `inventories`
    per unit; the shape is read defensively because a replay and a live env differ."""
    priv = obs.get("private") or {}
    invs = priv.get("inventories")
    if isinstance(invs, list):
        return [dict(x or {}) for x in invs]
    if isinstance(invs, dict):                       # {unit_index: {item: qty}}
        n = max([int(k) for k in invs] or [-1]) + 1
        return [dict(invs.get(str(i), invs.get(i, {})) or {}) for i in range(n)]
    return []


def _ops_of(act):
    """The op list for each unit, farmer first, normalised to [OP, item?, qty?]."""
    out = [list(act.get("farmer") or ["PASS"])]
    out += [list(c or ["PASS"]) for c in (act.get("hands") or [])]
    return out


def trace(obj, seat, label, max_turns, show_all):
    steps = _steps_of(obj)
    pair = collections.Counter()          # (op, item) per unit
    round_trips = collections.Counter()   # PICKUP x -> DROP x, per unit
    last_pickup = {}                      # unit -> item picked up and still held
    wasted = collections.Counter()        # unit -> turns holding an unusable item
    print(f"\n############ {label}  seat={seat} ############")
    printed = 0
    for t in range(len(steps) - 1):
        day = t // DAY
        if not _in(day):
            continue
        hour = t % DAY
        frame, nxt = steps[t], steps[t + 1]
        if len(frame) <= seat or len(nxt) <= seat:
            continue
        obs = frame[seat].get("observation")
        act = nxt[seat].get("action") or {}
        if not obs:
            continue
        farm = obs["farms"][seat]
        pos = [tuple(farm.get("farmer") or (0, 0))] + [tuple(p) for p in farm.get("hands") or []]
        invs = _inv_map(obs)
        ops = _ops_of(act)
        if show_all and printed < max_turns:
            printed += 1
            for u, op in enumerate(ops):
                inv = invs[u] if u < len(invs) else {}
                held = ",".join(f"{k}{v}" for k, v in sorted(inv.items()) if v) or "-"
                print(f"   d{day} h{hour:02d} u{u}{'(F)' if u == 0 else '   '} "
                      f"@{pos[u] if u < len(pos) else '?'} hold[{held}] -> {' '.join(str(x) for x in op)}")
        for u, op in enumerate(ops):
            name = str(op[0]) if op else "PASS"
            item = str(op[1]) if len(op) > 1 else ""
            inv = invs[u] if u < len(invs) else {}
            pair[(u, name, item)] += 1
            if name == "PICKUP":
                last_pickup[u] = item
            elif name == "DROP" and u in last_pickup:
                round_trips[(u, last_pickup[u])] += 1
                last_pickup.pop(u, None)
            elif name in ("FEED", "PLACE", "FERTILIZE", "PLANT", "WATER", "HARVEST", "DIG",
                          "CARE", "COLLECT_FERTILIZER", "BUILD_COOP", "BUILD_PASTURE"):
                last_pickup.pop(u, None)      # the carry was used, not wasted
            if inv and name in ("NORTH", "SOUTH", "EAST", "WEST", "PASS"):
                wasted[u] += 1

    print(f"\n   -- per-unit (op, item) over the window --")
    by_unit = collections.defaultdict(list)
    for (u, name, item), n in pair.items():
        by_unit[u].append((n, name, item))
    for u in sorted(by_unit):
        top = sorted(by_unit[u], reverse=True)[:10]
        tag = "F" if u == 0 else " "
        print(f"   u{u}{tag}: " + "  ".join(f"{name}{'(' + item + ')' if item else ''}={n}"
                                            for n, name, item in top))
    print(f"\n   -- PICKUP -> DROP round trips (carried for nothing) --")
    if round_trips:
        for (u, item), n in sorted(round_trips.items(), key=lambda kv: -kv[1]):
            print(f"   u{u} {item}: {n}")
    else:
        print("   none")
    print(f"   -- turns holding an item while only moving/passing (wasted carry) --")
    print("   " + ("  ".join(f"u{u}={n}" for u, n in sorted(wasted.items())) or "none"))
    return pair, round_trips, wasted


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", default="0-10",
                    help="day window to trace (default 0-10 = the opening)")
    ap.add_argument("--max-turns", type=int, default=72,
                    help="cap the per-turn lines printed (0 = none)")
    ap.add_argument("--no-turns", action="store_true", help="summary only")
    ap.add_argument("--pa", type=int, default=1, help="live: public opponent index")
    ap.add_argument("--seed", type=int, default=4362837462, help="live: episode seed")
    ap.add_argument("--seat", default="auto", help="replay: seat (auto finds DSM, else 1)")
    ap.add_argument("--dir", default=None, help="replay dir instead of a live run")
    ap.add_argument("--glob", default="*.json", help="glob inside --dir")
    ap.add_argument("--max-games", type=int, default=1)
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    ns = ap.parse_args(argv)
    team_mod.set_team(ns.team)

    global _WINDOW
    _WINDOW = parse_days(ns.days)
    print(f"unit_trace — window {describe(_WINDOW)}")

    steps = (max(_WINDOW[-1]) + 1) * DAY if _WINDOW else 720
    if ns.dir:
        paths = sorted(globmod.glob(os.path.join(ns.dir, ns.glob)))[:ns.max_games]
        if not paths:
            raise SystemExit(f"no replays in {ns.dir}")
        for p in paths:
            obj, seat, label = _load_replay(p, ns.seat)
            trace(obj, seat, label, 0 if ns.no_turns else ns.max_turns, not ns.no_turns)
    else:
        obj, seat, label = _load_live(ns.pa, ns.seed, steps)
        trace(obj, seat, label, 0 if ns.no_turns else ns.max_turns, not ns.no_turns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
