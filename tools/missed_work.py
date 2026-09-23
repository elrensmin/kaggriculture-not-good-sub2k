#!/usr/bin/env python
"""missed_work — enumerate, per turn, the farm work that EXISTS but is NOT being done.

This answers the F1 question directly: "what work exists and is not being done, and
are idle hands sitting on it?" It replays a game and, for our seat, classifies every
tile's pending work each step, records which units address it, and tallies:

  * MISSED work per day (pending on a day but never addressed that day), by type:
      WATER   unwatered crop that still needs water
      HARVEST ready produce (crop/animal) collectable
      FEED    animal not yet fed today
      CARE    animal not yet cared today
      FERT    ongoing crop needing fertilizer
      DIG     a weed to clear
  * IDLE-ON-WORK steps: a unit PASSes while STANDING on a pending-work tile (the
    smoking-gun "we have work but hands aren't doing it"), incl. the exact steps.
  * Uncovered work: pending tiles that no unit acted on all day (candidates for routing).

Usage:
  python -m tools.missed_work --path <game.json>
  python -m tools.missed_work --dir diag-replays/run-5 [--glob 'old_vs_*.json']
Run from the repo root with PYTHONPATH=. (or python -m from repo root).
"""
from __future__ import annotations

import argparse
import glob as globmod
from collections import Counter, defaultdict
from pathlib import Path

import diagnose

TEST_SEAT = 1  # our seat in --old/--compare games (public opponent is seat 0)
MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}
ACT_OPS = {"WATER", "HARVEST", "FEED", "CARE", "FERTILIZE", "DIG", "COLLECT_FERTILIZER"}
# crop water-relevant window (age in days): ongoing crops (tomato/strawberry) need
# water all season; 1-shot crops only up to their max-yield day.
CROP_MAXDAY = {"WHEAT": 4, "CARROT": 3, "TOMATO": 99, "STRAWBERRY": 99, "MELON": 12}
ONGOING = ("TOMATO", "STRAWBERRY")
SHED_CAP = 100


def _work_on_tile(t, day):
    """Return a set of pending-work kind(s) on tile t (dict) relevant at 'day'."""
    if not isinstance(t, dict):
        return set()
    work = set()
    kind = t.get("kind")
    if kind == "WEED":
        work.add("DIG")
        return work
    if kind == "PLANT":
        crop = t.get("crop")
        age = day - int(t.get("planted_day", 0))
        window = CROP_MAXDAY.get(crop, 0)
        if not t.get("watered_today") and 0 <= age <= window and crop:
            work.add("WATER")
        yld = int(t.get("yield_units", 0))
        if yld > 0 and crop in ONGOING:
            # ongoing crops: collect whenever product is accumulating (yield>0).
            work.add("HARVEST")
        elif yld > 0 and crop in CROP_MAXDAY and age >= CROP_MAXDAY[crop]:
            # 1-shot crops: only "ready" once mature (harvesting early forfeits yield).
            work.add("HARVEST")
        if yld <= 0 and crop in ONGOING and int(t.get("fertilized_until_day", -1)) < day:
            work.add("FERT")
        return work
    if "animal" in t:  # occupied coop/pasture
        fed = bool(t.get("fed_today"))
        if not fed:
            work.add("FEED")
        if not t.get("cared_today"):
            work.add("CARE")
        if int(t.get("yield_units", 0)) > 0:
            work.add("HARVEST")
        return work
    return set()


