"""tools/market/crop_demand.py — per-crop tile curve against the demand that buys it.

The open supply-side question: DSM ROTATES crops (melon -> strawberry -> carrot) while
we STACK them, so a crop keeps being planted after the shops that buy it have stopped
absorbing it. This prints, per crop and per day, side by side:

  * our tiles vs DSM's tiles for that crop
  * how many shops that BUY the crop are open that day (the demand line)
  * the implied daily absorption (shops x their consumption rate)
  * a SUPPLY/DEMAND ratio, so "we are 3x over demand" is a number, not a vibe

Consumption model (GAME_DYNAMICS): each shop consumes on its own timer every
`townShopSellInterval` turns (4), so a shop absorbs `turns_per_day / interval` = 6
units/day; single-product shops take 2 units per visit, multi-product shops 1. Shops
unlock every 3 days and are drawn WITH REPLACEMENT, capped at 8 instances -- and the
draw is a function of our own play (see tools/readme.md), so read the two arms'
demand columns as "each arm's own world", not as a controlled comparison.

Tiles come from the replay observation (the only place they exist); shops come from the
day CSV's `shop_unlocks`. LB replays have no day CSV worth reading for this, so DSM's
demand line is built from the same replay stream.

Usage:
  PYTHONPATH=src:. python -m tools.market.crop_demand --dir diag-replays/w7-b \
      --dsm-max 30 --out docs/supply/crop_demand.txt
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

# crop -> the shops that buy it (SHOPS table), and the single-product ones (2/turn).
CROP_SHOPS = {
    "WHEAT": ("BAKERY", "PIZZA_SHOP", "BRUNCH_SPOT", "ICE_CREAM_SHOP", "FARMERS_MARKET"),
    "CARROT": ("PET_CAFE", "FARMERS_MARKET"),
    "TOMATO": ("PIZZA_SHOP", "FARMERS_MARKET"),
    "STRAWBERRY": ("BRUNCH_SPOT", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP", "FARMERS_MARKET"),
    "MELON": ("FARMERS_MARKET",),
}
# Shops that sell exactly one product take 2 units per visit; the rest take 1.
SINGLE_PRODUCT = {"YARN_STORE", "PET_CAFE"}
INTERVAL = 4          # townShopSellInterval
TURNS_PER_DAY = 24


def _seat(rep, which):
    names = (rep.get("info") or {}).get("TeamNames") or []
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i if which == "dsm" else 1 - i
    return 0 if which == "dsm" else 1


def _one(arg):
    path, which = arg
    try:
        rep = json.load(open(path))
    except Exception:  # noqa: BLE001
        return None
    seat = _seat(rep, which)
    tiles = defaultdict(Counter)      # day -> crop -> tiles
    shops = defaultdict(set)          # day -> shops open
    seen_shops = set()
    for t, frame in enumerate(rep["steps"]):
        if len(frame) <= seat:
            continue
        obs = frame[seat].get("observation")
        if not obs:
            continue
        day = t // 24
        for s in ((obs.get("town") or {}).get("unlocked_shops") or []):
            if s not in seen_shops:
                seen_shops.add(s)
                for d in range(day, 30):
                    shops[d].add(s)
        if t % 24 != 0:
            continue
        for row in obs["farms"][seat]["tiles"]:
            for tile in row:
                if isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("crop"):
                    tiles[day][tile["crop"]] += 1
    return {"tiles": {d: dict(c) for d, c in tiles.items()},
            "shops": {d: set(s) for d, s in shops.items()}, "games": 1}


def _run(paths, which, workers, cap):
    tasks = [(p, which) for p in paths]
    workers = workers or min(max(1, len(tasks)), os.cpu_count() or 4)
    agg = {"tiles": defaultdict(lambda: defaultdict(list)), "shops": defaultdict(Counter),
           "games": 0}
    if not tasks:
        return agg
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        for r in ex.map(_one, tasks):
            if not r:
                continue
            agg["games"] += 1
            for d, cs in r["tiles"].items():
                for c in cap:
                    agg["tiles"][d][c].append(cs.get(c, 0))
            for d, ss in r["shops"].items():
                for c in cap:
                    agg["shops"][d][c] += sum(1 for s in ss if s in CROP_SHOPS[c])
    return agg


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def _demand(n_shops, crop):
    """Units/day the open shops absorb. Single-product shops take 2 per visit."""
    if n_shops <= 0:
        return 0.0
    singles = sum(1 for s in CROP_SHOPS[crop] if s in SINGLE_PRODUCT)
    # a crude split: assume the average shop takes a bit over 1 unit/visit
    per_visit = 1.0 + (singles / max(1, len(CROP_SHOPS[crop]))) * 1.0
    return n_shops * per_visit * (TURNS_PER_DAY / INTERVAL)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--dsm-dir", default=None)
    ap.add_argument("--dsm-max", type=int, default=30)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cap = tuple(CROP_SHOPS)

    ours = _run(sorted(glob.glob(os.path.join(args.dir, "*_vs_*.json"))), "ours",
                args.workers, cap)
    dsm_dir = args.dsm_dir
    if dsm_dir is None:
        for cand in ("replays/DSM/v1", "replays/DSM"):
            if glob.glob(f"{cand}/*.json"):
                dsm_dir = cand
                break
    dsm_paths = sorted(glob.glob(os.path.join(dsm_dir or "replays/DSM", "*.json")))[:args.dsm_max]
    dsm = _run(dsm_paths, "dsm", args.workers, cap)

    out = ["crop_demand — per-crop tile curve vs the shops that buy it",
           f"ours: {args.dir} ({ours['games']} games)",
           f"dsm : {dsm_dir} ({dsm['games']} games, capped {args.dsm_max})"]
    go, gd = max(1, ours["games"]), max(1, dsm["games"])
    for crop in cap:
        out.append(f"\n############ {crop}   (buyers: {', '.join(CROP_SHOPS[crop])}) ############")
        out.append(f"   {'day':>4}{'our tiles':>11}{'our shops':>11}{'our demand':>12}{'ratio':>8}"
                   f" | {'DSM tiles':>10}{'DSM shops':>11}")
        for d in range(4, 30, 2):
            ot = _med(ours["tiles"][d].get(crop, [0]))
            dt = _med(dsm["tiles"][d].get(crop, [0]))
            os_ = ours["shops"][d].get(crop, 0) / go
            ds_ = dsm["shops"][d].get(crop, 0) / gd
            dem = _demand(os_, crop)
            ratio = (ot / dem) if dem else (float("inf") if ot else 0.0)
            r = f"{ratio:7.1f}" if dem else "     --"
            out.append(f"   {d:>4}{ot:>11.0f}{os_:>11.1f}{dem:>12.1f}{r}"
                       f" | {dt:>10.0f}{ds_:>11.1f}")
    # peak-share summary
    out.append("\n############ PEAK and ROTATION SUMMARY ############")
    out.append(f"   {'crop':<12}{'our peak':>10}{'our peak day':>14}{'DSM peak':>10}{'DSM peak day':>14}")
    for crop in cap:
        op = max(((max(ours["tiles"][d].get(crop, [0]) or [0]), d) for d in range(30)), default=(0, 0))
        dp = max(((max(dsm["tiles"][d].get(crop, [0]) or [0]), d) for d in range(30)), default=(0, 0))
        out.append(f"   {crop:<12}{op[0]:>10.0f}{op[1]:>14}{dp[0]:>10.0f}{dp[1]:>14}")
    text = "\n".join(out)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        open(args.out, "w").write(text + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
