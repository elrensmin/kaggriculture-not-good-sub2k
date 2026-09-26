#!/usr/bin/env python
"""footprint — DSM-vs-us decision readout for the F3+ plan (READ-ONLY).

Reports the four axes the plan targets, from saved runs / replays:

  * shed dynamics        max/end shed per day (are we packing the shed like DSM?)
  * weeds per day        late-game crop abandonment (do we stop watering too late?)
  * crop fertilizing     plants_fertilized per day (we under-fertilize vs DSM)
  * herd composition     endgame COW/SHEEP/GOOSE counts
  * price-at-sell        qty-weighted market price at each SELL order, per product
                         (the biggest $ lever: DSM sells milk/straw/wool far higher)

Data sources:
  * structural columns come from the per-day CSVs (fast; audit-free fields are fair
    to compare across datasets);
  * herd composition and price-at-sell come from the replay JSONs (replay
    `market.prices` + each seat's SELL orders).

Profiles:
  --profile ours --run-dir diag-replays/run-5   (agent 'old', seat 1)
  --profile dsm                                  (replays/DSM, seat = DSM)
  --compare                                      (print both side by side)

Usage:
  PYTHONPATH=. python -m tools.report.footprint --compare
  PYTHONPATH=. python -m tools.report.footprint --profile ours --run-dir diag-replays/run-5
"""
from __future__ import annotations

import argparse
import csv
import glob as globmod
from collections import defaultdict
from pathlib import Path

from tools import diagnose

PRODUCTS = ("MILK", "STRAWBERRY", "MELON", "WOOL", "EGG")
ANIMAL_PRODUCTS = ("EGG", "MILK", "WOOL")
CROPS_ANIMALS = ("COW", "SHEEP", "GOOSE")
STRUCT_COLS = ("max_shed_total", "end_shed_total", "weeds_max", "plants_fertilized",
               "plants_died", "animals_fed", "feed_surplus")


def _csv_perday(paths, agent):
    acc = defaultdict(lambda: defaultdict(list))
    for f in paths:
        for r in csv.DictReader(open(f)):
            if agent and r.get("agent") != agent:
                continue
            try:
                d = int(r["day"])
            except (KeyError, ValueError):
                continue
            for col in STRUCT_COLS:
                try:
                    acc[d][col].append(float(r.get(col) or 0))
                except ValueError:
                    pass
    return {d: {c: (sum(v) / len(v) if v else 0.0) for c, v in cols.items()}
            for d, cols in acc.items()}


def _dsm_seat(rep):
    names = (rep.get("info") or {}).get("TeamNames") or ["", ""]
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i
    steps = rep["steps"]
    for i in range(len(steps) - 1, -1, -1):
        si = steps[i]
        if len(si) > 1:
            try:
                m0 = si[0]["observation"]["farms"][0]["money"]
                m1 = si[1]["observation"]["farms"][1]["money"]
                return 0 if m0 > m1 else 1
            except (KeyError, TypeError):
                pass
    return 1


def _replay_stats(paths, seat_fn, max_games):
    herd = defaultdict(float)
    price_q = defaultdict(float)
    price_rev = defaultdict(float)
    games = 0
    for p in paths[:max_games]:
        try:
            rep = diagnose.load_replay(Path(p))
        except Exception:  # noqa: BLE001
            continue
        seat = seat_fn(rep)
        steps = rep["steps"]
        # endgame footprint
        last = None
        for i in range(len(steps) - 1, -1, -1):
            si = steps[i]
            if len(si) > seat and si[seat].get("observation"):
                last = si[seat]["observation"]
                break
        if last is not None:
            games += 1
            for row in last["farms"][seat]["tiles"]:
                for t in row:
                    if isinstance(t, dict) and t.get("animal") in CROPS_ANIMALS:
                        herd[t["animal"]] += 1
        # price-at-sell
        for i in range(len(steps)):
            si = steps[i]
            if len(si) <= seat:
                continue
            obs = si[seat].get("observation")
            act = si[seat].get("action")
            if not obs or not act:
                continue
            prices = (obs.get("market") or {}).get("prices") or {}
            for o in (act.get("market") or []):
                if o and o[0] == "SELL" and len(o) >= 3 and o[1] in PRODUCTS:
                    qty = int(o[2])
                    price_q[o[1]] += qty
                    price_rev[o[1]] += qty * float(prices.get(o[1], 0) or 0)
    return games, herd, price_q, price_rev


