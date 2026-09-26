#!/usr/bin/env python
"""balance — the paired, TOTAL effect of one change.

Every structural fix in `docs/current-plan.md` is measured with this: it answers
"the target moved, but what else did I break?" by diffing TWO of our own arms on
the **same (opponent, seed) games only**, across the whole metric surface —
margin, guards, investment ledger, structures, herd, crops, labour, shed, wheat,
revenue mix.

Why paired-and-shared-keys matters
----------------------------------
A fix is usually verified on a smaller arm than the frozen baseline (24 games
vs 180). Comparing those two arms unpaired compares two different frames. This
tool intersects the `(opponent, seed)` keys first and computes *every* metric on
the intersection, so the baseline and the candidate describe the same games.

Why DSM is not a column here
----------------------------
DSM's own numbers are static and already live in `docs/current-plan.md`; what
changes per fix is *our* number. The plan's accept conditions reference DSM, but
the per-fix readout only needs the paired delta.

Judging
-------
Each row carries `OK` / `WARN` against a small tolerance and a direction. The
verdict at the bottom is a regression list, not a score: a change that hits its
target with an empty list is landable; one that hits its target and prints WARN
rows is the trade to weigh.

Usage::

    PYTHONPATH=. python -m tools.gates.balance \\
        --baseline diag-replays/sweep_old_s4362837462_b15 \\
        --candidate diag-replays/s5-24
"""
from __future__ import annotations

import argparse
import csv
import glob as globmod
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tools.report.dsm_profile import _one  # noqa: E402

# ---------------------------------------------------------------- scalars
# (name, extractor, direction, tolerance) -- direction +1 = higher is better.
GAME_SCALARS = (
    ("margin p10", lambda m: _q(m["mgn"], .10), +1, 500.0),
    ("margin p25", lambda m: _q(m["mgn"], .25), +1, 500.0),
    ("margin p50", lambda m: _q(m["mgn"], .50), +1, 500.0),
    ("margin p75", lambda m: _q(m["mgn"], .75), +1, 500.0),
    ("margin p90", lambda m: _q(m["mgn"], .90), +1, 500.0),
    ("median win", lambda m: _q(m["wins"], .50), +1, 500.0),
    ("median loss", lambda m: _q(m["losses"], .50), +1, 500.0),
    ("max loss", lambda m: min(m["mgn"]) if m["mgn"] else 0.0, +1, 500.0),
    ("win%", lambda m: 100.0 * len(m["wins"]) / max(1, len(m["mgn"])), +1, 1.0),
    ("% losing > $4k", lambda m: 100.0 * sum(1 for x in m["mgn"] if x < -4000)
     / max(1, len(m["mgn"])), -1, 1.0),
)

GUARDS = (
    ("idle_units_ready_total", -1, 0.5),
    ("locked_steps", -1, 2.0),
    ("idle_share_pct", -1, 0.2),
    ("discarded_units_total", -1, 0.5),
    ("shed_overflow_days", -1, 0.2),
    ("stranded_at_bell", -1, 5.0),
    ("floor_sales", -1, 3.0),
    ("animal_escapes", -1, 0.5),
    ("feed_surplus", +1, 5.0),
    ("harvests", +1, 5.0),
    ("missed_harvest_eod", -1, 0.5),
    ("plants_died", -1, 1.0),
    ("unwatered_eod", -1, 10.0),
    ("unfed_signals", -1, 3.0),
    ("weeds_peak", -1, 0.3),
    ("sell_revenue_total", +1, 1000.0),
)


def _q(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(f * len(xs)))] if xs else 0.0


def _med(xs):
    return _q(xs, .5)


def _key_from_path(p):
    """`old_vs_<opponent>_seed<seed>.json` -> (opponent, seed)."""
    m = re.search(r"_vs_(.+)_seed(\d+)\.json$", os.path.basename(p))
    return (m.group(1), m.group(2)) if m else None


def load_games(run_dir, agent):
    path = os.path.join(run_dir, "games.csv")
    if not os.path.isfile(path):
        raise SystemExit(f"no games.csv in {run_dir}")
    rows = list(csv.DictReader(open(path)))
    keep = [r for r in rows if (r.get("agent") or "") == agent]
    if not keep:
        labels = sorted({(r.get("agent") or "") for r in rows})
        alt = [a for a in labels if a and a != agent]
        if len(alt) == 1:
            keep = [r for r in rows if r.get("agent") == alt[0]]
        else:
            keep = rows
    return {(_r_opp(r), r["seed"]): r for r in keep}


