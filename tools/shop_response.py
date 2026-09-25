"""tools/shop_response.py — shop-conditioned supply/demand response, per pair.

Answers "when this shop is in the world, what does our farm DO about it?" for
every animal->product->shop and crop->shop pair, across games, seeds and
unlock-day conditions.

It exists because two things are easy to get wrong by hand:

1. **The shop draw is a function of our own play.** `_spawn_weeds` draws
   `rng.random()` once per empty tile of BOTH farms and the day's shop unlock is
   drawn from that same RNG, so leaving different ground empty moves which shops
   appear. Measured: the shop draw differed in 18/18 games between two arms on
   identical seeds. Section 1 prints the shop mix so a shop-conditioned metric is
   never read across arms without it.
2. **A flat "with vs without" hides when the shop arrived.** Our tape buys its
   animals in a fixed day-8..10 window, so a shop that unlocks at d12 arrives
   *after* the buys and the herd never responds. Section 2 breaks every pair down
   by unlock-day bucket, which is what isolates that case.

Everything is read from `days_seed*.csv` (per day, audit-backed), so this is fast
and needs no replay parsing.

Usage:
  PYTHONPATH=src:. python -m tools.shop_response --dir diag-replays/w1-final
  PYTHONPATH=src:. python -m tools.shop_response --dir A --vs B
  PYTHONPATH=src:. python -m tools.shop_response --dir A --games "SHEEP"
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
from collections import defaultdict

ANIMAL_PAIRS = (
    # label,             animal,  product, buyer shops
    ("WOOL <- SHEEP", "SHEEP", "WOOL", ("YARN_STORE",)),
    ("MILK <- COW", "COW", "MILK", ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP")),
    ("EGG  <- GOOSE", "GOOSE", "EGG", ("BAKERY", "BRUNCH_SPOT")),
)
CROP_PAIRS = (
    ("MELON", ("FARMERS_MARKET",)),
    ("TOMATO", ("PIZZA_SHOP", "FARMERS_MARKET")),
    ("CARROT", ("PET_CAFE", "FARMERS_MARKET")),
    ("STRAWBERRY", ("BRUNCH_SPOT", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP", "FARMERS_MARKET")),
    ("WHEAT", ("BAKERY", "PIZZA_SHOP", "BRUNCH_SPOT", "ICE_CREAM_SHOP", "FARMERS_MARKET")),
)
ALL_SHOPS = ("YARN_STORE", "PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP",
             "BAKERY", "BRUNCH_SPOT", "PET_CAFE", "FARMERS_MARKET")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load(run_dir):
    """{game_key: record} plus the seed list, from days CSVs only."""
    games = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "days_seed*.csv"))):
        for r in csv.DictReader(open(path)):
            key = (r.get("seed"), r.get("opponent"))
            g = games.get(key)
            if g is None:
                g = games[key] = {
                    "seed": r.get("seed"), "opponent": r.get("opponent"),
                    "shops": set(), "shop_day": {},
                    "animal": defaultdict(lambda: defaultdict(float)),
                    "product": defaultdict(lambda: defaultdict(float)),
                    "days": 0,
                }
            g["days"] += 1
            day = int(_f(r.get("day")))
            try:
                unlocked = json.loads(r.get("shop_unlocks") or "[]")
            except ValueError:
                unlocked = []
            for s in unlocked:
                g["shops"].add(s)
                g["shop_day"].setdefault(s, day)
            for a in ("COW", "SHEEP", "GOOSE"):
                buy = _f(r.get(f"buy_qty_{a}"))
                placed = _f(r.get(f"animals_placed_{a}"))
                g["animal"][a]["buy"] += buy
                g["animal"][a]["placed"] += placed
                g["animal"][a]["escaped"] += _f(r.get(f"animals_escaped_by_{a}"))
                # herd proxy: cumulative placed minus escaped, maxed over the season
                g["animal"][a]["herd_max"] = max(
                    g["animal"][a]["herd_max"], g["animal"][a]["placed"] - g["animal"][a]["escaped"])
                if buy > 0:
                    g["animal"][a]["first_buy"] = g["animal"][a].get("first_buy", float(day))
                    g["animal"][a]["last_buy"] = float(day)
            for p in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                      "EGG", "MILK", "WOOL", "FERTILIZER"):
                d = g["product"][p]
                d["units"] += _f(r.get(f"sell_qty_{p}"))
                d["rev"] += _f(r.get(f"revenue_{p}"))
                d["floor"] += _f(r.get(f"floor_sales_{p}"))
    return games


def med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def _bucket(day, cuts):
    if day is None:
        return "unlock ?"
    for lo, hi in zip([0] + list(cuts), list(cuts) + [999]):
        if lo <= day < hi:
            return f"unlock d{lo}-{hi - 1}" if hi != 999 else f"unlock d{lo}+"
    return "unlock ?"


def _line(label, group, animal, product, cuts):
    if not group:
        return
    a = [g["animal"][animal] for g in group]
    p = [g["product"][product] for g in group]
    units = [d["units"] for d in p]
    rev = [d["rev"] for d in p]
    floor = [d["floor"] for d in p]
    tot_u = sum(units) or 1
    px = [d["rev"] / d["units"] for d in p if d["units"] > 0]
    print(f"   {label:<18}{len(group):>4}"
          f"{med([v['buy'] for v in a]):>10.0f}{med([v['placed'] for v in a]):>8.0f}"
          f"{med([v['herd_max'] for v in a]):>7.0f}{med([v.get('last_buy', 0) for v in a]):>10.0f}"
          f" | {med(units):>8.0f}{med(px):>7.0f}{100 * sum(floor) / tot_u:>7.1f}%"
          f"{sum(1 for v in p if v['units'] <= 0):>8}")


def report(run_dir, name, cuts, workers_unused=0):
    games = load(run_dir)
    n = len(games) or 1
    print(f"\n############ {name}  ({n} games) ############")

    print("-- 1. SHOP MIX (read this before any shop-conditioned number) --")
    print(f"   {'shop':<18}{'games':>7}   unlock-day distribution")
    for s in ALL_SHOPS:
        have = [g for g in games.values() if s in g["shops"]]
        if not have:
            print(f"   {s:<18}{0:>7}   -")
            continue
        dist = defaultdict(int)
        for g in have:
            dist[g["shop_day"][s]] += 1
        ds = "  ".join(f"d{d}:{c}" for d, c in sorted(dist.items()))
        print(f"   {s:<18}{len(have):>7}   {ds}")

    print("\n-- 2. ANIMAL PAIRS: herd response to the buyer shop --")
    print(f"   {'condition':<18}{'n':>4}{'buy':>10}{'placed':>8}{'herd':>7}{'lastbuy':>10}"
          f" | {'sold':>8}{'px':>7}{'floor%':>8}{'nosale':>8}")
    for label, animal, product, shops in ANIMAL_PAIRS:
        buyers = [g for g in games.values() if any(s in g["shops"] for s in shops)]
        others = [g for g in games.values() if not any(s in g["shops"] for s in shops)]
        print(f"  {label}   (buyer: {', '.join(shops)})")
        _line("shop present", buyers, animal, product, cuts)
        by = defaultdict(list)
        for g in buyers:
            day = min(g["shop_day"][s] for s in shops if s in g["shops"])
            by[_bucket(day, cuts)].append(g)
        for b in sorted(by):
            _line("  " + b, by[b], animal, product, cuts)
        _line("shop ABSENT", others, animal, product, cuts)

    print("\n-- 3. CROP/PRODUCT PAIRS: supply response to the buyer shop --")
    for product, shops in CROP_PAIRS:
        buyers = [g for g in games.values() if any(s in g["shops"] for s in shops)]
        others = [g for g in games.values() if not any(s in g["shops"] for s in shops)]
        print(f"  {product}   (buyer: {', '.join(shops)})")
        for lbl, grp in (("shop present", buyers), ("shop ABSENT", others)):
            if not grp:
                continue
            p = [g["product"][product] for g in grp]
            u = sum(d["units"] for d in p) or 1
            px = [d["rev"] / d["units"] for d in p if d["units"] > 0]
            print(f"   {lbl:<18}{len(grp):>4}{'':>10}{'':>8}{'':>7}{'':>10}"
                  f" | {med([d['units'] for d in p]):>8.0f}{med(px):>7.0f}"
                  f"{100 * sum(d['floor'] for d in p) / u:>7.1f}%"
                  f"{sum(1 for d in p if d['units'] <= 0):>8}")
    return games


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--vs", default=None, help="second run dir to compare against")
    ap.add_argument("--buckets", default="6,9",
                    help="unlock-day cut points (default '6,9' -> d0-5 / d6-8 / d9+)")
    ap.add_argument("--games", default=None,
                    help="per-game dump for this animal/product (e.g. SHEEP)")
    args = ap.parse_args()
    cuts = tuple(int(x) for x in args.buckets.split(",") if x.strip())

    a = report(args.dir, os.path.basename(args.dir.rstrip("/")), cuts)
    if args.vs:
        b = report(args.vs, os.path.basename(args.vs.rstrip("/")), cuts)
        print("\n-- 4. SHOP-MIX DIVERGENCE between the two arms --")
        sa = {s: sum(1 for g in a.values() if s in g["shops"]) for s in ALL_SHOPS}
        sb = {s: sum(1 for g in b.values() if s in g["shops"]) for s in ALL_SHOPS}
        diverge = 0
        for s in ALL_SHOPS:
            if sa[s] != sb[s]:
                diverge += 1
                print(f"   {s:<18} {sa[s]:>3} -> {sb[s]:<3}  (worlds differ)")
        if not diverge:
            print("   none — shop draws match")
        print("   NOTE: any shop-conditioned number above is NOT controlled across "
              "arms unless this section is empty.")

    if args.games:
        want = args.games.upper()
        print(f"\n-- 5. PER-GAME DUMP for {want} --")
        print(f"   {'seed':>10} {'opponent':<22}{'shops':>6}{'unlock d':>9}"
              f"{'buy':>6}{'placed':>8}{'herd':>6}{'lastbuy':>8}{'sold':>7}{'floor%':>8}")
        rows = sorted(a.items())
        for key, g in rows:
            shops = [s for s in ALL_SHOPS if s in g["shops"]]
            prod = g["product"].get(want)
            animal = g["animal"].get(want)
            label = want
            if prod is None and animal is None:
                continue
            ud = min(g["shop_day"].values()) if g["shop_day"] else -1
            if animal is not None:
                det = (f"{med([animal['buy']]):>6.0f}{med([animal['placed']]):>8.0f}"
                       f"{med([animal['herd_max']]):>6.0f}{animal.get('last_buy', 0):>8.0f}")
            else:
                det = f"{'':>6}{'':>8}{'':>6}{'':>8}"
            if prod is not None:
                fl = 100 * prod["floor"] / prod["units"] if prod["units"] else 0
                det += f"{prod['units']:>7.0f}{fl:>7.1f}%"
            else:
                det += f"{'':>7}{'':>8}"
            print(f"   {str(key[0]):>10} {str(key[1])[-21:]:<22}{len(shops):>6}{ud:>9}{det}")


if __name__ == "__main__":
    main()
