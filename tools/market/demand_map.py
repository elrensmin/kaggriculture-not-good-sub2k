"""tools/market/demand_map.py — the demand-side running metric.

The engine's demand rule is exact (`_town_consume`): every **4 steps**, each unlocked
shop instance subtracts `multiplier` from `market["inventory"][item]` for each of its
products, where `multiplier = 2` for a single-product shop (`YARN_STORE`, `PET_CAFE`) and
1 otherwise; town center drains 1 every 24. Shops unlock every 3 days, drawn with
REPLACEMENT, so instances stack. Drain/day = `instances x multiplier x 6`.

This tool turns that into a per-game ledger from the harness day CSVs, so the shop
permutation is a number instead of a vibe:

  * the shop mix and unlock-day distribution,
  * per product: the season drain, our sold units, a COVERAGE ratio, qty-weighted price
    and the below-base share,
  * per relevant day: drain vs sold,
  * the YARN / no-YARN split for the wool and egg lines -- the reactive hypothesis.

Read the shop mix FIRST: the draw is a function of our own play (`_spawn_weeds` shares
the RNG stream), so two arms are not controlled worlds.

Usage:
  PYTHONPATH=. python -m tools.market.demand_map --dir diag-replays/v1-us
  PYTHONPATH=. python -m tools.market.demand_map --dir diag-replays/v1-us \
      --ref-dir diag-replays/boey-lb --team Boey
"""
from __future__ import annotations

try:
    from tools import team as team_mod
except ImportError:  # bare-script execution: add the repo root to sys.path
    import pathlib as _pl
    import sys as _sys
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))
    from tools import team as team_mod

import argparse
import csv
import glob
import json
import os
import statistics as st
from collections import Counter, defaultdict

from tools.diagnose.config import SHOPS
from tools.diagnose.window import parse_days, in_window, describe

INTERVAL = 4
TURNS_PER_DAY = 24
PRODUCTS = tuple(sorted({p for ps in SHOPS.values() for p in ps}))
SELL_COLS = {p: f"sell_qty_{p}" for p in PRODUCTS}
PX_COLS = {p: f"avg_price_{p}" for p in PRODUCTS}
BELOW_COLS = {p: f"below_base_sales_{p}" for p in PRODUCTS}


def _single(shop: str) -> bool:
    return len(SHOPS[shop]) == 1