def _r_opp(r):
    return r.get("opponent") or "unknown"


def _num(r, col):
    try:
        return float(r.get(col) or 0)
    except (TypeError, ValueError):
        return 0.0


def metrics_from_games(rows):
    mgn, wins, losses = [], [], []
    for r in rows:
        try:
            x = float(r["final_money"]) - float(r["opponent_final"])
        except (TypeError, ValueError):
            continue
        mgn.append(x)
        (wins if x > 0 else losses).append(x)
    out = {"mgn": mgn, "wins": wins, "losses": losses}
    for col, _d, _t in GUARDS:
        out[col] = [_num(r, col) for r in rows]
    for col in ("seed_cost_total", "animal_cost_total", "product_cost_total",
                "hire_cost_total", "land_cost_total"):
        out[col] = [_num(r, col) for r in rows]
    out["input spend"] = [sum(_num(r, c) for c in
                              ("seed_cost_total", "animal_cost_total",
                               "product_cost_total", "hire_cost_total")) for r in rows]
    return out


def load_replays(run_dir, keys, workers=0):
    """Per-replay structural aggregates, restricted to the shared keys."""
    paths = []
    for p in sorted(globmod.glob(os.path.join(run_dir, "*_vs_*.json"))):
        if _key_from_path(p) in keys:
            paths.append(p)
    if not paths:
        return None
    if workers == 0:
        workers = os.cpu_count() or 1
    recs = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_one, [(p, "ours") for p in paths]):
            if r:
                recs.append(r)
    return recs


