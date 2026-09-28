#!/usr/bin/env python
"""target_check — the d17 acceptance vector: did we actually reach Boey's midgame?

The goal is parity by the end of the midgame, so the check is a fixed vector of day-17
values, not a phase average. Values are **the same reduction `phase_map` uses** (`_series` /
`_agg` over d6-17, one number per game, then the median across games), so a PASS here is
consistent with the DAG report, and the target column is measurable on the reference arm
itself.

`--run-dir` evaluates a saved 96-game arm; without it, it runs the requested (opponent,
seed) grid live, truncated at d17. `--from-ref` recomputes the targets from the reference's
own replays instead of the frozen table below (use it when the reference changes).

Usage
-----
  PYTHONPATH=. python -m tools.phases.target_check --run-dir diag-replays/stepN
  PYTHONPATH=. python -m tools.phases.target_check --pa 2,3 --batch 4 --ref-max 60
"""
from __future__ import annotations

import argparse
import glob as globmod
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.diagnose.runbook import _make_seeds, _parse_pa_arg              # noqa: E402
from tools.phases.dag import PHASES                                       # noqa: E402
from tools.phases.phase_map import (_series, _agg, extract_games,          # noqa: E402
                                    extract_replays, _seat_of)

# metric key -> (direction, target). Targets are Boey's own d6-17 medians (8-60 replays)
# as read by the same reduction; see docs/DSM-vs-us(v0).md §3.4 and todo.md.
TARGETS = {
    "move_pct2":       ("<=", 45.0),
    "actions":         (">=", 0.48),     # acts per unit-turn
    "moves_per_act2":  ("<=", 1.00),
    "chain_fert2":     (">=", 70.0),
    "water_ops2":      (">=", 430.0),
    "harvests2":       (">=", 145.0),
    "feed_ops2":       (">=", 170.0),
    "collect_ops2":    (">=", 175.0),
    "animals2":        (">=", 17.0),
    "plant_ops2":      (">=", 95.0),
    "plants_died2":    ("<=", 4.0),
    "weeds2":          ("<=", 3.0),
    "pickup_ops2":     ("<=", 92.0),
    "drop_ops2":       ("<=", 33.0),
    "straw_tiles2":    (">=", 32.0),
    "trade_net2":      (">=", 48000.0),
}
_SRC = {
    "actions": "derived:acts_per_turn",
    "chain_fert2": "derived:chain_FERTILIZE",
    "move_pct2": "derived:move_pct",
    "moves_per_act2": "derived:moves_per_act",
    "water_ops2": "flow:WATER", "harvests2": "flow:HARVEST",
    "feed_ops2": "flow:FEED", "collect_ops2": "flow:COLLECT_FERTILIZER",
    "animals2": "stock:animals", "plant_ops2": "flow:PLANT",
    "plants_died2": "derived:plants_died", "weeds2": "stock:weed",
    "pickup_ops2": "flow:PICKUP", "drop_ops2": "flow:DROP",
    "straw_tiles2": "stock:plant_STRAWBERRY", "trade_net2": "flow:TRADE_NET",
}
_AGG = {"move_pct2": "median", "actions": "median", "moves_per_act2": "median",
        "chain_fert2": "median", "animals2": "max", "weeds2": "max",
        "straw_tiles2": "last", "plants_died2": "sum"}


def _values(games, day0, day1):
    per = {}
    for key, src in _SRC.items():
        vals = [_agg(_series({d: r for d, r in g.items() if day0 <= d <= day1}, src),
                     _AGG.get(key, "sum")) for g in games]
        vals = [v for v in vals if v == v]
        if vals:
            per[key] = st.median(vals)
    return per


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", default="phase2")
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--pa", default="2,3")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--ref-max", type=int, default=60)
    a = ap.parse_args(argv)
    spec = PHASES[a.phase]
    day0, day1 = spec["days"]

    if a.run_dir:
        paths = sorted(globmod.glob(str(Path(a.run_dir) / a.glob)))
        if a.max_games:
            paths = paths[:a.max_games]
        games = []
        from tools.diagnose.games import load_replay
        from tools.phases.phase_map import extract
        for p in paths:
            rep = load_replay(p)
            games.append(extract(rep, _seat_of(rep, "1")))
        label = f"{a.run_dir} ({len(games)} games)"
    else:
        games = extract_games(_parse_pa_arg(a.pa), _make_seeds(a.batch, a.seed),
                              workers=a.workers, steps=spec["steps"])
        label = f"live pa={a.pa} batch={a.batch} ({len(games)} games)"
    O = _values(games, day0, day1)
    targets = dict(TARGETS)
    if a.ref_from:
        ref_paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))[: a.ref_max]
        R = _values(extract_replays(ref_paths, seat=a.ref_seat), day0, day1)
        for k in targets:
            if k in R:
                targets[k] = (targets[k][0], R[k])
    print(f"# target_check — {a.phase} (d{day0}-d{day1})  {label}")
    print(f"# targets re-derived from {a.ref_from} ({a.ref_max} replays)"
          if a.ref_from else "# targets: frozen table")
    print()
    print(f"   {'metric':<22}{'ours':>10}{'target':>10}{'':>4}")
    fails = 0
    for key, (op, tgt) in targets.items():
        v = O.get(key)
        if v is None:
            continue
        ok = (v >= tgt) if op == ">=" else (v <= tgt)
        fails += 0 if ok else 1
        print(f"   {key:<22}{v:>10,.1f}{tgt:>10,.1f}   {'PASS' if ok else 'FAIL'}")
    print(f"\n   {len(targets) - fails}/{len(targets)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
