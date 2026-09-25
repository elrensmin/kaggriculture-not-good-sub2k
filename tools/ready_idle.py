"""tools/ready_idle.py — W3 trace: idle-on-ready and locked-tile turns, DSM vs ours.

W3 has two position-safe defects:

  (a) `idle_units_ready_total` — a unit PASSes while STANDING on a tile that has
      work it could do without moving: a crop/animal with `yield_units > 0`
      (HARVEST) or an animal with `fertilizer_available` (COLLECT_FERTILIZER).
  (b) `locked_steps` — a unit turn spent standing on, or routed across, a tile we
      do not own ("LOCKED"), where every tile op is a silent no-op.

This walks both arms step by step and reports, per arm:

  * passes-on-ready split by kind (crop harvest / animal harvest / fertilizer),
    with the units that could have been collected and their value at the step's
    own price
  * a per-day table of the same, so you can see WHEN it happens
  * passes-on-ready keyed by the product being left, so you know WHAT is wasted
  * LOCKED turns per day, and how many units are parked on locked land at the bell
  * a side-by-side summary line for ours vs DSM

Reads replay JSONs (the tile state is only in the observation), so it is slower
than the CSV tools; cap it with --max-games / --dsm-max.

Usage:
  PYTHONPATH=src:. python -m tools.ready_idle --dir diag-replays/w1-final \
      --dsm-dir replays/DSM/v1 --dsm-max 40 --out docs/w3/ready_idle.txt
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

PRODUCT_OF_ANIMAL = {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}


def _seat(rep, which):
    names = (rep.get("info") or {}).get("TeamNames") or []
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i if which == "dsm" else 1 - i
    return 1


def _one(arg):
    path, which = arg
    try:
        rep = json.load(open(path))
    except Exception:  # noqa: BLE001
        return None
    seat = _seat(rep, which)
    out = {"ready": Counter(), "ready_units": Counter(), "ready_val": Counter(),
           "by_day": defaultdict(Counter), "locked_day": Counter(),
           "locked_at_bell": 0, "unit_turns": 0, "pass_turns": 0, "games": 1}
    steps = rep["steps"]
    for t, frame in enumerate(steps):
        if len(frame) <= seat:
            continue
        obs = frame[seat].get("observation")
        act = frame[seat].get("action") or {}
        if not obs:
            continue
        day = t // 24
        farm = obs["farms"][seat]
        tiles = farm["tiles"]
        prices = (obs.get("market") or {}).get("prices") or {}
        positions = [tuple(farm["farmer"])] + [tuple(p) for p in farm["hands"]]
        units = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
        for i, cmd in enumerate(units):
            if i >= len(positions):
                break
            x, y = positions[i]
            if not (0 <= y < len(tiles) and 0 <= x < len(tiles[y])):
                continue
            tile = tiles[y][x]
            out["unit_turns"] += 1
            if tile == "LOCKED":
                out["locked_day"][day] += 1
                if t == len(steps) - 1:
                    out["locked_at_bell"] += 1
                continue
            if not (isinstance(cmd, list) and cmd and cmd[0] == "PASS"):
                continue
            out["pass_turns"] += 1
            if not isinstance(tile, dict):
                continue
            kind = None
            item = None
            n = 0
            if tile.get("yield_units", 0) > 0:
                if tile.get("kind") == "PLANT":
                    kind, item = "crop", tile.get("crop")
                elif tile.get("animal"):
                    kind, item = "animal", PRODUCT_OF_ANIMAL.get(tile["animal"])
                n = int(tile.get("yield_units", 0))
            elif tile.get("fertilizer_available"):
                kind, item, n = "fert", "FERTILIZER", 1
            if kind is None:
                continue
            out["ready"][kind] += 1
            out["ready_units"][item] += n
            out["ready_val"][item] += n * float(prices.get(item, 0) or 0)
            out["by_day"][day][kind] += 1
    return out


def _run(paths, which, workers):
    tasks = [(p, which) for p in paths]
    workers = workers or min(len(tasks), os.cpu_count() or 4)
    agg = {"ready": Counter(), "ready_units": Counter(), "ready_val": Counter(),
           "by_day": defaultdict(Counter), "locked_day": Counter(),
           "locked_at_bell": 0, "unit_turns": 0, "pass_turns": 0, "games": 0}
    if not tasks:
        return agg
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        for r in ex.map(_one, tasks):
            if not r:
                continue
            agg["games"] += 1
            agg["ready"] += r["ready"]
            agg["ready_units"] += r["ready_units"]
            agg["ready_val"] += r["ready_val"]
            agg["locked_day"] += r["locked_day"]
            agg["locked_at_bell"] += r["locked_at_bell"]
            agg["unit_turns"] += r["unit_turns"]
            agg["pass_turns"] += r["pass_turns"]
            for d, c in r["by_day"].items():
                agg["by_day"][d] += c
    return agg


def _dump(name, a, out):
    g = max(1, a["games"])
    ready = sum(a["ready"].values())
    out.append(f"\n############ {name}  (games={a['games']}) ############")
    out.append(f"  unit-turns {a['unit_turns']:,}   PASS {a['pass_turns']:,} "
               f"({100*a['pass_turns']/max(1,a['unit_turns']):.1f}%)")
    out.append(f"  PASS-on-READY events {ready:,}  ({ready/g:.1f}/game)   "
               f"locked turns {sum(a['locked_day'].values()):,} "
               f"({sum(a['locked_day'].values())/g:.1f}/game)   "
               f"parked on locked at bell {a['locked_at_bell']}")
    out.append("  -- by kind --")
    for k in ("crop", "animal", "fert"):
        n = a["ready"].get(k, 0)
        out.append(f"     {k:<8}{n:>8,}  ({n/g:.1f}/game)")
    out.append("  -- units left on the tile, and their value at the step price --")
    for item, n in a["ready_units"].most_common():
        out.append(f"     {item:<11}{n:>8,}u  (${a['ready_val'][item]:>10,.0f})")
    out.append("  -- PASS-on-READY by day --")
    days = sorted(a["by_day"])
    if days:
        out.append("     day:  " + "".join(f"{d:>5}" for d in days))
        out.append("     crop: " + "".join(f"{a['by_day'][d].get('crop',0):>5}" for d in days))
        out.append("     anim: " + "".join(f"{a['by_day'][d].get('animal',0):>5}" for d in days))
        out.append("     fert: " + "".join(f"{a['by_day'][d].get('fert',0):>5}" for d in days))
    out.append("  -- LOCKED turns by day (d6-29) --")
    lk = [a["locked_day"].get(d, 0) for d in range(6, 30)]
    out.append("     day:  " + "".join(f"{d:>5}" for d in range(6, 30)))
    out.append("     n:    " + "".join(f"{v:>5}" for v in lk))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="our run dir")
    ap.add_argument("--dsm-dir", default=None)
    ap.add_argument("--dsm-max", type=int, default=40)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ours = sorted(glob.glob(os.path.join(args.dir, "*_vs_*.json")))
    a = _run(ours, "ours", args.workers)
    dsm_dir = args.dsm_dir
    if dsm_dir is None:
        for cand in ("replays/DSM/v1", "replays/DSM"):
            if glob.glob(f"{cand}/*.json"):
                dsm_dir = cand
                break
    dsm = sorted(glob.glob(os.path.join(dsm_dir or "replays/DSM", "*.json")))[:args.dsm_max]
    b = _run(dsm, "dsm", args.workers)

    out = []
    out.append("ready_idle — W3 trace: PASS-on-ready tiles and LOCKED-tile turns")
    out.append(f"ours: {args.dir}  ({a['games']} games)")
    out.append(f"dsm : {dsm_dir}  ({b['games']} games, capped at {args.dsm_max})")
    _dump("ours", a, out)
    _dump("dsm", b, out)
    out.append("\n############ SIDE BY SIDE (per game) ############")
    go, gd = max(1, a["games"]), max(1, b["games"])
    rows = [
        ("unit-turns", a["unit_turns"] / go, b["unit_turns"] / gd),
        ("PASS share %", 100 * a["pass_turns"] / max(1, a["unit_turns"]),
         100 * b["pass_turns"] / max(1, b["unit_turns"])),
        ("PASS-on-READY", sum(a["ready"].values()) / go, sum(b["ready"].values()) / gd),
        ("  ...crop", a["ready"].get("crop", 0) / go, b["ready"].get("crop", 0) / gd),
        ("  ...animal", a["ready"].get("animal", 0) / go, b["ready"].get("animal", 0) / gd),
        ("  ...fert", a["ready"].get("fert", 0) / go, b["ready"].get("fert", 0) / gd),
        ("units left on tile", sum(a["ready_units"].values()) / go,
         sum(b["ready_units"].values()) / gd),
        ("value left ($)", sum(a["ready_val"].values()) / go, sum(b["ready_val"].values()) / gd),
        ("LOCKED turns", sum(a["locked_day"].values()) / go, sum(b["locked_day"].values()) / gd),
        ("parked on locked at bell", a["locked_at_bell"] / go, b["locked_at_bell"] / gd),
    ]
    out.append(f"   {'metric':<26}{'ours':>12}{'dsm':>12}{'gap':>12}")
    for label, x, y in rows:
        out.append(f"   {label:<26}{x:>12,.1f}{y:>12,.1f}{x-y:>+12,.1f}")
    text = "\n".join(out)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
