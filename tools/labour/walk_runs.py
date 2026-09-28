#!/usr/bin/env python
"""walk_runs — how LONG is each walk, not just how many there are.

`move_trace` charges moves to the act that caused them and `op_patterns` measures the
act-run lengths. Neither answers "does a unit walk one tile and act again, or cross
the farm?". This tool walks each unit's op stream per day and reports the distribution
of **consecutive-MOVE run lengths** (a run of k MOVEs = a walk of k tiles), plus the
act that starts and ends each run.

Read it as: mean walk length 1.2 with 70 % of runs == 1 is a unit *dwelling* in a tile
cluster; mean 3.0 with a fat tail means it is commuting.

Usage
-----
  PYTHONPATH=. python -m tools.labour.walk_runs --dir diag-replays/p2-h12 --glob '*.json'
  PYTHONPATH=. python -m tools.labour.walk_runs --dir replays/Boey/v1 --glob '*.json' --seat auto
  PYTHONPATH=. python -m tools.labour.walk_runs --days 6-17 --dir A --compare-dir B
"""
from __future__ import annotations

try:
    from tools import team as team_mod
except ImportError:  # bare-script execution
    import pathlib as _pl
    import sys as _sys
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))
    from tools import team as team_mod

import argparse
import glob as globmod
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from tools.diagnose import window as window_mod
from tools.diagnose.window import describe, in_window, parse_days
from tools.labour import op_patterns as op_mod
from tools.labour.op_patterns import MOVES, _units

_WINDOW = None


def _in(day):
    return in_window(day, _WINDOW)


def analyse(steps, seat):
    by_unit = defaultdict(list)          # (day, ui) -> [(op, pos)]
    for s, day, ui, pos, op, _item in _units(steps, seat):
        if not _in(day):                 # `_units` reads op_patterns' own window
            continue
        by_unit[(day, ui)].append((op, pos))
    runs = []                            # walk length in tiles
    start_act = Counter()
    end_act = Counter()
    for _key, seq in by_unit.items():
        i, n = 0, len(seq)
        while i < n:
            if seq[i][0] not in MOVES:
                i += 1
                continue
            j = i
            while j < n and seq[j][0] in MOVES:
                j += 1
            k = j - i
            runs.append(k)
            if i - 1 >= 0:
                start_act[seq[i - 1][0]] += 1
            if j < n:
                end_act[seq[j][0]] += 1
            i = j
    return runs, start_act, end_act


def _report(label, files, seat_mode):
    runs = []
    start_act = Counter()
    end_act = Counter()
    for f in files:
        rep = __import__("json").load(open(f))
        steps = rep["steps"] if isinstance(rep, dict) else rep.steps
        if seat_mode == "auto":
            seat = team_mod.seat_of_names(
                (rep.get("info") or {}).get("TeamNames") or [], fallback=0)
        else:
            seat = int(seat_mode)
        r, sa, ea = analyse(steps, seat)
        runs += r
        start_act += sa
        end_act += ea
    if not runs:
        print(f"### {label}: no runs")
        return
    hist = Counter(runs)
    tot = len(runs)
    tiles = sum(runs)
    print(f"### {label}  ({len(files)} games)")
    print(f"   walks {tot}   tiles walked {tiles}   mean walk {tiles/tot:.2f}"
          f"   median {statistics.median(runs):.0f}")
    cum = 0
    for k in sorted(hist):
        cum += hist[k]
        print(f"      len {k:2d}  {hist[k]:6d}  {100*hist[k]/tot:5.1f}%   cum {100*cum/tot:5.1f}%")
        if k >= 6:
            break
    print("   -- act BEFORE the walk --")
    for op, c in start_act.most_common(8):
        print(f"      {op:22s} {c:6d}  {100*c/tot:5.1f}%")
    print()


def main(argv=None):
    global _WINDOW
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=4)
    ap.add_argument("--seat", default="1")
    ap.add_argument("--days", default=None)
    ap.add_argument("--compare-dir", default=None)
    ap.add_argument("--compare-seat", default="auto")
    ap.add_argument("--label", default=None)
    a = ap.parse_args(argv)
    _WINDOW = parse_days(a.days) if a.days else None
    if _WINDOW:
        print(f"window: {describe(_WINDOW)}")
    files = sorted(globmod.glob(str(Path(a.dir) / a.glob)))[:a.max_games]
    _report(a.label or Path(a.dir).name, files, a.seat)
    if a.compare_dir:
        cfiles = sorted(globmod.glob(str(Path(a.compare_dir) / a.glob)))[:a.max_games]
        _report(Path(a.compare_dir).name, cfiles, a.compare_seat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