def analyze_game(path):
    """Return a structured missed-work report dict for one replay (our seat)."""
    rep = diagnose.load_replay(Path(path))
    steps = rep["steps"]
    me = TEST_SEAT
    day_done = defaultdict(set)   # (day, kind, x, y)  addressed at least once that day
    day_pending = defaultdict(set) # (day, kind, x, y)  seen pending that day
    idle_on_work = []             # list of (day, step, x, y, work_kinds, unit_idx)
    uncovered_steps = Counter()   # kind -> steps where pending work had no unit within 2 tiles acting this step
    n_idle_steps = 0
    final_money = None
    opp_final = None

    for i, steplist in enumerate(steps):
        if me >= len(steplist):
            break
        obs = steplist[me]["observation"]
        act = steplist[me]["action"]
        day = i // 24
        farm = obs["farms"][me]
        positions = [tuple(farm["farmer"])] + [tuple(p) for p in farm["hands"]]
        units = [list(act.get("farmer") or ["PASS"])] + [list(c) for c in act.get("hands") or []]
        if i == len(steps) - 1:
            final_money = steplist[me].get("reward")
            opp_final = steplist[0].get("reward") if 0 < len(steplist) else None

        # Which (x,y,kind) does this turn's action address? (a unit acts on its current tile)
        addressed = set()
        for ui, u in enumerate(units):
            op = u[0] if u else "PASS"
            if op in ACT_OPS and ui < len(positions):
                x, y = positions[ui]
                tile = farm["tiles"][y][x] if 0 <= y < len(farm["tiles"]) and 0 <= x < len(farm["tiles"][0]) else None
                # Map the op to the pending kind(s) it clears on that tile.
                wk = _work_on_tile(tile, day)
                if op == "WATER" and "WATER" in wk:
                    addressed.add((x, y, "WATER"))
                elif op in ("HARVEST",) and "HARVEST" in wk:
                    addressed.add((x, y, "HARVEST"))
                elif op == "FEED" and "FEED" in wk:
                    addressed.add((x, y, "FEED"))
                elif op == "CARE" and "CARE" in wk:
                    addressed.add((x, y, "CARE"))
                elif op == "FERTILIZE" and "FERT" in wk:
                    addressed.add((x, y, "FERT"))
                elif op == "DIG" and "DIG" in wk:
                    addressed.add((x, y, "DIG"))

        # Enumerate pending work across the board this step.
        for y, row in enumerate(farm["tiles"]):
            for x, tile in enumerate(row):
                wk = _work_on_tile(tile, day)
                for k in wk:
                    day_pending[(day, k, x, y)].add(None)

        # Idle-on-work: a unit PASSes while standing on pending work it could do.
        for ui, u in enumerate(units):
            op = u[0] if u else "PASS"
            if op != "PASS" or ui >= len(positions):
                continue
            n_idle_steps += 1
            x, y = positions[ui]
            if not (0 <= y < len(farm["tiles"]) and 0 <= x < len(farm["tiles"][0])):
                continue
            wk = _work_on_tile(farm["tiles"][y][x], day)
            if wk:
                idle_on_work.append((day, i, x, y, sorted(wk), ui))

        # Commit addressed for the day.
        for (x, y, k) in addressed:
            day_done[(day, k, x, y)].add(None)

    # Aggregate per-day missed: pending that day but never addressed that day.
    missed_by_day = defaultdict(Counter)
    for (day, k, x, y), _ in day_pending.items():
        if (day, k, x, y) not in day_done:
            missed_by_day[day][k] += 1
    missed_total = Counter()
    for c in missed_by_day.values():
        missed_total.update(c)

    # Idle-on-work summary.
    iow_counter = Counter(k for (_, _, _, _, kinds, _) in idle_on_work for k in kinds)
    iow_by_day = Counter(day for (day, *_rest) in idle_on_work)

    return {
        "path": str(path),
        "steps": len(steps),
        "final_money": final_money,
        "opp_final": opp_final,
        "missed_total": dict(missed_total),
        "missed_by_day": {d: dict(c) for d, c in sorted(missed_by_day.items())},
        "idle_on_work_total": len(idle_on_work),
        "idle_on_work_by_type": dict(iow_counter),
        "idle_on_work_by_day": dict(iow_by_day),
        "idle_on_work_steps": idle_on_work[:40],
        "n_idle_steps": n_idle_steps,
    }


def fmt_report(r, verbose=None):
    lines = []
    lines.append(f"Game: {Path(r['path']).name}  (final {r['final_money']:.0f} vs opp {r['opp_final']:.0f})")
    lines.append(f"  steps {r['steps']}  |  idle steps {r['n_idle_steps']}  |  idle-on-WORK steps {r['idle_on_work_total']}")
    mt = r["missed_total"]
    if mt:
        lines.append(f"  MISSED WORK (pending a full day, never addressed that day): " +
                     ", ".join(f"{k}={v}" for k, v in sorted(mt.items())))
    else:
        lines.append("  MISSED WORK: none (all pending work addressed same-day)")
    iow = r["idle_on_work_by_type"]
    if iow:
        lines.append(f"  idle-on-work by type: " + ", ".join(f"{k}={v}" for k, v in sorted(iow.items())))
    lines.append(f"  idle-on-work by day: " + ", ".join(f"d{d}={v}" for d, v in sorted(r['idle_on_work_by_day'].items())))
    if verbose and r["idle_on_work_steps"]:
        lines.append("  first idle-on-work steps (day,step,x,y,work):")
        for (d, st, x, y, kinds, ui) in r["idle_on_work_steps"][:25]:
            lines.append(f"    day {d:2d} step {st:3d} unit{ui} @({x},{y}) {kinds}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path")
    ap.add_argument("--dir")
    ap.add_argument("--glob", default=None, help="restrict files, e.g. 'old_vs_*.json'")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--summary-only", action="store_true", dest="summary_only")
    args = ap.parse_args()
    if args.path:
        paths = [args.path]
    else:
        d = args.dir or "."
        pat = args.glob or "*_vs_*.json"
        paths = sorted(globmod.glob(str(Path(d) / pat)))
    if not paths:
        print("no replays matched"); return
    totals = Counter(); games = 0; iow_games = 0
    for p in paths:
        try:
            r = analyze_game(p)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {Path(p).name}: {e}")
            continue
        games += 1
        totals.update(r["missed_total"])
        totals.update({("idle_on_work", r["idle_on_work_total"])})
        print(fmt_report(r, verbose=args.verbose and not args.summary_only))
        print()
    if games > 1:
        print(f"=== AGGREGATE over {games} games ===")
        for k, v in totals.most_common():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