def metrics_from_replays(recs):
    if not recs:
        return None
    days = defaultdict(list)
    crop = defaultdict(lambda: defaultdict(list))
    coop, land = defaultdict(int), defaultdict(int)
    ops = defaultdict(int)
    shed = []
    wheat = [0, 0, 0]
    yarn = 0
    late_coop = 0
    for r in recs:
        for d, t in r["days"].items():
            days[d].append(t)
        for d, cr in r["crop_day"].items():
            for c, n in cr.items():
                crop[d][c].append(n)
        for d, n in r["coop_day"].items():
            coop[d] += n
        for d, n in r["land_day"].items():
            land[d] += n
        ops.update(r["ops"])
        shed.append(r["shed_g"])
        wheat = [a + b for a, b in zip(wheat, r["wheat"])]
        if r["yarn_day"] is not None:
            yarn += 1
        if any(d >= 25 for d in r["coop_day"]):
            late_coop += 1
    n = len(recs)
    out = {"n": n}
    for d in (10, 16, 29):
        v = days.get(d, [])
        for i, sp in enumerate(("COW", "SHEEP", "GOOSE")):
            out[f"d{d} {sp}"] = _med([x[i] for x in v]) if v else 0
    out["COOP"] = sum(x[4] for v in days.values() for x in v) / max(1, sum(len(v) for v in days.values()))
    out["PASTURE"] = sum(x[3] for v in days.values() for x in v) / max(1, sum(len(v) for v in days.values()))
    for d in (6, 9, 12, 15, 18, 21, 24, 27):
        cr = crop.get(d)
        out[f"tiles d{d}"] = sum(_med(cr.get(c, [0])) for c in
                                 ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")) if cr else 0
    for d in (12, 18, 24):
        cr = crop.get(d)
        for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"):
            out[f"{c[:5]} d{d}"] = _med(cr.get(c, [0])) if cr else 0
    out["late coop (games)"] = late_coop
    out["coop build days"] = dict(sorted(coop.items()))
    out["land buy days"] = dict(sorted(land.items()))
    out["land buys after d12"] = sum(v for d, v in land.items() if d > 12)
    tot = sum(ops.values()) or 1
    for k in ("WATER", "HARVEST", "PASS", "PLANT", "FERTILIZE", "COLLECT_FERTILIZER", "CARE", "FEED"):
        out[f"op {k}%"] = 100.0 * ops.get(k, 0) / tot
    out["shed end/day"] = _med([x[0] for x in shed])
    out["shed peak"] = _med([x[1] for x in shed])
    out["system peak"] = _med([x[3] for x in shed])
    out["wheat bought"] = wheat[0] / n
    out["wheat fed"] = wheat[1] / n
    out["wheat sold"] = wheat[2] / n
    out["YARN games"] = yarn
    return out


def show(title, base, cand, direction=None, tol=None):
    b, c = base, cand
    d = c - b
    flag = ""
    if direction is not None and abs(d) > (tol or 0):
        good = (d > 0) if direction > 0 else (d < 0)
        flag = "  OK" if good else "  WARN"
    print(f"   {title:26s} {b:12,.1f} {c:12,.1f} {d:+12,.1f}{flag}")
    return flag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--agent", default="old")
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()

    gb = load_games(args.baseline, args.agent)
    gc = load_games(args.candidate, args.agent)
    keys = sorted(set(gb) & set(gc))
    if not keys:
        raise SystemExit("no shared (opponent, seed) keys between the two arms")
    print(f"=== PAIRED BALANCE SHEET ===")
    print(f"baseline  {args.baseline}  ({len(gb)} games)")
    print(f"candidate {args.candidate}  ({len(gc)} games)")
    print(f"shared    {len(keys)} games (every figure below is on these only)")

    rb = [gb[k] for k in keys]
    rc = [gc[k] for k in keys]
    mb = metrics_from_games(rb)
    mc = metrics_from_games(rc)

    warns = []
    print(f"\n-- MARGIN --   {'baseline':>12s} {'candidate':>12s} {'delta':>12s}")
    for name, fn, dr, tol in GAME_SCALARS:
        if show(name, fn(mb), fn(mc), dr, tol).strip() == "WARN":
            warns.append(name)

    print(f"\n-- GUARDS (per-game median) --")
    for col, dr, tol in GUARDS:
        v = show(col, _med(mb[col]), _med(mc[col]), dr, tol)
        if v.strip() == "WARN":
            warns.append(col)

    print(f"\n-- LEDGER (per-game median) --")
    for col in ("seed_cost_total", "animal_cost_total", "product_cost_total",
                "hire_cost_total", "input spend"):
        show(col, _med(mb[col]), _med(mc[col]))

    recb = load_replays(args.baseline, set(keys), args.workers)
    recc = load_replays(args.candidate, set(keys), args.workers)
    if recb and recc:
        xb = metrics_from_replays(recb)
        xc = metrics_from_replays(recc)
        print(f"\n-- STRUCTURE / HERD / CROPS (median) --")
        for k in ("COOP", "PASTURE", "late coop (games)", "land buys after d12",
                  "d10 COW", "d10 SHEEP", "d10 GOOSE", "d16 COW", "d16 SHEEP",
                  "d16 GOOSE", "d29 COW", "d29 SHEEP", "d29 GOOSE"):
            show(k, xb.get(k, 0), xc.get(k, 0))
        print(f"\n-- PLANTED TILES (sum of the 5 crops, median) --")
        for d in (6, 9, 12, 15, 18, 21, 24, 27):
            k = f"tiles d{d}"
            v = show(k, xb.get(k, 0), xc.get(k, 0), +1, 0.5)
            if v.strip() == "WARN":
                warns.append(k)
        print(f"\n-- PER CROP (median tiles) --")
        for d in (12, 18, 24):
            for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"):
                show(f"{c[:5]} d{d}", xb.get(f"{c[:5]} d{d}", 0), xc.get(f"{c[:5]} d{d}", 0))
        print(f"\n-- LABOUR (share of unit ops, %) + SHED + WHEAT --")
        for k in ("op WATER%", "op HARVEST%", "op PASS%", "op PLANT%",
                  "op FERTILIZE%", "op COLLECT_FERTILIZER%", "op CARE%", "op FEED%",
                  "shed end/day", "shed peak", "system peak",
                  "wheat bought", "wheat fed", "wheat sold", "YARN games"):
            show(k, xb.get(k, 0), xc.get(k, 0))
        print(f"\n   coop build days  base={xb.get('coop build days')}")
        print(f"                    cand={xc.get('coop build days')}")
        print(f"   land buy days    base={xb.get('land buy days')}")
        print(f"                    cand={xc.get('land buy days')}")

    print(f"\n=== VERDICT ===")
    if warns:
        print(f"   {len(warns)} WARN row(s): {', '.join(warns)}")
    else:
        print("   no regressions outside tolerance")


if __name__ == "__main__":
    main()
