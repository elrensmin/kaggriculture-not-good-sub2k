#!/usr/bin/env python
"""visit_trace — instrument the *tile visit*: how many ops a unit completes per stop,
and how often a tile's op-set is split across units/trips.

Why this exists
---------------
§3.6 established the root cause as **moves per op: 2.7 for us against the #1's 0.9**, a 3.0x
gap of which the same-tile chaining fix recovered only 15 %. The residual is hypothesised to be
that his turnaround unit is *a tile* (land once, run `FEED -> CARE -> COLLECT_FERTILIZER`, or
`PLANT -> WATER`, then leave) while ours is *an act* (re-decide globally every turn, so a visit
never completes).

This measures that directly, and it needs no rule re-implementation: every op in a replay is
performed on the tile the unit stands on, so a **visit** is recoverable from the work stream
alone.

  STOP      a maximal run of work ops by ONE unit on ONE tile with consecutive turns
            (`gap <= 1`). DSM's `FEED -> CARE -> COLLECT_FERTILIZER` is one stop of 3;
            a unit that waters a tile and walks off has a stop of 1.
  TILE-DAY  every op any unit performed on that tile on that day.
  ONE-STOP  a tile-day whose ops all fall inside a single stop -- the visit completed.
  SPLIT     otherwise. `extra_trips = (stops covering the tile-day) - 1` is the movement
            the split cost, and the tool attributes it to the op-pair that was broken.

So the headline numbers are **ops per stop** and **extra trips per tile-day**, plus the exact
op-pairs we split that he does not.

Reads the cache written by ``tools.labour.crew_extract`` (identical schema for his replays and
ours). Run with ``PYTHONPATH=.``.

Usage
-----
  PYTHONPATH=. python -m tools.labour.visit_trace --dsm diag-replays/crew-dsm
  PYTHONPATH=. python -m tools.labour.visit_trace --dsm diag-replays/crew-dsm \
      --us diag-replays/crew-us --phase 2
"""
from __future__ import annotations

from tools import team as team_mod

import argparse
import collections
import glob
import json
import os
import statistics as st

from .crew_extract import OPN, TILE_OPS

PHASES = [(1, 0, 5), (2, 6, 17), (3, 18, 29)]
WORK = set(TILE_OPS)


def load(dirpath, cap=0):
    out = []
    for p in sorted(glob.glob(os.path.join(dirpath, "*.json"))):
        try:
            g = json.load(open(p))
        except Exception:
            continue
        if g.get("records"):
            out.append(g)
        if cap and len(out) >= cap:
            break
    return out


def _work(g, lo, hi):
    """[(turn, unit, day, x, y, op)] for work ops inside the window, turn-ordered."""
    out = []
    for r in g["records"]:
        t = r[0]
        if not (lo * 24 <= t <= hi * 24 + 23):
            continue
        op = OPN.get(r[2])
        if op in WORK:
            out.append((t, r[1], t // 24, r[3], r[4], op))
    out.sort()
    return out


def analyse(games, phase):
    lo, hi = [p for p in PHASES if p[0] == phase][0][1:]
    stops_per_game = []
    ops_per_stop = []
    til = collections.Counter()
    pair_split = collections.Counter()
    pair_tot = collections.Counter()
    extra = 0
    for g in games:
        recs = _work(g, lo, hi)
        if not recs:
            continue
        # ---- stops: same unit, same tile, consecutive turns
        byunit = collections.defaultdict(list)
        for t, u, d, x, y, op in recs:
            byunit[u].append((t, u, d, x, y, op))
        stops = []                       # (tile, day, [ops], first_turn, last_turn)
        for u, seq in byunit.items():
            cur = None
            for item in seq:
                t, _u, d, x, y, op = item
                if cur and cur[0] == (x, y) and t - cur[4] <= 1:
                    cur[2].append(op)
                    cur[4] = t
                else:
                    if cur:
                        stops.append(cur)
                    cur = [(x, y), d, [op], t, t]
            if cur:
                stops.append(cur)
        stops_per_game.append(len(stops))
        for s in stops:
            ops_per_stop.append(len(s[2]))
        # ---- tile-day: which stops cover it
        cover = collections.defaultdict(list)   # (day,x,y) -> [stop index]
        for i, s in enumerate(stops):
            cover[(s[1], s[0][0], s[0][1])].append(i)
        for key, idxs in cover.items():
            til["tile_days"] += 1
            if len(idxs) == 1:
                til["one_stop"] += 1
            else:
                til["split"] += 1
                extra += len(idxs) - 1
                # attribute: every op-pair inside this tile-day that lands in
                # different stops is a broken chain
                seq = []
                for i in idxs:
                    for op in stops[i][2]:
                        seq.append((stops[i][3], op, i))
                seq.sort()
                for a, b in zip(seq, seq[1:]):
                    pair_tot[(a[1], b[1])] += 1
                    if a[2] != b[2]:
                        pair_split[(a[1], b[1])] += 1
    return {
        "games": len(games),
        "stops": stops_per_game,
        "ops_per_stop": ops_per_stop,
        "tile_days": til["tile_days"],
        "one_stop": til["one_stop"],
        "split": til["split"],
        "extra": extra,
        "pair_split": pair_split,
        "pair_tot": pair_tot,
    }


def _pct(v):
    return f"{100*v:.0f}%" if v == v else "--"


def show(res, label):
    if not res or not res["tile_days"]:
        return
    ops = res["ops_per_stop"]
    dist = collections.Counter(min(o, 4) for o in ops)
    n = len(ops) or 1
    print(f"\n  --- {label} ---")
    print(f"    games {res['games']}   stops/game {st.median(res['stops']):.0f}   "
          f"ops/stop mean {st.mean(ops):.2f}")
    print("    ops per stop  " + "  ".join(
        f"{k if k < 4 else '4+'}:{dist.get(k,0)/n:.0%}" for k in (1, 2, 3, 4)))
    print(f"    tile-days {res['tile_days']}   one-stop {res['one_stop']/res['tile_days']:.0%}   "
          f"split {res['split']/res['tile_days']:.0%}   "
          f"extra trips/tile-day {res['extra']/res['tile_days']:.3f}")
    if res["pair_tot"]:
        print("    most-split op-pairs inside a tile-day (split share):")
        rows = sorted(res["pair_tot"].items(), key=lambda kv: -kv[1])[:10]
        for (a, b), tot in rows:
            print(f"      {a + ' -> ' + b:32} n={tot:>7}  split {res['pair_split'][(a,b)]/tot:>5.0%}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsm", default="diag-replays/crew-dsm")
    ap.add_argument("--us", default=None)
    ap.add_argument("--phase", type=int, default=2)
    ap.add_argument("--cap", type=int, default=0)
    ap.add_argument("--label", default=None, help="reference arm label (default: $KAGG_OPPONENT / DSM)")
    a = ap.parse_args()
    a.label = a.label or team_mod.get()

    dsm, us = load(a.dsm, a.cap), (load(a.us, a.cap) if a.us else [])
    if not dsm and not us:
        print("no cached games — run tools.labour.crew_extract first")
        return
    print(f"\n{'='*88}\n  TILE VISITS — phase {a.phase}   "
          f"({a.label} {len(dsm)} games, US {len(us)} games)\n{'='*88}")
    if dsm:
        show(analyse(dsm, a.phase), f"{a.label} (#1)")
    if us:
        show(analyse(us, a.phase), "US")


if __name__ == "__main__":
    main()
