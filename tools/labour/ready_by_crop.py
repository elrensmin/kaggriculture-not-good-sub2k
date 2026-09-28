#!/usr/bin/env python
"""ready_by_crop — how much ripe produce is standing at the start of a day, and how
much of it the crew actually takes before the day ends.

`missed_harvest_eod` exists in `games.csv` but is season-wide and tile-conditioned.
This is the per-day, per-crop version, rebuilt from the observation, and it is the
measurement that separates "the plants never ripened" (left==ready at hour 0, ready stays
0) from "the crew never got there" (ready at hour 0 > 0, few HARVEST ops, still ready at
hour 23).

Usage
-----
  PYTHONPATH=. python -m tools.labour.ready_by_crop --days 6-17 --dir diag-replays/step10-ship
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.state import State                                    # noqa: E402
from tools import team as team_mod                             # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days   # noqa: E402


def _crop(tile):
    return tile.get("crop") if isinstance(tile, dict) else None


def run_game(rep, seat, window):
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    first = {}       # day -> Counter(crop -> ready tiles at hour 0)
    last = {}        # day -> Counter(crop -> ready tiles at hour 23)
    harvests = {}    # day -> Counter(crop -> HARVEST ops)
    planted = {}
    for t in range(len(steps) - 1):
        d = t // 24
        if not in_window(d, window) or len(steps[t]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        try:
            st = State(obs)
        except Exception:
            continue
        if st.hour == 0:
            c = Counter()
            p = Counter()
            for row in st.tiles:
                for tile in row:
                    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                        p[_crop(tile)] += 1
                        if st.plant_ready(tile):
                            c[_crop(tile)] += 1
            first[d] = c
            planted[d] = p
        if st.hour == 23:
            c = Counter()
            for row in st.tiles:
                for tile in row:
                    if (isinstance(tile, dict) and tile.get("kind") == "PLANT"
                            and st.plant_ready(tile)):
                        c[_crop(tile)] += 1
            last[d] = c
        act = steps[t + 1][seat].get("action") or {}
        cmds = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
        for cmd in cmds:
            op = cmd[0] if isinstance(cmd, list) and cmd else "PASS"
            if op == "HARVEST":
                harvests.setdefault(d, Counter())[
                    cmd[1] if len(cmd) > 1 else "?"] += 1
    return first, last, harvests, planted


def report(label, dirpath, seat_mode, max_games, window):
    agg_first = defaultdict(Counter)
    agg_last = defaultdict(Counter)
    agg_harv = defaultdict(Counter)
    agg_plant = defaultdict(Counter)
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
            f, l, h, p = run_game(rep, seat, window)
        except Exception:
            continue
        if not f:
            continue
        games += 1
        for d in f:
            agg_first[d].update(f[d])
        for d in l:
            agg_last[d].update(l[d])
        for d in h:
            agg_harv[d].update(h[d])
        for d in p:
            agg_plant[d].update(p[d])
    if not games:
        print(f"### {label}: nothing")
        return
    print(f"### {label}  ({games} games, {window})")
    a0 = Counter()
    a23 = Counter()
    hv = Counter()
    pl = Counter()
    for c in agg_first.values():
        a0.update(c)
    for c in agg_last.values():
        a23.update(c)
    for c in agg_harv.values():
        hv.update(c)
    for c in agg_plant.values():
        pl.update(c)
    print(f"   {'crop':12s} {'planted':>8s} {'ready@0':>8s} {'harvest':>8s}"
          f" {'ready@23':>9s} {'take%':>6s} {'harv/plant':>10s} {'left/ready':>10s}")
    for crop in sorted(set(pl) | set(hv) | set(a0), key=lambda k: -pl.get(k, 0)):
        p_, r0, h_, r23 = pl.get(crop, 0), a0.get(crop, 0), hv.get(crop, 0), a23.get(crop, 0)
        print(f"   {crop:12s} {p_:8.0f} {r0:8.0f} {h_:8.0f} {r23:9.0f}"
              f" {100*h_/max(r0,1):6.0f} {h_/max(p_,1):10.2f} {r23/max(r0,1):10.2f}")
    print()
    # per-day totals, the shape of the day
    print("   per-day: ready@0 / harvested / ready@23")
    days = sorted(set(agg_first) | set(agg_harv))
    for d in days:
        r0 = sum(agg_first.get(d, Counter()).values())
        h_ = sum(agg_harv.get(d, Counter()).values())
        r23 = sum(agg_last.get(d, Counter()).values())
        p_ = sum(agg_plant.get(d, Counter()).values())
        print(f"      d{d:2d}  planted {p_:3d}   ready {r0:3d}   harvest {h_:3d}"
              f"   still ready {r23:3d}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="6-17")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--seat", default="1")
    ap.add_argument("--max-games", type=int, default=8)
    ap.add_argument("--ref-from", default=None)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--label", default=None)
    a = ap.parse_args(argv)
    window = parse_days(a.days)
    print(f"window: {describe(window)}")
    report(a.label or Path(a.dir).name, a.dir, a.seat, a.max_games, window)
    if a.ref_from:
        report(Path(a.ref_from).name, a.ref_from, a.ref_seat, a.max_games, window)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
