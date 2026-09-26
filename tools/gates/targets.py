#!/usr/bin/env python
"""targets.py — the deterministic per-workstream acceptance gate.

Success is STRUCTURAL: each workstream has a target metric that must move and a
watchlist of other critical components that must not regress. Revenue is reported
but is never the pass condition. Exit code is non-zero if any watchlist item
regressed against the baseline.

Usage:
  PYTHONPATH=. python -m tools.gates.targets --run-dir diag-replays/<arm> \
      --baseline diag-replays/run-1
"""
from __future__ import annotations

import argparse
import csv
import glob as globmod
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from tools.report.dsm_profile import SELL_PRODUCTS, _one

BASKET = ("STRAWBERRY", "MILK", "WOOL")
LB_START = ">I0+100"
# DSM reference values (dsm_v1.md §8.3, §8.2, §3, §7).
DSM = {
    "floor_pct_STRAWBERRY": 0.44, "floor_pct_MILK": 1.60, "floor_pct_WOOL": 2.70,
    "locked_med": 106, "idle_ready_med": 0, "shed_end_mean": 4.0,
    "quad4_pct": 100.0, "mix_max": 21.1,
}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def metrics(run_dir, workers=0):
    m = {}
    # ---- games.csv (per game)
    games = list(csv.DictReader(open(os.path.join(run_dir, "games.csv"))))
    n = len(games) or 1
    m["games"] = len(games)
    m["wins"] = sum(1 for g in games if g.get("result") == "WIN")
    m["floor_total"] = sum(_f(g.get("floor_sales")) for g in games)
    m["shed_ovf_mean"] = _mean([_f(g.get("shed_overflow_days")) for g in games])
    m["discarded_mean"] = _mean([_f(g.get("discarded_units_total")) for g in games])
    m["stranded_max"] = max((_f(g.get("stranded_at_bell")) for g in games), default=0)
    m["escapes_mean"] = _mean([_f(g.get("animal_escapes")) for g in games])
    m["idle_ready_med"] = _med([_f(g.get("idle_units_ready_total")) for g in games])
    m["locked_med"] = _med([_f(g.get("locked_steps")) for g in games])
    m["idle_share_mean"] = _mean([_f(g.get("idle_share_pct")) for g in games])
    m["feed_surplus_min"] = min((_f(g.get("feed_surplus")) for g in games), default=0)
    m["at_risk_max"] = max((_f(g.get("at_risk_of_escape")) for g in games), default=0)
    m["escapes"] = sum(_f(g.get("animal_escapes")) for g in games)
    money = sorted(_f(g.get("final_money")) for g in games)
    m["money_med"] = _med(money)
    m["money_p10"] = money[len(money) // 10] if money else 0.0

    # ---- days CSVs: revenue mix + day-level weed/water endgame
    mix = defaultdict(float)
    gmix = defaultdict(list)
    per_game = defaultdict(lambda: defaultdict(float))
    for f in sorted(globmod.glob(os.path.join(run_dir, "days_seed*.csv"))):
        for r in csv.DictReader(open(f)):
            key = (f, r.get("seed"))
            for prod in SELL_PRODUCTS:
                per_game[key][prod] += _f(r.get(f"revenue_{prod}"))
    for _k, byp in per_game.items():
        tot = sum(byp.values())
        if tot <= 0:
            continue
        for prod, v in byp.items():
            gmix[prod].append(100.0 * v / tot)
    for prod, v in gmix.items():
        mix[prod] = _med(v)
    m["mix"] = dict(mix)
    m["mix_max"] = max(mix.values()) if mix else 0.0
    m["mix_top"] = max(mix, key=mix.get) if mix else "-"

    # ---- replays: quadrants, curve buckets, shed, crops, discards, wheat
    paths = sorted(globmod.glob(os.path.join(run_dir, "*_vs_*.json")))
    workers = workers or min(len(paths), os.cpu_count() or 4)
    agg = {"quad4": 0, "shed_end": [], "shed_peak": [], "shed_top": [],
           "crop": defaultdict(lambda: defaultdict(list)), "disc": Counter(),
           "inv_start": defaultdict(Counter), "inv_end": defaultdict(Counter),
           "sell": {}, "wheat": [0, 0], "n": 0, "yarn_sheep": [],
           "peak_g": [], "end_g": []}
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        for r in ex.map(_one, [(p, "ours") for p in paths]):
            if not r:
                continue
            agg["n"] += 1
            if "SE" in r["quad_day"]:
                agg["quad4"] += 1
            if r.get("yarn_day") is not None:
                agg["yarn_sheep"].append(max((v[1] for v in r["days"].values()), default=0))
            for d, rec in r["shed_day"].items():
                agg["shed_end"].append(rec[0]); agg["shed_peak"].append(rec[1])
            if r["shed_day"]:
                agg["end_g"].append(_mean([v[0] for v in r["shed_day"].values()]))
                agg["peak_g"].append(max(v[1] for v in r["shed_day"].values()))
            for d, comp in r["shed_comp"].items():
                ct = sum(comp.values())
                if ct:
                    agg["shed_top"].append(max(comp.values()) / ct)
            for d, cr in r["crop_day"].items():
                for c, v in cr.items():
                    agg["crop"][d][c].append(v)
            agg["disc"] += r["disc"]
            for item, cnt in r["inv_hist"].items():
                agg["inv_start"][item] += cnt
            for item, cnt in r["inv_hist_end"].items():
                agg["inv_end"][item] += cnt
            for item, v in r["sell"].items():
                cell = agg["sell"].setdefault(item, [0, 0.0, 0])
                cell[0] += v[0]; cell[1] += v[1]; cell[2] += v[2]
            agg["wheat"] = [a + b for a, b in zip(agg["wheat"], [r["wheat"][0], r["wheat"][1]])]

    g = max(1, agg["n"])
    m["quad4_pct"] = 100.0 * agg["quad4"] / g
    m["shed_end_mean"] = _mean(agg["shed_end"])
    # per-game max mid-day peak (not p90 over day-level peaks: our shed is pinned
    # at 100 in nearly every game, so the day-level p90 understates it)
    m["shed_peak_p90"] = sorted(agg["peak_g"])[int(0.9 * len(agg["peak_g"]))] if agg["peak_g"] else 0
    m["shed_end_mean"] = _mean(agg["end_g"]) if agg["end_g"] else m.get("shed_end_mean", 0)
    m["shed_top_share"] = 100.0 * _mean(agg["shed_top"])
    for item in BASKET:
        q, _rev, fl = agg["sell"].get(item, (0, 0.0, 0))
        m[f"units_{item}"] = q / g
        m[f"floor_pct_{item}"] = 100.0 * fl / q if q else 0.0
        m[f"px_{item}"] = (_rev / q) if q else 0.0
        m[f"band50_{item}"] = (agg["inv_start"].get(item, {}) or {}).get("+50..+100", 0) / g
        m[f"end_over_{item}"] = (agg["inv_end"].get(item, {}) or {}).get(">I0+100", 0) / g
    m["basket_floor_pct"] = (
        sum(100.0 * agg["sell"].get(i, (0, 0, 0))[2] for i in BASKET)
        / max(1, sum(agg["sell"].get(i, (0, 0, 0))[0] for i in BASKET)))
    dt = sum(agg["disc"].values()) or 1
    m["disc_wheat"] = agg["disc"].get("WHEAT", 0) / g
    m["disc_straw"] = agg["disc"].get("STRAWBERRY", 0) / g
    m["disc_top_share"] = 100.0 * max(agg["disc"].values(), default=0) / dt
    b, fed = agg["wheat"]
    m["wheat_buy_per_fed"] = b / max(1, fed)
    for d in (13, 26, 28):
        for c in ("MELON", "STRAWBERRY", "CARROT"):
            m[f"crop_{c}_d{d}"] = _mean(agg["crop"][d].get(c, [0]))
    m["yarn_sheep_med"] = _med(agg["yarn_sheep"])
    for d in range(6, 30):
        means = {c: _mean(agg["crop"][d].get(c, [0]))
                 for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")}
        tot = sum(means.values())
        share = 100.0 * max(means.values()) / tot if tot else 0.0
        m["crop_maxshare_max"] = max(m.get("crop_maxshare_max", 0), share)
        if 10 <= d <= 28:
            m["crop_maxshare_mid"] = max(m.get("crop_maxshare_mid", 0), share)
    return m


# (workstream, kind, metric, op, value, label)
SPEC = [
    ("W0 land", "target", "quad4_pct", ">=", 90.0, "4 quadrants (% of games)"),
    ("W0 land", "watch", "locked_med", "no_increase", 0.0, "locked_steps (median)"),
    ("W0 land", "watch", "idle_share_mean", "no_increase", 0.05, "idle_share_pct (mean)"),
    ("W0 land", "watch", "at_risk_max", "<=", 0.0, "at_risk_of_escape (max)"),
    ("W0 land", "watch", "money_p10", "no_decrease", 0.10, "final_money p10"),
    ("W3 labour", "target", "idle_ready_med", "<=", 3.0, "idle_units_ready (median)"),
    ("W3 labour", "target", "locked_med", "<=", 130.0, "locked_steps (median)"),
    ("W3 labour", "watch", "shed_ovf_mean", "no_increase", 0.10, "shed_overflow_days (mean)"),
    ("W1 price discipline", "target", "basket_floor_pct", "<=", 3.0, "floor % STRAW+MILK+WOOL"),
    ("W1 price discipline", "target", "end_over_STRAWBERRY", "<=", 1.0, "STRAWBERRY orders ending >I0+100"),
    ("W1 price discipline", "target", "end_over_MILK", "<=", 1.0, "MILK orders ending >I0+100"),
    ("W1 price discipline", "target", "end_over_WOOL", "<=", 1.0, "WOOL orders ending >I0+100"),
    ("W1 price discipline", "watch", "shed_ovf_mean", "no_increase", 0.10, "shed_overflow_days (mean)"),
    ("W1 price discipline", "watch", "stranded_max", "<=", 1.0, "stranded_at_bell (max)"),
    ("W1 price discipline", "watch", "discarded_mean", "no_increase", 0.10, "discarded_units_total (mean)"),
    ("W1 price discipline", "watch", "mix_max", "<=", 22.0, "revenue mix max share (DSM rule)"),
    ("W2 rotation", "target", "crop_MELON_d13", "<=", 0.5, "MELON tiles at d13"),
    ("W2 rotation", "target", "crop_STRAWBERRY_d28", "<=", 10.0, "STRAWBERRY tiles at d28"),
    ("W2 rotation", "target", "crop_CARROT_d26", ">=", 15.0, "CARROT tiles at d26"),
    ("W2 rotation", "watch", "mix_max", "<=", 22.0, "revenue mix max share (DSM rule)"),
    ("W2 rotation", "target", "crop_maxshare_mid", "<=", 45.0, "max single-crop share d10-28"),
    ("W4 scale", "target", "yarn_sheep_med", ">=", 8.0, "SHEEP (max) in YARN worlds"),
    ("W4 scale", "watch", "at_risk_max", "<=", 0.0, "at_risk_of_escape (max)"),
    ("W4 scale", "watch", "escapes_mean", "<=", 3.0, "animal_escapes (mean)"),
    ("W4 scale", "watch", "mix_max", "<=", 22.0, "revenue mix max share (DSM rule)"),
    ("W5 discards", "target", "disc_wheat", "<=", 0.5, "WHEAT discarded / game"),
    ("W5 discards", "target", "disc_straw", "<=", 0.5, "STRAWBERRY discarded / game"),
    ("W5 discards", "watch", "discarded_mean", "no_increase", 0.10, "discarded_units_total (mean)"),
    ("W5 discards", "watch", "shed_ovf_mean", "no_increase", 0.10, "shed_overflow_days (mean)"),
    ("W7 shed", "target", "shed_end_mean", "<=", 5.0, "end-of-day shed (mean)"),
    ("W7 shed", "target", "shed_peak_p90", "<=", 95.0, "mid-day shed peak (p90)"),
    ("W7 shed", "target", "shed_top_share", "<=", 50.0, "largest product share at day end"),
    ("W7 shed", "watch", "discarded_mean", "no_increase", 0.10, "discarded_units_total (mean)"),
    ("W7 shed", "watch", "at_risk_max", "<=", 0.0, "at_risk_of_escape (max)"),
    ("W8 anti-wash", "target", "wheat_buy_per_fed", "<=", 1.10, "wheat bought / fed"),
    ("W8 anti-wash", "watch", "feed_surplus_min", ">=", -40.0, "feed_surplus (min, proxy)"),
]

INFO = ["games", "wins", "money_med", "money_p10", "floor_total", "mix_max", "mix_top",
        "units_STRAWBERRY", "px_STRAWBERRY", "units_MILK", "px_MILK", "units_WOOL", "px_WOOL"]


def _verdict(kind, op, want, base, cur):
    """Return (pass_bool, text). Ops: <=, >=, no_increase(tol), no_decrease(tol)."""
    if op == "<=":
        return cur <= want, f"{cur:10.2f}  target <= {want:g}"
    if op == ">=":
        return cur >= want, f"{cur:10.2f}  target >= {want:g}"
    if op == "no_increase":
        return cur <= base * (1 + want), f"{base:10.2f} -> {cur:.2f}  (<=+{100*want:.0f}%)"
    if op == "no_decrease":
        return cur >= base * (1 - want), f"{base:10.2f} -> {cur:.2f}  (>=-{100*want:.0f}%)"
    return True, f"{cur:.2f}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args(argv)

    cur = metrics(args.run_dir, args.workers)
    base = metrics(args.baseline, args.workers)

    print(f"=== targets: {args.run_dir}  (baseline {args.baseline}) ===")
    fails = 0
    seen = []
    for w, kind, key, op, want, label in SPEC:
        if w not in seen:
            seen.append(w)
            print(f"\n{w}")
        ok, text = _verdict(kind, op, want, base.get(key, 0.0), cur.get(key, 0.0))
        tag = "TARGET" if kind == "target" else "watch "
        if not ok:
            fails += 1
        print(f"  {tag} {label:<42} {text:>28}   {'PASS' if ok else 'FAIL'}")

    print("\n-- info (never a pass condition) --")
    for k in INFO:
        b, c = base.get(k), cur.get(k)
        if k == "mix_top":
            print(f"   {k:<24} {str(b):>12} -> {str(c)}")
        else:
            print(f"   {k:<24} {b:12.2f} -> {c:.2f}")
    print(f"\n{fails} target/watch FAIL(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