def profile(name, days_glob, replay_glob, agent, seat_fn, max_games):
    perday = _csv_perday(sorted(globmod.glob(days_glob)), agent)
    games, herd, pq, prev = _replay_stats(sorted(globmod.glob(replay_glob)), seat_fn, max_games)
    return {"name": name, "perday": perday, "games": games, "herd": herd,
            "price_q": pq, "price_rev": prev}


def _herd_mean(prof):
    n = max(1, prof["games"])
    return {a: prof["herd"].get(a, 0) / n for a in CROPS_ANIMALS}


def _price_mean(prof):
    return {p: (prof["price_rev"][p] / prof["price_q"][p] if prof["price_q"].get(p) else 0.0)
            for p in PRODUCTS}


def print_profile(prof):
    pd = prof["perday"]
    print(f"\n===== {prof['name']}  (replay games sampled: {prof['games']}) =====")
    print("day | max_shed end_shed weeds_max plants_fert | animals_fed")
    for d in range(30):
        c = pd.get(d, {})
        if not c:
            continue
        print(f" {d:2d} | {c.get('max_shed_total',0):8.1f} {c.get('end_shed_total',0):8.1f} "
              f"{c.get('weeds_max',0):9.2f} {c.get('plants_fertilized',0):11.1f} | "
              f"{c.get('animals_fed',0):11.1f}")
    h = _herd_mean(prof)
    print(f"herd endgame: COW {h['COW']:.1f}  SHEEP {h['SHEEP']:.1f}  GOOSE {h['GOOSE']:.1f}")
    print("price-at-sell (qty-weighted): " + "  ".join(
        f"{p}={_price_mean(prof)[p]:.1f}(q{prof['price_q'].get(p,0):.0f})" for p in PRODUCTS))


def _herd_one(args):
    """Worker: per-day COW/SHEEP/GOOSE counts for one replay. Returns (day, c, s, g) tuples."""
    path, which = args
    try:
        rep = diagnose.load_replay(Path(path))
    except Exception:  # noqa: BLE001
        return []
    seat = _dsm_seat(rep) if which == "dsm" else 1
    steps = rep["steps"]
    out = []
    seen = set()
    for i in range(len(steps)):
        si = steps[i]
        if len(si) <= seat:
            continue
        obs = si[seat].get("observation")
        if not obs:
            continue
        d = i // 24
        if d in seen:
            continue
        seen.add(d)
        c = s = g = 0
        for row in obs["farms"][seat]["tiles"]:
            for t in row:
                if isinstance(t, dict) and "animal" in t:
                    if t["animal"] == "COW":
                        c += 1
                    elif t["animal"] == "SHEEP":
                        s += 1
                    elif t["animal"] == "GOOSE":
                        g += 1
        out.append((d, c, s, g))
    return out


def herd_curve(replay_glob, which, workers=0):
    """Per-day mean COW/SHEEP/GOOSE, parallelised over all cores by default."""
    import os
    from concurrent.futures import ProcessPoolExecutor
    paths = sorted(globmod.glob(replay_glob))
    tasks = [(p, which) for p in paths]
    acc = defaultdict(lambda: [[], [], []])
    if workers == 0:
        workers = os.cpu_count() or 1
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for rows in ex.map(_herd_one, tasks):
            for d, c, s, g in rows:
                acc[d][0].append(c)
                acc[d][1].append(s)
                acc[d][2].append(g)
    return len(paths), acc


def print_herd_curve(label, n, acc):
    print(f"\n===== {label} per-day herd curve (n={n} games) =====")
    print("day |  COW  SHEEP  GOOSE")
    for d in range(30):
        if d not in acc:
            continue
        c, s, g = (sum(v) / len(v) if v else 0.0 for v in acc[d])
        print(f" {d:2d} | {c:5.1f} {s:6.1f} {g:6.1f}")


