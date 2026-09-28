#!/usr/bin/env python
"""death_cause — attribute every plant death instead of guessing at it.

Why this exists
---------------
The day-wise benchmark says the reference loses **0 plants every day to d19** and we lose
1-4/day. Four arms were spent trying to fix that by changing the valuation:

  arm                     died
  baseline                 54
  flood routing            48
  value v3 (standing)      70
  value v4 (tile option)   61
  v5 (+ critical boost)    62      <- rank dominance changed NOTHING and cost $4,188

v5 is the tell: making critical work rank-dominant did not move the number, so the deaths are
NOT a ranking problem. Continuing to tune is guessing. This measures the cause instead.

For every PLANT -> WEED transition it records:

  WHEN      day, hour, and whether it happened at the day boundary (the engine's
            `_daily_refresh_plants`: unwatered twice) or mid-day (`_decay_plants`: the yield
            decayed to zero because the tile was never harvested)
  TILE      crop, age, `consecutive_unwatered`, `watered_today`, `yield_units`
  ORPHAN    whether the tile had EVER been watered since it was planted  <- a plant that
            never got its planting-day water never had a chance
  OFFER     whether a WATER job existed for that tile on the previous turn, and whether any
            unit was standing on or next to it  <- separates "we never asked" from "we asked
            and nobody went"

The same scanner runs on the reference's replays, so the comparison is like-for-like and the
difference is a cause rather than a correlation.

Usage
-----
  PYTHONPATH=. python -m tools.labour.death_cause --dir /tmp/ga-vk4 --glob 'treatment_*.json'
  PYTHONPATH=. python -m tools.labour.death_cause --dir replays/Boey/v1 --max-games 20
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import team as team_mod                                       # noqa: E402
from tools.diagnose.games import load_replay                             # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days        # noqa: E402
from tools.phases.phase_map import _seat_of                              # noqa: E402

DAY = 24
_WINDOW = None


def _is_plant(t):
    return isinstance(t, dict) and t.get("kind") == "PLANT"


def _is_weed(t):
    return isinstance(t, dict) and t.get("kind") == "WEED"


def _jobs_for(steps, t, seat):
    """The WATER jobs the layers offered on the previous turn, and where units stood."""
    try:
        from src.state import State
        from src import crop_plan
        obs = steps[t][seat].get("observation")
        if not obs:
            return set(), set()
        st_ = State(obs)
        offered = {j.tile for j in crop_plan.jobs(st_) if j.op == "WATER"}
        near = set()
        for p in st_.positions:
            near.add(tuple(p))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                near.add((p[0] + dx, p[1] + dy))
        return offered, near
    except Exception:                                     # noqa: BLE001
        return set(), set()


def analyse(rep, seat, lo, hi):
    steps = rep["steps"]
    ever_watered = {}
    born = {}
    deaths = []
    for t in range(len(steps) - 1):
        if not in_window(t // DAY, _WINDOW):
            continue
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        ob = steps[t][seat].get("observation")
        nb = steps[t + 1][seat].get("observation")
        if not ob or not nb:
            continue
        day, hour = t // DAY, t % DAY
        tiles_b = ob["farms"][seat]["tiles"]
        tiles_a = nb["farms"][seat]["tiles"]
        # track history
        for y in range(len(tiles_b)):
            for x in range(len(tiles_b[y])):
                tb = tiles_b[y][x]
                if _is_plant(tb):
                    key = (x, y)
                    if born.get(key) != tb.get("planted_day"):
                        born[key] = tb.get("planted_day")
                        ever_watered[key] = False
                    if tb.get("watered_today"):
                        ever_watered[key] = True
        for y in range(len(tiles_b)):
            for x in range(len(tiles_b[y])):
                tb, ta = tiles_b[y][x], tiles_a[y][x]
                if not (_is_plant(tb) and _is_weed(ta)):
                    continue
                key = (x, y)
                offered, near = _jobs_for(steps, max(0, t - 1), seat)
                deaths.append({
                    "day": day, "hour": hour,
                    "boundary": hour == DAY - 1,
                    "crop": tb.get("crop"),
                    "age": day - tb.get("planted_day", day),
                    "consec": tb.get("consecutive_unwatered", 0),
                    "watered_today": bool(tb.get("watered_today")),
                    "yield": tb.get("yield_units", 0),
                    "ever_watered": bool(ever_watered.get(key, False)),
                    "offered": key in offered,
                    "unit_near": key in near,
                })
    return deaths


def _worker(task):
    path, seat_mode, lo, hi = task
    try:
        rep = load_replay(Path(path))
        seat = _seat_of(rep, seat_mode)
        return analyse(rep, seat, lo, hi)
    except Exception as exc:                              # noqa: BLE001
        return [{"error": repr(exc)}]


def report(label, dirpath, seat_mode, max_games, window, glob="*.json"):
    tasks = []
    for p in sorted(globmod.glob(str(Path(dirpath) / glob)))[:max_games]:
        tasks.append((p, seat_mode, window[0][0], window[-1][1]))
    deaths = []
    for tk in tasks:
        deaths.extend(_worker(tk))
    deaths = [d for d in deaths if "error" not in d]
    n_games = len(tasks)
    print(f"\n############ {label}  ({n_games} games, {describe(window)}) ############")
    print(f"   deaths {len(deaths)}  ({len(deaths)/max(1,n_games):.1f}/game)")
    if not deaths:
        return
    by = collections.Counter()
    for d in deaths:
        by["MIDDAY_DECAY" if not d["boundary"] else "DAY_END_DRY"] += 1
    print("   cause:", dict(by))
    for key, lab in (("crop", "by crop"), ("age", "by age")):
        if key == "crop":
            c = collections.Counter(d["crop"] for d in deaths)
            print(f"   {lab}: {dict(c.most_common(6))}")
        else:
            ages = [d["age"] for d in deaths]
            print(f"   {lab}: median {st.median(ages):.0f}  "
                  f"p25 {sorted(ages)[len(ages)//4]}  p75 {sorted(ages)[3*len(ages)//4]}")
    print(f"   NEVER WATERED since planting: "
          f"{sum(1 for d in deaths if not d['ever_watered'])}/{len(deaths)}")
    print(f"   dry at the last observation:  "
          f"{sum(1 for d in deaths if not d['watered_today'])}/{len(deaths)}")
    print(f"   a WATER job existed for it:   "
          f"{sum(1 for d in deaths if d['offered'])}/{len(deaths)}")
    print(f"   a unit was on/next to it:     "
          f"{sum(1 for d in deaths if d['unit_near'])}/{len(deaths)}")
    both = sum(1 for d in deaths if d["offered"] and not d["unit_near"])
    print(f"   OFFERED BUT NOBODY WENT:      {both}/{len(deaths)}")
    print("   day-wise:", dict(sorted(collections.Counter(d['day'] for d in deaths).items())))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--days", default="0-29")
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--team", default="Boey")
    ap.add_argument("--max-games", type=int, default=4)
    ap.add_argument("--label", default=None)
    ns = ap.parse_args(argv)
    team_mod.set_team(ns.team)
    global _WINDOW
    _WINDOW = parse_days(ns.days)
    report(ns.label or ns.dir, ns.dir, ns.seat, ns.max_games, _WINDOW, ns.glob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
