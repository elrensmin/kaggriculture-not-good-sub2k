#!/usr/bin/env python
"""wheat_flow — where the wheat goes, ours vs the #1's, and who does the feeding.

Why this exists
---------------
`crop_demand` shows the tile curve and `dsm_profile` shows the season totals, but neither
answers the midgame question: **we grow a full wheat plateau (32 tiles) and still feed only
110 units and sell almost nothing, while the #1 feeds 380 and sells 591.** This tool puts the
whole chain in one place -- tiles -> plant ops -> harvest ops -> units fed / bought / sold --
and then breaks the work down **per hire**, so "is the feeding scheduled onto the right
worker" is answerable.

It also reports wheat-only deaths, because a wheat tile that dies before harvest is a tile
that produced nothing: 32 standing tiles mean nothing if they weed.

Usage
-----
  PYTHONPATH=. python -m tools.labour.wheat_flow --days 6-17 --dir diag-replays/arm
  PYTHONPATH=. python -m tools.labour.wheat_flow --days 6-17 --dir replays/DSM/v1 \
      --glob '*.json' --max-games 4 --seat auto
  PYTHONPATH=. python -m tools.labour.wheat_flow --days 0-29 --compare --dsm-max 4
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
import statistics as st
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


def _steps_of(obj):
    return obj.steps if hasattr(obj, "steps") else obj.get("steps", [])


def analyse(obj, seat):
    """Return the per-game wheat accounting for one seat over the window."""
    steps = _steps_of(obj)
    ops = collections.Counter()          # PLANT/HARVEST/FEED/DIG ops by item
    fed = bought = sold = 0
    tiles_by_day = {}
    died = 0
    per_unit = collections.defaultdict(collections.Counter)
    prev = None
    for t in range(len(steps)):
        day = t // DAY
        if not _in(day) or len(steps[t]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        farm = obs["farms"][seat]
        tl = farm["tiles"]
        if t % DAY == 0:
            tiles_by_day[day] = sum(
                1 for r in tl for x in r
                if isinstance(x, dict) and x.get("kind") == "PLANT" and x.get("crop") == "WHEAT")
        if prev is not None:
            for y, row in enumerate(tl):
                if y >= len(prev):
                    break
                for x, cell in enumerate(row):
                    if x >= len(prev[y]):
                        continue
                    p = prev[y][x]
                    if (isinstance(cell, dict) and cell.get("kind") == "WEED"
                            and isinstance(p, dict) and p.get("kind") == "PLANT"
                            and p.get("crop") == "WHEAT"):
                        died += 1
        prev = tl
        if t + 1 >= len(steps) or len(steps[t + 1]) <= seat:
            continue
        act = steps[t + 1][seat].get("action") or {}
        cmds = [list(act.get("farmer") or ["PASS"])] + [list(c) for c in (act.get("hands") or [])]
        for u, c in enumerate(cmds):
            if not c:
                continue
            op = c[0]
            if op in ("PLANT", "HARVEST", "DIG") and len(c) > 1:
                ops[(op, c[1])] += 1
            if op == "FEED":
                ops[("FEED", "WHEAT")] += 1
                fed += 1
            per_unit[u][op] += 1
        for o in act.get("market") or []:
            if not o or len(o) < 3:
                continue
            if o[0] == "SELL" and o[1] == "WHEAT":
                sold += int(o[2])
            if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT":
                bought += int(o[2])
    return {"ops": ops, "fed": fed, "sold": sold, "bought": bought,
            "tiles": tiles_by_day, "died": died, "per_unit": per_unit}


def report(rows, label, win):
    fed = st.median([r["fed"] for r in rows])
    sold = st.median([r["sold"] for r in rows])
    bought = st.median([r["bought"] for r in rows])
    died = st.median([r["died"] for r in rows])
    ops = collections.Counter()
    for r in rows:
        ops.update(r["ops"])
    print(f"\n############ {label}  ({win}, {len(rows)} games) ############")
    print(f"   wheat units:  fed {fed:.0f}   bought {bought:.0f}   sold {sold:.0f}   "
          f"feed_surplus(produced-fed) = {sold + fed - bought:.0f} if nothing is held")
    print(f"   wheat tiles that DIED unharvested: {died:.0f}")
    print(f"   PLANT  wheat {ops[('PLANT','WHEAT')]:>5}   HARVEST wheat {ops[('HARVEST','WHEAT')]:>5}"
          f"   DIG wheat {ops[('DIG','WHEAT')]:>5}   FEED {ops[('FEED','WHEAT')]:>5}")
    print(f"   HARVEST/PLANT on wheat = "
          f"{ops[('HARVEST','WHEAT')] / max(1, ops[('PLANT','WHEAT')]):.2f}"
          f"   (a tile that is planted but never harvested was wasted)")
    # feeding vs field work per hire
    agg = collections.Counter()
    for r in rows:
        for u, c in r["per_unit"].items():
            agg[("FEED", u)] += c["FEED"]
            agg[("FIELD", u)] += c["PLANT"] + c["WATER"] + c["HARVEST"] + c["DIG"]
            agg[("CARE", u)] += c["CARE"]
    units = sorted({u for (_k, u) in agg})
    print(f"   -- per-hire work split (median-ish totals across games) --")
    for u in units[:16]:
        print(f"      u{u:<3} FEED {agg[('FEED',u)]:>5}   FIELD {agg[('FIELD',u)]:>6}   "
              f"CARE {agg[('CARE',u)]:>5}")
    days = sorted({d for r in rows for d in r["tiles"]})
    if days:
        print("   -- wheat tiles at start of day --")
        print("      " + "  ".join(f"d{d}:{st.median([r['tiles'].get(d,0) for r in rows]):.0f}"
                                   for d in days))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", default="6-17")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=4)
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--dsm-dir", default="replays/DSM/v1")
    ap.add_argument("--dsm-max", type=int, default=4)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    ns = ap.parse_args(argv)
    team_mod.set_team(ns.team)

    global _WINDOW
    _WINDOW = parse_days(ns.days)
    win = describe(_WINDOW)
    from tools.diagnose.games import load_replay
    from tools.phases.phase_map import _seat_of
    if ns.dir:
        rows = []
        for p in sorted(globmod.glob(os.path.join(ns.dir, ns.glob)))[:ns.max_games]:
            try:
                rep = load_replay(Path(p))
            except Exception as e:
                print(f"   SKIP {Path(p).name}: {e}")
                continue
            rows.append(analyse(rep, _seat_of(rep, ns.seat)))
        if rows:
            report(rows, f"ours ({ns.dir})", win)
    if ns.compare:
        rows = []
        for p in sorted(globmod.glob(os.path.join(ns.dsm_dir, "*.json")))[:ns.dsm_max]:
            try:
                rep = load_replay(Path(p))
            except Exception as e:
                continue
            rows.append(analyse(rep, _seat_of(rep, "auto")))
        if rows:
            report(rows, "DSM (the #1's replays)", win)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