def _animal_rev_csv(days_glob, agent):
    """Audited animal-product units/revenue from the per-day CSVs (our runs)."""
    q = defaultdict(float)
    rev = defaultdict(float)
    for f in sorted(globmod.glob(days_glob)):
        for r in csv.DictReader(open(f)):
            if agent and r.get("agent") != agent:
                continue
            for p in ANIMAL_PRODUCTS:
                try:
                    q[p] += float(r.get("sell_qty_" + p) or 0)
                    rev[p] += float(r.get("revenue_" + p) or 0)
                except ValueError:
                    pass
    return q, rev


def print_animal_rev(label, q, rev, games=1):
    print(f"\n===== {label} animal-product revenue =====")
    print("product | units/game | revenue/game | avg_price")
    tot = 0.0
    for p in ANIMAL_PRODUCTS:
        print(f"{p:8s}| {q[p]/games:10.1f} | {rev[p]/games:12.1f} | "
              f"{(rev[p]/q[p] if q[p] else 0):.1f}")
        tot += rev[p]
    print(f"TOTAL animal revenue/game: {tot/games:.1f}")


def _dsm_dir(explicit=None):
    """DSM replays may live directly in replays/DSM or in a versioned subdir."""
    if explicit:
        return explicit
    for cand in ("replays/DSM/v1", "replays/DSM"):
        if globmod.glob(f"{cand}/*.json"):
            return cand
    return "replays/DSM"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=("ours", "dsm"), default="ours")
    ap.add_argument("--run-dir", default="diag-replays/run-5")
    ap.add_argument("--dsm-dir", default=None, help="DSM replay dir (default: replays/DSM/v1 if present)")
    ap.add_argument("--max-games", type=int, default=40)
    ap.add_argument("--workers", type=int, default=0, help="0 = all cores")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--herd-curve", action="store_true",
                    help="print per-day COW/SHEEP/GOOSE over ALL replays (parallel)")
    ap.add_argument("--animal-rev", action="store_true",
                    help="print animal-product units/revenue/avg_price per game")
    args = ap.parse_args()
    dsm = _dsm_dir(args.dsm_dir)

    if args.animal_rev:
        want = ("ours", "dsm") if args.compare else (args.profile,)
        if "ours" in want:
            n = len(sorted(globmod.glob(f"{args.run_dir}/*_vs_*.json"))) or 1
            q, rev = _animal_rev_csv(f"{args.run_dir}/days_seed*.csv", "old")
            print_animal_rev(f"ours[{args.run_dir}]", q, rev, max(1, n // 2))
        if "dsm" in want:
            games, _herd, pq, prev = _replay_stats(
                sorted(globmod.glob(f"{dsm}/*.json")), _dsm_seat, args.max_games)
            print_animal_rev("dsm (replay sell proxy)", pq, prev, max(1, games))
        return

    if args.herd_curve:
        want = ("ours", "dsm") if args.compare else (args.profile,)
        if "ours" in want:
            n, acc = herd_curve(f"{args.run_dir}/*_vs_*.json", "ours", args.workers)
            print_herd_curve(f"ours[{args.run_dir}]", n, acc)
        if "dsm" in want:
            n, acc = herd_curve(f"{dsm}/*.json", "dsm", args.workers)
            print_herd_curve("dsm", n, acc)
        return

    profiles = []
    want = ("ours", "dsm") if args.compare else (args.profile,)
    if "ours" in want:
        profiles.append(profile(
            f"ours[{args.run_dir}]",
            f"{args.run_dir}/days_seed*.csv", f"{args.run_dir}/*_vs_*.json",
            "old", lambda rep: 1, args.max_games))
    if "dsm" in want:
        profiles.append(profile(
            "dsm", f"{dsm}/days_seed*.csv", f"{dsm}/*.json",
            "DSM", _dsm_seat, args.max_games))
    for p in profiles:
        print_profile(p)


if __name__ == "__main__":
    main()
