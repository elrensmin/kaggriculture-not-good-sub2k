#!/usr/bin/env python
"""fertilizer_flow — where does the herd's fertilizer actually go?

Why this exists
---------------
`src/sell_policy.py` opens with "FERTILIZER (nobody buys it): dump past a reserve", and
`src/market.py` excludes FERTILIZER from `TOWN_CENTER_BUYS`. Both are **false**: the #1 sells a
median of **266 units a game**, a first-class revenue line. So the question is not whether to
fertilize (that op is separately priced and negative at our movement cost) but **how much of the
fertilizer we collect do we actually sell, and where does the rest go**.

Flow identity, all measurable from the replay stream (no audit needed):

    collected + bought - fertilized - sold - delta_shed = discarded_at_eod

`COLLECT_FERTILIZER` ops move one unit per op from an animal tile to the worker, then it lands in
the shed; `FERTILIZE` ops consume one unit each; `SELL FERTILIZER` orders carry the quantity, and
the quoted price is in the same frame's `market.prices`.

Runs identically on the #1's replays and on ours.

Usage
-----
  PYTHONPATH=. python -m tools.market.fertilizer_flow --dir replays/DSM/v1 --max 30
  PYTHONPATH=. python -m tools.market.fertilizer_flow --agent --pa 1-12 --batch 2
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor

TURNS = 24


def _dsm_seats(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    out = [i for i, n in enumerate(names) if "DSM" in (n or "").upper()]
    return out or [0]


def scan_steps(steps, seat):
    A = collections.Counter()
    shed_prev = None
    for t in range(len(steps)):
        if len(steps[t]) <= seat:
            continue
        o = steps[t][seat].get("observation")
        if not o:
            continue
        shed = (o.get("private") or {}).get("shed") or {}
        f_now = int(shed.get("FERTILIZER", 0))
        if t == 0:
            A["shed_start"] = f_now
        A["shed_end"] = f_now
        if t + 1 >= len(steps) or len(steps[t + 1]) <= seat:
            continue
        a = steps[t + 1][seat].get("action")
        if not a:
            continue
        prices = (o.get("market") or {}).get("prices") or {}
        for cmd in [a.get("farmer")] + list(a.get("hands") or []):
            if cmd and cmd[0] == "COLLECT_FERTILIZER":
                A["collected"] += 1
            elif cmd and cmd[0] == "FERTILIZE":
                A["fertilized"] += 1
        for m in (a.get("market") or []):
            if not isinstance(m, list) or len(m) < 3:
                continue
            if m[0] == "SELL" and m[1] == "FERTILIZER":
                A["sold"] += m[2]
                A["revenue"] += m[2] * prices.get("FERTILIZER", 0)
            elif m[0] == "BUY_PRODUCT" and len(m) >= 3 and m[1] == "FERTILIZER":
                A["bought"] += m[2]
        shed_prev = f_now
    # price reference at the end (the curve floors at I0+493)
    A["px_end"] = (o.get("market") or {}).get("prices", {}).get("FERTILIZER", 0)
    A["discarded"] = (A["collected"] + A["bought"] - A["fertilized"] - A["sold"]
                      - (A["shed_end"] - A["shed_start"]))
    return dict(A)


def scan_replay(path, seat=None):
    rep = json.load(open(path))
    if seat is None:
        seat = _dsm_seats(rep)[0]
    a = scan_steps(rep["steps"], seat)
    a["_file"] = os.path.basename(path)
    return a


def _work(path, seat):
    try:
        return scan_replay(path, seat)
    except Exception as e:                                    # pragma: no cover
        return {"_file": os.path.basename(path), "_error": repr(e)}


def report(rows, label):
    rows = [r for r in rows if "_error" not in r]
    if not rows:
        print(f"\n  {label}: no usable games")
        return
    def med(k):
        return st.median([r.get(k, 0) for r in rows])

    print(f"\n{'='*88}\n  {label}   ({len(rows)} games)\n{'='*88}")
    print(f"  {'collected (COLLECT ops)':36} {med('collected'):>9.1f}")
    print(f"  {'bought':36} {med('bought'):>9.1f}")
    print(f"  {'fertilized (FERTILIZE ops)':36} {med('fertilized'):>9.1f}")
    print(f"  {'SOLD (units)':36} {med('sold'):>9.1f}")
    print(f"  {'sold / collected':36} "
          f"{(med('sold')/med('collected') if med('collected') else 0):>9.0%}")
    print(f"  {'revenue ($)':36} {med('revenue'):>9,.0f}")
    print(f"  {'avg price ($/unit)':36} "
          f"{(med('revenue')/med('sold') if med('sold') else 0):>9.1f}")
    print(f"  {'shed FERTILIZER at end':36} {med('shed_end'):>9.1f}")
    print(f"  {'discarded at EOD (derived)':36} {med('discarded'):>9.1f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="replays/DSM/v1")
    ap.add_argument("--seat", type=int, default=None)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--agent", action="store_true")
    ap.add_argument("--pa", default="1-12")
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--label", default=None)
    a = ap.parse_args()

    if a.agent:
        import sys
        sys.path.insert(0, ".")
        from tools.diagnose.agents import load_public_agent
        from tools.diagnose.games import run_game

        def fresh():
            for m in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
                del sys.modules[m]
            import src
            return src.agent

        pa = []
        for part in str(a.pa).split(","):
            if "-" in part:
                lo, hi = part.split("-")
                pa += list(range(int(lo), int(hi) + 1))
            else:
                pa.append(int(part))
        rows = []
        for opp in pa:
            for b in range(a.batch):
                s = a.seed + b * 7919
                env = run_game(fresh(), load_public_agent(opp), seed=s, seat=1,
                               audit=False)
                steps = env.steps if hasattr(env, "steps") else env["steps"]
                r = scan_steps(steps, 1)
                r["_file"] = f"pa{opp}_s{s}"
                rows.append(r)
        report(rows, a.label or f"US (agents {a.pa} x {a.batch})")
        return

    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))
    if a.max:
        files = files[:a.max]
    if not files:
        print(f"no replays in {a.dir}")
        return
    with ProcessPoolExecutor(max_workers=a.workers or None) as ex:
        rows = list(ex.map(_work, files, [a.seat] * len(files)))
    report(rows, a.label or f"{a.dir} (seat auto)")


if __name__ == "__main__":
    main()
