#!/usr/bin/env python
"""wheat_cycle — how long a wheat tile takes to turn over, and what it yields.

Round 3 established that the phase-2 gap is wheat OUTPUT per tile: 0.51 units/tile-day
against the reference's 0.70, where the theoretical unfertilised maximum is 0.60 (3 units,
harvested at age 4, replanted the same day -> a 4-day cycle). That leaves exactly two
candidate losses, and they need different fixes:

  * **yield loss** — the tile is harvested at 1 or 2 units instead of 3, because a
    bonus-window water (ages 2-4) was missed. Fix lives in the water assignment.
  * **cycle loss** — the tile is replanted the day AFTER it is harvested instead of the
    same day. A 5-day cycle instead of 4 is a flat 20 % of the whole wheat line. Fix lives
    in the plant queue / job supply.

This reads both straight off the action stream and the observation, with no attribution
guesswork: a PLANT op names its crop; a HARVEST op stands on the tile, and the observation
at that step still carries the pre-harvest `planted_day` and `yield_units`.

Usage
-----
  PYTHONPATH=. python -m tools.labour.wheat_cycle --days 6-17 --dir diag-replays/step10-ship
  PYTHONPATH=. python -m tools.labour.wheat_cycle --days 6-17 --dir diag-replays/step10-ship \
      --ref-from replays/Boey/v1 --ref-max 12
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import team as team_mod                          # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days   # noqa: E402


def run_game(rep, seat, window):
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    plants = defaultdict(list)      # tile -> [day planted]
    harvests = defaultdict(list)    # tile -> [(day, age, yield)]
    for t in range(len(steps) - 1):
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        act = steps[t + 1][seat].get("action") or {}
        if not obs:
            continue
        day = t // 24
        farm = obs["farms"][seat]
        pos = [tuple(farm["farmer"])] + [tuple(p) for p in farm.get("hands") or []]
        cmds = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
        for ui, cmd in enumerate(cmds):
            if ui >= len(pos) or not cmd:
                continue
            op = cmd[0]
            item = cmd[1] if len(cmd) > 1 else None
            if not in_window(day, window):
                continue
            if op == "PLANT" and item == "WHEAT":
                plants[pos[ui]].append(day)
            elif op == "HARVEST":
                x, y = pos[ui]
                tile = farm["tiles"][y][x]
                if (isinstance(tile, dict) and tile.get("kind") == "PLANT"
                        and tile.get("crop") == "WHEAT"):
                    harvests[pos[ui]].append(
                        (day, day - tile["planted_day"], tile.get("yield_units", 0)))
    cycles, gaps, yields, ages = [], [], [], []
    for tile, hv in harvests.items():
        ps = plants.get(tile, [])
        for hd, age, y in hv:
            yields.append(y)
            ages.append(age)
            nxt = [p for p in ps if p > hd]
            if nxt:
                gaps.append(min(nxt) - hd)
        for a, b in zip(ps, ps[1:]):
            cycles.append(b - a)
    return cycles, gaps, yields, ages


def report(label, dirpath, seat_mode, max_games, window):
    C, G, Y, A = [], [], [], []
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
            c, g, y, a = run_game(rep, seat, window)
        except Exception:
            continue
        C += c
        G += g
        Y += y
        A += a
        games += 1
    if not games:
        print(f"### {label}: nothing")
        return {}
    def med(v):
        return statistics.median(v) if v else float("nan")
    print(f"### {label}  ({games} games, {window})")
    print(f"   replant cycles (plant->plant, days): n={len(C)} median {med(C):.1f}"
          f"  mean {(statistics.mean(C) if C else float('nan')):.2f}")
    if C:
        from collections import Counter
        print(f"      {dict(sorted(Counter(C).items()))}")
    print(f"   harvest -> next plant gap (days): n={len(G)} median {med(G):.1f}"
          f"  mean {(statistics.mean(G) if G else float('nan')):.2f}")
    if G:
        from collections import Counter
        print(f"      {dict(sorted(Counter(G).items()))}")
    print(f"   harvest age (days): n={len(A)} median {med(A):.1f}"
          f"  mean {(statistics.mean(A) if A else float('nan')):.2f}")
    print(f"   harvest yield (units): n={len(Y)} mean"
          f" {(statistics.mean(Y) if Y else float('nan')):.2f}"
          f"  median {med(Y):.1f}")
    if Y:
        from collections import Counter
        print(f"      {dict(sorted(Counter(Y).items()))}")
    cyc = statistics.mean(C) if C else float("nan")
    yy = statistics.mean(Y) if Y else float("nan")
    print(f"   => implied units/tile-day {yy/cyc if cyc == cyc and cyc else float('nan'):.3f}")
    print()
    return {"cycle": med(C), "gap": med(G), "yield": yy, "units": yy / cyc if cyc else 0}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="6-17")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--seat", default="1")
    ap.add_argument("--max-games", type=int, default=8)
    ap.add_argument("--ref-from", default=None)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--ref-max", type=int, default=None)
    ap.add_argument("--label", default=None)
    a = ap.parse_args(argv)
    window = parse_days(a.days)
    print(f"window: {describe(window)}")
    report(a.label or Path(a.dir).name, a.dir, a.seat, a.max_games, window)
    if a.ref_from:
        report(Path(a.ref_from).name, a.ref_from, a.ref_seat,
               a.ref_max or a.max_games, window)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
