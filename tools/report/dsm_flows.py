"""tools/dsm_flows.py — what DSM (or any agent) actually DOES with WHEAT and MILK.

Leaderboard replays carry no market audit, so the ``days_seed*.csv`` money/price
columns are zero. Everything here is instead reconstructed from the replay's own
per-step ``action`` + ``observation`` stream, which is exact:

  * unit ops            — PLANT / HARVEST / FEED / DROP, and the tile underfoot
  * market orders       — SELL / BUY_PRODUCT, with the quoted price
  * ``market.inventory``, ``private.shed``, ``private.inventories`` per step
  * ``town.unlocked_shops`` per step

Wheat/milk flow identity used for the sold quantities (no audit needed)::

    W[t] = shed[item] + sum(worker inventories[item])
    harvested[t] = sum(yield_units) for HARVESTs on that crop's tiles
    sold[t] = W[t] + harvested[t] + bought[t] - fed[t] - W[t+1]

The day-end force-drop can discard overflow, which would inflate ``sold`` on the
hour-23 step; that step is reported separately as ``eod_drop_units``.

Judgement is PER GAME — never averaged. Use ``--summary`` for one line per game
and the cross-game tallies, ``--daily`` for a per-day series of one episode.

Run with ``PYTHONPATH=src:.``.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK",
            "WOOL", "FERTILIZER")
MILK_SHOPS = ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP")
YARN_SHOP = "YARN_STORE"
TURNS_PER_DAY = 24
FLOOR = 1.0

_CROP_OF_ITEM = {"WHEAT": "WHEAT", "CARROT": "CARROT", "TOMATO": "TOMATO",
                 "STRAWBERRY": "STRAWBERRY", "MELON": "MELON"}


def _dsm_seats(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    out = [i for i, n in enumerate(names) if "DSM" in (n or "").upper()]
    return out or [1]


def _tiles(o, seat):
    farm = o["farms"][seat]
    return farm["tiles"], [tuple(farm["farmer"])] + [tuple(p) for p in farm["hands"]]


def _count_animals(tiles):
    c = Counter()
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("animal"):
                c[t["animal"]] += 1
    return c


def _count_crops(tiles):
    c = Counter()
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("crop"):
                c[t["crop"]] += 1
    return c


def analyse(path, seat=None):
    """Return (per_day_rows, game_row) for one replay's chosen seat."""
    rep = json.load(open(path))
    steps = rep["steps"]
    if seat is None:
        seat = _dsm_seats(rep)[0]
    ep = (rep.get("info") or {}).get("EpisodeId") or os.path.basename(path)
    names = (rep.get("info") or {}).get("TeamNames") or ["?", "?"]
    other = 1 - seat

    days = defaultdict(lambda: defaultdict(float))
    days[0]["shops"] = []
    inv_series = defaultdict(list)
    price_at_sell = {p: [] for p in PRODUCTS}
    eod_drop = defaultdict(float)
    prev_w = None
    seen_shops = set()

    for t, frame in enumerate(steps):
        o = frame[seat]["observation"]
        a = frame[seat].get("action") or {}
        day = t // TURNS_PER_DAY
        d = days[day]
        inv = o["market"]["inventory"]
        prices = o["market"]["prices"]
        shed = o["private"]["shed"]
        invs = o["private"]["inventories"] or []
        tiles, pos = _tiles(o, seat)
        shops = list(o["town"]["unlocked_shops"])
        new_shops = [s for s in shops if s not in seen_shops]
        seen_shops.update(shops)
        d["new_shops"] = d.get("new_shops") or []
        d["new_shops"].extend(new_shops)

        units = [a.get("farmer") or ["PASS"]] + list(a.get("hands") or [])

        # market orders
        bought = Counter()
        sold_req = Counter()
        for order in (a.get("market") or []):
            if not isinstance(order, list) or len(order) < 3:
                continue
            op, item, qty = order[0], order[1], int(order[2])
            if op == "BUY_PRODUCT":
                bought[item] += qty
                d["cost_%s" % item] += qty * prices.get(item, 0)
            elif op == "SELL":
                sold_req[item] += qty
                price_at_sell[item].append((t, prices.get(item, 0), qty))

        # unit ops (counts only -- the replay's tile snapshots are post-action, so
        # harvests are recovered from the state balance below instead)
        fed = 0
        planted = Counter()
        for u in units:
            if not isinstance(u, list) or not u:
                continue
            if u[0] == "FEED":
                fed += 1
            elif u[0] == "PLANT" and len(u) >= 2:
                planted[u[1]] += 1

        # system totals for the flow identity:
        #   dW = harvested + bought - fed - sold   (DROPs are internal to W)
        w_now = {}
        for item in PRODUCTS:
            w_now[item] = shed.get(item, 0) + sum((iv or {}).get(item, 0) for iv in invs)
        if prev_w is not None:
            for item in PRODUCTS:
                req = sold_req.get(item, 0)
                dW = w_now[item] - prev_w[item]
                # Assume the order book commits in full (DSM's orders are small and
                # his shed holds them); harvested is then the residual. A negative
                # residual means a sell was clipped -- clamped, and noted by
                # `clip_<item>` so the assumption is auditable.
                harv = dW - bought.get(item, 0) + (fed if item == "WHEAT" else 0) + req
                if harv < 0:
                    d["clip_%s" % item] += -harv
                    harv = 0
                d["harvested_%s" % item] += harv
                d["sold_%s" % item] += req
                if item == "WHEAT" and t % TURNS_PER_DAY == TURNS_PER_DAY - 1 \
                        and harv > req:
                    eod_drop[item] += harv - req
        prev_w = w_now

        d["fed_WHEAT"] += fed
        d["bought_WHEAT"] += bought.get("WHEAT", 0)
        for item, n in planted.items():
            d["planted_%s" % item] += n
        for item in PRODUCTS:
            inv_series[item].append(inv.get(item, 0))
            d["invmax_%s" % item] = max(d.get("invmax_%s" % item, 0), inv.get(item, 0))
            d["invmin_%s" % item] = min(d.get("invmin_%s" % item, 1 << 30), inv.get(item, 0))
        d["shed_total"] = max(d.get("shed_total", 0), sum(shed.values()))
        an = _count_animals(tiles)
        cr = _count_crops(tiles)
        for s in ("COW", "SHEEP", "GOOSE"):
            d["animals_%s" % s] = max(d.get("animals_%s" % s, 0), an.get(s, 0))
        d["animals_%s_end" % "COW"] = an.get("COW", 0)
        for c in ("WHEAT", "STRAWBERRY", "MELON", "CARROT", "TOMATO"):
            d["plants_%s" % c] = max(d.get("plants_%s" % c, 0), cr.get(c, 0))
        d["money"] = o["farms"][seat].get("money", 0)

    rows = []
    for day in sorted(days):
        d = dict(days[day])
        d["day"] = day
        d["episode"] = ep
        d["yarn"] = int(any(YARN_SHOP in (r.get("new_shops") or []) for r in [d]))
        rows.append(d)

    game = {"episode": ep, "seat": seat, "team": names[seat], "opp": names[other]}
    yarn_day = next((r["day"] for r in rows if YARN_SHOP in (r.get("new_shops") or [])), None)
    for r in rows:
        r["yarn"] = int(yarn_day is not None and r["day"] >= yarn_day)
    game["yarn"] = int(yarn_day is not None)
    game["yarn_day"] = yarn_day
    milk_day = next((r["day"] for r in rows
                     if any(s in MILK_SHOPS for s in (r.get("new_shops") or []))), None)
    game["milk_shop"] = int(milk_day is not None)
    game["milk_day"] = milk_day

    for item in PRODUCTS:
        game["sold_%s" % item] = sum(r.get("sold_%s" % item, 0) for r in rows)
        game["harvested_%s" % item] = sum(r.get("harvested_%s" % item, 0) for r in rows)
        game["invmax_%s" % item] = max((r.get("invmax_%s" % item, 0) for r in rows), default=0)
        game["invmin_%s" % item] = min((r.get("invmin_%s" % item, 1 << 30) for r in rows),
                                       default=0)
    game["fed_WHEAT"] = sum(r.get("fed_WHEAT", 0) for r in rows)
    game["bought_WHEAT"] = sum(r.get("bought_WHEAT", 0) for r in rows)
    game["cost_WHEAT"] = sum(r.get("cost_WHEAT", 0) for r in rows)
    game["shed_max"] = max((r.get("shed_total", 0) for r in rows), default=0)
    game["plants_WHEAT"] = max((r.get("plants_WHEAT", 0) for r in rows), default=0)
    game["plants_STRAWBERRY"] = max((r.get("plants_STRAWBERRY", 0) for r in rows), default=0)
    game["cows_max"] = max((r.get("animals_COW", 0) for r in rows), default=0)
    game["sheep_max"] = max((r.get("animals_SHEEP", 0) for r in rows), default=0)
    game["geese_max"] = max((r.get("animals_GOOSE", 0) for r in rows), default=0)
    game["cows_end"] = rows[-1].get("animals_COW_end", 0) if rows else 0
    game["money_end"] = rows[-1].get("money", 0) if rows else 0
    game["eod_drop"] = dict(eod_drop)

    # price at sell, and how much of it was at the floor
    for item in PRODUCTS:
        recs = price_at_sell[item]
        units = sum(q for _, _, q in recs)
        game["px_%s" % item] = (sum(p * q for _, p, q in recs) / units) if units else 0.0
        game["floorunits_%s" % item] = sum(q for _, p, q in recs if p <= FLOOR)
    game["_rows"] = rows
    return rows, game


