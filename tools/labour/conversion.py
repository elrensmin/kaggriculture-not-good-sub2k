#!/usr/bin/env python
"""conversion — does a unit CASH the job it was assigned?

Why this exists
---------------
`move_trace` says a WATER costs us 2.16 tiles of walking against the reference's 1.03.
`walk_runs` says we take the SAME NUMBER of walks as the reference (2,126 vs 2,207) and
each one is 0.7 tiles longer. `hop_regret` says **27.5 % of all our walking was
avoidable-by-nearest even after removing tiles another unit serves** -- so it is the
kernel, not the geometry.

None of them can say WHERE the walk is lost. This does. The agent is stateless, so
`scheduler.plan(state)` on a recorded observation reproduces the decision exactly; the
tool re-derives it every turn, follows each unit's **intent** (the job it was assigned)
until the intent changes, and classifies how the intent EPISODE ended:

  LANDED      the unit reached the tile and performed the op
  DIVERTED    the intent changed to another tile while this one was still on offer
              (the op was re-offered for that tile from the same state) -- assignment thrash
  LOST        the intent changed because the tile no longer offers that op (a window
              closed, someone else did it, the crop turned over)
  DAY_END     the day boundary arrived mid-walk (units are re-hired, the walk is dead)
  PASSED      no action at all on the last turn of the episode

Read `tiles/land` as the cost of one delivered op, and `DIVERTED` as the share of the
assignment work thrown away.

!! ONLY VALID ON OUR OWN REPLAYS !!
The intent is re-derived by calling `scheduler.plan` on the recorded observation. That
reproduces OUR decision exactly (the agent is stateless) but NOT the reference's -- so on
a Boey replay the CONVERSION block describes what OUR kernel would have done on his farm,
not what he did. The replay-derived sections of `crew_audit` (turn budget, walks, day
edges, hop regret, cost sheet) are valid on any replay; CONVERSION is not.

Usage
-----
  PYTHONPATH=. python -m tools.labour.conversion --dir /tmp/arm-base12 \
      --glob 'treatment_*.json' --days 11-17 --seat auto --team Boey --max-games 2
  PYTHONPATH=. python -m tools.labour.conversion --dir /tmp/kern --glob 'control_*.json' \
      --days 11-17 --seat auto --team Boey --max-games 2 --label "his play"
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
from tools.diagnose.window import describe, in_window, parse_days    # noqa: E402
from tools.phases.phase_map import _seat_of                          # noqa: E402

DAY = 24
MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
_WINDOW = None


def _in(day):
    return in_window(day, _WINDOW)


def _ops_of(act):
    act = act or {}
    out = [list(act.get("farmer") or ["PASS"])]
    out += [list(c or ["PASS"]) for c in (act.get("hands") or [])]
    return [str(o[0]) if o else "PASS" for o in out]


def _pos(obs, seat, u):
    farm = obs["farms"][seat]
    if u == 0:
        return tuple(farm["farmer"])
    hands = farm.get("hands") or []
    return tuple(hands[u - 1]) if u - 1 < len(hands) else None


def analyse(rep, seat, lo, hi):
    from src import scheduler, crop_plan, herd_plan
    from src.state import State

    steps = rep["steps"]
    orig = scheduler._pick
    turns = []                       # (t, state, picks, offered)

    def make_pick(store):
        def pick(jobs, assigned, pos, inv, only_delivery, prefer=None, claimed=None,
                 owner=None, me=None, day=0, deliver_margin=None, horizon=None):
            res = orig(jobs, assigned, pos, inv, only_delivery, prefer, claimed,
                       owner, me, day, deliver_margin, horizon)
            if me is not None and me not in store and res is not None:
                store[me] = (res[1].op, res[1].tile, res[2], only_delivery,
                             res[1].priority)
            return res
        return pick

    for t in range(len(steps) - 1):
        if not _in(t // DAY):
            continue
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        state = State(obs)
        store = {}
        scheduler._pick = make_pick(store)
        try:
            scheduler.plan(state)
        except Exception:                        # noqa: BLE001
            pass
        finally:
            scheduler._pick = orig
        offered = set()
        try:
            for j in list(crop_plan.jobs(state)) + list(herd_plan.jobs(state)):
                if j.tile is not None:
                    offered.add((j.op, j.tile))
        except Exception:                        # noqa: BLE001
            pass
        turns.append((t, state, store, offered))

    intent = {}
    for t, state, store, _off in turns:
        nxt = _ops_of(steps[t + 1][seat].get("action"))
        obs_t = steps[t][seat]["observation"]
        rec = {}
        for u in range(state.unit_count()):
            carrying = bool(state.unit_inv(u))
            if u in store:
                op, tile, d, _od, prio = store[u]
                rec[u] = (op, tile, d, carrying, prio)
            elif u < len(nxt) and nxt[u] not in MOVES + ("PASS",):
                rec[u] = (nxt[u], _pos(obs_t, seat, u), 0, carrying, 99)
        intent[t] = rec

    stats = collections.Counter()
    divert = collections.Counter()
    episodes = collections.Counter()
    walked = collections.Counter()
    detail = collections.Counter()
    landing_detail = collections.Counter()
    by_unit = collections.defaultdict(list)
    for idx, (t, _state, _s, _o) in enumerate(turns):
        for u, rec in intent[t].items():
            by_unit[u].append((idx, t, rec))
    for u, seq in by_unit.items():
        seq.sort()
        i = 0
        while i < len(seq):
            idx, t, rec = seq[i]
            op, tile, _d, carrying, prio = rec
            stats["intents"] += 1
            stats["carrying" if carrying else "free"] += 1
            j = i
            while j + 1 < len(seq):
                idx2, t2, rec2 = seq[j + 1]
                if t2 // DAY != t // DAY or idx2 != idx + (j + 1 - i):
                    break
                if rec2[1] != tile:
                    break
                j += 1
            path = 0
            for k in range(i, j + 1):
                t_k = seq[k][1]
                acted = _ops_of(steps[t_k + 1][seat].get("action"))
                if u < len(acted) and acted[u] in MOVES:
                    path += 1
            episodes[op] += 1
            walked[op] += path
            idx_end, t_end, _re = seq[j]
            acted = _ops_of(steps[t_end + 1][seat].get("action"))
            a = acted[u] if u < len(acted) else "PASS"
            at_tile = _pos(steps[t_end][seat]["observation"], seat, u) == tile
            if at_tile and a == op:
                reason = "LANDED"
                landing_detail[op] += path
            elif at_tile and a not in MOVES and a != "PASS":
                reason = "OTHER_AT_TILE"
            elif a in MOVES:
                if (j + 1 < len(seq) and seq[j + 1][1] // DAY == t // DAY
                        and seq[j + 1][1] == t_end + 1):
                    if (op, tile) in turns[idx_end + 1][3]:
                        reason = "DIVERTED"
                        nxt_rec = seq[j + 1][2]
                        pos_here = _pos(steps[t_end + 1][seat]["observation"], seat, u)
                        if nxt_rec[1] == pos_here and nxt_rec[1] != tile:
                            divert["ON_TILE"] += 1
                        elif any(v[1] == tile for w, v in intent[t_end + 1].items()
                                 if w != u):
                            divert["TAKEN_BY_OTHER"] += 1
                        elif nxt_rec[4] > prio:
                            divert["HIGHER_PRIORITY"] += 1
                        else:
                            divert["OTHER"] += 1
                        divert[op] += 1
                    else:
                        reason = "LOST"
                else:
                    reason = "DAY_END"
            else:
                reason = "PASSED"
            stats[reason] += 1
            detail[(op, reason)] += 1
            i = j + 1

    return {"stats": stats, "episodes": episodes, "walked": walked,
            "detail": detail, "landing_detail": landing_detail, "divert": divert,
            "by_unit": {u: len(s) for u, s in by_unit.items()}}


def _merge(acc, r):
    for key in ("stats", "episodes", "walked", "detail", "landing_detail", "by_unit",
                "divert"):
        for k, v in r[key].items():
            acc[key][k] += v


def report(label, dirpath, seat_mode, max_games, window, glob="*.json"):
    acc = {k: collections.Counter() for k in
           ("stats", "episodes", "walked", "detail", "landing_detail", "by_unit",
            "divert")}
    n = 0
    for p in sorted(globmod.glob(str(Path(dirpath) / glob)))[:max_games]:
        try:
            rep = load_replay(Path(p))
        except Exception as e:                   # noqa: BLE001
            print(f"   SKIP {Path(p).name}: {e}")
            continue
        seat = _seat_of(rep, seat_mode)
        _merge(acc, analyse(rep, seat, window[0][0], window[-1][1]))
        n += 1
    s = acc["stats"]
    print(f"\n############ {label}  ({n} games, {describe(window)}) ############")
    print(f"   intent episodes {s['intents']}   carrying {s['carrying']} "
          f"({100*s['carrying']/max(1,s['intents']):.0f}%)   free {s['free']}")
    tot = max(1, s["intents"])
    for k in ("LANDED", "DIVERTED", "LOST", "DAY_END", "PASSED", "OTHER_AT_TILE"):
        print(f"      {k:<15}{s[k]:>7}  {100*s[k]/tot:>5.1f}%")
    print(f"   DIVERSION REASON  " + "   ".join(
        f"{k} {v} ({100*v/max(1,s['DIVERTED']):.0f}%)" for k, v in
        acc["divert"].most_common() if k in
        ("ON_TILE", "TAKEN_BY_OTHER", "HIGHER_PRIORITY", "OTHER")))
    print(f"   {'op':<22}{'episodes':>9}{'LANDED':>8}{'DIVERTED':>10}{'LOST':>7}"
          f"{'DAYEND':>8}{'tiles/ep':>9}{'tiles/land':>11}")
    for op in sorted(acc["episodes"], key=lambda o: -acc["episodes"][o]):
        ep = acc["episodes"][op]
        if ep < 20:
            continue
        ld = acc["detail"][(op, "LANDED")]
        tl = acc["landing_detail"][op] / ld if ld else float("nan")
        print(f"   {op:<22}{ep:>9}{ld:>8}{acc['detail'][(op, 'DIVERTED')]:>10}"
              f"{acc['detail'][(op, 'LOST')]:>7}{acc['detail'][(op, 'DAY_END')]:>8}"
              f"{acc['walked'][op]/ep:>9.2f}{tl:>11.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--days", default="11-20")
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--team", default="Boey")
    ap.add_argument("--max-games", type=int, default=2)
    ap.add_argument("--label", default=None)
    ns = ap.parse_args(argv)
    team_mod.set_team(ns.team)
    global _WINDOW
    _WINDOW = parse_days(ns.days)
    report(ns.label or ns.dir, ns.dir, ns.seat, ns.max_games, _WINDOW, ns.glob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
