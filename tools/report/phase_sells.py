#!/usr/bin/env python
"""phase_sells — what actually got SOLD, per item and per seat, in a day window.

`phase_revenue` says the midgame earns 0.44x what the opponent does. This says *which
lines* are missing, which is the difference between "the farm produced less" (every line
down together) and "the farm never entered a product" (a line at zero).

Both seats are valued the same way: each SELL order at that step's observed quote, capped
by the shed and by the per-turn order list. No market audit is needed, so a public agent's
replay and ours are measured identically.

Usage
-----
  PYTHONPATH=. python -m tools.report.phase_sells --days 11-20 --dir diag-replays/step10-ship
  PYTHONPATH=. python -m tools.report.phase_sells --days 11-20 --dir replays/Boey/v1 --seat auto
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import params as agent_params                     # noqa: E402
from tools import team as team_mod                         # noqa: E402
from tools.diagnose.window import in_window, parse_days    # noqa: E402


def sells(rep, seat, window):
    """item -> [sell_units, sell_value, buy_units, buy_value] over the window.

    Both order types are valued at the quote the seat could see when it issued them, so
    the two seats are measured identically. SELL is capped by the shed the seat can
    deliver from (an agent that over-orders relative to its shed is under-counted, which
    is why TRADE_NET -- not this -- is the cross-seat number to judge); BUY is capped by
    nothing, so it is an upper bound on the spend.
    """
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    per_item = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for t in range(len(steps) - 1):
        if not in_window(t // 24, window):
            continue
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        obs = steps[t][seat].get("observation")
        act = steps[t + 1][seat].get("action") or {}
        if not obs:
            continue
        prices = (obs.get("market") or {}).get("prices") or {}
        shed = dict((obs.get("private") or {}).get("shed") or {})
        for o in (act.get("market") or [])[:agent_params.MAX_ORDERS]:
            if not o or len(o) < 2:
                continue          # HIRE / BUY_LAND carry no item
            px = float(prices.get(o[1], 0) or 0)
            qty = float(o[2]) if len(o) > 2 else 1.0
            e = per_item[o[1]]
            if o[0] == "SELL":
                q = min(qty, shed.get(o[1], 0.0))
                if q <= 0:
                    continue
                shed[o[1]] = shed.get(o[1], 0.0) - q
                e[0] += q
                e[1] += q * px
            elif o[0] == "BUY_PRODUCT":
                e[2] += qty
                e[3] += qty * px
    return per_item


def collect(dirpath, window, glob, seat_mode, max_games):
    total = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    n = 0
    for path in sorted(globmod.glob(str(Path(dirpath) / glob)))[:max_games]:
        rep = json.load(open(path))
        steps = rep["steps"] if isinstance(rep, dict) else rep.steps
        if not steps or len(steps[0]) < 2:
            continue
        if seat_mode == "auto":
            seat = team_mod.seat_of_names(
                (rep.get("info") or {}).get("TeamNames") or [], fallback=0)
        else:
            seat = int(seat_mode)
        for item, vals in sells(rep, seat, window).items():
            e = total[item]
            for k in range(4):
                e[k] += vals[k]
        n += 1
    return n, total


def merge(mine, theirs):
    keys = sorted(set(mine) | set(theirs),
                  key=lambda k: -(mine.get(k, [0, 0, 0, 0])[1] + theirs.get(k, [0, 0, 0, 0])[1]))
    print(f"   {'item':12s} {'our u':>9s} {'our $':>9s} {'our buy$':>9s} {'our net$':>9s}"
          f" | {'opp u':>8s} {'opp $':>9s} {'opp buy$':>9s} {'opp net$':>9s}"
          f" | {'net x':>6s}")
    tn = oon = 0.0
    for k in keys:
        mu, mr, mb, _ = mine.get(k, [0.0, 0.0, 0.0, 0.0])
        ou, orr, ob, _ = theirs.get(k, [0.0, 0.0, 0.0, 0.0])
        mn, on = mr - mb, orr - ob
        tn += mn
        oon += on
        ratio = mn / on if on else float("nan")
        print(f"   {k:12s} {mu:9,.0f} {mr:9,.0f} {mb:9,.0f} {mn:9,.0f}"
              f" | {ou:8,.0f} {orr:9,.0f} {ob:9,.0f} {on:9,.0f} | {ratio:6.2f}")
    print(f"   {'TOTAL':12s} {'':9s} {'':9s} {'':9s} {tn:9,.0f}"
          f" | {'':8s} {'':9s} {'':9s} {oon:9,.0f} | {tn/oon if oon else float('nan'):6.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="11-20")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--seat", default="1")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=20)
    ap.add_argument("--ref-from", default=None)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--ref-max", type=int, default=20)
    a = ap.parse_args(argv)
    window = parse_days(a.days)
    n, mine = collect(a.dir, window, a.glob, a.seat, a.max_games)
    print(f"### {a.dir}  seat={a.seat}  {n} games  {a.days}")
    if a.ref_from:
        rn, theirs = collect(a.ref_from, window, a.glob, a.ref_seat, a.ref_max)
        print(f"### {a.ref_from}  seat={a.ref_seat}  {rn} games")
        merge(mine, theirs)
    else:
        merge(mine, {})
    print("   # shed-capped ESTIMATE: a SELL order is capped by the seat's shed at the "
          "quote step, because\n   # audit-less arms send sentinel-sized orders. Do NOT "
          "compare a raw requested\n   # order sum against an audit-backed arm -- that is "
          "how the phantom 13.6x wheat gap was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