# --------------------------------------------------------------------------
def _one(arg):
    return analyse(*arg)


def load_games(pattern, seat=None, workers=0, limit=0):
    files = sorted(glob.glob(pattern))
    if limit:
        files = files[:limit]
    tasks = [(f, seat) for f in files]
    workers = workers or min(len(tasks), os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        out = list(ex.map(_one, tasks))
    return [g for _, g in out]


def _fmt(v):
    if isinstance(v, str):
        return v
    return f"{v:,.0f}" if isinstance(v, (int, float)) and abs(v) >= 100 else f"{v:,.1f}"


def summary(games):
    print(f"\n== dsm_flows: {len(games)} games (per game, no averaging) ==")
    head = ("episode", "yarn", "milk", "cow", "shp", "gse", "fedW", "buyW", "solW",
            "invW", "harW", "plW", "solM", "invM", "pxW", "pxM", "pxS", "shed")
    print("  " + " ".join(f"{h:>7s}" for h in head))
    for g in games:
        row = (str(g["episode"])[-7:], g["yarn"], g["milk_shop"], g["cows_max"],
               g["sheep_max"], g["geese_max"], g["fed_WHEAT"], g["bought_WHEAT"],
               g["sold_WHEAT"], g["invmax_WHEAT"], g["harvested_WHEAT"], g["plants_WHEAT"],
               g["sold_MILK"], g["invmax_MILK"], g["px_WHEAT"], g["px_MILK"],
               g["px_STRAWBERRY"], g["shed_max"])
        print("  " + " ".join(f"{_fmt(v):>7s}" for v in row))

    for label, sub in (("ALL", games),
                       ("YARN", [g for g in games if g["yarn"]]),
                       ("no-YARN", [g for g in games if not g["yarn"]]),
                       ("MILK-shop", [g for g in games if g["milk_shop"]]),
                       ("no-MILK-shop", [g for g in games if not g["milk_shop"]])):
        if not sub:
            continue
        med = lambda k: sorted(g.get(k, 0) for g in sub)[len(sub) // 2]
        print(f"\n  [{label}] n={len(sub)}  (median per game)")
        print(f"    herd  COW {med('cows_max'):>4}  SHEEP {med('sheep_max'):>4}  GOOSE {med('geese_max'):>4}")
        print(f"    WHEAT fed {med('fed_WHEAT'):>6}  bought {med('bought_WHEAT'):>5}  "
              f"harvested {med('harvested_WHEAT'):>6}  sold {med('sold_WHEAT'):>6}  "
              f"plants {med('plants_WHEAT'):>3}")
        print(f"    WHEAT mkt-inv max {med('invmax_WHEAT'):>6}  px@sell {med('px_WHEAT'):>6.1f}")
        print(f"    MILK  sold {med('sold_MILK'):>6}  mkt-inv max {med('invmax_MILK'):>6}  "
              f"px@sell {med('px_MILK'):>6.1f}  floor u {med('floorunits_MILK'):>5}")
        print(f"    SHED  max {med('shed_max'):>4}   money ${med('money_end'):>9,.0f}")


def daily(games, episode):
    g = next((x for x in games if str(x["episode"]).endswith(str(episode))), None)
    if g is None:
        g = games[0]
    print(f"\n== daily series: episode {g['episode']} (seat {g['seat']}, "
          f"yarn={g['yarn']}@d{g['yarn_day']}, milk={g['milk_shop']}@d{g['milk_day']}) ==")
    print("  day  newshops            fedW buyW solW invW harvW plW | cows solM invM pxM | shed money")
    for r in g["_rows"]:
        ns = ",".join(s.replace("_SHOP", "").replace("_STORE", "")[:7]
                      for s in (r.get("new_shops") or [])) or "-"
        print(f"  {r['day']:>3}  {ns:<20} {r.get('fed_WHEAT',0):>4.0f} {r.get('bought_WHEAT',0):>4.0f} "
              f"{r.get('sold_WHEAT',0):>4.0f} {r.get('invmax_WHEAT',0):>5.0f} {r.get('harvested_WHEAT',0):>5.0f} "
              f"{r.get('plants_WHEAT',0):>3.0f} | {r.get('animals_COW',0):>4.0f} {r.get('sold_MILK',0):>4.0f} "
              f"{r.get('invmax_MILK',0):>5.0f} {r.get('px_MILK',0):>5.0f} | {r.get('shed_total',0):>4.0f} "
              f"{r.get('money',0):>9,.0f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="replays/DSM/v1", help="replay directory")
    ap.add_argument("--glob", default=None, help="override the replay glob")
    ap.add_argument("--seat", type=int, default=None, help="seat to analyse (default: DSM)")
    ap.add_argument("--summary", action="store_true", help="per-game table + tallies")
    ap.add_argument("--daily", default=None, metavar="EPISODE", help="per-day series")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()

    pattern = args.glob or os.path.join(args.dir, "*.json")
    games = load_games(pattern, seat=args.seat, workers=args.workers, limit=args.max_games)
    games.sort(key=lambda g: str(g["episode"]))
    if args.daily is not None or not args.summary:
        daily(games, args.daily)
    if args.summary or (args.daily is None and not args.summary):
        summary(games)


if __name__ == "__main__":
    main()
