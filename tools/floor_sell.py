#!/usr/bin/env python
"""floor_sell — per-game floor-sale inspector (NO averaging).

Point it at a harness run dir (or a single replay) and it prints one block per
GAME showing, for the agent's seat:

  * the shop consumer counts (how many shops that actually BUY each product);
  * YARN_STORE count (the wool buyer);
  * herd size COW/SHEEP/GOOSE at d10/d16/d29 plus the peak;
  * coop / pasture counts at the end;
  * which products sold at the $1 floor, with units floored / units sold and the
    realised average price, plus below-base units.

Never averages across games -- each game is its own line so you can point at a
specific seed. Floor units come from the replay's market audit when present
(our runs); for leaderboard replays (no audit) they are recomputed from each
SELL order and the observation price at that step.

Usage:
  PYTHONPATH=src:. python -m tools.floor_sell --dir diag-replays/woolbase-543
  PYTHONPATH=src:. python -m tools.floor_sell --dir replays/DSM/v1 --glob '*.json' --seat 0
  PYTHONPATH=src:. python -m tools.floor_sell --path some_replay.json
  PYTHONPATH=src:. python -m tools.floor_sell --dir diag-replays/woolbase-543 --product WOOL
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import diagnose
from kaggle_environments.envs.kaggriculture.kaggriculture import SHOPS, MARKET_PARAMS, PRICE_FLOOR

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
            "EGG", "MILK", "WOOL", "FERTILIZER")
BASE = {p: MARKET_PARAMS[p]["base"] for p in MARKET_PARAMS}
FOCUS = ("WOOL", "MILK", "EGG", "STRAWBERRY", "MELON")
SHORT = {"STRAWBERRY": "STRAW", "FERTILIZER": "FERT", "BRUNCH_SPOT": "BRUNCH",
         "FARMERS_MARKET": "FM", "ICE_CREAM_SHOP": "ICE", "SMOOTHIE_SHOP": "SMTH",
         "PIZZA_SHOP": "PIZZA", "PET_CAFE": "PET", "YARN_STORE": "YARN"}

# product -> shops that demand it (engine table)
CONSUMERS = defaultdict(list)
for _shop, _items in SHOPS.items():
    for _it in _items:
        CONSUMERS[_it].append(_shop)


def _short(name):
    return SHORT.get(name, name[:5])


def _seat_of(rep, seat):
    if seat is not None:
        return seat
    names = (rep.get("info") or {}).get("TeamNames") or []
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i
    return 1


def analyse(path, seat=None):
    try:
        rep = diagnose.load_replay(Path(path))
    except Exception:  # noqa: BLE001
        return None
    seat = _seat_of(rep, seat)
    steps = rep["steps"]
    # ---- shops + consumers (final state) ----
    shops = []
    for t in range(len(steps) - 1, -1, -1):
        si = steps[t]
        if len(si) > seat and si[seat].get("observation"):
            shops = si[seat]["observation"]["town"]["unlocked_shops"]
            break
    shop_ct = Counter(shops)
    consumers = {p: sum(shop_ct[s] for s in CONSUMERS[p]) for p in PRODUCTS}
    # ---- herd + structures per day ----
    herd = {}
    coop = past = coop_peak = past_peak = 0
    for t in range(len(steps)):
        si = steps[t]
        if len(si) <= seat:
            continue
        obs = si[seat].get("observation")
        if not obs:
            continue
        d = t // 24
        if d in herd:
            continue
        c = Counter()
        held = Counter()
        for row in obs["farms"][seat]["tiles"]:
            for tile in row:
                if isinstance(tile, dict):
                    a = tile.get("animal")
                    if a:
                        held[a] += 1
                    k = tile.get("kind")
                    if k == "COOP":
                        c["COOP"] += 1
                    elif k == "PASTURE":
                        c["PASTURE"] += 1
        herd[d] = (held["COW"], held["SHEEP"], held["GOOSE"])
        coop, past = c["COOP"], c["PASTURE"]          # end-of-game values
        coop_peak = max(coop_peak, coop)
        past_peak = max(past_peak, past)
    # ---- selling: audit if present, else recompute from action + price ----
    qty, rev, floor, below = (defaultdict(int) for _ in range(4))
    audit = (rep.get("_diagnose_meta") or {}).get("audit")
    if audit:
        for bucket in audit.values():
            s = bucket.get(str(seat)) or bucket.get(seat) or {}
            for item, rec in (s.get("sells") or {}).items():
                qty[item] += rec.get("qty", 0)
                rev[item] += rec.get("revenue", 0.0)
                floor[item] += rec.get("floor", 0)
                below[item] += rec.get("below", 0)
    else:
        for t in range(len(steps)):
            si = steps[t]
            if len(si) <= seat:
                continue
            obs = si[seat].get("observation")
            act = si[seat].get("action") or {}
            if not obs:
                continue
            px = obs["market"]["prices"]
            for o in (act.get("market") or []):
                if o and o[0] == "SELL" and len(o) >= 3 and o[1] in PRODUCTS:
                    q = max(0, int(o[2]))
                    pr = float(px.get(o[1], 0) or 0)
                    qty[o[1]] += q
                    rev[o[1]] += q * pr
                    if pr <= PRICE_FLOOR:
                        floor[o[1]] += q
                    if pr < BASE.get(o[1], 0):
                        below[o[1]] += q
    peak = max((sum(v) for v in herd.values()), default=0)
    seed = (rep.get("info") or {}).get("seed")
    stem = Path(path).stem
    opp = ""
    if "_vs_" in stem:
        opp = stem.split("_vs_", 1)[1].rsplit("_seed", 1)[0].replace("kaggriculture-", "")
    tag = (str(seed) if seed else stem) + (f" vs {opp}" if opp else "")
    agent = ""
    for i, nm in enumerate((rep.get("info") or {}).get("TeamNames") or []):
        if i == seat:
            agent = nm or ""
    return {"tag": tag, "agent": agent, "seat": seat, "shops": shop_ct,
            "consumers": consumers, "herd": herd, "peak": peak,
            "coop": coop, "past": past, "coop_peak": coop_peak, "past_peak": past_peak,
            "qty": dict(qty), "rev": dict(rev), "floor": dict(floor), "below": dict(below)}


def _one(arg):
    return analyse(*arg)


def _herd_str(g, days=(10, 16, 29)):
    out = []
    for d in days:
        c, s, go = g["herd"].get(d, (0, 0, 0))
        out.append(f"{c}/{s}/{go}")
    return " ".join(f"d{d}:{v}" for d, v in zip(days, out))


def print_game(g, product=None):
    floored = [p for p in PRODUCTS if g["floor"].get(p, 0) > 0]
    floored.sort(key=lambda p: -g["floor"][p])
    print(f"--- {g['tag']}  seat={g['seat']} agent={g['agent']} ---")
    print("    shops: " + " ".join(f"{_short(s)}x{n}" for s, n in sorted(g["shops"].items(), key=lambda kv: -kv[1])))
    print("    consumers: " + "  ".join(f"{_short(p)}={g['consumers'][p]}" for p in FOCUS))
    print(f"    herd(COW/SHEEP/GOOSE): {_herd_str(g)}  peak={g['peak']}  coop/pasture={g['coop']}/{g['past']}")
    if product:
        p = product
        if g["qty"].get(p):
            avg = g["rev"][p] / g["qty"][p]
            print(f"    {p}: sold={g['qty'][p]} floor={g['floor'].get(p,0)} ({100*g['floor'].get(p,0)/g['qty'][p]:.0f}%) avg_px={avg:.1f} below_base={g['below'].get(p,0)}")
        else:
            print(f"    {p}: not sold")
        print()
        return
    if not floored:
        print("    floor: (none)")
    else:
        print("    floor: " + "  ".join(
            f"{_short(p)} {g['floor'][p]}/{g['qty'][p]}u@{g['rev'][p]/max(1,g['qty'][p]):.1f}" for p in floored))
    below = [(p, g["below"].get(p, 0)) for p in PRODUCTS if g["below"].get(p, 0)]
    below.sort(key=lambda kv: -kv[1])
    if below:
        print("    below_base: " + "  ".join(f"{_short(p)} {n}" for p, n in below[:8]))
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="run dir containing replay JSONs")
    ap.add_argument("--path", default=None, help="a single replay JSON")
    ap.add_argument("--glob", default=None, help="glob inside --dir (default *_vs_*.json, else *.json)")
    ap.add_argument("--seat", type=int, default=None, help="seat of the agent (default: LB auto, else 1)")
    ap.add_argument("--product", default=None, help="focus one product (e.g. WOOL)")
    ap.add_argument("--workers", type=int, default=0, help="0 = all cores")
    ap.add_argument("--summary", action="store_true", help="one compact line per game instead of a block")
    args = ap.parse_args()

    pattern = args.glob
    if args.path:
        paths = [args.path]
    else:
        d = args.dir or "."
        if pattern is None:
            pattern = "*_vs_*.json" if globmod.glob(os.path.join(d, "*_vs_*.json")) else "*.json"
        paths = sorted(globmod.glob(os.path.join(d, pattern)))
    if not paths:
        print("no replays found")
        return
    workers = args.workers or (os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        games = [g for g in ex.map(_one, [(p, args.seat) for p in paths]) if g]
    if args.product:
        args.product = args.product.upper()
    print(f"\n===== floor_sell: {args.path or args.dir}  ({len(games)} games, no averaging) =====")
    if args.summary:
        print(f"{'game':<34}{'YARN':>5}{'MILK':>5}{'EGG':>5}{'STRAW':>6} | "
              f"{'herd d10':>9}{'d16':>9}{'d29':>9} peak coop | floor products")
        for g in games:
            h = [g["herd"].get(d, (0, 0, 0)) for d in (10, 16, 29)]
            fl = " ".join(f"{_short(p)}:{g['floor'][p]}" for p in PRODUCTS if g["floor"].get(p, 0) > 0)
            print(f"{g['tag']:<34}{g['consumers']['WOOL']:>5}"
                  f"{g['consumers']['MILK']:>5}{g['consumers']['EGG']:>5}{g['consumers']['STRAWBERRY']:>6} | "
                  f"{h[0][0]}/{h[0][1]}/{h[0][2]:<3}{h[1][0]}/{h[1][1]}/{h[1][2]:<3}{h[2][0]}/{h[2][1]}/{h[2][2]:<3} "
                  f"{g['peak']:>4} {g['coop']:>4} | {fl}")
    else:
        for g in games:
            print_game(g, args.product)


if __name__ == "__main__":
    main()
