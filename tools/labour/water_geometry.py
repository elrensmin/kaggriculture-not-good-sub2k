#!/usr/bin/env python
"""water_geometry — is the day's water demand SCATTERED, or is the crew just wandering?

`move_trace` says WATER starts 40 % of our walks and `walk_runs` says our walks are 15 %
longer than the opponent's. Neither answers the question that decides the fix: **are the
tiles that need water today neighbours, or singletons?**

This rebuilds each farm from the day's first observation, takes the set of tiles that
need water inside their window, and reports its shape:

  * `demand`      — tiles needing water at the start of the day
  * `components`  — 4-connected clusters of that set
  * `isolated`    — tiles with no demand neighbour (a walk each, no matter what)
  * `met`         — how many of the demand tiles the crew actually watered that day
  * `nnd`         — mean nearest-neighbour distance inside the demand set

If `isolated / demand` is high on our farm and low on the opponent's, the fix is the
PLANTING GEOMETRY (a band sown one tile per day carries one water window per tile). If
the two farms look alike, the fix is routing and the geometry theory is dead.

Usage
-----
  PYTHONPATH=. python -m tools.labour.water_geometry --days 11-20 --dir diag-replays/step10-ship
  PYTHONPATH=. python -m tools.labour.water_geometry --days 11-20 \
      --dir diag-replays/step10-ship --ref-from replays/Boey/v1 --ref-max 12
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.state import State                                   # noqa: E402
from tools import team as team_mod                            # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days   # noqa: E402

_MOVES = {"NORTH", "SOUTH", "EAST", "WEST"}
_WINDOW = None


def _in(d):
    return in_window(d, _WINDOW)


def _nnd(pts):
    if len(pts) < 2:
        return 0.0
    out = []
    for p in pts:
        out.append(min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in pts if q != p))
    return statistics.mean(out)


def _components(pts):
    s = set(pts)
    seen = set()
    comps = 0
    for p in s:
        if p in seen:
            continue
        comps += 1
        stack = [p]
        seen.add(p)
        while stack:
            x, y = stack.pop()
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in s and q not in seen:
                    seen.add(q)
                    stack.append(q)
    return comps


def day_stats(rep, seat):
    """{day: (demand, comps, isolated, watered)} for one game."""
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    by_day = {}
    watered = {}
    for t in range(len(steps) - 1):
        d = t // 24
        if not _in(d) or len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        try:
            st = State(obs)
        except Exception:
            continue
        if st.hour == 0 and obs["player"] == seat:
            pts = []
            for y in range(len(st.tiles)):
                for x in range(len(st.tiles[y])):
                    tile = st.tiles[y][x]
                    if not isinstance(tile, dict) or tile.get("kind") != "PLANT":
                        continue
                    if st.plant_ready(tile):
                        continue
                    if st.needs_water(tile) and st.in_water_window(tile):
                        pts.append((x, y))
            if pts:
                by_day[d] = (pts, _components(pts), _nnd(pts))
        act = steps[t + 1][seat].get("action") or {}
        cmds = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
        farm = obs["farms"][seat]
        pos = [tuple(farm["farmer"])] + [tuple(p) for p in farm.get("hands") or []]
        for ui, cmd in enumerate(cmds):
            if ui >= len(pos):
                break
            op = cmd[0] if isinstance(cmd, list) and cmd else "PASS"
            if op == "WATER":
                watered.setdefault(d, set()).add(pos[ui])
    out = {}
    for d, (pts, comps, nnd) in by_day.items():
        w = watered.get(d, set())
        iso = sum(1 for p in pts
                  if not any((p[0] + dx, p[1] + dy) in set(pts)
                             for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))))
        out[d] = (len(pts), comps, iso, len(w & set(pts)), nnd)
    return out


def report(label, dirpath, seat_mode, max_games, window):
    per_day = {}
    games = 0
    for path in sorted(globmod.glob(str(Path(dirpath) / "*.json")))[:max_games]:
        rep = json.load(open(path))
        steps = rep["steps"] if isinstance(rep, dict) else rep.steps
        if not steps or len(steps[0]) < 2:
            continue
        if seat_mode == "auto":
            seat = team_mod.seat_of_names(
                (rep.get("info") or {}).get("TeamNames") or [], fallback=0)
        else:
            seat = int(seat_mode)
        try:
            stats = day_stats(rep, seat)
        except Exception:
            continue
        if not stats:
            continue
        games += 1
        for d, v in stats.items():
            per_day.setdefault(d, []).append(v)
    if not games:
        print(f"### {label}: nothing")
        return
    demand = [statistics.median([v[0] for v in vs]) for vs in per_day.values()]
    comps = [statistics.median([v[1] for v in vs]) for vs in per_day.values()]
    iso = [statistics.median([v[2] for v in vs]) for vs in per_day.values()]
    met = [statistics.median([v[3] for v in vs]) for vs in per_day.values()]
    nnd = [statistics.median([v[4] for v in vs]) for vs in per_day.values()]
    td, tc, ti, tm = sum(demand), sum(comps), sum(iso), sum(met)
    print(f"### {label}  ({games} games, {window})")
    print(f"   per-day medians: demand {statistics.median(demand):.1f}  components"
          f" {statistics.median(comps):.1f}  isolated {statistics.median(iso):.1f}"
          f"  watered {statistics.median(met):.1f}  mean-nnd {statistics.median(nnd):.2f}")
    print(f"   totals: demand {td:,.0f}  components {tc:,.0f}  isolated {ti:,.0f}"
          f" ({100*ti/max(td,1):.0f}% of demand)  watered {tm:,.0f}"
          f" ({100*tm/max(td,1):.0f}% of demand)  demand per component"
          f" {td/max(tc,1):.2f}")
    print()


def main(argv=None):
    global _WINDOW
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="11-20")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--seat", default="1")
    ap.add_argument("--max-games", type=int, default=8)
    ap.add_argument("--ref-from", default=None)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--label", default=None)
    a = ap.parse_args(argv)
    _WINDOW = parse_days(a.days)
    print(f"window: {describe(_WINDOW)}")
    report(a.label or Path(a.dir).name, a.dir, a.seat, a.max_games, a.days)
    if a.ref_from:
        report(Path(a.ref_from).name, a.ref_from, a.ref_seat, a.max_games, a.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
