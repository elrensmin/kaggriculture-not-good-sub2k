#!/usr/bin/env python
"""divergence — WHEN does each metric go bad, not just by how much.

Why this exists
---------------
`phase_map` reduces a whole phase to one number per metric, and that hides the thing that
matters most about a phase: **its shape in time**. MEASURED (2026-09-28, d0-d29 vs Boey's 60
replays, median bank delta per day):

    day  1-5   cumulative gap  -$74     <- the opening tape is at parity
    day  6-10  cumulative gap -$162     <- still level
    day 11+    +$3,000/day, compounding to +$39,032 by d29

A phase-aggregate table says "phase 2 is 0.54x", which is true and useless: the phase-2 gap
does not exist before d11. This tool prints, for every metric the DAG knows, the FIRST day
in the window where it reads BAD against the reference, plus the per-day series behind it.
That is the reading that turns a ratio into a date, and a date into a mechanism.

Both arms are reduced identically: our games through `extract_games`, the reference through
its saved replays, and the same `_series` / `_agg` / `_status` the phase tool uses.

Usage
-----
  PYTHONPATH=. python -m tools.phases.divergence --pa 2,3 --batch 4 \
      --ref-from replays/Boey/v1 --ref-max 60
  PYTHONPATH=. python -m tools.phases.divergence --phase phase3 --pa 2,3 --batch 4 \
      --ref-from replays/Boey/v1 --ref-max 60 --metric revenue2
"""
from __future__ import annotations

import argparse
import glob as globmod
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.diagnose.runbook import _make_seeds, _parse_pa_arg     # noqa: E402
from tools.phases.dag import METRICS, PHASES                       # noqa: E402
from tools.phases.phase_map import (                               # noqa: E402
    _agg, _pnums, _series, _status, extract_games, extract_replays,
)


def _daily_medians(games, key, src, agg, day0, day1):
    """{day: MEDIAN over games} for one metric, restricted to the window.

    The metric's own `agg` reduces a day SERIES to one value per game (that is what
    `reduce_game` does); across games the reduction is always a median, exactly like
    `phase_map.analyse`. Applying `agg` across games instead SUMS them, which inflated
    every count by the number of games -- the first version of this tool reported 977
    FEED/day for the reference against a true 15.
    """
    per = defaultdict(list)
    for days in games:
        win = {d: r for d, r in days.items() if day0 <= d <= day1}
        for d, v in _series(win, src):
            per[d].append(v)
    return {d: st.median(vals) for d, vals in per.items() if vals}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="phase2")
    ap.add_argument("--pa", default="2,3")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=60)
    ap.add_argument("--metric", default=None, help="print only this metric's series")
    a = ap.parse_args(argv)

    spec = PHASES[a.phase]
    day0, day1 = spec["days"]
    pnums = _pnums(a.phase, day0, day1)
    seeds = _make_seeds(a.batch, a.seed)
    pa = _parse_pa_arg(a.pa)

    ours = extract_games(pa, seeds, workers=a.workers, steps=spec["steps"])
    ref_dir = Path(a.ref_from)
    ref_paths = sorted(globmod.glob(str(ref_dir / a.ref_glob)))[: a.ref_max]
    theirs = extract_replays(ref_paths, seat="auto")
    print(f"# divergence — {a.phase} (d{day0}-d{day1})")
    print(f"# ours: pa={a.pa} batch={a.batch} -> {len(ours)} games")
    print(f"# ref : {len(theirs)} replays from {a.ref_from}")
    print()

    rows = []
    for key, m in METRICS.items():
        if m["phase"] not in pnums:
            continue
        o = _daily_medians(ours, key, m["src"], m["agg"], day0, day1)
        t = _daily_medians(theirs, key, m["src"], m["agg"], day0, day1)
        if not o or not t:
            continue
        first_bad = None
        for d in sorted(o):
            if d not in t:
                continue
            target = _agg([(d, v) for v in [t[d]]], "median")
            status, _ = _status(m, o[d], target)
            if status == "BAD":
                first_bad = d
                break
        agg_ours = _agg([(d, v) for d, v in sorted(o.items())], m["agg"])
        agg_ref = _agg([(d, v) for d, v in sorted(t.items())], m["agg"])
        rows.append((first_bad if first_bad is not None else 10 ** 6, key, m, o, t,
                     agg_ours, agg_ref))

    rows.sort(key=lambda r: (r[0], r[1]))
    print(f"{'first BAD':>9} {'metric':26s} {'agg ours':>10s} {'agg ref':>10s} {'ratio':>7s}"
          f"   per-day (ours vs ref, first 4 gap days)")
    for fb, key, m, o, t, ao, ar in rows:
        fbs = "-" if fb >= 10 ** 6 else f"d{fb}"
        ratio = ao / ar if ar else float("nan")
        days = sorted(d for d in o if d in t)
        worst = sorted(days, key=lambda d: -(abs(t[d] - o[d]) / max(abs(t[d]), 1e-9)))[:4]
        worst.sort()
        series = "  ".join(f"d{d}:{o[d]:.0f}|{t[d]:.0f}" for d in worst)
        print(f"{fbs:>9} {m['label'][:26]:26s} {ao:10.2f} {ar:10.2f} {ratio:7.2f}   {series}")
    print()
    print("# `first BAD` is the first day the metric crosses its tolerance against the")
    print("# reference ON THAT DAY -- the date the phase table cannot show. Rows sorted by it.")
    print("# A metric that is BAD in aggregate but has no BAD day is a WARN-level drift.")

    if a.metric:
        for label, games in (("ours", ours), ("ref", theirs)):
            m = METRICS[a.metric]
            s = _daily_medians(games, a.metric, m["src"], m["agg"], day0, day1)
            print(f"\n{a.metric} [{label}]: " +
                  "  ".join(f"d{d}:{s[d]:.1f}" for d in sorted(s)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
