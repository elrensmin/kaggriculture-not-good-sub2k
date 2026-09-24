#!/usr/bin/env python
"""herd_hold — DSM-vs-us cattle hold, feed amortisation and floor sales, per day.

Answers, in one readout:

  * how many COW / SHEEP / GOOSE each side holds on each day;
  * what that herd costs to hold (`wheat_fed` x wheat) vs what it earns
    (EGG+MILK+WOOL revenue), i.e. the carry;
  * when the herd is released toward the end (the count drop) and how many
    animals are let go (`animals_escaped_by_*`);
  * where WOOL / MILK / STRAWBERRY / EGG actually land: units sold, average
    price, and how many units are dumped at the $1 floor.

Sources:
  * per-day herd counts come from the replay JSONs (tile scan), so they exist for
    leaderboard replays too;
  * feed, escapes, sell quantity, floor and below-base units come from the per-day
    CSVs written by `diagnose` (the `--lb` CSVs for DSM).

NOTE: leaderboard replays carry no market audit, so their day-CSV `revenue_*` /
`avg_price_*` are 0 — DSM's price columns are intentionally shown as 0.0. Quantities
and floor/below-base counts are populated for both and are the comparison that
matters; `sell_qty_*` is the *executed* amount, not the tape's requested order size
(the terminal route asks for 1000s that the engine clamps).

Usage:
  PYTHONPATH=src:. python -m tools.herd_hold --compare
  PYTHONPATH=src:. python -m tools.herd_hold --profile dsm
  PYTHONPATH=src:. python -m tools.herd_hold --profile ours --run-dir diag-replays/release-543
  PYTHONPATH=src:. python -m tools.herd_hold --compare --max-games 40
"""
from __future__ import annotations

import argparse
import csv
import glob as globmod
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import diagnose

ANIMALS = ("COW", "SHEEP", "GOOSE")
PRODUCTS = ("WOOL", "MILK", "STRAWBERRY", "EGG")
WHEAT_COST = 25          # market base price of wheat (feed input)
DAYS = 30

_DAY_SIMPLE = ("animals_fed", "animals_cared", "animals_escaped", "feed_surplus",
               "wheat_fed", "wheat_bought", "wheat_sold")
_DAY_SUM = tuple(f"{m}_{p}" for p in PRODUCTS
                 for m in ("sell_qty", "floor_sales", "below_base_sales", "revenue"))
_DAY_ESC = tuple(f"animals_escaped_by_{a}" for a in ANIMALS)


# ---------------------------------------------------------------------------
# per-day herd counts from replays (parallel over games)
# ---------------------------------------------------------------------------
def _dsm_seat(rep):
    names = (rep.get("info") or {}).get("TeamNames") or ["", ""]
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i
    return 1


def _herd_one(arg):
    path, which = arg
    try:
        rep = diagnose.load_replay(Path(path))
    except Exception:  # noqa: BLE001
        return None
    seat = _dsm_seat(rep) if which == "dsm" else 1
    steps = rep["steps"]
    out = {}
    px = {}
    for i in range(len(steps)):
        si = steps[i]
        if len(si) <= seat:
            continue
        obs = si[seat].get("observation")
        if not obs:
            continue
        d = i // 24
        prices = (obs.get("market") or {}).get("prices") or {}
        for p in PRODUCTS:
            v = prices.get(p)
            if v:
                cell = px.setdefault(d, {}).setdefault(p, [0.0, 0])
                cell[0] += float(v)
                cell[1] += 1
        if d in out:
            continue
        c = s = g = 0
        for row in obs["farms"][seat]["tiles"]:
            for t in row:
                if isinstance(t, dict) and "animal" in t:
                    a = t["animal"]
                    if a == "COW":
                        c += 1
                    elif a == "SHEEP":
                        s += 1
                    elif a == "GOOSE":
                        g += 1
        out[d] = (c, s, g)
    return {"herd": out, "px": px}


