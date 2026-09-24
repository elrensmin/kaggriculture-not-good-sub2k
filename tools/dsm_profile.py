#!/usr/bin/env python
"""dsm_profile — full behavioural map of the top player (DSM) vs us, for cloning.

Covers the modalities that matter, from the DSM replays + day CSVs:
  * herd        COW/SHEEP/GOOSE per day (endgame + curve)
  * structures  COOP/PASTURE counts per day, coop build days, land buys
  * shed        max/end shed pressure per day
  * lifecycle   weeds, plants_fertilized, plants_watered, animals_fed/cared, discs
  * selling     per product: units, price-at-sell, share at the $1 floor, below base
  * labour      unit-op mix (WATER/HARVEST/FEED/CARE/FERTILIZE/...), idle share

Usage:
  PYTHONPATH=src:. python -m tools.dsm_profile --compare
  PYTHONPATH=src:. python -m tools.dsm_profile --profile dsm
"""
from __future__ import annotations

import argparse
import csv
import glob as globmod
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import diagnose

SELL_PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
STRUCT = ("max_shed_total", "end_shed_total", "weeds_max", "plants_fertilized",
          "plants_watered", "animals_fed", "animals_cared", "discarded_units",
          "hires", "idle_share_pct")


def _seat_dsm(rep):
    names = (rep.get("info") or {}).get("TeamNames") or ["", ""]
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i
    steps = rep["steps"]
    for i in range(len(steps) - 1, -1, -1):
        si = steps[i]
        if len(si) > 1:
            try:
                return 0 if si[0]["observation"]["farms"][0]["money"] > si[1]["observation"]["farms"][1]["money"] else 1
            except (KeyError, TypeError):
                pass
    return 1


def _one(arg):
    path, which = arg
    try:
        rep = diagnose.load_replay(Path(path))
    except Exception:  # noqa: BLE001
        return None
    seat = _seat_dsm(rep) if which == "dsm" else 1
    steps = rep["steps"]
    out = {"days": {}, "ops": Counter(), "sell": {},
           "coop_day": Counter(), "land_day": Counter(), "pasture_end": 0, "coop_end": 0}
    seen = set()
    for i in range(len(steps)):
        si = steps[i]
        if len(si) <= seat:
            continue
        obs = si[seat].get("observation")
        act = si[seat].get("action")
        if not obs:
            continue
        d = i // 24
        if d not in seen:
            seen.add(d)
            farm = obs["farms"][seat]
            c = s = g = pa = co = 0
            for row in farm["tiles"]:
                for t in row:
                    if isinstance(t, dict):
                        a = t.get("animal")
                        if a == "COW": c += 1
                        elif a == "SHEEP": s += 1
                        elif a == "GOOSE": g += 1
                        if t.get("kind") == "PASTURE": pa += 1
                        elif t.get("kind") == "COOP": co += 1
            out["days"][d] = (c, s, g, pa, co)
            out["pasture_end"] = pa
            out["coop_end"] = co
        if not act:
            continue
        prices = (obs.get("market") or {}).get("prices") or {}
        cmds = [act.get("farmer") or []] + list(act.get("hands") or [])
        for cmd in cmds:
            if cmd:
                out["ops"][cmd[0]] += 1
                if cmd[0] == "BUILD_COOP":
                    out["coop_day"][d] += 1
        for o in (act.get("market") or []):
            if not o:
                continue
            if o[0] == "BUY_LAND":
                out["land_day"][d] += 1
            elif o[0] == "SELL" and len(o) >= 3 and o[1] in SELL_PRODUCTS:
                q = int(o[2]); p = float(prices.get(o[1], 0) or 0)
                cell = out["sell"].setdefault(o[1], [0, 0.0, 0])
                cell[0] += q; cell[1] += q * p
                if p <= 1:
                    cell[2] += q
    return out


def _days_csv(days_glob, agent):
    acc = defaultdict(lambda: defaultdict(list))
    for f in sorted(globmod.glob(days_glob)):
        for r in csv.DictReader(open(f)):
            if agent and r.get("agent") != agent:
                continue
            try:
                d = int(r["day"])
            except (KeyError, ValueError):
                continue
            for col in STRUCT:
                try:
                    acc[d][col].append(float(r.get(col) or 0))
                except ValueError:
                    pass
    return {d: {c: (sum(v) / len(v) if v else 0.0) for c, v in cols.items()} for d, cols in acc.items()}