def drain_per_day(shop: str):
    """Units/day each product of `shop` loses, per instance."""
    return {p: (2 if _single(shop) else 1) * (TURNS_PER_DAY // INTERVAL) for p in SHOPS[shop]}


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _shops(cell):
    try:
        v = json.loads(cell or "[]")
    except (TypeError, ValueError):
        return []
    return [s for s in v if s]


def load_arm(run_dir, agent, window):
    """One episode per (opponent, seed) -> {day: row}, plus the first day each shop shows."""
    by_ep = defaultdict(dict)
    shop_first = {}
    for f in sorted(glob.glob(os.path.join(run_dir, "days_seed*.csv"))):
        with open(f) as fh:
            for r in csv.DictReader(fh):
                if agent and (r.get("agent") or "") != agent:
                    continue
                key = (r.get("opponent") or "", r.get("seed") or "")
                by_ep[key][int(_num(r.get("day"), -1))] = r
                for s in set(_shops(r.get("shop_unlocks"))):
                    d = int(_num(r.get("day"), 0))
                    prev = shop_first.setdefault(s, {})
                    prev[key] = min(prev.get(key, 99), d)
    eps = {k: v for k, v in by_ep.items() if v}
    return eps, shop_first


def arm_stats(eps, shop_first, window):
    """Aggregate one arm: per-episode season totals + per-day medians for the day table."""
    per_day = defaultdict(lambda: defaultdict(list))    # product -> day -> [sold]
    drain_day = defaultdict(lambda: defaultdict(list))  # product -> day -> [drain]
    tot = defaultdict(lambda: defaultdict(list))        # product -> metric -> [per-episode]
    for key, days in eps.items():
        ep_drain = defaultdict(float)
        ep_sold = defaultdict(float)
        ep_below = defaultdict(float)
        open_shops = set()          # shop_unlocks in the day CSV is the per-day DELTA
        for day, r in sorted(days.items()):
            if not in_window(day, window):
                continue
            open_shops.update(_shops(r.get("shop_unlocks")))
            for s in open_shops:
                for p, d in drain_per_day(s).items():
                    drain_day[p][day].append(d)
                    ep_drain[p] += d
            for p in PRODUCTS:
                sold = _num(r.get(SELL_COLS[p]))
                per_day[p][day].append(sold)
                ep_sold[p] += sold
                if sold > 0:
                    tot[p]["px_w"].append((_num(r.get(PX_COLS[p])), sold))
                ep_below[p] += _num(r.get(BELOW_COLS[p]))
        for p in PRODUCTS:
            tot[p]["drain"].append(ep_drain[p])
            tot[p]["sold"].append(ep_sold[p])
            tot[p]["below_frac"].append(ep_below[p] / ep_sold[p] if ep_sold[p] else 0.0)
    return per_day, drain_day, tot


def _wq(px_w):
    num = sum(p * q for p, q in px_w)
    den = sum(q for _, q in px_w)
    return num / den if den else 0.0


def show_arm(name, eps, shop_first, window):
    per_day, drain_day, tot = arm_stats(eps, shop_first, window)
    days_span = range(30)
    per_day_avail = [d for d in days_span if in_window(d, window)]
    print(f"\n############ {name}  (episodes={len(eps)}) ############")

    print("-- shop mix (read first: the draw is coupled to our own empty tiles) --")
    all_shops = sorted(SHOPS)
    for s in all_shops:
        hits = shop_first.get(s) or {}
        games = len(hits)
        if not games:
            continue
        ds = sorted(hits.values())
        med = st.median(ds)
        mult = 2 if _single(s) else 1
        print(f"   {s:<16} games {games:>5}   median unlock d{med:g}   {mult}x/{INTERVAL}t "
              f"= {mult * TURNS_PER_DAY // INTERVAL}/product/day")

    print("\n-- per product: season drain vs our sales (medians over episodes) --")
    print(f"   {'product':<12}{'drain':>8}{'sold':>8}{'cov%':>7}{'px':>8}{'below%':>8}  hypotheses")
    hype = {
        "WOOL": "YARN_STORE only; 2x/turn. React AFTER the reveal (sheep).",
        "CARROT": "PET_CAFE only (2x). FARMERS_MARKET adds demand.",
        "EGG": "BAKERY/BRUNCH; the no-YARN line. Keep geese without wool demand.",
        "MILK": "PIZZA/ICE_CREAM/SMOOTHIE; cow line.",
        "STRAWBERRY": "4 shops; knife-edge curve -- price tail matters.",
        "WHEAT": "5 shops; log curve, absorbs volume -- the trade line.",
        "TOMATO": "PIZZA/FARMERS.",
        "MELON": "FARMERS_MARKET only; no other buyer.",
        "FERTILIZER": "town center + resale; log-ish, absorbs volume.",
    }
    for p in PRODUCTS:
        drain = st.median(tot[p]["drain"]) if tot[p]["drain"] else 0
        sold = st.median(tot[p]["sold"]) if tot[p]["sold"] else 0
        cov = (sold / drain * 100) if drain else 0
        px = _wq(tot[p]["px_w"])
        below = 100.0 * (st.median(tot[p]["below_frac"]) if tot[p]["below_frac"] else 0.0)
        print(f"   {p:<12}{drain:>8.0f}{sold:>8.0f}{cov:>7.0f}{px:>8.1f}{below:>8.0f}  {hype.get(p,'')}")

    print("\n-- drain vs our sales by day (median units/day) --")
    keys = [p for p in ("WHEAT", "STRAWBERRY", "MELON", "CARROT", "WOOL", "MILK", "EGG") if p in PRODUCTS]
    print("   day | " + " ".join(f"{p[:6]:>7}" for p in keys))
    print("       | " + " ".join(f"{'drain':>7}" for _ in keys))
    for d in per_day_avail:
        if d % 6 and d not in (9, 27):
            continue
        row = []
        for p in keys:
            dl = drain_day[p].get(d) or [0]
            row.append(f"{st.median(dl):>7.0f}")
        print(f"   {d:>3} | " + " ".join(row))
    print("       | " + " ".join(f"{'sold':>7}" for _ in keys))
    for d in per_day_avail:
        if d % 6 and d not in (9, 27):
            continue
        row = []
        for p in keys:
            sd = st.median(per_day[p].get(d, [0])) if per_day[p].get(d) else 0
            row.append(f"{sd:>7.0f}")
        print(f"   {d:>3} | " + " ".join(row))

    # YARN split for the reactive hypothesis
    yarn_eps = [k for k, days in eps.items()
                if any("YARN_STORE" in _shops(r.get("shop_unlocks")) for r in days.values())]
    noyarn = [k for k in eps if k not in set(yarn_eps)]
    print(f"\n-- YARN split (reactive hypothesis): {len(yarn_eps)} YARN games / {len(noyarn)} no-YARN --")
    for p in ("WOOL", "EGG", "MILK"):
        if p not in PRODUCTS:
            continue
        def med_arm(keys):
            vals = []
            for k in keys:
                v = sum(_num(r.get(SELL_COLS[p])) for d, r in eps[k].items() if in_window(d, window))
                vals.append(v)
            return st.median(vals) if vals else 0.0
        ys, ns = med_arm(yarn_eps), med_arm(noyarn)
        print(f"   {p:<6} YARN sold {ys:>7.0f}   no-YARN sold {ns:>7.0f}   delta {ys-ns:+.0f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="our run dir (day CSVs)")
    ap.add_argument("--agent", default="scratch", help="games.csv agent label for our arm")
    ap.add_argument("--ref-dir", default=None, help="reference arm run dir (day CSVs)")
    ap.add_argument("--ref-agent", default=None)
    ap.add_argument("--team", default=None, help="reference team for seat/agent resolution")
    ap.add_argument("--days", default=None)
    args = ap.parse_args()
    team_mod.set_team(args.team)
    window = parse_days(args.days)
    if window:
        print("window:", describe(window))

    ref_agent = args.ref_agent or team_mod.get()
    ours, of = load_arm(args.dir, args.agent, window)
    show_arm(f"ours [{args.dir}] agent={args.agent}", ours, of, window)
    if args.ref_dir:
        ref, rf = load_arm(args.ref_dir, ref_agent, window)
        show_arm(f"{ref_agent} [{args.ref_dir}]", ref, rf, window)


if __name__ == "__main__":
    main()
