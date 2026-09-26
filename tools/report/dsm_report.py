"""tools/dsm_report.py — turn the dsm_extract cache into markdown tables.

Reads the JSON cache produced by ``tools/dsm_extract.py`` and prints the data
tables used by ``docs/dsm_v1.md``. Judgement is per game; every cross-game figure
is an explicit median or a count, never a pooled average of a rate.

Usage::

    PYTHONPATH=. python tools/dsm_report.py --cache /tmp/dsm_cache.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK",
            "WOOL", "FERTILIZER")
ANIMALS = ("COW", "SHEEP", "GOOSE")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
MILK_SHOPS = ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP")


def med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def fmt(v, nd=0):
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return f"{v:,}"


def col(games, key, nd=0):
    return [g_ for g_ in (gg.get(key) for gg in games) if g_ is not None]


def day_rows(games):
    """{day: {field: [values]}} across games."""
    out = defaultdict(lambda: defaultdict(list))
    for g in games:
        for r in g["days"]:
            for k, v in r.items():
                if k in ("new_shops", "shed_end_items"):
                    continue
                out[r["day"]][k].append(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/dsm_cache.json")
    ap.add_argument("--section", default="all")
    args = ap.parse_args()

    blob = json.load(open(args.cache))
    games = blob["games"]
    n = len(games)
    print(f"# DSM data tables (n={n} games)\n")

    # ---------------- herd / structure / crops, by day
    dr = day_rows(games)
    print("## A. Farm timeline (median per game, by day)\n")
    print("| day | money | hands | quad | shed max | COW | SHEEP | GOOSE | structs | "
          "wheat | straw | carrot | tomato | melon | weeds | escapes | feed | care | water | fert |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for day in sorted(dr):
        d = dr[day]
        def m(k):
            return med(d.get(k, [0]))
        structs = m("struct_COW_end") + m("struct_SHEEP_end") + m("struct_GOOSE_end")
        print(f"| {day} | {fmt(m('money'))} | {fmt(m('hands'))} | {fmt(m('quadrants'))} | "
              f"{fmt(m('shed_max'))} | {fmt(m('animal_COW_end'))} | {fmt(m('animal_SHEEP_end'))} | "
              f"{fmt(m('animal_GOOSE_end'))} | {fmt(structs)} | {fmt(m('crop_WHEAT_end'))} | "
              f"{fmt(m('crop_STRAWBERRY_end'))} | {fmt(m('crop_CARROT_end'))} | "
              f"{fmt(m('crop_TOMATO_end'))} | {fmt(m('crop_MELON_end'))} | {fmt(m('weeds_end'))} | "
              f"{fmt(m('escapes'))} | {fmt(m('feed'))} | {fmt(m('care'))} | {fmt(m('water'))} | "
              f"{fmt(m('fertilize'))} |")

    # ---------------- per-product season totals
    print("\n## B. Per-product season totals (median per game)\n")
    print("| product | sold | harvested | bought | fed | revenue | inv min | inv mean | inv max | "
          "px sold avg | px min | px max | floor units | floor games |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in PRODUCTS:
        sold, harv, bought, invmin, invmean, invmax, pxs, pxn, pxmin, pxmax = ([] for _ in range(10))
        floor_u, floor_g = [], 0
        for g in games:
            days = g["days"]
            sold.append(sum(r.get(f"sold_{p}", 0) for r in days))
            harv.append(sum(r.get(f"flow_{p}", 0) for r in days))
            bought.append(sum(r.get(f"buyunits_{p}", 0) for r in days))
            invmin.append(min(r.get(f"inv_{p}_min", 0) for r in days))
            invmax.append(max(r.get(f"inv_{p}_max", 0) for r in days))
            invmean.append(med([r.get(f"inv_{p}_mean", 0) for r in days]))
            recs = g.get("sells", {}).get(p) or []
            u = sum(q for _, _, _, q in recs)
            if u:
                pxs.append(sum(pr * q for _, _, pr, q in recs) / u)
                pxmin.append(min(pr for _, _, pr, _ in recs))
                pxmax.append(max(pr for _, _, pr, _ in recs))
            f = sum(q for _, _, pr, q in recs if pr <= 1)
            floor_u.append(f)
            if f:
                floor_g += 1
        fed = med([sum(r.get("feed", 0) for r in g["days"]) for g in games]) if p == "WHEAT" else None
        rev = [sum(r.get(f"rev_{p}", 0) for r in g["days"]) for g in games]
        print(f"| {p} | {fmt(med(sold))} | {fmt(med(harv))} | "
              f"{fmt(med(bought)) if p in ('WHEAT','FERTILIZER') else '—'} | "
              f"{fmt(fed) if fed is not None else '—'} | ${fmt(med(rev))} | {fmt(med(invmin))} | {fmt(med(invmean))} | "
              f"{fmt(med(invmax))} | {fmt(med(pxs), 1) if pxs else '—'} | "
              f"{fmt(med(pxmin)) if pxmin else '—'} | {fmt(med(pxmax)) if pxmax else '—'} | "
              f"{fmt(med(floor_u))} | {floor_g}/{n} |")

    # ---------------- where on the price curve does he sell
    print("\n## C. Where on the curve he sells: market inventory at the moment of each SELL\n")
    print("| product | sell orders | unit-orders median inv | inv<9900 | 9900-10000 | "
          "10000-10050 | 10050-10100 | >10100 |")
    print("|---|---|---|---|---|---|---|---|")
    for p in PRODUCTS:
        buckets = Counter()
        invs = []
        q = 0
        for g in games:
            for _, iv, _, qty in (g.get("sells", {}).get(p) or []):
                q += 1
                invs.append(iv)
                if iv < 9900:
                    buckets["a"] += qty
                elif iv < 10000:
                    buckets["b"] += qty
                elif iv <= 10050:
                    buckets["c"] += qty
                elif iv <= 10100:
                    buckets["d"] += qty
                else:
                    buckets["e"] += qty
        if not q:
            continue
        print(f"| {p} | {q:,} | {fmt(med(invs))} | {buckets['a']:,} | {buckets['b']:,} | "
              f"{buckets['c']:,} | {buckets['d']:,} | {buckets['e']:,} |")

    # ---------------- shop unlocks
    print("\n## D. Shop unlocks\n")
    days = []
    for g in games:
        for d, sh in (g.get("shop_days") or {}).items():
            for s in sh:
                days.append((int(d), s))
    cnt = Counter(s for _, s in days)
    print("| shop | first-unlock day (median) | games with it |")
    print("|---|---|---|")
    for s, c in cnt.most_common():
        print(f"| {s} | {fmt(med([d for d, x in days if x == s]))} | {c}/{n} |")

    # ---------------- YARN / MILK splits
    for label, test in (("YARN", lambda g: g.get("yarn_day") is not None),
                        ("no-YARN", lambda g: g.get("yarn_day") is None)):
        sub = [g for g in games if test(g)]
        if not sub:
            continue
        print(f"\n### {label} (n={len(sub)})\n")
        print("| metric | median |")
        print("|---|---|")
        for sp in ANIMALS:
            print(f"| herd {sp} (max) | "
                  f"{fmt(med([max(r.get(f'animal_{sp}_max', 0) for r in g['days']) for g in sub]))} |")
        for p in ("WHEAT", "MILK", "WOOL", "STRAWBERRY", "EGG"):
            print(f"| {p} sold | "
                  f"{fmt(med([sum(r.get(f'sold_{p}', 0) for r in g['days']) for g in sub]))} |")
            px = []
            for g in sub:
                recs = g.get("sells", {}).get(p) or []
                u = sum(q for _, _, _, q in recs)
                if u:
                    px.append(sum(pr * q for _, _, pr, q in recs) / u)
            print(f"| {p} px@sell | {fmt(med(px), 1) if px else '—'} |")
        print(f"| max weeds | "
              f"{fmt(med([max(r.get('weeds_max', 0) for r in g['days']) for g in sub]))} |")
        print(f"| max shed | "
              f"{fmt(med([max(r.get('shed_max', 0) for r in g['days']) for g in sub]))} |")
        print(f"| end money | {fmt(med([g['money_end'] for g in sub]))} |")

    # ---------------- discards
    print("\n## E. Day-end discard estimate (units that did not fit at hour 23)\n")
    tot = Counter()
    for g in games:
        for k, v in (g.get("discard_by_item") or {}).items():
            tot[k] += v
    print("| item | units over all games |")
    print("|---|---|")
    for k, v in tot.most_common():
        print(f"| {k} | {v:,} |")
    print(f"\nGames with any discard: "
          f"{sum(1 for g in games if g.get('discard_by_item'))}/{n}")


if __name__ == "__main__":
    main()
