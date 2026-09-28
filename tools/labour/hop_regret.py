#!/usr/bin/env python
"""hop_regret — is the walking because the work is SCATTERED, or because we chose badly?

Why this exists
---------------
`walk_runs` says our mean walk is 2.65 tiles against the reference's 1.79, and `op_patterns`
says our units commute where his dwell. What neither can say is whether a shorter walk was
available: a unit that walks 3 tiles to a job when an identical job sat next to it is a
KERNEL defect (`_pick`/preop), while a unit that walks 3 tiles because the nearest job of
that kind was 3 tiles away is a GEOMETRY defect (`layout`/crop plan). They need opposite
fixes, and the two look identical in every aggregate.

This measures it directly, per act:

    hop      = MOVEs this unit took since its previous act (the path it walked to get here)
    nearest  = manhattan distance from where that walk STARTED to the closest tile that
               offered the same op at that step (read off the observation)
    regret   = hop - nearest                     (how much walking the choice wasted)

`sum(regret) / total_moves` is the share of all walking that a nearest-job rule would have
saved. High regret => fix the kernel. Low regret => the work is scattered; fix the layout.

Most acts happen on the tile the unit already stands on (hop 0, regret 0), so read the
per-op rows, not the total.

Reads the observation for the offered-work map and uses the verified pairing
(`steps[t].observation` -> `steps[t+1].action`); positions come from the same observation.

Usage
-----
  PYTHONPATH=. python -m tools.labour.hop_regret --days 6-17 --dir /tmp/arm-ship --seat 1
  PYTHONPATH=. python -m tools.labour.hop_regret --days 6-17 --dir /tmp/arm-ship --seat 1 \
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

from tools import team as team_mod                                  # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days   # noqa: E402

DAY = 24
MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
OP_FOR = {
    "WATER": lambda t, d: t.get("kind") == "PLANT" and not t.get("watered_today"),
    "FERTILIZE": lambda t, d: (t.get("kind") == "PLANT"
                               and t.get("fertilized_until_day", -1) < d),
    "FEED": lambda t, d: "animal" in t and not t.get("fed_today"),
    "CARE": lambda t, d: "animal" in t and not t.get("cared_today"),
    "COLLECT_FERTILIZER": lambda t, d: "animal" in t and bool(t.get("fertilizer_available")),
    "HARVEST": lambda t, d: ((t.get("kind") == "PLANT" and t.get("yield_units", 0) > 0)
                             or ("animal" in t and t.get("yield_units", 0) > 0)),
    "DIG": lambda t, d: t.get("kind") == "WEED",
}


def _offer_map(farm, day, want):
    rows = farm.get("tiles") or []
    out = []
    pred = OP_FOR[want]
    for y, row in enumerate(rows):
        for x, t in enumerate(row):
            if isinstance(t, dict) and pred(t, day):
                out.append((x, y))
    return out


def _manh(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def run_game(rep, seat, window, exclude_claimed=False):
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    walk_len = {}
    walk_start = {}          # ui -> (tile, obs, day)
    stats = collections.defaultdict(lambda: {"n": 0, "hop": 0, "near": 0, "regret": 0})
    total_moves = 0
    total_regret = 0
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
        # tiles another unit acts on THIS turn: a walker that passes one did not
        # "miss" it -- someone else is serving it. Without this filter the regret is an
        # upper bound that mixes kernel error with legitimate claiming.
        claimed = set()
        if exclude_claimed:
            for ui2, c2 in enumerate(cmds):
                if ui2 < len(pos) and c2 and str(c2[0]) in OP_FOR:
                    claimed.add(pos[ui2])
        for ui, c in enumerate(cmds):
            if ui >= len(pos):
                continue
            op = str(c[0]) if c else "PASS"
            if op in MOVES:
                total_moves += 1
                if walk_len.get(ui, 0) == 0:
                    walk_start[ui] = (pos[ui], obs, day)
                walk_len[ui] = walk_len.get(ui, 0) + 1
                continue
            hop = walk_len.get(ui, 0)
            walk_len[ui] = 0
            if op not in OP_FOR or hop <= 0:
                continue
            start, sobs, sday = walk_start.get(ui, (pos[ui], obs, day))
            cands = _offer_map(sobs["farms"][seat], sday, op)
            if exclude_claimed:
                cands = [q for q in cands if q not in claimed]
            if not cands:
                near = hop
            else:
                near = min(_manh(start, q) for q in cands)
            regret = max(0, hop - near)
            r = stats[op]
            r["n"] += 1
            r["hop"] += hop
            r["near"] += near
            r["regret"] += regret
            total_regret += regret
    return stats, total_moves, total_regret


def _merge(acc, r):
    st, mv, rg = r
    acc["moves"] += mv
    acc["regret"] += rg
    for op, v in st.items():
        a = acc["ops"][op]
        for k in ("n", "hop", "near", "regret"):
            a[k] += v[k]


def report(label, dirpath, seat_mode, max_games, window, glob="*.json",
           exclude_claimed=False):
    acc = {"moves": 0, "regret": 0, "ops": collections.defaultdict(
        lambda: {"n": 0, "hop": 0, "near": 0, "regret": 0})}
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
            _merge(acc, run_game(rep, seat, window, exclude_claimed))
        except Exception:
            continue
        games += 1
    if not games:
        print(f"### {label}: nothing")
        return
    print(f"\n############ {label}  ({games} games, {describe(window)}) ############")
    pct = 100.0 * acc["regret"] / max(1, acc["moves"])
    print(f"   moves {acc['moves']}   regret {acc['regret']}"
          f"   = {pct:.1f}% of all walking was avoidable-by-nearest")
    print(f"   {'op':<22}{'walks':>7}{'hop':>6}{'nearest':>9}{'regret':>8}{'mean':>7}")
    for op in sorted(acc["ops"], key=lambda o: -acc["ops"][o]["regret"]):
        v = acc["ops"][op]
        if v["n"] == 0:
            continue
        print(f"   {op:<22}{v['n']:>7}{v['hop'] / v['n']:>6.2f}"
              f"{v['near'] / v['n']:>9.2f}{v['regret']:>8}{v['regret'] / v['n']:>7.2f}")
    print("   # high `mean` per op => the kernel is picking badly (fix _pick/preop);")
    print("   # low `mean` with a high `hop` => the work really is that far (fix layout).")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", default="6-17")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--seat", default="1")
    ap.add_argument("--max-games", type=int, default=8)
    ap.add_argument("--label", default=None)
    ap.add_argument("--ref-from", default=None)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--ref-max", type=int, default=None)
    ap.add_argument("--team", default=None)
    ap.add_argument("--exclude-claimed", action="store_true",
                    help="skip tiles another unit serves this turn (kernel regret only)")
    a = ap.parse_args(argv)
    team_mod.set_team(a.team)
    window = parse_days(a.days)
    report(a.label or Path(a.dir).name, a.dir, a.seat, a.max_games, window, a.glob,
           a.exclude_claimed)
    if a.ref_from:
        report(Path(a.ref_from).name, a.ref_from, a.ref_seat,
               a.ref_max or a.max_games, window, a.glob, a.exclude_claimed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
