#!/usr/bin/env python
"""crew_patterns — break the #1's crew / plant / move management down by phase.

Reads the cache written by ``tools.labour.crew_extract`` (both the #1's 123
leaderboard episodes and our own runs share the schema) and reports, for each of
the three phases, the things a scheduler actually controls:

  CREW    unit-turn budget, the op mix, how many turns go to walking, how many
          productive ops a unit gets out of a day, and how much of the crew is idle.

  ALLOC   the allocation kernel's own scoreboard: the **chain distance** between a
          unit's consecutive work tiles, the **walk turns** between them, and the
          share of work that is back-to-back or adjacent. A nearest-job scheduler
          scores ~1.0 here; letting priority override distance scores 2-3.

  PLANTS  waters and harvests per tile-day, harvest age and units-per-harvest by
          crop — the plant-management half, and the surface the yield gap lives on.

  RADIUS  mean distance of each op type from the shed (the central 2x2 access set),
          which is what makes an op cheap or expensive in the first place.

Judgement is per phase and per game; cross-game figures are medians, never means
of an aggregate. Run with ``PYTHONPATH=.``.

Usage
-----
  PYTHONPATH=. python -m tools.report.crew_patterns --dsm diag-replays/crew-dsm
  PYTHONPATH=. python -m tools.report.crew_patterns --dsm diag-replays/crew-dsm \
      --us diag-replays/crew-us
  PYTHONPATH=. python -m tools.report.crew_patterns --dsm diag-replays/crew-dsm --phase 2
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics as st

from ..labour.crew_extract import OPN, MOVE_OPS, SHED_OPS, TILE_OPS, shed_dist

PHASES = [(1, 0, 5), (2, 6, 17), (3, 18, 29)]
WORK = set(TILE_OPS)
MOVES = set(MOVE_OPS)
SHEDOPS = set(SHED_OPS)


def load(dirpath, cap=0):
    out = []
    for p in sorted(glob.glob(os.path.join(dirpath, "*.json"))):
        try:
            g = json.load(open(p))
        except Exception:
            continue
        if g.get("records") or g.get("turns"):
            out.append(g)
        if cap and len(out) >= cap:
            break
    return out


def _chain(recs, ops_filter):
    """Per-unit chain statistics over the given op set."""
    byunit = collections.defaultdict(list)
    for r in recs:
        op = OPN.get(r[2])
        if op in ops_filter:
            byunit[r[1]].append((r[0], r[3], r[4], op))
    cd, wt, n = [], [], 0
    for u, seq in byunit.items():
        seq.sort()
        for a, b in zip(seq, seq[1:]):
            cd.append(abs(a[1] - b[1]) + abs(a[2] - b[2]))
            wt.append(max(0, b[0] - a[0] - 1))
            n += 1
    return cd, wt


def metrics(games, phase):
    lo = [p for p in PHASES if p[0] == phase][0]
    lo, hi = lo[1], lo[2]
    M = collections.defaultdict(list)
    for g in games:
        recs = [r for r in g["records"] if lo <= r[0] // 24 <= hi]
        turns = {int(k): v for k, v in g["turns"].items()
                 if lo <= int(k) // 24 <= hi}
        if not recs:
            continue
        ops = collections.Counter(OPN.get(r[2]) for r in recs)
        ut = len(recs)
        M["unit_turns"].append(ut)
        M["hands"].append(st.median([v[1] for v in turns.values()]) if turns else 0)
        M["hires"].append(max([v[2] for v in turns.values()], default=0))
        M["work_share"].append(sum(ops[o] for o in WORK) / ut)
        M["move_share"].append(sum(ops[o] for o in MOVES) / ut)
        M["pass_share"].append(ops["PASS"] / ut)
        M["moves_per_work"].append(
            sum(ops[o] for o in MOVES) / max(1, sum(ops[o] for o in WORK)))
        # the allocation scoreboard
        cd, wt = _chain(recs, WORK)
        if cd:
            M["chain_dist"].append(st.mean(cd))
            M["chain_eq1"].append(sum(1 for d in cd if d <= 1) / len(cd))
            M["chain_eq0"].append(sum(1 for d in cd if d == 0) / len(cd))
            M["walk_turns"].append(st.mean(wt))
            M["b2b"].append(sum(1 for w in wt if w == 0) / len(wt))
        # distinct work tiles per unit per day
        per = collections.defaultdict(set)
        for r in recs:
            if OPN.get(r[2]) in WORK:
                per[(r[0] // 24, r[1])].add((r[3], r[4]))
        if per:
            M["tiles_per_unit_day"].append(st.mean([len(v) for v in per.values()]))
        # radius
        for o in ("WATER", "HARVEST", "PLANT", "FEED", "CARE",
                  "COLLECT_FERTILIZER", "FERTILIZE", "DIG"):
            rr = [shed_dist(r[3], r[4]) for r in recs if OPN.get(r[2]) == o]
            if rr:
                M[f"rad_{o}"].append(st.mean(rr))
        # plants
        hb = collections.defaultdict(list)
        hq = collections.defaultdict(list)
        for r in recs:
            if OPN.get(r[2]) == "HARVEST" and r[5]:
                if r[6] >= 0:
                    hb[r[5]].append(r[6])
                if r[8] >= 0:
                    hq[r[5]].append(r[8])
        for c in ("WHEAT", "CARROT", "MELON", "STRAWBERRY", "TOMATO"):
            if hb.get(c):
                M[f"hage_{c}"].append(st.mean(hb[c]))
            if hq.get(c):
                M[f"hyld_{c}"].append(st.mean(hq[c]))
            M[f"hn_{c}"].append(len(hq.get(c, [])))
        M["waters"].append(ops["WATER"])
        M["harvests"].append(ops["HARVEST"])
        M["plants"].append(ops["PLANT"])
    return M


def chains(games, phase, top=16):
    """Consecutive-work-op transition matrix for one phase.

    This is the crew-management fingerprint: which op follows which, and at what
    tile distance. DSM's whole advantage shows up here as d=0 chains
    (PLANT->WATER, FEED->CARE, FERTILIZE->WATER, HARVEST->PLANT) — he finishes a
    tile's op set before moving on.
    """
    lo = [p for p in PHASES if p[0] == phase][0]
    lo, hi = lo[1], lo[2]
    pairs = collections.Counter()
    dist = collections.Counter()
    for g in games:
        byu = collections.defaultdict(list)
        for r in g["records"]:
            if not (lo <= r[0] // 24 <= hi):
                continue
            op = OPN.get(r[2])
            if op in WORK:
                byu[r[1]].append((r[0], r[3], r[4], op))
        for u, seq in byu.items():
            seq.sort()
            for a, b in zip(seq, seq[1:]):
                pairs[(a[3], b[3])] += 1
                dist[(a[3], b[3], min(abs(a[1] - b[1]) + abs(a[2] - b[2]), 2))] += 1
    tot = sum(pairs.values()) or 1
    print(f"\n  --- phase {phase} chains ({tot} transitions over {len(games)} games) ---")
    print(f"  {'chain':34} {'n':>8} {'share':>7} {'d=0':>7} {'d=1':>7} {'d>=2':>7}")
    for (a, b), n in pairs.most_common(top):
        print(f"  {a + ' -> ' + b:34} {n:>8} {n/tot:>6.1%} "
              f"{dist[(a,b,0)]/n:>6.0%} {dist[(a,b,1)]/n:>6.0%} {dist[(a,b,2)]/n:>6.0%}")


def _fmt(rows, label, phases):
    print(f"\n{'='*92}\n  {label}\n{'='*92}")
    hdr = "  " + f"{'metric':26}" + "".join(f"{'p'+str(p):>21}" for p, _, _ in phases)
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for key in rows:
        print(f"  {key:26}" + "".join(f"{rows[key][i]:>21}" for i in range(len(phases))))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsm", default="diag-replays/crew-dsm")
    ap.add_argument("--us", default=None)
    ap.add_argument("--phase", type=int, default=0)
    ap.add_argument("--cap", type=int, default=0)
    ap.add_argument("--chains", action="store_true",
                    help="print the consecutive-op transition matrix instead")
    a = ap.parse_args()

    phases = [p for p in PHASES if not a.phase or p[0] == a.phase]
    dsm = load(a.dsm, a.cap)
    us = load(a.us, a.cap) if a.us else []
    if not dsm:
        print(f"no cached games in {a.dsm} — run tools.labour.crew_extract first")
        return
    print(f"DSM games: {len(dsm)}   US games: {len(us)}")

    # metric order
    order = ["hands", "hires", "unit_turns", "work_share", "move_share",
             "pass_share", "moves_per_work",
             "chain_dist", "chain_eq1", "chain_eq0", "walk_turns", "b2b",
             "tiles_per_unit_day",
             "rad_WATER", "rad_HARVEST", "rad_FEED", "rad_CARE",
             "rad_COLLECT_FERTILIZER", "rad_FERTILIZE",
             "waters", "harvests", "plants",
             "hage_WHEAT", "hyld_WHEAT", "hn_WHEAT",
             "hage_CARROT", "hyld_CARROT", "hn_CARROT",
             "hage_MELON", "hyld_MELON", "hn_MELON",
             "hage_STRAWBERRY", "hyld_STRAWBERRY", "hn_STRAWBERRY",
             "hage_TOMATO", "hyld_TOMATO", "hn_TOMATO"]

    def med(M, key):
        v = M.get(key)
        return st.median(v) if v else float("nan")

    if a.chains:
        for label, games in (("DSM (#1)", dsm), ("US", us)):
            if games:
                print(f"\n##### {label} #####")
                for p in phases:
                    chains(games, p[0])
        return

    for label, games in (("DSM (#1)", dsm), ("US", us)):
        if not games:
            continue
        per = [metrics(games, p[0]) for p in phases]
        rows = {k: [med(m, k) for m in per] for k in order}
        _fmt(rows, f"{label}  —  per-phase medians over {len(games)} games", phases)

    if us and dsm:
        print(f"\n{'='*92}\n  DELTA (US - DSM), positive = we have MORE of it\n{'='*92}")
        dper = [metrics(dsm, p[0]) for p in phases]
        uper = [metrics(us, p[0]) for p in phases]
        hdr = "  " + f"{'metric':26}" + "".join(f"{'p'+str(p):>21}" for p, _, _ in phases)
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for k in order:
            cells = []
            for i in range(len(phases)):
                d, u = med(dper[i], k), med(uper[i], k)
                cells.append(f"{u-d:>+21.2f}" if d == d and u == u else f"{'--':>21}")
            print(f"  {k:26}" + "".join(cells))


if __name__ == "__main__":
    main()