def profile(name, replay_glob, days_glob, agent, workers=0):
    paths = sorted(globmod.glob(replay_glob))
    agg = {"days": defaultdict(list), "ops": Counter(), "sell": {},
           "coop_day": Counter(), "land_day": Counter(), "games": 0}
    tasks = [(p, name) for p in paths]
    if workers == 0:
        workers = os.cpu_count() or 1
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_one, tasks):
            if not r:
                continue
            agg["games"] += 1
            for d, rec in r["days"].items():
                agg["days"][d].append(rec)
            agg["ops"] += r["ops"]
            for k, v in r["sell"].items():
                cell = agg["sell"].setdefault(k, [0, 0.0, 0])
                cell[0] += v[0]; cell[1] += v[1]; cell[2] += v[2]
            agg["coop_day"] += r["coop_day"]; agg["land_day"] += r["land_day"]
    return {"name": name, "agg": agg, "days_csv": _days_csv(days_glob, agent)}


def show(p):
    a = p["agg"]; g = max(1, a["games"])
    print(f"\n############ {p['name']}  (replay games={a['games']}) ############")
    print("-- structures per game (endgame mean) --")
    ce = sum(r[4] for v in a["days"].values() for r in v) / max(1, sum(len(v) for v in a["days"].values()))
    pe = sum(r[3] for v in a["days"].values() for r in v) / max(1, sum(len(v) for v in a["days"].values()))
    print(f"   COOP~{ce:.1f}  PASTURE~{pe:.1f}")
    print("-- herd per game (day10 / day16 / day29 mean COW/SHEEP/GOOSE) --")
    for d in (10, 16, 29):
        v = a["days"].get(d, [])
        if v:
            print(f"   d{d}: {sum(r[0] for r in v)/len(v):.1f}/{sum(r[1] for r in v)/len(v):.1f}/{sum(r[2] for r in v)/len(v):.1f}")
    print("-- coop builds / land buys by day --")
    print("   coop:", dict(sorted(a["coop_day"].items())))
    print("   land:", dict(sorted(a["land_day"].items())))
    print("-- unit op mix (share) --")
    tot = sum(a["ops"].values()) or 1
    print("   " + "  ".join(f"{k}={100*v/tot:.0f}%" for k, v in a["ops"].most_common(12)))
    print("-- selling (per game): units / avg_price_at_sell / %at$1 floor --")
    for prod in SELL_PRODUCTS:
        q, rev, fl = a["sell"].get(prod, (0, 0.0, 0))
        if q:
            print(f"   {prod:11s} {q/g:7.1f}u  {rev/q:7.1f}  {100*fl/q:5.1f}%")
    print("-- structural per day (day CSV means) --")
    dc = p["days_csv"]
    print("   day | shed_max shed_end weeds fert watered fed_cared disc idle%")
    for d in range(6, 30, 3):
        c = dc.get(d)
        if not c:
            continue
        print(f"   {d:3d} | {c.get('max_shed_total',0):8.1f} {c.get('end_shed_total',0):8.1f} "
              f"{c.get('weeds_max',0):5.2f} {c.get('plants_fertilized',0):5.1f} "
              f"{c.get('plants_watered',0):6.1f} {c.get('animals_fed',0):5.1f}/{c.get('animals_cared',0):5.1f} "
              f"{c.get('discarded_units',0):5.1f} {c.get('idle_share_pct',0):5.2f}")


def _dsm_dir():
    """DSM replays may live directly in replays/DSM or in a versioned subdir."""
    for cand in ("replays/DSM/v1", "replays/DSM"):
        if globmod.glob(f"{cand}/*.json"):
            return cand
    return "replays/DSM"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=("ours", "dsm"), default="dsm")
    ap.add_argument("--run-dir", default="diag-replays/run-5")
    ap.add_argument("--dsm-dir", default=None, help="DSM replay dir (default: replays/DSM/v1 if present)")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    want = ("ours", "dsm") if args.compare else (args.profile,)
    profs = []
    if "ours" in want:
        profs.append(profile("ours", f"{args.run_dir}/*_vs_*.json", f"{args.run_dir}/days_seed*.csv", "old", args.workers))
    if "dsm" in want:
        d = args.dsm_dir or _dsm_dir()
        profs.append(profile("dsm", f"{d}/*.json", f"{d}/days_seed*.csv", "DSM", args.workers))
    for p in profs:
        show(p)


if __name__ == "__main__":
    main()
