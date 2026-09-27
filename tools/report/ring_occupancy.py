#!/usr/bin/env python
"""ring_occupancy — who claims the shed ring, the animals or the crops?

Why this exists
---------------
§3.6 found the herd's failure mode is not per-animal management (care capture and escapes are
better than the #1's) but the **cost of servicing it**: his animals cost **1.12 moves/op** and ours
**2.25**, and he builds PASTUREs *on* the four shed-access tiles `(4,4),(5,4),(4,5),(5,5)` and
still `DROP`s there. An animal that occupies the ring is fed, cared, collected and delivered to
from one or two steps; an animal out in the field costs a round trip per op.

So the question this answers, per game: **is the ring taken by animals before the crops take it?**

Board bands are Chebyshev rings around the shed centre `(4.5, 4.5)`:
band 0 = the 4 shed-access tiles, band 1 = the 12 tiles around them, ... band 5 = the board edge.
For each band it reports animal / plant / empty counts, the *first day* each band saw an animal or
a plant, and the share of all animals sitting in bands 0-2.

Reads replays directly (no cache) and runs the identical scanner on our own agent, so his 30
episodes and our 24 games are directly comparable.

Usage
-----
  PYTHONPATH=. python -m tools.report.ring_occupancy --dir replays/DSM/v1 --max 30
  PYTHONPATH=. python -m tools.report.ring_occupancy --agent --pa 1-12 --batch 2
  PYTHONPATH=. python -m tools.report.ring_occupancy --dir replays/DSM/v1 --max 4 --daily
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
import collections
import glob
import json
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor

TURNS = 24
SHED_C = (4.5, 4.5)


def band_of(x, y):
    return int(max(abs(x - SHED_C[0]), abs(y - SHED_C[1])) - 0.5)


def _dsm_seats(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    return team_mod.seats_of_names(names) or [0]


def scan_steps(steps, seat):
    """Returns (per_game, per_day).

    per_game: band -> {animals, plants, empty, other} day-17 and day-29 snapshots,
              first_animal_day / first_plant_day per band, animal band share.
    """
    snap = {17: collections.defaultdict(collections.Counter),
            29: collections.defaultdict(collections.Counter)}
    first = collections.defaultdict(dict)          # band -> {'A'|'P': first day}
    per_day = collections.defaultdict(collections.Counter)
    seen_bands = set()
    for t in range(len(steps)):
        if len(steps[t]) <= seat:
            continue
        o = steps[t][seat].get("observation")
        if not o:
            continue
        day = t // TURNS
        tiles = o["farms"][seat]["tiles"]
        for y, row in enumerate(tiles):
            for x, cell in enumerate(row):
                b = band_of(x, y)
                seen_bands.add(b)
                if isinstance(cell, dict):
                    k = cell.get("kind")
                    if "animal" in cell:
                        kind = "animals"
                        first[b].setdefault("A", day)
                    elif k == "PLANT":
                        kind = "plants"
                        first[b].setdefault("P", day)
                    elif k in ("COOP", "PASTURE"):
                        kind = "structures"
                    else:
                        kind = "other"
                elif cell is None:
                    kind = "empty"
                else:
                    kind = "other"
                if day in snap:
                    snap[day][b][kind] += 1
                if day <= 29:
                    per_day[day][f"{kind}_b{b}"] += 1
    # animal band share at d29
    tot_an = sum(snap[29][b]["animals"] for b in snap[29])
    per_game = {
        "bands": sorted(seen_bands),
        "snap": {d: {b: dict(c) for b, c in snap[d].items()} for d in snap},
        "first_animal_band": {b: first[b].get("A") for b in first},
        "first_plant_band": {b: first[b].get("P") for b in first},
        "animals_in_ring29": sum(snap[29][b]["animals"] for b in (0, 1, 2)),
        "animals_total29": tot_an,
    }
    return per_game, {str(k): dict(v) for k, v in per_day.items()}


def scan_replay(path, seat=None):
    rep = json.load(open(path))
    if seat is None:
        seat = _dsm_seats(rep)[0]
    g, pd_ = scan_steps(rep["steps"], seat)
    g["_file"] = os.path.basename(path)
    return {"g": g, "per_day": pd_}


def _work(path, seat):
    try:
        return scan_replay(path, seat)
    except Exception as e:                                    # pragma: no cover
        return {"g": {"_file": os.path.basename(path), "_error": repr(e)}, "per_day": {}}


def report(games, label):
    gs = [x["g"] for x in games if "_error" not in x["g"]]
    if not gs:
        print(f"\n  {label}: no usable games")
        return
    bands = sorted({b for g in gs for b in g["bands"]})
    print(f"\n{'='*94}\n  {label}   ({len(gs)} games)\n{'='*94}")
    for day in (17, 29):
        print(f"\n  --- board composition at day {day} (mean tiles per game) ---")
        print(f"  {'band':>5} {'tiles':>7} {'animals':>9} {'plants':>8} {'struct':>8} "
              f"{'empty':>7} {'animal%':>9}")
        for b in bands:
            n = st.median([sum(g['snap'].get(day, {}).get(b, {}).values()) for g in gs])
            a = st.median([g['snap'].get(day, {}).get(b, {}).get('animals', 0) for g in gs])
            p = st.median([g['snap'].get(day, {}).get(b, {}).get('plants', 0) for g in gs])
            s_ = st.median([g['snap'].get(day, {}).get(b, {}).get('structures', 0) for g in gs])
            e = st.median([g['snap'].get(day, {}).get(b, {}).get('empty', 0) for g in gs])
            print(f"  {b:>5} {n:>7.0f} {a:>9.1f} {p:>8.1f} {s_:>8.1f} {e:>7.1f} "
                  f"{(a/n if n else 0):>8.0%}")
    print(f"\n  --- claim order (median first day a band sees one) ---")
    print(f"  {'band':>5} {'first ANIMAL':>14} {'first PLANT':>13}")
    for b in bands:
        fa = [g["first_animal_band"].get(b) for g in gs if g["first_animal_band"].get(b) is not None]
        fp = [g["first_plant_band"].get(b) for g in gs if g["first_plant_band"].get(b) is not None]
        print(f"  {b:>5} {(st.median(fa) if fa else float('nan')):>14.0f} "
              f"{(st.median(fp) if fp else float('nan')):>13.0f}")
    ring = st.median([g["animals_in_ring29"] for g in gs])
    tot = st.median([g["animals_total29"] for g in gs])
    print(f"\n  animals at d29: ring(0-2) {ring:.1f} / total {tot:.1f} "
          f"= {(ring/tot if tot else 0):.0%} of the herd inside radius 2")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="replays/DSM/v1")
    ap.add_argument("--seat", type=int, default=None)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--agent", action="store_true")
    ap.add_argument("--pa", default="1-12")
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--label", default=None)
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    a = ap.parse_args()
    team_mod.set_team(a.team)

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
                g, pd_ = scan_steps(steps, 1)
                g["_file"] = f"pa{opp}_s{s}"
                games.append({"g": g, "per_day": pd_})
        report(games, a.label or f"US (agents {a.pa} x {a.batch})")
        return

    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))
    if a.max:
        files = files[:a.max]
    if not files:
        print(f"no replays in {a.dir}")
        return
    with ProcessPoolExecutor(max_workers=a.workers or None) as ex:
        games = list(ex.map(_work, files, [a.seat] * len(files)))
    report(games, a.label or f"{a.dir} (seat auto)")
    if a.daily:
        g = next((x for x in games if x["per_day"]), None)
        if g:
            print(f"\n  --- per-day ring(0-2) occupancy, {g['g'].get('_file')} ---")
            print(f"  {'day':>3} {'anim':>6} {'plant':>6} {'empty':>6} {'animal%':>8}")
            for d in sorted(g["per_day"], key=int):
                c = g["per_day"][d]
                an = sum(c.get(f"animals_b{b}", 0) for b in (0, 1, 2))
                pl = sum(c.get(f"plants_b{b}", 0) for b in (0, 1, 2))
                em = sum(c.get(f"empty_b{b}", 0) for b in (0, 1, 2))
                n = an + pl + em
                print(f"  {d:>3} {an:>6} {pl:>6} {em:>6} {(an/n if n else 0):>7.0%}")


if __name__ == "__main__":
    main()