def herd_curve(replay_glob, which, max_games, workers):
    paths = sorted(globmod.glob(replay_glob))
    if max_games:
        paths = paths[:max_games]
    acc = defaultdict(lambda: [[], [], []])
    px = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    if not paths:
        return 0, acc, px
    if workers == 0:
        workers = os.cpu_count() or 1
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_herd_one, [(p, which) for p in paths]):
            if not r:
                continue
            for d, (c, s, g) in r["herd"].items():
                acc[d][0].append(c)
                acc[d][1].append(s)
                acc[d][2].append(g)
            for d, items in r["px"].items():
                for p, cell in items.items():
                    t = px[d][p]
                    t[0] += cell[0]
                    t[1] += cell[1]
    return len(paths), acc, px


def curve_mean(acc):
    return {d: tuple((sum(v) / len(v) if v else 0.0) for v in cols) for d, cols in acc.items()}


# ---------------------------------------------------------------------------
# per-day feed / escapes / selling from the day CSVs
# ---------------------------------------------------------------------------
def day_stats(days_glob, agent_match):
    sums = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(lambda: defaultdict(int))
    for f in sorted(globmod.glob(days_glob)):
        for r in csv.DictReader(open(f)):
            if agent_match and agent_match.lower() not in str(r.get("agent", "")).lower():
                continue
            try:
                d = int(r["day"])
            except (KeyError, ValueError):
                continue
            for c in _DAY_SIMPLE + _DAY_SUM + _DAY_ESC:
                if c not in r:
                    continue
                try:
                    v = float(r[c] or 0)
                except ValueError:
                    continue
                sums[d][c] += v
                counts[d][c] += 1
    return {d: {c: (sums[d][c] / counts[d][c] if counts[d][c] else 0.0) for c in sums[d]}
            for d in sums}


def _release_day(curve):
    peak = 0
    for d in range(DAYS):
        if d not in curve:
            continue
        tot = sum(curve[d])
        if tot < peak:
            return d, peak - tot
        peak = max(peak, tot)
    return None, 0.0


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------
def print_herd_table(la, ca, fa, ea, lb, cb, fb, eb):
    print(f"\n== herd hold (mean animals / game, mean FEED ops / day) ==  {la} vs {lb} ==")
    print(f"{'day':>3} | {la:>6} COW SHEEP GOOSE tot feed esc | {lb:>6} COW SHEEP GOOSE tot feed esc")
    for d in range(DAYS):
        if d not in ca and d not in cb:
            continue
        a = ca.get(d, (0.0, 0.0, 0.0))
        b = cb.get(d, (0.0, 0.0, 0.0))
        print(f"{d:>3} | {'':>6} {a[0]:>3.1f} {a[1]:>5.1f} {a[2]:>5.1f} {sum(a):>4.1f} "
              f"{fa.get(d,0):>4.1f} {ea.get(d,0):>3.1f} | {'':>6} {b[0]:>3.1f} {b[1]:>5.1f} {b[2]:>5.1f} "
              f"{sum(b):>4.1f} {fb.get(d,0):>4.1f} {eb.get(d,0):>3.1f}")


def print_sell_table(la, da, lb, db):
    print(f"\n== animal-product selling per game (units @ avg price, floor units, below base) ==  {la} vs {lb} ==")
    def tot(day, p, m):
        return sum(day.get(d, {}).get(f"{m}_{p}", 0.0) for d in range(DAYS))
    for p in PRODUCTS:
        qa, qb = tot(da, p, "sell_qty"), tot(db, p, "sell_qty")
        if not (qa or qb):
            continue
        ra, rb = tot(da, p, "revenue"), tot(db, p, "revenue")
        print(f"  {p:<11} {la:>6} {qa:>7.0f}u @{(ra/qa if qa else 0):>6.1f}  floor={tot(da,p,'floor_sales'):>5.0f} "
              f"below={tot(da,p,'below_base_sales'):>5.0f}  rev={ra:>9.0f} | {lb:>6} {qb:>7.0f}u @{(rb/qb if qb else 0):>6.1f} "
              f" floor={tot(db,p,'floor_sales'):>5.0f} below={tot(db,p,'below_base_sales'):>5.0f}  rev={rb:>9.0f}")
    fa = sum(tot(da, p, "floor_sales") for p in PRODUCTS)
    fb = sum(tot(db, p, "floor_sales") for p in PRODUCTS)
    print(f"  {'FLOOR TOT':<11} {la:>6} {fa:>7.0f}{'':>40}| {lb:>6} {fb:>7.0f}")


