#!/usr/bin/env python
"""herd_gate — per-day readout of WHAT IS BLOCKING the herd purchase, and why.

The phase DAG says `animals` is the midgame root with a blast radius of 6, but a root is
not a reason. The buy is gated by three independent conditions plus housing, and they
bind in sequence, so "the herd is stuck at 11" has three different causes on three
different days. This tool prints them day by day.

Measured on the shipped tree (d6-17, 4 games): the wheat gate blocks d6-d9 (3-14 standing
wheat tiles against a requirement of 16-17), the cash gate blocks d10-d12 (money $691-1,345
against a feed cover of $1,650-1,725), and from d13 both gates PASS while money grows to
$7,792 -- because `HERD_BUY_UNTIL=12` closed the window at d12. Three gates, one herd.

Columns:
  owned     animals owned anywhere (board + shed + carried) -- what the buy gate reads
  board     animals placed on tiles -- what the DAG's `animals2` measures
  wheatT    standing WHEAT tiles
  need      `WHEAT_TILES_PER_ANIMAL * (owned + 1)`
  cover$    `ANIMAL_FEED_RESERVE_DAYS * FEED_PRICE_GUESS * (owned + 1)` held back in cash
  cost$     cheapest animal the day's target still needs
  W C T     the three gates: W = wheat base, C = cash for cost+cover, T = window open
  bought    net animals bought that day

Usage:
  PYTHONPATH=. python -m tools.phases.herd_gate --pa 1-4 --batch 4
  PYTHONPATH=. python -m tools.phases.herd_gate --days 6-17 --pa 1-3 --batch 2
  PYTHONPATH=. python -m tools.phases.herd_gate --ref-from replays/Boey/v1 --ref-max 20 --team Boey
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import statistics as st
from collections import defaultdict

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS

from tools.diagnose.agents import load_agent, load_public_agent
from tools.diagnose.config import TEST_SEAT
from tools.diagnose.games import load_replay, run_game
from tools.diagnose.runbook import _make_seeds, _parse_pa_arg
from tools.diagnose.window import parse_days
from tools.phases.phase_map import DAY, _owned_animals, _steps_of
from src import params as P

_AGENT = None


def _day_rows(steps, seat):
    """{day: dict} for the phase window, from raw steps (live env or replay)."""
    days = defaultdict(dict)
    for t in range(len(steps)):
        frame = steps[t]
        if len(frame) <= seat:
            continue
        obs = frame[seat].get("observation")
        if not obs:
            continue
        d = t // DAY
        act = (steps[t + 1][seat].get("action") or {}) if t + 1 < len(steps) else {}
        rec = days[d]
        rec["money"] = float(obs["farms"][seat].get("money") or 0.0)
        rec["owned"] = sum(_owned_animals(obs, seat).values())
        planted = 0
        wheat = 0
        structs = 0
        board = 0
        for row in obs["farms"][seat]["tiles"]:
            for tile in row:
                if not isinstance(tile, dict):
                    continue
                if "animal" in tile:
                    board += 1
                if tile.get("kind") == "PLANT":
                    planted += 1
                    if tile.get("crop") == "WHEAT":
                        wheat += 1
                elif tile.get("kind") in ("COOP", "PASTURE"):
                    structs += 1
        rec["board"] = board
        rec["wheat_tiles"] = wheat
        rec["planted"] = planted
        rec["structures"] = structs
        rec["buys"] = rec.get("buys", 0) + sum(
            1 for o in (act.get("market") or [])
            if o and o[0] == "BUY_ANIMAL")
    return days


def _worker(task):
    pa, seed, steps, day0, day1 = task
    global _AGENT
    if _AGENT is None:
        _AGENT = load_agent(fresh=True)
    env = run_game(_AGENT, load_public_agent(pa), seed=seed,
                   episode_steps=steps, seat=TEST_SEAT, audit=False)
    return _day_rows(_steps_of(env), TEST_SEAT)


def collect_live(pa_indices, seeds, day1, workers):
    steps = (day1 + 1) * DAY
    tasks = [(pa, s, steps, 0, day1) for pa in pa_indices for s in seeds]
    w = int(workers or os.cpu_count() or 1)
    if w <= 1 or len(tasks) <= 1:
        return [_worker(t) for t in tasks]
    ctx = mp.get_context("fork")
    with ctx.Pool(processes=min(w, len(tasks))) as pool:
        return list(pool.imap_unordered(_worker, tasks))


def collect_replays(paths, seat="auto"):
    out = []
    for p in paths:
        rep = load_replay(p)
        names = (rep.get("info") or {}).get("TeamNames") or []
        i = next((k for k, n in enumerate(names)
                  if n and "boey" in str(n).lower()), None)
        if i is None:
            continue
        out.append(_day_rows(_steps_of(rep), i))
    return out


def report(games, day0, day1, label):
    per = defaultdict(list)
    for days in games:
        for d, rec in days.items():
            if day0 <= d <= day1:
                per[d].append(rec)
    if not per:
        print(f"{label}: no days in window")
        return
    print(f"\n=== {label}  ({len(games)} games) ===")
    print(" day  money  owned board wheatT  need  cover$  "
          "W  C  T   bought  planted structs")
    for d in sorted(per):
        rows = per[d]
        med = lambda k: st.median(x.get(k, 0) for x in rows)
        owned = med("owned")
        need = P.WHEAT_TILES_PER_ANIMAL * (owned + 1)
        cover = P.ANIMAL_FEED_RESERVE_DAYS * P.FEED_PRICE_GUESS * (owned + 1)
        wheat_ok = med("wheat_tiles") >= need
        cost = min(a["cost"] for a in ANIMALS.values())
        cash_ok = med("money") >= cost + P.ANIMAL_CASH_RESERVE + cover
        win_ok = P.HERD_BUY_FROM_DAY <= d <= P.HERD_BUY_UNTIL
        print(f"{d:4d} {med('money'):6.0f} {owned:6.0f} {med("board"):5.0f} "
              f"{med('wheat_tiles'):6.0f} {need:5.1f} {cover:6.0f}  "
              f"{'Y' if wheat_ok else '.'}  {'Y' if cash_ok else '.'}  "
              f"{'Y' if win_ok else '.'}   {med('buys'):5.0f}  "
              f"{med('planted'):7.0f} {med('structures'):7.0f}")
    print(f"  W=wheat base ok (needs {P.WHEAT_TILES_PER_ANIMAL}/animal)   "
          f"C=cash ok (cost+{P.ANIMAL_FEED_RESERVE_DAYS}d feed cover)   "
          f"T=window open (d{P.HERD_BUY_FROM_DAY}-d{P.HERD_BUY_UNTIL})")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="per-day readout of what is blocking the herd purchase",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--pa", default="1-4", help="public agent indices (live mode)")
    ap.add_argument("--batch", type=int, default=4, help="seeds per opponent")
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--days", default="6-17", help="day window, e.g. 6-17")
    ap.add_argument("--ref-from", default=None, help="replay dir to probe instead (e.g. Boey)")
    ap.add_argument("--ref-max", type=int, default=20)
    ap.add_argument("--team", default=None)
    a = ap.parse_args(argv)
    spans = parse_days(a.days) or ((0, 29),)
    day0 = min(lo for lo, _ in spans)
    day1 = max(hi for _, hi in spans)
    if a.ref_from:
        import glob
        paths = sorted(glob.glob(os.path.join(a.ref_from, "*.json")))[:a.ref_max]
        games = collect_replays(paths)
        report(games, day0, day1, f"REFERENCE {a.ref_from}")
    else:
        games = collect_live(_parse_pa_arg(a.pa), _make_seeds(a.batch, a.seed),
                             day1, a.workers)
        report(games, day0, day1, f"OURS  pa={a.pa} seeds={a.batch}")


if __name__ == "__main__":
    main()
