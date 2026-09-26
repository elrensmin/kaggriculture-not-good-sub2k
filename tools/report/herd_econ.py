#!/usr/bin/env python
"""herd_econ — per-animal economics, measured the same way on the #1 and on us.

The open question this answers
------------------------------
The #1 runs ~18 animals at ring distance 1.6 from the shed; we run ~4 and our
attempts to expand measured **-$8,014 (0/24) even with the chaining fix on**. Same
crew. So the herd is not a routing problem any more — it is an economics problem,
and this tool measures every term of that economics, per animal-day, from the
replay stream alone:

  STOCK        animal-days, placements, escapes, structures built, by species
  FEED         wheat fed (1/animal/day), whether it was home-grown or bought
  CARE         the care bonus is only paid when ``cared_today AND fed_today``
               (``_daily_refresh_animals`` pops ``pending_care_bonus`` only on a
               fed day). So the quantity that matters is not "care ops" but
               **care capture = cared_days / fed_days**, and the tool prints it
               per species. Missing it silently halves herd output.
  PRODUCTION   yield collected per animal-day vs the theoretical base rate
               (COW milk every 2 days = 0.5/day, SHEEP wool every 3 = 0.333/day,
               GOOSE egg every 1 = 1.0/day). A ratio below 1.0 is lost output.
  LABOUR       moves charged to FEED / CARE / COLLECT, per op and per animal-day
  REVENUE      MILK / WOOL / EGG units sold and revenue (leaderboard replays have
               no audit, so units come from the SELL orders themselves)
  FERTILIZER   units collected -- the reason the herd exists (it doubles crop yield)

Every number is per game and cross-game figures are medians. The tool runs on a
replay directory (the #1's 123 episodes) and on our own runs through the identical
scanner, so the two tables are directly comparable.

Usage
-----
  PYTHONPATH=. python -m tools.report.herd_econ --dir replays/DSM/v1 --max 40
  PYTHONPATH=. python -m tools.report.herd_econ --agent --pa 1-12 --batch 2
  PYTHONPATH=. python -m tools.report.herd_econ --dir replays/DSM/v1 --daily --game 0
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor

TURNS_PER_DAY = 24
SPECIES = ("COW", "SHEEP", "GOOSE")
PRODUCT = {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}
# engine production cadence: first yield day, then every `interval` days
CADENCE = {"COW": (8, 2), "SHEEP": (6, 3), "GOOSE": (4, 1)}
MOVE = ("NORTH", "SOUTH", "EAST", "WEST")


def _dsm_seats(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    out = [i for i, n in enumerate(names) if "DSM" in (n or "").upper()]
    return out or [0]


def scan_steps(steps, seat):
    """One pass over a game. Returns a flat dict of per-game herd aggregates."""
    A = collections.Counter()
    per_day = collections.defaultdict(lambda: collections.defaultdict(float))
    seen = {}
    prev_animals = None
    n = len(steps)
    for t in range(n):
        if len(steps[t]) <= seat:
            continue
        o = steps[t][seat].get("observation")
        if not o:
            continue
        day = t // TURNS_PER_DAY
        tiles = o["farms"][seat]["tiles"]
        # ---- census every animal on the board this turn
        animals = {}
        for y, row in enumerate(tiles):
            for x, cell in enumerate(row):
                if isinstance(cell, dict) and cell.get("animal"):
                    animals[(x, y)] = cell
        # A fed/cared flag is only set from the turn it happens, so counting turns
        # would measure *when* he fed, not *whether* he did. An animal-day is a
        # distinct (day, x, y) occupancy; the day counts as fed if ANY turn that
        # day shows fed_today. That is the correct denominator for care capture.
        for (x, y), c in animals.items():
            sp = c["animal"]
            if sp not in SPECIES:
                continue
            e = seen.get((day, x, y))
            if e is None:
                e = seen[(day, x, y)] = [sp, False, False, False, False, False,
                                         False, False, False]
            if c.get("fed_today"):
                e[1] = True
            if c.get("cared_today"):
                e[2] = True
            if c.get("fed_today") and c.get("cared_today"):
                e[3] = True
            if (c.get("yield_units") or 0) > 0:
                e[4] = True
            if (c.get("pending_care_bonus") or 0) > 0:
                e[5] = True
            if c.get("fertilizer_available"):
                e[6] = True
            if (c.get("consecutive_unfed") or 0) >= 2:
                e[7] = True
            # production day: _daily_refresh_animals runs at the END of `day-1` with
            # next_day = day, and pays base (+bonus if that day's feed was given).
            # So the yield_units appear on `day` when (day - placed - first) % interval
            # == 0. This is the ONLY day a feed can capture the accumulated care bonus,
            # and a missed feed that day also wipes pending_care_bonus to 0.
            placed = c.get("placed_day")
            if placed is not None:
                first, interval = CADENCE[sp]
                dsi = day - int(placed) - first
                if dsi >= 0 and dsi % interval == 0:
                    e[8] = True
        # ---- escapes: animal gone but the structure remains
        if prev_animals is not None:
            for pos, sp in prev_animals.items():
                x, y = pos
                if (x, y) in animals:
                    continue
                cell = tiles[y][x] if (0 <= y < len(tiles) and 0 <= x < len(tiles[y])) else None
                if isinstance(cell, dict) and cell.get("kind") in ("COOP", "PASTURE"):
                    A[f"escape_{sp}"] += 1
        prev_animals = {p: c["animal"] for p, c in animals.items()
                        if c.get("animal") in SPECIES}
        # ---- the action decided from THIS observation lives one frame later
        if t + 1 >= n or len(steps[t + 1]) <= seat:
            continue
        a = steps[t + 1][seat].get("action")
        if not a:
            continue
        farm = o["farms"][seat]
        pos = [tuple(farm.get("farmer") or (0, 0))]
        pos += [tuple(p) for p in (farm.get("hands") or [])]
        cmds = [a.get("farmer")] + list(a.get("hands") or [])
        carried = collections.Counter()
        for u, c in enumerate(cmds):
            if not c:
                continue
            op = c[0]
            if op in MOVE:
                A["moves"] += 1
                if u < len(pos):
                    px, py = pos[u]
                    cell = tiles[py][px] if (py < len(tiles) and px < len(tiles[py])) else None
                    if isinstance(cell, dict) and cell.get("kind") in ("COOP", "PASTURE"):
                        A["moves_at_animal"] += 1
            elif op in ("FEED", "CARE", "COLLECT_FERTILIZER", "PLACE", "DIG"):
                A[f"op_{op}"] += 1
                if u < len(pos):
                    px, py = pos[u]
                    cell = tiles[py][px] if (py < len(tiles) and px < len(tiles[py])) else None
                    sp = cell.get("animal") if isinstance(cell, dict) else None
                    if op == "FEED" and sp in SPECIES:
                        A[f"feed_{sp}"] += 1
                    if op == "CARE" and sp in SPECIES:
                        A[f"care_{sp}"] += 1
                    if op == "COLLECT_FERTILIZER" and sp in SPECIES:
                        A[f"collect_{sp}"] += 1
                if op == "FEED":
                    carried["wheat_fed"] += 1
            elif op in ("BUILD_COOP", "BUILD_PASTURE"):
                A[f"op_{op}"] += 1
        # ---- market: SELL orders (price from the observation's own quote)
        prices = (o.get("market") or {}).get("prices") or {}
        for m in (a.get("market") or []):
            if not isinstance(m, list) or not m:
                continue
            if m[0] == "SELL" and len(m) >= 3:
                item, qty = m[1], m[2]
                if item in ("MILK", "WOOL", "EGG"):
                    A[f"sold_{item}"] += qty
                    A[f"rev_{item}"] += qty * prices.get(item, 0)
            elif m[0] == "BUY_PRODUCT" and len(m) >= 3 and m[1] == "WHEAT":
                A["wheat_bought"] += m[2]
            elif m[0] == "BUY_ANIMAL" and len(m) >= 3:
                sp = m[1]
                if sp in SPECIES:
                    A[f"bought_{sp}"] += m[2]
    # ---- collapse the per-turn census into per-animal-day facts
    for (day, _x, _y), e in seen.items():
        sp, fed, cared, both, ready, pend, fert, risk, prod = e
        A[f"animalday_{sp}"] += 1
        d = per_day[day]
        d[f"n_{sp}"] += 1
        if prod:
            A[f"prodday_{sp}"] += 1
            d[f"prod_{sp}"] += 1
            if fed:
                A[f"fedprod_{sp}"] += 1       # <-- the feed that captures the bonus
            if both:
                A[f"bothprod_{sp}"] += 1
        if fed:
            A[f"fedday_{sp}"] += 1
            d[f"fed_{sp}"] += 1
        if cared:
            A[f"careday_{sp}"] += 1
            d[f"cared_{sp}"] += 1
        if both:
            A[f"bothday_{sp}"] += 1
            d[f"both_{sp}"] += 1
        if ready:
            A[f"readyday_{sp}"] += 1
            d[f"ready_{sp}"] += 1
        if pend:
            A[f"pendday_{sp}"] += 1
            d[f"pend_{sp}"] += 1
        if fert:
            A[f"fertavail_{sp}"] += 1
            d[f"fertavail_{sp}"] += 1
        if risk:
            A[f"riskday_{sp}"] += 1
            d[f"risk_{sp}"] += 1
    return dict(A), {str(k): dict(v) for k, v in per_day.items()}


def scan_replay(path, seat=None):
    rep = json.load(open(path))
    steps = rep["steps"]
    if seat is None:
        seat = _dsm_seats(rep)[0]
    info = rep.get("info") or {}
    names = info.get("TeamNames") or ["?", "?"]
    A, per_day = scan_steps(steps, seat)
    A["_team"] = names[seat] if seat < len(names) else "?"
    A["_episode"] = str(info.get("EpisodeId") or os.path.basename(path))
    A["_file"] = os.path.basename(path)
    A["_seat"] = seat
    return {"agg": A, "per_day": per_day}


def _work(path, seat):
    try:
        return scan_replay(path, seat)
    except Exception as e:                                        # pragma: no cover
        return {"agg": {"_file": os.path.basename(path), "_error": repr(e)}, "per_day": {}}


# --------------------------------------------------------------------------- report

def _theo_per_day(sp):
    first, interval = CADENCE[sp]
    return 1.0 / interval


def report(games, label, per_day_of=None):
    agg = [g["agg"] for g in games if "_error" not in g["agg"]]
    if not agg:
        print(f"\n  {label}: no usable games")
        return
    def med(key, default=0.0):
        v = [a.get(key, default) for a in agg]
        return st.median(v) if v else default

    print(f"\n{'='*100}\n  {label}   ({len(agg)} games)\n{'='*100}")
    print(f"  {'species':7} {'anim-days':>10} {'prod-days':>10} {'fed-on-prod':>12} "
          f"{'cared-on-prod':>14} {'bonus-earned':>13} {'collected':>10} {'u/an-day':>9} "
          f"{'theo':>6} {'output-ratio':>13}")
    for sp in SPECIES:
        ad = med(f"animalday_{sp}")
        if ad <= 0:
            print(f"  {sp:7} {'0':>10}")
            continue
        pd_ = med(f"prodday_{sp}")
        fp = (med(f"fedprod_{sp}") / pd_) if pd_ else 0.0
        cp = (med(f"bothprod_{sp}") / pd_) if pd_ else 0.0
        be = med(f"pendday_{sp}") / ad
        sold = med(f"sold_{PRODUCT[sp]}")
        per = sold / ad
        th = _theo_per_day(sp)
        print(f"  {sp:7} {ad:>10.1f} {pd_:>10.1f} {fp:>11.0%} {cp:>13.0%} "
              f"{be:>12.0%} {sold:>10.1f} {per:>9.3f} {th:>6.3f} {per/th:>13.2f}")

    tot_ad = sum(med(f"animalday_{sp}") for sp in SPECIES)
    print(f"\n  {'total animal-days/game':32} {tot_ad:>8.1f}")
    print(f"  {'herd revenue/game ($)':32} "
          f"{sum(med(f'rev_{PRODUCT[sp]}') for sp in SPECIES):>8,.0f}")
    print(f"  {'herd revenue/animal-day ($)':32} "
          f"{(sum(med(f'rev_{PRODUCT[sp]}') for sp in SPECIES) / tot_ad if tot_ad else 0):>8.1f}")

    print(f"\n  --- feed / labour ---")
    print(f"  {'wheat fed (units, = animal-days fed)':40} {med('op_FEED'):>8.0f}")
    print(f"  {'wheat bought (units)':40} {med('wheat_bought'):>8.0f}")
    print(f"  {'feed ops':40} {med('op_FEED'):>8.0f}")
    print(f"  {'care ops':40} {med('op_CARE'):>8.0f}")
    print(f"  {'collect ops':40} {med('op_COLLECT_FERTILIZER'):>8.0f}")
    print(f"  {'BUILD_COOP + BUILD_PASTURE ops':40} "
          f"{med('op_BUILD_COOP') + med('op_BUILD_PASTURE'):>8.0f}")
    print(f"  {'moves at an animal tile':40} {med('moves_at_animal'):>8.0f}")
    print(f"  {'total moves':40} {med('moves'):>8.0f}")

    print(f"\n  --- risk / loss ---")
    print(f"  {'escapes/game':40} {sum(med(f'escape_{sp}') for sp in SPECIES):>8.1f}")
    print(f"  {'animal-days at >=2 consecutive unfed':40} "
          f"{sum(med(f'riskday_{sp}') for sp in SPECIES):>8.1f}")
    print(f"  {'animal-days with yield ready':40} "
          f"{sum(med(f'readyday_{sp}') for sp in SPECIES):>8.1f}")
    print(f"  {'animal-days with pending care bonus':40} "
          f"{sum(med(f'pendday_{sp}') for sp in SPECIES):>8.1f}")
    print(f"  {'animal-days fertilizer available':40} "
          f"{sum(med(f'fertavail_{sp}') for sp in SPECIES):>8.1f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="replays/DSM/v1")
    ap.add_argument("--seat", type=int, default=None)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--agent", action="store_true", help="run OUR agent instead")
    ap.add_argument("--pa", default="1-12")
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--daily", action="store_true",
                    help="print the per-day series instead of the summary")
    ap.add_argument("--label", default=None)
    a = ap.parse_args()

    if a.agent:
        import sys
        sys.path.insert(0, ".")
        from tools.diagnose.agents import load_public_agent
        from tools.diagnose.games import run_game

        def fresh():
            for m in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
                del sys.modules[m]
            import src
            return src.agent

        pa = []
        for part in str(a.pa).split(","):
            if "-" in part:
                lo, hi = part.split("-")
                pa += list(range(int(lo), int(hi) + 1))
            else:
                pa.append(int(part))
        games = []
        for opp in pa:
            for b in range(a.batch):
                s = a.seed + b * 7919
                env = run_game(fresh(), load_public_agent(opp), seed=s, seat=1,
                               audit=False)
                steps = env.steps if hasattr(env, "steps") else env["steps"]
                A, pd_ = scan_steps(steps, 1)
                A.update({"_team": "US", "_episode": f"pa{opp}_s{s}",
                          "_file": f"pa{opp}_s{s}", "_seat": 1})
                games.append({"agg": A, "per_day": pd_})
        report(games, a.label or f"US  (agents {a.pa} x {a.batch})")
        return

    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))
    if a.max:
        files = files[:a.max]
    if not files:
        print(f"no replays in {a.dir}")
        return
    w = a.workers or None
    with ProcessPoolExecutor(max_workers=w) as ex:
        games = list(ex.map(_work, files, [a.seat] * len(files)))
    report(games, a.label or f"{a.dir}  (seat {'auto' if a.seat is None else a.seat})")

    if a.daily and games:
        g = next((x for x in games if x["per_day"]), None)
        if g:
            print(f"\n{'='*100}\n  per-day series — {g['agg'].get('_file')}\n{'='*100}")
            hdr = (f"  {'day':>3} " + "".join(
                f"{sp:>26}" for sp in SPECIES) + f"{'fert':>8}{'pend':>8}{'risk':>8}")
            print(hdr)
            print(f"  {'':>3} " + "".join(f"{'n/fed/cared/ready':>26}" for _ in SPECIES)
                  + f"{'avail':>8}{'bonus':>8}{'unfed':>8}")
            for day in sorted(g["per_day"], key=int):
                d = g["per_day"][day]
                cells = []
                for sp in SPECIES:
                    n = d.get(f"n_{sp}", 0)
                    if not n:
                        cells.append(f"{'-':>26}")
                        continue
                    cells.append(f"{n:.0f}/{d.get('fed_'+sp,0):.0f}/"
                                 f"{d.get('cared_'+sp,0):.0f}/"
                                 f"{d.get('ready_'+sp,0):.0f}".rjust(26))
                print(f"  {day:>3} " + "".join(cells)
                      + f"{sum(d.get('fertavail_'+s,0) for s in SPECIES):>8.0f}"
                      + f"{sum(d.get('pend_'+s,0) for s in SPECIES):>8.0f}"
                      + f"{sum(d.get('risk_'+s,0) for s in SPECIES):>8.0f}")


if __name__ == "__main__":
    main()
