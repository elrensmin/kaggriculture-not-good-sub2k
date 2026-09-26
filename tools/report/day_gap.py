#!/usr/bin/env python
"""day_gap — where, by day, our farm falls behind DSM's.

`dsm_profile` answers *what* our farm is; this answers *when* it loses the game.
It reads the per-day CSVs of both arms and prints three things:

  1. a per-day side-by-side of work and output (`unit_turns`, `idle_*`,
     `plants_watered`, `animals_fed/cared`, `max_shed_total`, `revenue`);
  2. the same series aggregated into day bands, with the revenue gap each band
     contributes and the idle work-units each band wastes;
  3. cumulative revenue for both arms, so the day our curve breaks away is
     visible rather than asserted.

Normalisation matters here and is not optional. DSM's arm is 67 ladder teams with
1-14 games each; ours is 13 public agents x N seeds. A pooled per-day median is
partly a description of the *matchmaking pool* — 14 games against one team outvote
one game against another. So every figure is computed as
**per-opponent median -> median across opponents**, and the pooled value is printed
next to it only to show the size of the distortion.

The `revenue` column is a signal, not a fact: on leaderboard replays there is no
market audit, so DSM's per-day revenue is the sign-split of the money delta, which
undercounts a step that both buys and sells. Ours is audit-backed. Compare the
*shape* and the sign of the gap, not the last dollar.

Usage:
    PYTHONPATH=. python -m tools.report.day_gap \\
        --ours diag-replays/sweep_old_s4362837462_b15 --dsm replays/DSM/v1
"""
from __future__ import annotations

import argparse
import csv
import glob as globmod
import os
from collections import defaultdict

from tools.diagnose.window import parse_days, in_window, describe

# Work/output columns present in BOTH arms' day CSVs, audit-free unless noted.
COLS = ("unit_turns", "idle_units", "idle_share_pct", "plants_watered",
        "plants_fertilized", "animals_fed", "animals_cared", "max_shed_total",
        "end_shed_total", "weeds_max", "revenue")
BANDS = (("d0-5", range(0, 6)), ("d6-11", range(6, 12)), ("d12-17", range(12, 18)),
         ("d18-23", range(18, 24)), ("d24-29", range(24, 30)))


def _q(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(f * len(xs)))] if xs else 0.0


def _med(xs):
    return _q(xs, .5)


def load(days_glob, agent, ranges=None):
    """{(opponent, day): {col: [values]}} — one value per GAME (file x opponent).

    `ranges` restricts the rows to a day window (`--days 0-5`).
    """
    per = defaultdict(lambda: defaultdict(list))
    seen = set()
    nfiles = 0
    for f in sorted(globmod.glob(days_glob)):
        nfiles += 1
        rows_by_key = defaultdict(list)
        for r in csv.DictReader(open(f)):
            if r.get("agent") != agent:
                continue
            try:
                day = int(r["day"])
            except (KeyError, ValueError):
                continue
            if ranges and not in_window(day, ranges):
                continue
            opp = (r.get("opponent") or "?").strip()
            rows_by_key[(opp, day)].append(r)
        for (opp, day), rs in rows_by_key.items():
            if (f, opp, day) in seen:
                continue
            seen.add((f, opp, day))
            for c in COLS:
                try:
                    per[(opp, day)][c].append(float(rs[0].get(c) or 0))
                except (TypeError, ValueError):
                    pass
    return per, nfiles


