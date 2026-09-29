#!/usr/bin/env python
"""turn_budget — is the reference's midgame workload even reachable with our crew?

Why this exists
---------------
`phase_map` says "phase 2 is 0.6x"; `divergence` says when. Neither answers the question
that decides the roadmap: **can 12 hands do the reference's day-17 workload at OUR
conversion rate?** MEASURED 2026-09-29 (`op_patterns`, d6-17, 8 games each, shipped tree vs
`replays/Boey/v1`):

    unit-turns / game   ours 3,075   Boey 3,092      <- the crew-hours are IDENTICAL
    acts / game         ours 1,062   Boey 1,706
    moves / game        ours 1,917   Boey 1,290
    moves per act       ours 1.81    Boey 0.76

Same turns, half the acts: the whole gap is conversion, not crew size, hiring or idle.
Boey's 1,706 acts at our 2.81 turns/act needs **4,794 unit-turns (~20 hands)**; at his 1.76
it needs 3,004, inside our crew. So exact parity is a conversion problem, and this tool
prints that arithmetic instead of asserting it.

It also prints the per-op act deficit, so the deficit is attributed to the ops that carry
it (WATER, HARVEST, FEED/CARE/COLLECT) rather than to one aggregate.

Usage
-----
  PYTHONPATH=. python -m tools.phases.turn_budget --pa 2,3 --batch 4 \
      --ref-from replays/Boey/v1 --ref-max 60
  PYTHONPATH=. python -m tools.phases.turn_budget --phase phase2 --dir diag-replays/arm \\
      --ref-from replays/Boey/v1 --ref-max 60
"""
from __future__ import annotations

import argparse
import glob as globmod
import statistics as st
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.diagnose.runbook import _make_seeds, _parse_pa_arg          # noqa: E402
from tools.phases.dag import PHASES                                     # noqa: E402
from tools.phases.phase_map import extract_games, extract_replays       # noqa: E402

NON_ACT = ("MOVE", "PASS", "REVENUE", "TRADE_NET")   # ops that are not unit-turns


def _game_stats(days, day0, day1):
    """Per-game totals for one arm inside the window."""
    ut = acts = moves = passes = 0
    ops = Counter()
    for d, r in days.items():
        if not (day0 <= d <= day1):
            continue
        ut += r["unit_turns"]
        moves += r["flow"].get("MOVE", 0)
        passes += r.get("pass", 0)
        for op, n in r["flow"].items():
            if op in NON_ACT or op.startswith("__"):
                continue
            ops[op] += n
            acts += n
    return {"unit_turns": ut, "acts": acts, "moves": moves, "pass": passes, "ops": ops}


def _med(vals):
    return st.median(vals) if vals else 0.0


def _stats(games, day0, day1):
    per = [_game_stats(g, day0, day1) for g in games]
    per = [p for p in per if p["unit_turns"]]
    if not per:
        return None
    ops = sorted({o for p in per for o in p["ops"]},
                 key=lambda o: -_med([p["ops"].get(o, 0) for p in per]))
    return {
        "n": len(per),
        "unit_turns": _med([p["unit_turns"] for p in per]),
        "acts": _med([p["acts"] for p in per]),
        "moves": _med([p["moves"] for p in per]),
        "pass": _med([p["pass"] for p in per]),
        "moves_per_act": (_med([p["moves"] for p in per]) / _med([p["acts"] for p in per])
                          if _med([p["acts"] for p in per]) else float("nan")),
        "ops": {o: _med([p["ops"].get(o, 0) for p in per]) for o in ops},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", default="phase2")
    ap.add_argument("--days", default=None, help="override the phase window, e.g. 11-20")
    ap.add_argument("--pa", default="2,3")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dir", default=None, help="analyse a saved run dir instead of running")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--ref-max", type=int, default=60)
    ap.add_argument("--hands", type=int, default=12, help="crew size for the hand-equivalent")
    a = ap.parse_args(argv)

    spec = PHASES[a.phase]
    if a.days:
        lo, _, hi = a.days.partition("-")
        day0, day1 = int(lo), int(hi)
    else:
        day0, day1 = spec["days"]
    ndays = day1 - day0 + 1

    if a.dir:
        paths = sorted(globmod.glob(str(Path(a.dir) / a.glob)))
        if a.max_games:
            paths = paths[:a.max_games]
        ours = extract_replays(paths, seat=1)
        ours_n = len(paths)
    else:
        seeds = _make_seeds(a.batch, a.seed)
        pa = _parse_pa_arg(a.pa)
        ours = extract_games(pa, seeds, workers=a.workers, steps=spec["steps"])
        ours_n = len(ours)
    ref_paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))[: a.ref_max]
    theirs = extract_replays(ref_paths, seat=a.ref_seat)

    O, T = _stats(ours, day0, day1), _stats(theirs, day0, day1)
    if O is None:
        print("no games")
        return 1
    print(f"# turn_budget — {a.phase} (d{day0}-d{day1}, {ndays} days)")
    print(f"# ours: {a.dir or ('pa=' + a.pa)} -> {ours_n} games")
    print(f"# ref : {len(ref_paths)} replays from {a.ref_from} -> {T['n'] if T else 0} parsed")
    print()
    print(f"   {'':22}{'ours':>10}{'ref':>10}{'ratio':>8}")
    for k, scale in (("unit_turns", 1), ("acts", 1), ("moves", 1), ("pass", 1)):
        r = O[k] / T[k] if T and T[k] else float("nan")
        print(f"   {k:<22}{O[k]:>10,.0f}{T[k]:>10,.0f}{r:>8.2f}")
    print(f"   {'moves per act':<22}{O['moves_per_act']:>10.2f}{T['moves_per_act']:>10.2f}"
          f"{O['moves_per_act'] / T['moves_per_act'] if T and T['moves_per_act'] else float('nan'):>8.2f}")

    if T:
        print(f"\n   -- act deficit by op (per game, median) --")
        print(f"   {'op':<22}{'ours':>8}{'ref':>8}{'short':>8}")
        for op in T["ops"]:
            o, t = O["ops"].get(op, 0.0), T["ops"][op]
            print(f"   {op:<22}{o:>8.0f}{t:>8.0f}{t - o:>8.0f}")

    # ---- the closure arithmetic ------------------------------------------------
    if T:
        demand = sum(T["ops"].values())
        mpa = O["moves_per_act"]
        turns_need = demand * (1 + mpa) + O["pass"]
        turns_have = O["unit_turns"]
        hands_need = turns_need / (24 * ndays)
        hands_have = turns_have / (24 * ndays)
        print(f"\n   -- CLOSURE: can our crew do the reference's workload? --")
        print(f"   reference acts/game            {demand:>10,.0f}")
        print(f"   at OUR moves/act {mpa:.2f}      turns needed {turns_need:>9,.0f}"
              f"   available {turns_have:>9,.0f}   ratio {turns_need / turns_have:>5.2f}x")
        print(f"      -> hand-equivalent {hands_need:>6.1f} vs the {hands_have:.1f} we run")
        for target in (1.0, 0.8, T["moves_per_act"]):
            need = demand * (1 + target) + O["pass"]
            print(f"   at moves/act {target:.2f}             turns needed {need:>9,.0f}"
                  f"   ratio {need / turns_have:>5.2f}x   hands {need / (24 * ndays):>5.1f}")
        print()
        print("   # The binding constraint is conversion, not crew size: the two arms have")
        print("   # the SAME unit-turns. A ratio > 1.0 at our moves/act means the reference")
        print("   # state is unreachable until walks per act fall.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
