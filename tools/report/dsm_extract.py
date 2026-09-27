"""tools/dsm_extract.py — full behavioural extraction from replay JSONs.

Parses each replay once and writes a compact JSON cache so the DSM write-up (and
any later analysis) can be done without re-reading 4.2 GB of raw replays.

Leaderboard replays carry no market audit, so money/price columns in
``days_seed*.csv`` are zero. Everything below is reconstructed from the replay's
own per-step ``action`` + ``observation`` stream:

  * unit ops       PLANT / WATER / FERTILIZE / HARVEST / FEED / CARE /
                   COLLECT_FERTILIZER / DIG / DROP / PICKUP / PLACE / BUILD_*
  * market orders  SELL / BUY_PRODUCT / BUY_SEED / BUY_ANIMAL / HIRE / BUY_LAND,
                   each with the engine's quoted price at that step
  * state          shed, per-worker inventories, seeds, market inventory+prices,
                   unlocked shops, money, hands, hires_today, unlocked quadrants
  * board          tiles: PLANT{crop}, WEED, COOP/PASTURE (+animal), LOCKED, empty

Derived (no audit needed):

  harvested[item] = dW - bought + fed + sold          where W = shed + inventories
  animal escape   = a tile held an animal at step t, is still an animal structure
                    at t+1, and the animal is gone (DIG cannot remove a structure
                    that has an animal on it, so a disappearance is an escape)
  discards        = units force-dropped at hour 23 that did not fit in the shed

Usage::

    PYTHONPATH=. python tools/dsm_extract.py --dir replays/DSM/v1 \\
        --dump /tmp/dsm_cache.json --workers 0
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
import glob
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK",
            "WOOL", "FERTILIZER")
ANIMALS = ("COW", "SHEEP", "GOOSE")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
SHEDS_CAP = 100
TURNS_PER_DAY = 24


def _dsm_seats(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    return team_mod.seats_of_names(names) or [0]


def _tile_animals(tiles):
    """{animal: count} currently on the board."""
    c = Counter()
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("animal"):
                c[t["animal"]] += 1
    return c


def _tile_crops(tiles):
    c = Counter()
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop"):
                c[t["crop"]] += 1
    return c


def _tile_kinds(tiles):
    c = Counter()
    for row in tiles:
        for t in row:
            if t is None:
                c["EMPTY"] += 1
            elif isinstance(t, dict):
                c[t.get("kind") or "?"] += 1
    return c


def _animal_slots(tiles):
    """{(x,y): animal or None} for animal structures."""
    out = {}
    for y, row in enumerate(tiles):
        for x, t in enumerate(row):
            if isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE"):
                out[(x, y)] = t.get("animal")
    return out


def analyse(path, seat=None):
    rep = json.load(open(path))
    steps = rep["steps"]
    if seat is None:
        seat = _dsm_seats(rep)[0]
    info = rep.get("info") or {}
    ep = info.get("EpisodeId") or os.path.basename(path)
    names = info.get("TeamNames") or ["?", "?"]

    days = defaultdict(lambda: defaultdict(float))
    shops_by_day = defaultdict(list)
    sells = defaultdict(list)          # item -> [(step, inv_before, price, qty)]
    discard_by_item = Counter()
    prev_w = None
    prev_slots = None
    seen_shops = set()

    for t, frame in enumerate(steps):
        st = frame[seat]
        o = st["observation"]
        a = st.get("action") or {}
        day = t // TURNS_PER_DAY
        d = days[day]
        farm = o["farms"][seat]
        tiles = farm["tiles"]
        private = o["private"]
        shed = private.get("shed") or {}
        invs = private.get("inventories") or []
        inv = o["market"]["inventory"]
        prices = o["market"]["prices"]

        # ---- shop unlocks
        shops = list(o["town"]["unlocked_shops"])
        new = [s for s in shops if s not in seen_shops]
        seen_shops.update(shops)
        shops_by_day[day].extend(new)

        # ---- board / shed / money snapshots (end-of-day values overwritten below)
        d["money"] = farm.get("money", 0)
        d["hands"] = len(farm.get("hands") or [])
        d["hires_today"] = max(d.get("hires_today", 0), farm.get("hires_today", 0))
        d["quadrants"] = len(farm.get("unlocked_quadrants") or [])
        shed_total = sum(v for v in shed.values() if v > 0)
        d["shed_max"] = max(d.get("shed_max", 0), shed_total)
        if t % TURNS_PER_DAY == TURNS_PER_DAY - 1:
            d["shed_end"] = shed_total
            d["shed_end_items"] = {k: v for k, v in shed.items() if v > 0}
        an = _tile_animals(tiles)
        cr = _tile_crops(tiles)
        kinds = _tile_kinds(tiles)
        for sp in ANIMALS:
            d["animal_%s_end" % sp] = an.get(sp, 0)
            d["animal_%s_max" % sp] = max(d.get("animal_%s_max" % sp, 0), an.get(sp, 0))
            d["struct_%s_end" % sp] = kinds.get("COOP" if sp == "GOOSE" else "PASTURE", 0)
        for c in CROPS:
            d["crop_%s_end" % c] = cr.get(c, 0)
            d["crop_%s_max" % c] = max(d.get("crop_%s_max" % c, 0), cr.get(c, 0))
        d["weeds_end"] = kinds.get("WEED", 0)
        d["weeds_max"] = max(d.get("weeds_max", 0), kinds.get("WEED", 0))
        d["empty_end"] = kinds.get("EMPTY", 0)
        if kinds.get("LOCKED"):
            d["locked_tiles"] = kinds["LOCKED"]

        # ---- market inventory / price band
        for p in PRODUCTS:
            v = inv.get(p, 0)
            d["inv_%s_min" % p] = min(d.get("inv_%s_min" % p, 1 << 30), v)
            d["inv_%s_max" % p] = max(d.get("inv_%s_max" % p, 0), v)
            d["inv_%s_sum" % p] = d.get("inv_%s_sum" % p, 0) + v
            d["inv_%s_n" % p] = d.get("inv_%s_n" % p, 0) + 1
            pr = prices.get(p, 0)
            d["px_%s_min" % p] = min(d.get("px_%s_min" % p, 1 << 30), pr)
            d["px_%s_max" % p] = max(d.get("px_%s_max" % p, 0), pr)

        # ---- market orders
        bought = Counter()
        sold_req = Counter()
        for order in (a.get("market") or []):
            if not isinstance(order, list) or not order:
                continue
            op = order[0]
            item = order[1] if len(order) > 1 else None
            qty = int(order[2]) if len(order) > 2 else 1
            if op == "HIRE":                      # HIRE / BUY_LAND carry no item
                d["hire_orders"] += 1
                continue
            if op == "BUY_LAND":
                d["land_orders"] += 1
                continue
            if item is None:
                continue
            if op == "BUY_PRODUCT":
                bought[item] += qty
                d["buyunits_%s" % item] += qty
                d["cost_%s" % item] += qty * prices.get(item, 0)
            elif op == "SELL":
                sold_req[item] += qty
                d["sellreq_%s" % item] += qty
                d["rev_%s" % item] += qty * prices.get(item, 0)
                sells[item].append((t, inv.get(item, 0), prices.get(item, 0), qty))
            elif op == "BUY_SEED":
                d["seed_%s" % item] += qty
                d["seedcost"] += qty * prices.get(item, 0)
            elif op == "BUY_ANIMAL":
                d["buy_%s" % item] += qty
                d["animalcost"] += qty * 0  # cost not in prices

        # ---- unit ops
        units = [a.get("farmer") or ["PASS"]] + list(a.get("hands") or [])
        fed_step = 0
        for u in units:
            if not isinstance(u, list) or not u:
                continue
            op = u[0]
            if op == "PLANT" and len(u) >= 2:
                d["plant_%s" % u[1]] += 1
            elif op == "WATER":
                d["water"] += 1
                if u[1:] and u[1] == "SHED":
                    pass
            elif op == "FERTILIZE":
                d["fertilize"] += 1
            elif op == "HARVEST":
                d["harvest_ops"] += 1
            elif op == "FEED":
                d["feed"] += 1
                fed_step += 1
            elif op == "CARE":
                d["care"] += 1
            elif op == "COLLECT_FERTILIZER":
                d["collect_fert"] += 1
            elif op == "DIG":
                d["dig"] += 1
            elif op == "BUILD_COOP":
                d["build_coop"] += 1
            elif op == "BUILD_PASTURE":
                d["build_pasture"] += 1
            elif op == "DROP":
                d["drop_ops"] += 1

        # ---- escapes (animal vanished from an animal structure)
        slots = _animal_slots(tiles)
        if prev_slots is not None:
            esc = 0
            for xy, sp in prev_slots.items():
                if sp and slots.get(xy) is None:
                    esc += 1
            d["escapes"] += esc

        # ---- wheat/milk flow identity: harvested = dW - bought + fed + sold
        w_now = {}
        for p in PRODUCTS:
            w_now[p] = shed.get(p, 0) + sum((iv or {}).get(p, 0) for iv in invs)
        #   dW = harvested + bought - fed - sold   (DROPs are internal to W)
        for p in PRODUCTS:
            req = sold_req.get(p, 0)
            d["sold_%s" % p] += req
            if prev_w is not None:
                # FEED consumes exactly 1 WHEAT per op, from the worker's inventory
                harv = (w_now[p] - prev_w[p]) - bought.get(p, 0) + req \
                    + (fed_step if p == "WHEAT" else 0)
                d["flow_%s" % p] += harv
        prev_w = w_now
        prev_slots = slots

        # ---- day-end force-drop discard estimate
        if t % TURNS_PER_DAY == TURNS_PER_DAY - 1:
            total = sum(v for v in shed.values() if v > 0)
            held = Counter()
            for iv in invs:
                for k, v in (iv or {}).items():
                    if v > 0:
                        held[k] += v
            room = max(0, SHEDS_CAP - total)
            for k, v in held.items():
                d["incoming_%s" % k] += v
                if v > room:
                    discard_by_item[k] += v - room
                room = max(0, room - v)
    # ---- finalise
    rows = []
    for day in sorted(days):
        r = dict(days[day])
        r["day"] = day
        r["new_shops"] = shops_by_day.get(day, [])
        for p in PRODUCTS:
            n = r.get("inv_%s_n" % p, 0)
            if n:
                r["inv_%s_mean" % p] = r.get("inv_%s_sum" % p, 0) / n
        rows.append(r)

    game = {
        "episode": ep, "seat": seat, "team": names[seat],
        "opp": names[1 - seat] if len(names) > 1 else "?",
        "self_play": len(set(names)) == 1,
        "money_end": rows[-1]["money"] if rows else 0,
        "yarn_day": next((r["day"] for r in rows
                          if any("YARN" in s for s in (r.get("new_shops") or []))), None),
        "shop_days": {r["day"]: list(r["new_shops"]) for r in rows if r.get("new_shops")},
        "discard_by_item": dict(discard_by_item),
        "sells": {p: v for p, v in sells.items()},
        "days": rows,
    }
    return game


def _one(arg):
    return analyse(*arg)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="replays/DSM/v1")
    ap.add_argument("--glob", default=None)
    ap.add_argument("--seat", type=int, default=None)
    ap.add_argument("--dump", default="dsm_cache.json")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    args = ap.parse_args()
    team_mod.set_team(args.team)

    files = sorted(glob.glob(args.glob or os.path.join(args.dir, "*.json")))
    if args.max_games:
        files = files[:args.max_games]
    workers = args.workers or min(len(files), os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        games = list(ex.map(_one, [(f, args.seat) for f in files]))
    games.sort(key=lambda g: str(g["episode"]))
    with open(args.dump, "w") as f:
        json.dump({"n": len(games), "games": games}, f)
    print(f"wrote {args.dump}: {len(games)} games")


if __name__ == "__main__":
    main()
