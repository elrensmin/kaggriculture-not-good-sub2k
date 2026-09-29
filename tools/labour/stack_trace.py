#!/usr/bin/env python
"""stack_trace — tile-day completion: does a visit finish the tile, or split it?

Why this exists
---------------
`op_patterns` says our `FERTILIZE` is followed by another act 3.1 % of the time against the
reference's 93.3 %; `move_trace` prices it at 3.00 vs 0.02 moves/op. Neither says **which
op-pair gets split across separate visits**, which is the thing a fix has to join.

A **visit** is a maximal run of ops one unit performs on one tile on consecutive turns. A
**tile-day** is every op any unit performed on that tile that day. A tile-day whose ops all
fall in ONE visit is *finished*; otherwise it is *split*, and the split costs a walk in and
back out. This reports, per arm:

  * visits, tile-days, **extra trips** (`sum(visits per tile-day) - tile_days`), revisit %
  * **ops per visit** and the visit-length distribution
  * the **split-pair matrix**: for each tile-day with >=2 visits, the last op of visit N and
    the first op of visit N+1 (`WATER -> FERTILIZE` is the pair the kernel gate creates)

It also lists ops a unit was eligible for on the tile it was standing on and did not do, but
that table is near-universal (~100 % on BOTH arms) because a visit cannot always finish
everything -- read it as context, and the split-pair matrix as the signal. NOTE `HARVEST` in
that table uses the ENGINE's eligibility (yield > 0), not a policy's readiness rule, so it
over-counts; the split pairs are policy-free.

Pairing is the verified one: the action decided from `steps[t]["observation"]` lives at
`steps[t+1]["action"]`, and positions come from the same observation's farm.

Usage
-----
  PYTHONPATH=. python -m tools.labour.stack_trace --days 11-20 --dir /tmp/arm-ship --seat 1
  PYTHONPATH=. python -m tools.labour.stack_trace --days 11-20 --dir /tmp/arm-ship --seat 1 \
      --ref-from replays/Boey/v1 --ref-max 8 --team Boey
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

from tools import team as team_mod                                       # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days        # noqa: E402

DAY = 24
MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
OPS = ("WATER", "FERTILIZE", "FEED", "CARE", "COLLECT_FERTILIZER", "HARVEST", "DIG",
       "PLANT", "PICKUP", "DROP", "PLACE", "BUILD_COOP", "BUILD_PASTURE")


def _inv_at(obs, ui):
    priv = obs.get("private") or {}
    invs = priv.get("inventories")
    if isinstance(invs, list) and ui < len(invs):
        return {k: v for k, v in (invs[ui] or {}).items() if v > 0}
    return {}


def _eligible(op, tile, inv, day):
    if not isinstance(tile, dict):
        return False
    if op == "WATER":
        return tile.get("kind") == "PLANT" and not tile.get("watered_today")
    if op == "FERTILIZE":
        return (tile.get("kind") == "PLANT" and inv.get("FERTILIZER", 0) > 0
                and tile.get("fertilized_until_day", -1) < day)
    if op == "FEED":
        return "animal" in tile and inv.get("WHEAT", 0) > 0 and not tile.get("fed_today")
    if op == "CARE":
        return "animal" in tile and not tile.get("cared_today")
    if op == "COLLECT_FERTILIZER":
        return "animal" in tile and bool(tile.get("fertilizer_available"))
    if op == "HARVEST":
        if tile.get("kind") == "PLANT":
            cd = CROPS.get(tile.get("crop", ""))
            age = day - tile.get("planted_day", day)
            return bool(cd) and tile.get("yield_units", 0) > 0 and age >= cd["first_yield_day"]
        return "animal" in tile and tile.get("yield_units", 0) > 0
    if op == "DIG":
        return tile.get("kind") == "WEED"
    return False


def run_game(rep, seat, window, tag=0):
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    open_visit = {}
    tile_day_visits = collections.defaultdict(list)     # (day, tile) -> [ [op,...] ]
    abandoned = collections.Counter()
    next_after = collections.defaultdict(collections.Counter)
    eligible_seen = collections.Counter()

    def close(ui, cause):
        v = open_visit.pop(ui, None)
        if not v or not v["order"]:
            return
        tile_day_visits[(tag, v["day"], v["tile"])].append(list(v["order"]))
        for op in v["pending"]:
            eligible_seen[op] += 1
            if op not in v["ops"]:
                abandoned[op] += 1
                next_after[op][cause or "?"] += 1

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
        for ui, c in enumerate(cmds):
            if ui >= len(pos):
                continue
            op = str(c[0]) if c else "PASS"
            tile_pos = pos[ui]
            if op not in OPS:
                close(ui, "MOVE" if op in MOVES else op)
                continue
            x, y = tile_pos
            rows = farm.get("tiles") or []
            tile = rows[y][x] if 0 <= y < len(rows) and 0 <= x < len(rows[y]) else None
            inv = _inv_at(obs, ui)
            v = open_visit.get(ui)
            if (v and v["tile"] == tile_pos and v["last_t"] == t - 1 and v["day"] == day):
                v["last_t"] = t
                v["order"].append(op)
                v["ops"].add(op)
            else:
                close(ui, "MOVE")
                v = {"tile": tile_pos, "day": day, "last_t": t,
                     "order": [op], "ops": {op}, "pending": set()}
                open_visit[ui] = v
            if isinstance(tile, dict):
                pend = {cand for cand in OPS
                        if cand != op and _eligible(cand, tile, inv, day)}
                v["pending"] = pend
    for ui in list(open_visit):
        close(ui, "END")
    return {"tile_day_visits": tile_day_visits, "abandoned": abandoned,
            "next_after": next_after, "eligible": eligible_seen}


def _merge(acc, r):
    for k, v in r["tile_day_visits"].items():
        acc["tile_day_visits"][k].extend(v)
    acc["abandoned"] += r["abandoned"]
    acc["eligible"] += r["eligible"]
    for op, c in r["next_after"].items():
        acc["next_after"][op] += c


def report(label, dirpath, seat_mode, max_games, window, glob="*.json"):
    td = collections.defaultdict(list)
    acc = {"tile_day_visits": td, "abandoned": collections.Counter(),
           "eligible": collections.Counter(), "next_after": collections.defaultdict(collections.Counter)}
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
            _merge(acc, run_game(rep, seat, window, tag=games))
        except Exception:
            continue
        games += 1
    if not games:
        print(f"### {label}: nothing")
        return

    visits = sum(len(v) for v in td.values())
    n_td = len(td)
    extra = visits - n_td
    lengths = [len(v) for vs in td.values() for v in vs]
    revisit = sum(1 for vs in td.values() if len(vs) > 1)
    splits = collections.Counter()
    for vs in td.values():
        for a, b in zip(vs, vs[1:]):
            splits[(a[-1], b[0])] += 1

    print(f"\n############ {label}  ({games} games, {describe(window)}) ############")
    print(f"   visits {visits}   tile-days {n_td}   extra trips {extra}"
          f"   revisit {100.0 * revisit / max(1, n_td):.0f}%"
          f"   ops/visit {statistics.mean(lengths):.2f}"
          f"   median visit {statistics.median(lengths):.0f}")
    hist = collections.Counter(lengths)
    print("   visit length: " + "  ".join(f"{k}:{100.0 * hist[k] / max(1, visits):.0f}%"
                                          for k in sorted(hist) if k <= 6))
    print(f"\n   -- SPLIT PAIRS: last op of one visit -> first op of the next, same tile-day --")
    print(f"   {'pair':<36}{'n':>6}")
    for (a, b), n in splits.most_common(12):
        print(f"   {a + ' -> ' + b:<36}{n:>6}")
    print(f"\n   -- ops eligible on the standing tile and not done (context; ~100 % both arms) --")
    for op, el in acc["eligible"].most_common(6):
        print(f"   {op:<22}{acc['abandoned'].get(op, 0):>7}/{el:<7}"
              f"{100.0 * acc['abandoned'].get(op, 0) / el:>5.0f}%"
              f"   next: {', '.join(k for k, _ in acc['next_after'].get(op, {}).most_common(2))}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", default="11-20")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--seat", default="1")
    ap.add_argument("--max-games", type=int, default=8)
    ap.add_argument("--label", default=None)
    ap.add_argument("--ref-from", default=None)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--ref-max", type=int, default=None)
    ap.add_argument("--team", default=None)
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
