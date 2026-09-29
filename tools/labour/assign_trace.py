#!/usr/bin/env python
"""assign_trace — why did THIS unit get THAT job, and how much of the crew is stuck?

Why this exists
---------------
The first `EXACT_ASSIGN` attempt collapsed the farm (WATER 445 -> 26) and the aggregate
metrics could only say *that* it collapsed, not *where*. This instruments the scheduler's
own op choice per unit per turn and classifies it, so a broken path is visible immediately:

  DELIVER   a carrying unit sent to FEED / PLACE / FERTILIZE
  WORK      an act on a tile (WATER / PLANT / HARVEST / CARE / DIG / ...)
  DEPOSIT   a move toward the shed / a DROP  <-- a carrying unit that is only hauling
  MOVE      walking to an assigned job
  PASS      nothing assigned

The number that catches the bug is **DEPOSIT as a share of carrying unit-turns**: in a
healthy scheduler a carrying unit keeps working and deposits opportunistically; in the
broken one it deposits nearly every turn and the farm stalls. It also reports the same-tile
(d=0) rate and per-op mean distance, which is what `_pick` is supposed to optimise.

Usage
-----
  PYTHONPATH=. python -m tools.labour.assign_trace --days 11-20 --pa 1
  SCRATCH_PARAMS='EXACT_ASSIGN=1' PYTHONPATH=. python -m tools.labour.assign_trace \
      --days 11-20 --pa 1          # trace the broken arm and compare
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.diagnose.window import parse_days, in_window, describe   # noqa: E402

_WINDOW = None
DAY = 24
ACTS = ("PLANT", "WATER", "HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER", "FERTILIZE",
        "DIG", "BUILD_COOP", "BUILD_PASTURE", "PLACE")
DELIVER = ("FEED", "PLACE", "FERTILIZE")


def _in(day):
    return in_window(day, _WINDOW)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", default="11-20")
    ap.add_argument("--pa", type=int, default=1)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--top", type=int, default=6, help="days to print in the per-day table")
    ns = ap.parse_args(argv)

    global _WINDOW
    _WINDOW = parse_days(ns.days)
    print(f"assign_trace — window {describe(_WINDOW)}  "
          f"SCRATCH_PARAMS={os.environ.get('SCRATCH_PARAMS', '(none)')}")

    import src.scheduler as sch
    from src import params
    from tools.diagnose.agents import load_agent, load_public_agent
    from tools.diagnose.games import run_game

    # count which internal path produced each op, by wrapping the two exits
    hits = collections.Counter()
    orig_deposit, orig_move = sch._deposit_op, sch._move_or_act

    def deposit(state, pos, cost):
        hits["deposit_calls"] += 1
        return orig_deposit(state, pos, cost)

    def move_or_act(state, pos, job, cost):
        hits["act" if job.tile == pos else "walk"] += 1
        return orig_move(state, pos, job, cost)

    sch._deposit_op, sch._move_or_act = deposit, move_or_act
    steps = (max(_WINDOW[-1]) + 1) * DAY
    env = run_game(load_agent(fresh=True), load_public_agent(ns.pa),
                   seed=ns.seed, episode_steps=steps, seat=1, audit=False)
    sch._deposit_op, sch._move_or_act = orig_deposit, orig_move

    st = env.steps
    kind = collections.Counter()          # classification per unit-turn
    carry_turns = collections.Counter()
    dist = collections.defaultdict(list)
    per_day = collections.defaultdict(collections.Counter)
    for t in range(len(st)):
        d = t // DAY
        if not _in(d) or len(st[t]) <= 1:
            continue
        obs = st[t][1].get("observation")
        if not obs:
            continue
        farm = obs["farms"][1]
        invs = (obs.get("private") or {}).get("inventories") or []
        pos = [tuple(farm.get("farmer") or (0, 0))] + [tuple(p) for p in farm.get("hands") or []]
        if t + 1 >= len(st) or len(st[t + 1]) <= 1:
            continue
        act = st[t + 1][1].get("action") or {}
        ops = [list(act.get("farmer") or ["PASS"])] + [list(c or ["PASS"]) for c in (act.get("hands") or [])]
        for u, op in enumerate(ops):
            name = str(op[0]) if op else "PASS"
            inv = (invs[u] if u < len(invs) else {}) or {}
            carrying = any(v > 0 for v in inv.values())
            if carrying:
                carry_turns["all"] += 1
            if name in DELIVER:
                k = "DELIVER"
            elif name in ACTS:
                k = "WORK"
                if carrying:
                    carry_turns["work_while_carrying"] += 1
            elif name == "DROP":
                k = "DEPOSIT"
            elif name in ("NORTH", "SOUTH", "EAST", "WEST"):
                k = "MOVE"
            else:
                k = "PASS"
            if carrying and k == "MOVE":
                # a carrying unit that is only walking is hauling unless it is delivering
                k = "MOVE_CARRY"
                carry_turns["move_carrying"] += 1
            kind[k] += 1
            per_day[d][k] += 1

    n = sum(kind.values())
    print(f"\n   unit-turns {n}")
    print(f"   {'DELIVER':<10}{kind['DELIVER']:>7}  ({100*kind['DELIVER']/max(1,n):4.0f}%)")
    print(f"   {'WORK':<10}{kind['WORK']:>7}  ({100*kind['WORK']/max(1,n):4.0f}%)")
    print(f"   {'MOVE':<10}{kind['MOVE']:>7}  ({100*kind['MOVE']/max(1,n):4.0f}%)")
    print(f"   {'MOVE_CARRY':<10}{kind['MOVE_CARRY']:>7}  ({100*kind['MOVE_CARRY']/max(1,n):4.0f}%)"
          f"   <- carrying and only walking")
    print(f"   {'DEPOSIT':<10}{kind['DEPOSIT']:>7}  ({100*kind['DEPOSIT']/max(1,n):4.0f}%)")
    print(f"   {'PASS':<10}{kind['PASS']:>7}  ({100*kind['PASS']/max(1,n):4.0f}%)")
    ct = max(1, carry_turns["all"])
    print(f"\n   carrying unit-turns {carry_turns['all']}: "
          f"WORK {100*carry_turns['work_while_carrying']/ct:.0f}%  "
          f"MOVE {100*carry_turns['move_carrying']/ct:.0f}%")
    print(f"   scheduler internals: _deposit_op {hits['deposit_calls']}  "
          f"_move_or_act act {hits['act']} / walk {hits['walk']}")
    print(f"\n   -- first {ns.top} days (WORK / MOVE / MOVE_CARRY / DEPOSIT / PASS) --")
    for d in sorted(per_day)[:ns.top]:
        c = per_day[d]
        print(f"      d{d:<3} {c['WORK']:>5} {c['MOVE']:>6} {c['MOVE_CARRY']:>10} "
              f"{c['DEPOSIT']:>8} {c['PASS']:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