def print_carry(label, curve, day):
    fed = sum(day.get(d, {}).get("wheat_fed", 0.0) for d in range(DAYS))
    rev = sum(sum(day.get(d, {}).get(f"revenue_{p}", 0.0) for p in ("WOOL", "MILK", "EGG"))
              for d in range(DAYS))
    esc = sum(sum(day.get(d, {}).get(c, 0.0) for c in _DAY_ESC) for d in range(DAYS))
    fl = sum(sum(day.get(d, {}).get(f"floor_sales_{p}", 0.0) for p in PRODUCTS) for d in range(DAYS))
    rd, drop = _release_day(curve)
    end = curve.get(29, (0, 0, 0))
    peak = max((sum(curve[d]) for d in curve), default=0)
    print(f"  {label:<6} peak_herd={peak:>5.1f} end_herd={sum(end):>5.1f} (C{end[0]:.0f}/S{end[1]:.0f}/G{end[2]:.0f})  "
          f"release_day={str(rd):>4} peak_drop={drop:>4.1f}  wheat_fed={fed:>6.0f} (${fed*WHEAT_COST:>7.0f})  "
          f"animal_rev=${rev:>8.0f}  carry=${rev-fed*WHEAT_COST:>8.0f}  released={esc:>5.1f}  floor_units={fl:>5.0f}")


def _bundle(which, args):
    if which == "dsm":
        label, rglob, dglob, match = "DSM", f"{args.dsm_dir}/*.json", f"{args.dsm_dir}/days_seed*.csv", "DSM"
    else:
        label, rglob, dglob, match = "ours", f"{args.run_dir}/*_vs_*.json", f"{args.run_dir}/days_seed*.csv", "old"
    n, acc, px = herd_curve(rglob, which, args.max_games, args.workers)
    day = day_stats(dglob, match)
    # Leaderboard replays carry no market audit: estimate each day's revenue from
    # the CSV's *executed* sell quantity and the replay's mean price that day.
    for d in range(DAYS):
        day.setdefault(d, {})
        for p in PRODUCTS:
            q = day[d].get(f"sell_qty_{p}", 0.0)
            if q and not day[d].get(f"revenue_{p}"):
                cell = px.get(d, {}).get(p)
                if cell and cell[1]:
                    day[d][f"revenue_{p}"] = q * (cell[0] / cell[1])
                    day[d]["_est"] = 1
    fed = {d: day.get(d, {}).get("animals_fed", 0.0) for d in range(DAYS)}
    esc = {d: sum(day.get(d, {}).get(c, 0.0) for c in _DAY_ESC) for d in range(DAYS)}
    return {"label": label, "n": n, "curve": curve_mean(acc), "day": day, "fed": fed, "esc": esc}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=("ours", "dsm"), default="dsm")
    ap.add_argument("--run-dir", default="diag-replays/release-543")
    ap.add_argument("--dsm-dir", default="replays/DSM/v1")
    ap.add_argument("--max-games", type=int, default=40, help="replays sampled per profile (0=all)")
    ap.add_argument("--workers", type=int, default=0, help="0 = all cores")
    ap.add_argument("--compare", action="store_true", help="print DSM and ours side by side")
    args = ap.parse_args()

    want = ("dsm", "ours") if args.compare else (args.profile,)
    data = {w: _bundle(w, args) for w in want}

    if args.compare:
        a, b = data["dsm"], data["ours"]
        print(f"\n############ herd_hold: {a['label']} (n={a['n']}) vs {b['label']} (n={b['n']}) ############")
        print_herd_table(a["label"], a["curve"], a["fed"], a["esc"],
                         b["label"], b["curve"], b["fed"], b["esc"])
        print_sell_table(a["label"], a["day"], b["label"], b["day"])
        print("\n== carry (season totals per game) ==")
        print_carry(a["label"], a["curve"], a["day"])
        print_carry(b["label"], b["curve"], b["day"])
    else:
        w = data[want[0]]
        print(f"\n############ herd_hold: {w['label']} (n={w['n']}) ############")
        print_herd_table(w["label"], w["curve"], w["fed"], w["esc"], "-", {}, {}, {})
        print_sell_table(w["label"], w["day"], "-", {})
        print("\n== carry (season totals per game) ==")
        print_carry(w["label"], w["curve"], w["day"])


if __name__ == "__main__":
    main()
