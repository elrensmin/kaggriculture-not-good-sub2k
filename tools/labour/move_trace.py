#!/usr/bin/env python
"""move_trace — attribute every MOVE to the act that caused it.

Why this exists
---------------
`op_patterns` says what immediately follows an act (ACT / MOVE / PASS), and
`movement.py` gives the movement share. Neither answers the question that decides the
midgame: **which work is buying all the walking?** A unit that waters one tile then
walks 3 turns to the next costs 4x a unit that waters the tile it is standing on, and
the aggregate cannot tell those apart.

This walks each unit's op stream and charges every MOVE turn to the ACT that preceded
it, so the output is "WATER: 409 ops, 1.9 moves each, 780 moves = 43 % of all moves".
Read it as a cost sheet, not a count.

It also splits moves by carried state (`empty` vs `carrying`), because the two have
different fixes: moving empty is a routing problem, moving while carrying is a
delivery/fetch problem.

Usage
-----
  PYTHONPATH=. python -m tools.labour.move_trace --days 11-20 --dir diag-replays/arm
  PYTHONPATH=. python -m tools.labour.move_trace --days 11-20 --pa 1 --seed 4362837462
  PYTHONPATH=. python -m tools.labour.move_trace --days 11-20 --dir replays/DSM/v1 \
      --glob '*.json' --max-games 8 --seat auto --compare
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
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.diagnose.window import parse_days, in_window, describe   # noqa: E402

_WINDOW = None
DAY = 24
MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
ACTS = ("PLANT", "WATER", "HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER", "FERTILIZE",
        "DIG", "BUILD_COOP", "BUILD_PASTURE", "PICKUP", "DROP", "PLACE")


def _in(day):
    return in_window(day, _WINDOW)


def _steps_of(obj):
    return obj.steps if hasattr(obj, "steps") else obj.get("steps", [])


def _inv_at(obs, unit):
    priv = obs.get("private") or {}
    invs = priv.get("inventories")
    if isinstance(invs, list) and unit < len(invs):
        return {k: v for k, v in (invs[unit] or {}).items() if v > 0}
    if isinstance(invs, dict):
        return {k: v for k, v in (invs.get(str(unit), invs.get(unit, {})) or {}).items() if v > 0}
    return {}


def analyse(obj, seat, label, window_label):
    """Charge each MOVE turn to the last ACT the unit performed."""
    steps = _steps_of(obj)
    # per unit: list of (turn, op, carried_before)
    seq = collections.defaultdict(list)
    for t in range(len(steps) - 1):
        day = t // DAY
        if not _in(day):
            continue
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        act = steps[t + 1][seat].get("action") or {}
        if not obs:
            continue
        ops = [list(act.get("farmer") or ["PASS"])]
        ops += [list(c or ["PASS"]) for c in (act.get("hands") or [])]
        for u, op in enumerate(ops):
            name = str(op[0]) if op else "PASS"
            seq[u].append((t, name, bool(_inv_at(obs, u))))

    cost = collections.defaultdict(lambda: {"ops": 0, "moves": 0, "pass": 0})
    move_state = collections.Counter()
    total_moves = 0
    for u, events in seq.items():
        last_act = "START"
        for _t, name, carrying in events:
            if name in ACTS:
                cost[name]["ops"] += 1
                last_act = name
            elif name in MOVES:
                cost[last_act]["moves"] += 1
                move_state["carrying" if carrying else "empty"] += 1
                total_moves += 1
            else:
                cost[last_act]["pass"] += 1

    print(f"\n############ {label}  ({window_label}) ############")
    print(f"   total moves {total_moves}   "
          f"empty {move_state['empty']} ({100*move_state['empty']/max(1,total_moves):.0f}%)   "
          f"carrying {move_state['carrying']} "
          f"({100*move_state['carrying']/max(1,total_moves):.0f}%)")
    print(f"\n   -- moves charged to the act that preceded them --")
    print(f"   {'after act':<22}{'ops':>6}{'moves':>8}{'mv/op':>8}{'% of moves':>12}")
    rows = sorted(cost.items(), key=lambda kv: -kv[1]["moves"])
    for name, c in rows:
        if c["ops"] == 0 and c["moves"] == 0:
            continue
        mv_op = c["moves"] / c["ops"] if c["ops"] else float("nan")
        pct = 100 * c["moves"] / max(1, total_moves)
        print(f"   {name:<22}{c['ops']:>6}{c['moves']:>8}{mv_op:>8.2f}{pct:>11.1f}%")
    return {"total_moves": total_moves, "empty": move_state["empty"],
            "carrying": move_state["carrying"],
            "by_act": {k: dict(v) for k, v in cost.items()}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", default="11-20", help="day window (default 6-17 = the midgame)")
    ap.add_argument("--pa", type=int, default=1)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=4)
    ap.add_argument("--dsm-dir", default="replays/DSM/v1")
    ap.add_argument("--dsm-max", type=int, default=4)
    ap.add_argument("--compare", action="store_true", help="also trace DSM's replays")
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    ns = ap.parse_args(argv)
    team_mod.set_team(ns.team)

    global _WINDOW
    _WINDOW = parse_days(ns.days)
    win = describe(_WINDOW)

    if ns.dir:
        from tools.diagnose.games import load_replay
        from tools.phases.phase_map import _seat_of
        paths = sorted(globmod.glob(os.path.join(ns.dir, ns.glob)))[:ns.max_games]
        for p in paths:
            try:
                rep = load_replay(Path(p))
            except Exception as e:            # a truncated/killed run leaves bad JSON
                print(f"   SKIP {Path(p).name}: {e}")
                continue
            analyse(rep, _seat_of(rep, ns.seat), Path(p).name, win)
    else:
        from tools.diagnose.agents import load_agent, load_public_agent
        from tools.diagnose.games import run_game
        steps = (max(_WINDOW[-1]) + 1) * DAY
        env = run_game(load_agent(fresh=True), load_public_agent(ns.pa),
                       seed=ns.seed, episode_steps=steps, seat=1, audit=False)
        analyse(env, 1, f"live vs pa#{ns.pa} seed {ns.seed}", win)

    if ns.compare:
        from tools.diagnose.games import load_replay
        from tools.phases.phase_map import _seat_of
        for p in sorted(globmod.glob(os.path.join(ns.dsm_dir, "*.json")))[:ns.dsm_max]:
            try:
                rep = load_replay(Path(p))
            except Exception as e:
                print(f"   SKIP {Path(p).name}: {e}")
                continue
            analyse(rep, _seat_of(rep, "auto"), f"DSM {Path(p).name}", win)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