def series(per, col, day, normalise=True):
    """Per-opponent medians for one day/column, then one pooled number.

    Returns `(pooled_median, median_of_per_opponent_medians, n_opponents)`.
    """
    by_opp = defaultdict(list)
    for (opp, d), cols in per.items():
        if d != day:
            continue
        for v in cols.get(col, []):
            by_opp[opp].append(v)
    pooled = [v for vs in by_opp.values() for v in vs]
    meds = [_med(vs) for vs in by_opp.values() if vs]
    if normalise:
        return (_med(meds), len(meds))
    return (_med(pooled), len(meds))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="diag-replays/sweep_old_s4362837462_b15",
                    help="our run dir (its days_seed*.csv)")
    ap.add_argument("--dsm", default=None, help="DSM replay dir (default replays/DSM/v1)")
    ap.add_argument("--ours-agent", default="old")
    ap.add_argument("--dsm-agent", default="DSM")
    ap.add_argument("--pooled-too", action="store_true",
                    help="also print the pooled medians, to show the frame distortion")
    ap.add_argument("--days", default=None,
                    help="restrict to a day window, e.g. 0-5 or 0-5,12-17")
    args = ap.parse_args()

    ranges = parse_days(args.days)
    days = [d for d in range(30) if in_window(d, ranges)]
    bands = ([("d" + describe(ranges).replace("d", ""), days)] if ranges else list(BANDS))

    dsm_dir = args.dsm
    if not dsm_dir:
        for cand in ("replays/DSM/v1", "replays/DSM"):
            if globmod.glob(f"{cand}/days_seed*.csv"):
                dsm_dir = cand
                break
        else:
            dsm_dir = "replays/DSM"

    if ranges:
        print("window:", describe(ranges))
    O, no = load(os.path.join(args.ours, "days_seed*.csv"), args.ours_agent, ranges)
    D, nd = load(os.path.join(dsm_dir, "days_seed*.csv"), args.dsm_agent, ranges)
    if not O or not D:
        print(f"no day CSVs found (ours={len(O)} dsm={len(D)}) -- check --ours / --dsm")
        return

    print("############ ours vs dsm — per-day gap ############")
    print(f"ours {args.ours}  (agent={args.ours_agent}, {no} day files)")
    print(f"dsm  {dsm_dir}  (agent={args.dsm_agent}, {nd} day files)")
    print("every figure = median of per-opponent medians (each opponent counts once)")

    print(f"\n-- per-day medians (ours / dsm) --")
    print("   day | " + " | ".join(f"{c[:13]:>13s}" for c in COLS))
    for day in [d for d in days if d % 2 == 0]:
        cells = []
        for c in COLS:
            o, _ = series(O, c, day)
            s, _ = series(D, c, day)
            cells.append(f"{o:6.0f}/{s:<6.0f}")
        print(f"   {day:3d} | " + " | ".join(f"{v:>13s}" for v in cells))

    print(f"\n-- by band: revenue contribution and idle work-units --")
    print(f"   {'band':7s} {'ours rev':>10s} {'dsm rev':>10s} {'gap':>10s} {'%':>7s} | "
          f"{'ours idle_u':>11s} {'dsm idle_u':>10s}")
    to = ts = 0
    for name, days in bands:
        o = sum(series(O, "revenue", d)[0] for d in days)
        s = sum(series(D, "revenue", d)[0] for d in days)
        oi = sum(series(O, "idle_units", d)[0] for d in days)
        si = sum(series(D, "idle_units", d)[0] for d in days)
        to += o
        ts += s
        pct = f"{(o/s-1)*100:+.1f}%" if s else "n/a"
        print(f"   {name:7s} {o:10.0f} {s:10.0f} {o-s:10.0f} {pct:>7s} | "
              f"{oi:11.0f} {si:10.0f}")
    print(f"   {'TOTAL':7s} {to:10.0f} {ts:10.0f} {to-ts:10.0f} "
          f"{((to/ts-1)*100 if ts else 0):+6.1f}%")

    print(f"\n-- cumulative revenue (sum of per-day medians) --")
    co = cs = 0
    prev_gap = 0.0
    for day in days:
        co += series(O, "revenue", day)[0]
        cs += series(D, "revenue", day)[0]
        gap = co - cs
        step = gap - prev_gap
        prev_gap = gap
        if day == days[-1] or day in (5, 8, 11, 14, 17, 20, 23, 26, 29):
            print(f"   through d{day:2d}: ours {co:9.0f}  dsm {cs:9.0f}  "
                  f"gap {gap:9.0f}  ({(co/cs-1)*100 if cs else 0:+6.1f}%)  "
                  f"this day {step:+8.0f}")

    print(f"\n-- totals over the season (sum of per-day medians) --")
    for c in COLS:
        o = sum(series(O, c, d)[0] for d in days)
        s = sum(series(D, c, d)[0] for d in days)
        pct = f"{((o/s-1)*100):+7.1f}%" if s else "n/a"
        print(f"   {c:20s} ours {o:10.1f}   dsm {s:10.1f}   {pct}")

    if args.pooled_too:
        print(f"\n-- frame-distortion check (pooled vs normalised, season totals) --")
        print(f"   {'column':20s} {'ours pooled':>12s} {'ours norm':>10s} "
              f"{'dsm pooled':>11s} {'dsm norm':>9s}")
        for c in COLS:
            op = sum(series(O, c, d, normalise=False)[0] for d in days)
            on = sum(series(O, c, d)[0] for d in days)
            sp = sum(series(D, c, d, normalise=False)[0] for d in days)
            sn = sum(series(D, c, d)[0] for d in days)
            print(f"   {c:20s} {op:12.1f} {on:10.1f} {sp:11.1f} {sn:9.1f}")


if __name__ == "__main__":
    main()
