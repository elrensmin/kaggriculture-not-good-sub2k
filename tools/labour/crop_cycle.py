#!/usr/bin/env python
"""crop_cycle — per-crop tile agronomy: cycle, harvest age, yield, and FERTILIZATION.

Why this exists
---------------
`wheat_cycle` answers "how fast does a wheat tile turn over and what does it yield", and
`phase_map` prints `FERTILIZE ops 0 vs N` as a stock/flow node. Neither JOINS the two, and
that is exactly how the midgame root stayed invisible: the phase tool named the 0-vs-64
gap, but the params carried a measured note ("never fertilizing is +$2,294"), so it was
read as a portfolio choice. MEASURED on the reference (replays/Boey/v1, d6-17, 40 games):

    ours : wheat yield 2.93 units, harvest age 4.0, cycle 5.0 d, FERTILIZE 0 ops
    Boey : wheat yield 4.41 units, harvest age 3.3, cycle 4.0 d, FERTILIZE 41.5 wheat ops

The engine pays `+2` instead of `+1` on a water in the window when the tile is fertilized
(`fertilized_until_day >= day`), and the water bonus is once-per-day (`watered_today`). So
a fertilized wheat tile peaks at 5 on age 3 and 6 on age 4; an unfertilized one at 3 and 4.
Boey fertilizes roughly every wheat cycle and harvests at age 3 — **1.10 units/tile-day**
(`yield / (age + replant gap)`) against our **0.59**.

`cycle` is reported as **age + replant gap**, never from plant->plant action alignment: the
measured ~8% action<->position mismatch makes the raw plant cycle read *below* the harvest
age (impossible), so it is not trustworthy. Age comes off the tile's own `planted_day` and
is alignment-free.

This tool exists so that finding is one command, and so the next agronomy gap is too. It
reports, per crop and per seat: harvest count, harvest-age and yield distributions, the
share of harvests that were fertilized, the plant->plant cycle, the harvest->replant gap,
water-days per cycle, missed bonus-window days, and the implied units/tile-day. It also
charges MOVE turns to the act that preceded them, so `FERTILIZE` *moves/op* (our measured
4.35 against the reference's 0.10) is visible beside the yield it buys.

Pairing follows `wheat_cycle` (and the AGENTS.md note): the action decided from
`steps[t]["observation"]` lives at `steps[t+1]["action"]`, positions come from the same
observation's farm, and `HARVEST` carries no crop argument — the crop is read off the tile.

Usage
-----
  PYTHONPATH=. python -m tools.labour.crop_cycle --days 6-17 --dir diag-replays/arm \\
      --ref-from replays/Boey/v1 --ref-max 40 --team Boey
  PYTHONPATH=. python -m tools.labour.crop_cycle --days 6-17 --dir /tmp/arm --seat 1
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import json
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS   # noqa: E402

from tools import team as team_mod                                         # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days          # noqa: E402

DAY = 24
MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
ACTS = ("PLANT", "WATER", "HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER", "FERTILIZE",
        "DIG", "BUILD_COOP", "BUILD_PASTURE", "PICKUP", "DROP", "PLACE")


def _med(v):
    return statistics.median(v) if v else float("nan")


def _mean(v):
    return statistics.mean(v) if v else float("nan")


def _window_days(crop, plant_day, harvest_day):
    """Bonus-window days for a one-shot crop, clipped to the cycle; None if ongoing."""
    cd = CROPS[crop]
    if cd.get("ongoing"):
        return None
    start = (cd["max_yield_day"] + 1) // 2
    end = cd["max_yield_day"]
    return [d for d in range(plant_day + start, plant_day + end + 1) if d <= harvest_day]


def run_game(rep, seat, window):
    """Return (per-crop agronomy, move-cost-by-act) for one replay/seat."""
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    per = collections.defaultdict(lambda: {
        "harv": [], "yields": [], "ages": [], "fert": [], "cycles": [], "gaps": [],
        "water_days": [], "missed": [], "fert_ops": 0, "water_ops": 0,
    })
    tile_open = {}        # pos -> {crop, day, watered:set, fert:set, water_ops, fert_ops}
    last_harvest = {}     # pos -> (day, crop)
    last_act = collections.defaultdict(str)
    move_cost = collections.defaultdict(lambda: {"ops": 0, "moves": 0})

    def _tile(farm, x, y):
        rows = farm.get("tiles") or []
        if 0 <= y < len(rows) and 0 <= x < len(rows[y]):
            return rows[y][x]
        return None

    for t in range(len(steps) - 1):
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        act = steps[t + 1][seat].get("action") or {}
        if not obs:
            continue
        day = t // DAY
        if not in_window(day, window):
            continue
        farm = obs["farms"][seat]
        pos = [tuple(farm["farmer"])] + [tuple(p) for p in farm.get("hands") or []]
        cmds = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
        for ui, cmd in enumerate(cmds):
            if ui >= len(pos) or not cmd:
                continue
            op = str(cmd[0])
            x, y = pos[ui]
            p = pos[ui]
            tile = _tile(farm, x, y)
            if op in ACTS:
                move_cost[op]["ops"] += 1
                last_act[ui] = op
            elif op in MOVES:
                move_cost[last_act[ui] or "START"]["moves"] += 1

            if op == "PLANT" and len(cmd) > 1 and not (
                    isinstance(tile, dict) and tile.get("kind") == "PLANT"):
                crop = cmd[1]
                prev = tile_open.get(p)
                # A second PLANT on the same tile on the SAME day is a duplicate request
                # (the engine silently rejects it); it must not reset the cycle to 0 or
                # invent a plant->plant cycle of 0 days.
                if prev and day == prev["day"]:
                    continue
                if prev:                       # plant -> plant cycle on this tile
                    per[prev["crop"]]["cycles"].append(day - prev["day"])
                lh = last_harvest.pop(p, None)
                if lh and day > lh[0]:         # harvest -> replant gap
                    per[lh[1]]["gaps"].append(day - lh[0])
                tile_open[p] = {"crop": crop, "day": day, "watered": set(),
                                "fert": set(), "water_ops": 0, "fert_ops": 0}
            elif op == "WATER" and p in tile_open:
                c = tile_open[p]
                c["watered"].add(day)
                c["water_ops"] += 1
            elif op == "FERTILIZE" and p in tile_open:
                c = tile_open[p]
                c["fert"].add(day)
                c["fert_ops"] += 1
            elif op == "HARVEST":
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop = tile["crop"]
                    c = tile_open.pop(p, None)
                    h = per[crop]
                    h["harv"].append(day)
                    h["yields"].append(int(tile.get("yield_units", 0)))
                    h["ages"].append(day - tile["planted_day"])
                    h["fert"].append(tile.get("fertilized_until_day", -1) >= day)
                    if c:
                        h["fert_ops"] += c["fert_ops"]
                        h["water_ops"] += c["water_ops"]
                        wd = _window_days(crop, c["day"], day)
                        if wd:
                            h["water_days"].append(len(c["watered"] & set(wd)))
                            h["missed"].append(len(set(wd) - c["watered"]))
                        else:
                            h["water_days"].append(len(c["watered"]))
                    last_harvest[p] = (day, crop)
    return per, move_cost


def report(label, dirpath, seat_mode, max_games, window, glob="*.json"):
    agg = collections.defaultdict(lambda: collections.defaultdict(list))
    agg_ops = collections.defaultdict(int)
    agg_moves = collections.defaultdict(int)
    games = 0
    for path in sorted(globmod.glob(str(Path(dirpath) / glob)))[:max_games]:
        try:
            rep = json.load(open(path))
        except Exception:
            continue
        steps = rep["steps"] if isinstance(rep, dict) else rep.steps
        if not steps or len(steps[0]) < 2:
            continue
        seat = (team_mod.seat_of_names((rep.get("info") or {}).get("TeamNames") or [],
                                       fallback=0)
                if seat_mode == "auto" else int(seat_mode))
        try:
            per, move_cost = run_game(rep, seat, window)
        except Exception:
            continue
        for crop, h in per.items():
            for k, v in h.items():
                agg[crop][k].extend(v if isinstance(v, list) else [v])
        for op, c in move_cost.items():
            agg_ops[op] += c["ops"]
            agg_moves[op] += c["moves"]
        games += 1

    if not games:
        print(f"### {label}: nothing")
        return {}

    print(f"\n############ {label}  ({games} games, {describe(window)}) ############")
    print(f"   {'crop':<11}{'harv':>6}{'age':>6}{'yield':>7}{'fert%':>7}"
          f"{'gap':>6}{'water/cyc':>10}{'missed':>7}{'u/tile-day':>11}")
    for crop in sorted(agg, key=lambda c: -len(agg[c]["harv"])):
        h = agg[crop]
        n = len(h["harv"])
        if not n:
            continue
        yld = _mean(h["yields"])
        # `cycle` from the agent's PLANT ops is corrupted by the measured ~8%
        # action<->position misalignment (it can read BELOW the harvest age, which is
        # impossible). Use age + replant gap: age is read off the tile's own
        # `planted_day`, so it is alignment-free, and the gap is the one action-derived
        # term -- both come out stable here (1.0 for both arms).
        age, gap = _med(h["ages"]), _med(h["gaps"])
        cycle = age + gap if age == age and gap == gap else float("nan")
        utd = yld / cycle if cycle == cycle and cycle else float("nan")
        print(f"   {crop:<11}{n:>6}{age:>6.1f}{yld:>7.2f}"
              f"{100 * sum(1 for f in h['fert'] if f) / n:>6.0f}%{gap:>6.1f}"
              f"{_mean(h['water_days']):>10.2f}"
              f"{(_mean(h['missed']) if h['missed'] else float('nan')):>7.2f}{utd:>11.3f}")

    print(f"\n   -- yield distribution (units: count), split by fertilization at harvest --")
    for crop in sorted(agg, key=lambda c: -len(agg[c]["harv"])):
        h = agg[crop]
        if not h["yields"]:
            continue
        print(f"   {crop:<11}{dict(sorted(collections.Counter(h['yields']).items()))}")
        print(f"   {'':<11}fert mean {_mean([y for y, f in zip(h['yields'], h['fert']) if f]):.2f}"
              f" (n={sum(1 for f in h['fert'] if f)})"
              f"   unfert mean {_mean([y for y, f in zip(h['yields'], h['fert']) if not f]):.2f}"
              f" (n={sum(1 for f in h['fert'] if not f)})"
              f"   FERTILIZE ops {sum(h['fert_ops'])}")

    print(f"\n   -- moves charged to the act that preceded them --")
    print(f"   {'after act':<22}{'ops':>7}{'moves':>8}{'mv/op':>8}")
    for op in sorted(agg_ops, key=lambda o: -agg_moves[o]):
        o, m = agg_ops[op], agg_moves[op]
        if o == 0 and m == 0:
            continue
        print(f"   {op:<22}{o:>7}{m:>8}{(m / o if o else float('nan')):>8.2f}")
    return agg


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", default="6-17")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--seat", default="1")
    ap.add_argument("--max-games", type=int, default=8)
    ap.add_argument("--ref-from", default=None)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--ref-max", type=int, default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--team", default=None,
                    help="leaderboard arm to resolve seats for (default: DSM/$KAGG_OPPONENT)")
    a = ap.parse_args(argv)
    team_mod.set_team(a.team)
    window = parse_days(a.days)
    report(a.label or Path(a.dir).name, a.dir, a.seat, a.max_games, window, a.glob)
    if a.ref_from:
        report(Path(a.ref_from).name, a.ref_from, a.ref_seat,
               a.ref_max or a.max_games, window, a.glob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
