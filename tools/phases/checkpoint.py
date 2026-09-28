#!/usr/bin/env python
"""checkpoint — WHERE and on WHICH DAY the state gap opens, ours vs the reference.

Why this exists
---------------
Everything else in `tools/` measures a mechanism. None of them answers the question the
objective is actually scored on: **at day N, which of the reference's state quantities are
we missing, and on which day did each one start missing?**

`transplant --prefix ours --cut-day N` prints a single column of gaps at day N. That tells
you the shape of the hole but not when it was dug, and a whole-game margin on 12 games has
a ±$8k noise band dominated by whether the farm starves -- so an arm can move every
mechanism you aimed at and still read as "no change". This runs the SAME episodes twice,
in lockstep, day by day:

  HIS   both seats play the recorded actions  -> his trajectory
  OURS  our agent plays his seat from d0, his opponent keeps its recorded actions

and prints, per day, the median over episodes of each state metric for both, plus the gap
and the FIRST DAY the gap exceeded the tolerance. That is the instrument for the
checkpoint: it says which day to look at, and which metric to fix.

Usage
-----
  PYTHONPATH=. python -m tools.phases.checkpoint --n 24 --cut-day 10
  PYTHONPATH=. python -m tools.phases.checkpoint --all --cut-day 10 --workers 4
  PYTHONPATH=. python -m tools.phases.checkpoint --n 24 --days 0-10 --metric planted,animals
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import multiprocessing as mp
import random
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments import make                                   # noqa: E402
from tools import team as team_mod                                     # noqa: E402
from tools.phases.transplant import (DAY, STEPS, _agent, _final_money,  # noqa: E402
                                     _recorded, _selfplay, _snapshot)

# The checkpoint metrics, in the order the gap is worth reading.
_KEYS = ("money", "animals", "structs", "planted", "empty", "wheat", "straw",
         "melon", "tomato", "carrot", "quadrants", "shed_total", "hands")


def _series(path, seat, cut_day, prefix):
    """Per-day snapshots of `seat`'s farm. `prefix` = 'recorded' (his) or 'ours'."""
    from tools.diagnose.games import load_replay
    rep = load_replay(Path(path))
    own = team_mod.seat_of_names((rep.get("info") or {}).get("TeamNames") or [], fallback=0)
    seat = own if seat is None else seat
    seed = (rep.get("info") or {}).get("seed")
    env = make("kaggriculture", configuration={"episodeSteps": STEPS, "seed": seed})
    env.reset()
    agent = _agent()
    cut_step = (cut_day + 1) * DAY
    snaps = {}
    for t in range(cut_step):
        obs = [env.state[i]["observation"] for i in range(2)]
        acts = [None, None]
        acts[1 - seat] = _recorded(rep, t, 1 - seat)
        acts[seat] = (_recorded(rep, t, seat) if prefix == "recorded"
                      else agent(obs[seat]))
        if acts[seat] is None or acts[1 - seat] is None:
            break
        env.step(acts)
        if (t + 1) % DAY == 0:
            snaps[(t + 1) // DAY] = _snapshot(env.state[seat]["observation"], seat)
        if env.done:
            break
    return snaps, int(seed or 0), seat


def _worker(task):
    path, cut_day, prefix = task
    try:
        snaps, seed, seat = _series(path, None, cut_day, prefix)
        return {"file": Path(path).name, "prefix": prefix, "seed": seed,
                "seat": seat, "snaps": {str(k): v for k, v in snaps.items()}}
    except Exception as exc:                    # noqa: BLE001
        return {"file": Path(path).name, "prefix": prefix, "error": repr(exc)}


def _med(rows, day, key):
    vals = [r["snaps"][str(day)].get(key, 0) for r in rows if str(day) in r["snaps"]]
    return st.median(vals) if vals else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--shuffle-seed", type=int, default=20260929)
    ap.add_argument("--cut-day", type=int, default=10)
    ap.add_argument("--days", default=None, help="window to print (default 0..cut-day)")
    ap.add_argument("--metric", default=None, help="comma list; default all")
    ap.add_argument("--tol", type=float, default=1.0, help="gap%% tolerance for 'within'")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--team", default=None)
    ap.add_argument("--include-selfplay", action="store_true")
    a = ap.parse_args(argv)
    team_mod.set_team(a.team or "Boey")

    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))
    if not a.all:
        rnd = random.Random(a.shuffle_seed)
        paths = rnd.sample(paths, min(a.n, len(paths)))
    if not a.include_selfplay:
        keep = []
        for p in paths:
            try:
                if not _selfplay(json.load(open(p))):
                    keep.append(p)
            except Exception:                   # noqa: BLE001
                pass
        paths = keep
    keys = a.metric.split(",") if a.metric else list(_KEYS)
    # `cash_flow` is DERIVED: the day-over-day change in `money`, i.e. that day's NET.
    # It is what says WHEN the revenue gap opens -- a stock column cannot.
    want_flow = "cash_flow" in keys
    keys = [k for k in keys if k != "cash_flow"]
    lo, hi = 0, a.cut_day
    if a.days:
        lo, hi = (int(x) for x in a.days.split("-"))
    print(f"# checkpoint  ref={a.ref_from}  {len(paths)} episodes  d{lo}-{hi}")
    tasks = [(p, a.cut_day, pre) for pre in ("recorded", "ours") for p in paths]
    w = int(a.workers or 0)
    if w <= 1 or len(tasks) <= 1:
        rows = [_worker(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_worker, tasks))
    his = [r for r in rows if r.get("prefix") == "recorded" and "error" not in r]
    ours = [r for r in rows if r.get("prefix") == "ours" and "error" not in r]
    errs = [r for r in rows if "error" in r]
    if errs:
        print(f"   {len(errs)} errored, e.g. {errs[0]['error']}")
    if not his or not ours:
        print("no data")
        return 1
    if want_flow:
        for rows in (his, ours):
            for r in rows:
                snaps = r["snaps"]
                prev = None
                flow = {}
                for d in range(0, a.cut_day + 1):
                    cur = snaps.get(str(d))
                    if cur is None:
                        continue
                    if prev is not None:
                        flow[str(d)] = {"cash_flow": cur["money"] - prev}
                    prev = cur["money"]
                for k, v in flow.items():
                    snaps.setdefault(k, {}).update(v)
        keys = list(keys) + ["cash_flow"]
    print(f"   {len(his)} episodes per arm\n")
    opens = {}
    for k in keys:
        print(f"   == {k} ==")
        print(f"   {'day':>4}{'ours':>10}{'his':>10}{'delta':>9}{'gap%':>9}")
        first = None
        for d in range(lo, hi + 1):
            o, h = _med(ours, d, k), _med(his, d, k)
            if o is None or h is None:
                continue
            dlt = o - h
            if abs(h) > 1e-9:
                pct = dlt / h * 100.0
                txt = f"{pct:+.1f}%"
                good = abs(pct) <= a.tol
            else:
                txt = "n/a" if abs(o) > 1e-9 else "0.0%"
                good = abs(o) <= 1e-9
            if not good and first is None:
                first = d
            print(f"   {d:>4}{o:>10.1f}{h:>10.1f}{dlt:>+9.1f}{txt:>9}"
                  f"{'  <-- gap opens' if d == first and first is not None else ''}")
        opens[k] = first
        if first is None:
            print(f"        WITHIN {a.tol}% for every day d{lo}-d{hi}")
        else:
            print(f"        first day outside {a.tol}%: d{first}")
    print("\n   == SUMMARY: the day each gap opens ==")
    for k in keys:
        print(f"   {k:<14}{('d' + str(opens[k])) if opens[k] is not None else 'never':>8}")
    ok = sum(1 for k in keys if opens[k] is None)
    print(f"   WITHIN {a.tol}% ALL DAYS: {ok}/{len(keys)}")
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"his": his, "ours": ours, "opens": opens}, default=str))
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
