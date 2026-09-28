#!/usr/bin/env python
"""production — units that actually ARRIVED in the shed, per item, per day.

Everything measured so far counts crew ACTIONS (`HARVEST ops`, `FEED ops`) or standing
stock (`planted tiles`). Round 2 established that our action count is 0.55x the reference's
while our standing stock is 1.0x, and that no scheduler knob fixes it -- so the question
becomes: **is the shortfall in the ops, or in the output those ops move?**

This answers it exactly and seat-symmetrically. The shed is the one place both players'
production is observable: a positive step-to-step delta in `private.shed[item]` is a unit
that was produced (or bought), and units only leave by selling, feeding, or discarding.
So:

    inflow(item, window) = sum of positive shed deltas
    production           = inflow - bought          (BUY_PRODUCT orders in the same window)

No market audit is needed, so Boey's leaderboard replays and ours are measured identically.
Output per tile-day (crops) and per animal-day (herd) come from the same run, so
"we farm the same area and make half as much" is checkable rather than inferred.

Usage
-----
  PYTHONPATH=. python -m tools.labour.production --days 6-17 --dir diag-replays/step10-ship
  PYTHONPATH=. python -m tools.labour.production --days 6-17 --dir diag-replays/step10-ship \
      --ref-from replays/Boey/v1 --ref-max 12
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

from src import params as agent_params                      # noqa: E402
from tools import team as team_mod                          # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days   # noqa: E402

ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
HERD = ("GOOSE", "COW", "SHEEP")


def run_game(rep, seat, window):
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    inflow = Counter()
    bought = Counter()
    animal_days = Counter()
    tile_days = Counter()
    prev_shed = None
    for t in range(len(steps) - 1):
        d = t // 24
        if len(steps[t]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        shed = dict((obs.get("private") or {}).get("shed") or {})
        if _in(d, window):
            if prev_shed is not None:
                for k, v in shed.items():
                    dv = v - prev_shed.get(k, 0)
                    if dv > 0:
                        inflow[k] += dv
            farm = obs["farms"][seat]
            for row in farm["tiles"]:
                for tile in row:
                    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                        tile_days[tile["crop"]] += 1
                    if isinstance(tile, dict) and "animal" in tile:
                        animal_days[tile["animal"]] += 1
        prev_shed = shed
        if _in(d, window) and t + 1 < len(steps) and len(steps[t + 1]) > seat:
            act = steps[t + 1][seat].get("action") or {}
            for o in (act.get("market") or [])[:agent_params.MAX_ORDERS]:
                if o and len(o) > 2 and o[0] == "BUY_PRODUCT":
                    bought[o[1]] += float(o[2])
    prod = Counter()
    for k, v in inflow.items():
        prod[k] = v - bought.get(k, 0.0)
    return prod, animal_days, tile_days


def _in(d, window):
    return in_window(d, window)


def report(label, dirpath, seat_mode, max_games, window):
    prod = Counter()
    adays = Counter()
    tdays = Counter()
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
            p, a, t_ = run_game(rep, seat, window)
        except Exception:
            continue
        prod.update(p)
        adays.update(a)
        tdays.update(t_)
        games += 1
    if not games:
        print(f"### {label}: nothing")
        return {}
    print(f"### {label}  ({games} games, {window})")
    print(f"   {'item':12s} {'produced':>10s} {'per game':>9s} {'source days':>12s}"
          f" {'per day':>9s}")
    out = {}
    for item in sorted(prod, key=lambda k: -prod[k]):
        v = prod[item] / games
        if item in ANIMAL_PRODUCT.values():
            src = sum(adays[k] for k, p in ANIMAL_PRODUCT.items() if p == item) / games
            kind = "animal-day"
        elif item in ("FERTILIZER",):
            src = sum(adays.values()) / games
            kind = "animal-day"
        else:
            src = tdays.get(item, 0) / games
            kind = "tile-day"
        per = v / src if src else float("nan")
        out[item] = (v, per)
        print(f"   {item:12s} {prod[item]:10,.0f} {v:9,.1f} {src:12,.0f} {per:9.3f}")
    total_animals = sum(adays.values()) / games
    total_tiles = sum(tdays.values()) / games
    print(f"   animal-days/game {total_animals:,.0f}   tile-days/game {total_tiles:,.0f}")
    print()
    return out


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
    mine = report(a.label or Path(a.dir).name, a.dir, a.seat, a.max_games, window)
    if a.ref_from:
        theirs = report(Path(a.ref_from).name, a.ref_from, a.ref_seat,
                        a.ref_max or a.max_games, window)
        print("=== output per source-day, ours vs reference ===")
        print(f"   {'item':12s} {'ours':>9s} {'ref':>9s} {'ratio':>7s}")
        for item in sorted(set(mine) | set(theirs), key=lambda k: -mine.get(k, (0, 0))[0]):
            mo = mine.get(item, (0, 0))[1]
            to = theirs.get(item, (0, 0))[1]
            print(f"   {item:12s} {mo:9.3f} {to:9.3f} {mo/to if to else float('nan'):7.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
