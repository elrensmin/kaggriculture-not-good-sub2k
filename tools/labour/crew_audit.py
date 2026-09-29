#!/usr/bin/env python
"""crew_audit — one screen for "where did the crew's turns go?".

The midgame's whole deficit is crew-turn conversion: on the reference's own farm we
spend 56 % of unit-turns walking against his 41 %, so we deliver 15 waters/day against
his 44 and half the farm dies. Five separate tools measure five pieces of that
(`move_trace`, `walk_runs`, `hop_regret`, `conversion`, `visit_trace`); this runs the
ones that matter on ONE directory and prints them as a single comparable block, so two
arms can be diffed at a glance.

Sections
--------
  TURN BUDGET   units / acts / moves / PASS and the move share
  WALKS         runs, tiles walked, mean, and the length histogram (dwelling vs commuting)
  DAY EDGES     the first and LAST walk of each unit-day -- the last one is pure waste
                because hands are wiped at `_end_of_day`
  KERNEL        how much walking a nearest-job rule would have saved (`hop_regret`)
  CONVERSION    how many assigned intents ever LAND, and why the rest did not.
                !! re-derives OUR decision from the observation, so it is valid on OUR
                replays ONLY -- use --skip-conversion for a reference replay.
  COST SHEET    moves charged to the act that preceded them

Usage
-----
  PYTHONPATH=. python -m tools.labour.crew_audit --dir /tmp/arm-base12 \
      --glob 'treatment_*.json' --days 11-17 --seat auto --team Boey --max-games 4
  PYTHONPATH=. python -m tools.labour.crew_audit --dir /tmp/kern \
      --glob 'control_*.json' --days 11-17 --seat auto --team Boey --max-games 4 \
      --label "his play" --skip-conversion
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import team as team_mod                                   # noqa: E402
from tools.diagnose.games import load_replay                         # noqa: E402
from tools.diagnose.window import describe, parse_days               # noqa: E402
from tools.phases.phase_map import _seat_of                          # noqa: E402

DAY = 24
MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
ACTS = ("PLANT", "WATER", "HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER", "FERTILIZE",
        "DIG", "BUILD_COOP", "BUILD_PASTURE", "PICKUP", "DROP", "PLACE", "SELL")


def _in(t, window):
    from tools.diagnose.window import in_window
    return in_window(t // DAY, window)


def _inv_at(obs, u):
    priv = obs.get("private") or {}
    invs = priv.get("inventories")
    if isinstance(invs, list) and u < len(invs):
        return {k: v for k, v in (invs[u] or {}).items() if v > 0}
    return {}


def turn_budget(steps, seat, window, acc):
    for t in range(len(steps) - 1):
        if not _in(t, window):
            continue
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        act = steps[t + 1][seat].get("action") or {}
        ops = [list(act.get("farmer") or ["PASS"])]
        ops += [list(c or ["PASS"]) for c in (act.get("hands") or [])]
        for u, op in enumerate(ops):
            nm = str(op[0]) if op else "PASS"
            acc["ut"] += 1
            if nm in MOVES:
                acc["moves"] += 1
                acc["carrying" if _inv_at(obs, u) else "empty"] += 1
            elif nm == "PASS":
                acc["pass"] += 1
            else:
                acc["acts"] += 1


def walks(steps, seat, window, acc):
    seq = collections.defaultdict(list)
    for t in range(len(steps) - 1):
        if not _in(t, window):
            continue
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        act = steps[t + 1][seat].get("action") or {}
        ops = [list(act.get("farmer") or ["PASS"])]
        ops += [list(c or ["PASS"]) for c in (act.get("hands") or [])]
        for u, op in enumerate(ops):
            seq[(t // DAY, u)].append(str(op[0]) if op else "PASS")
    for _k, ev in seq.items():
        i = 0
        while i < len(ev):
            if ev[i] not in MOVES:
                i += 1
                continue
            j = i
            while j < len(ev) and ev[j] in MOVES:
                j += 1
            run = j - i
            acc["runs"] += 1
            acc["tiles"] += run
            acc["len_%d" % min(run, 7)] += 1
            i = j
    for _k, ev in seq.items():
        f = 0
        for nm in ev:
            if nm in ACTS:
                break
            if nm in MOVES:
                f += 1
        acc["first_%d" % min(f, 7)] += 1
        acc["unit_days"] += 1
        l = 0
        for nm in reversed(ev):
            if nm in ACTS:
                break
            if nm in MOVES:
                l += 1
        acc["last_%d" % min(l, 7)] += 1


def cost_sheet(steps, seat, window, acc):
    seq = collections.defaultdict(list)
    for t in range(len(steps) - 1):
        if not _in(t, window):
            continue
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        act = steps[t + 1][seat].get("action") or {}
        ops = [list(act.get("farmer") or ["PASS"])]
        ops += [list(c or ["PASS"]) for c in (act.get("hands") or [])]
        for u, op in enumerate(ops):
            seq[(t // DAY, u)].append(str(op[0]) if op else "PASS")
    for _k, ev in seq.items():
        last = "START"
        for nm in ev:
            if nm in ACTS:
                acc["cost_ops"][nm] += 1
                last = nm
            elif nm in MOVES:
                acc["cost_mv"][last] += 1
            else:
                last = "PASS"


def _mean(counter, lo, hi, total):
    """Mean of a `prefix_<n>` histogram, with the top bucket clamped at `hi`."""
    num = 0
    for k, v in counter.items():
        try:
            n = int(str(k).rsplit("_", 1)[1])
        except (ValueError, IndexError):
            continue
        num += min(n, hi) * v
    return num / max(1, total)


def report(label, dirpath, seat_mode, max_games, window, glob="*.json",
           skip_conversion=False):
    acc = collections.Counter()
    acc["cost_ops"] = collections.Counter()
    acc["cost_mv"] = collections.Counter()
    regret = None
    conv = None
    if not skip_conversion:
        from tools.labour import conversion as conv_mod
        from tools.labour import hop_regret as hop_mod
        conv_mod._WINDOW = window        # `analyse` reads the module-global window
        regret = {"moves": 0, "regret": 0, "ops": collections.defaultdict(
            lambda: {"n": 0, "hop": 0, "near": 0, "regret": 0})}
        conv = {k: collections.Counter() for k in
                ("stats", "episodes", "walked", "detail", "landing_detail", "by_unit")}
    n = 0
    for p in sorted(globmod.glob(str(Path(dirpath) / glob)))[:max_games]:
        try:
            rep = load_replay(Path(p))
        except Exception as e:                    # noqa: BLE001
            print(f"   SKIP {Path(p).name}: {e}")
            continue
        seat = _seat_of(rep, seat_mode)
        steps = rep["steps"]
        turn_budget(steps, seat, window, acc)
        walks(steps, seat, window, acc)
        cost_sheet(steps, seat, window, acc)
        if regret is not None:
            r = hop_mod.run_game(rep, seat, window, exclude_claimed=True)
            hop_mod._merge(regret, r)
            c = conv_mod.analyse(rep, seat, window[0][0], window[-1][1])
            conv_mod._merge(conv, c)
        n += 1

    print(f"\n########## {label}  ({n} games, {describe(window)}) ##########")
    ut, mv, ac, ps = acc["ut"], acc["moves"], acc["acts"], acc["pass"]
    print(f"  TURN BUDGET   unit-turns {ut}   acts {ac} ({100*ac/max(1,ut):>4.1f}%)   "
          f"moves {mv} ({100*mv/max(1,ut):>4.1f}%)   pass {ps} "
          f"({100*ps/max(1,ut):>4.1f}%)")
    print(f"                moves per act {mv/max(1,ac):.2f}   "
          f"empty {100*acc['empty']/max(1,mv):.0f}% of moves")
    print(f"  WALKS         runs {acc['runs']}   tiles {acc['tiles']}   "
          f"mean {acc['tiles']/max(1,acc['runs']):.2f}   "
          f"len1 {100*acc.get('len_1',0)/max(1,acc['runs']):.0f}%   "
          f"len>=3 {100*sum(acc.get('len_%d'%k,0) for k in range(3,8))/max(1,acc['runs']):.1f}%   "
          f"len>=6 {100*sum(acc.get('len_%d'%k,0) for k in (6,7))/max(1,acc['runs']):.1f}%")
    ud = acc["unit_days"]
    print(f"  DAY EDGES     unit-days {ud}   first-walk mean "
          f"{_mean({k:v for k,v in acc.items() if k.startswith('first_')}, 1, 7, ud):.2f}   "
          f"LAST-walk mean "
          f"{_mean({k:v for k,v in acc.items() if k.startswith('last_')}, 1, 7, ud):.2f}   "
          f"last>=6 {100*sum(acc.get('last_%d'%k,0) for k in (6,7))/max(1,ud):.1f}%")
    if regret is not None:
        print(f"  KERNEL        avoidable-by-nearest "
              f"{100*regret['regret']/max(1,regret['moves']):.1f}% of walking "
              f"({regret['regret']} of {regret['moves']} tiles)")
        for op, c in sorted(regret["ops"].items(), key=lambda kv: -kv[1]["regret"])[:5]:
            if c["n"] < 20:
                continue
            print(f"                  {op:<20} walks {c['n']:>5}  hop "
                  f"{c['hop']/c['n']:>4.2f}  nearest {c['near']/c['n']:>4.2f}"
                  f"  regret {c['regret']:>5}")
    if conv is not None:
        s = conv["stats"]
        tot = max(1, s["intents"])
        print(f"  CONVERSION    intents {s['intents']} (carrying "
              f"{100*s['carrying']/tot:.0f}%)   LANDED {100*s['LANDED']/tot:.1f}%   "
              f"DIVERTED {100*s['DIVERTED']/tot:.1f}%   LOST {100*s['LOST']/tot:.1f}%   "
              f"DAY_END {100*s['DAY_END']/tot:.1f}%   "
              f"OTHER {100*s['OTHER_AT_TILE']/tot:.1f}%")
        for op in ("WATER", "HARVEST", "FERTILIZE", "FEED", "CARE", "COLLECT_FERTILIZER",
                   "PICKUP"):
            ep = conv["episodes"].get(op, 0)
            if ep < 20:
                continue
            ld = conv["detail"][(op, "LANDED")]
            print(f"                  {op:<20} ep {ep:>5}  landed {ld:>5} "
                  f"({100*ld/ep:>3.0f}%)  diverted {conv['detail'][(op,'DIVERTED')]:>5}"
                  f"  tiles/ep {conv['walked'][op]/ep:>4.2f}  tiles/land "
                  f"{(conv['landing_detail'][op]/ld if ld else float('nan')):>4.2f}")
    print(f"  COST SHEET    {'op':<22}{'ops':>7}{'moves':>8}{'mv/op':>8}{'share':>8}")
    for op, m in sorted(acc["cost_mv"].items(), key=lambda kv: -kv[1])[:10]:
        print(f"                {op:<22}{acc['cost_ops'][op]:>7}{m:>8}"
              f"{m/max(1,acc['cost_ops'][op]):>8.2f}{100*m/max(1,mv):>7.1f}%")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--days", default="11-20")
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--team", default="Boey")
    ap.add_argument("--max-games", type=int, default=4)
    ap.add_argument("--label", default=None)
    ap.add_argument("--skip-conversion", action="store_true")
    ns = ap.parse_args(argv)
    team_mod.set_team(ns.team)
    report(ns.label or ns.dir, ns.dir, ns.seat, ns.max_games, parse_days(ns.days),
           ns.glob, ns.skip_conversion)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
