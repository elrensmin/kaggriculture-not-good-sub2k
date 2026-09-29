#!/usr/bin/env python
"""phase_revenue — the midgame money race, seat-symmetric, over many seeds.

Why this exists
---------------
`phase_map` judges structure, and its phase-2 table had no money in it at all, so a whole
round of midgame work was done without ever asking whether the midgame EARNED more. A
margin over a whole season is the wrong instrument for that: it mixes d0-d5 and d18-29
into one number, and the public agents win or lose the season on the endgame.

This tool asks one question per game: **in days A-B, did we out-earn the opponent?**

Both seats are measured with the *same* estimator (`phase_map.extract`):
  * `TRADE_NET` — the exact ledger identity `d_money + fixed spend = sells - product
    buys`, from the money the engine actually moved. **This is the number to judge**, and
    the only one that is fair across seats.
  * `REVENUE` — every SELL order valued at that step's observed quote, capped by the
    shed and by `MAX_ORDERS`. Validated at 0.970 median against the market audit **for our
    own seat**, because our agent sizes each SELL from the shed it can see. It is NOT
    trustworthy for an opponent that over-orders (a public agent issued 579 units of SELL
    orders from a shed holding 262): it under-counts them by ~2x. Treat the `rev x` column
    as a floor for the opponent, or use `--audit-dir` for our own exact number.

Aggregation follows AGENTS.md: per-opponent **median**, then median across opponents —
never a pooled mean.

Usage
-----
  PYTHONPATH=. python -m tools.report.phase_revenue --days 11-20 --dir diag-replays/step10-ship
  PYTHONPATH=. python -m tools.report.phase_revenue --days 11-20 \
      --dir diag-replays/step10-pre --compare diag-replays/step10-ship
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import team as team_mod                      # noqa: E402
from tools.diagnose.window import in_window, parse_days    # noqa: E402
from tools.phases.phase_map import extract              # noqa: E402


def _steps(rep):
    return rep["steps"] if isinstance(rep, dict) else rep.steps


def _our_seat(rep):
    """Seat of the agent under test: the scratch row is always seat 1."""
    return 1


def _seat_flow(rep, seat, window):
    days = extract(rep, seat)
    rev = net = 0.0
    for d, rec in days.items():
        if not in_window(d, window):
            continue
        rev += rec["flow"].get("REVENUE", 0.0)
        net += rec["flow"].get("TRADE_NET", 0.0)
    return rev, net


def scan(run_dir, window, glob="*.json"):
    """[(opponent, seed, our_rev, our_net, opp_rev, opp_net)] over the run dir."""
    out = []
    for path in sorted(globmod.glob(str(Path(run_dir) / glob))):
        try:
            rep = json.load(open(path))
        except Exception:
            continue
        steps = _steps(rep)
        if not steps or len(steps[0]) < 2:
            continue
        me = _our_seat(rep)
        opp = 1 - me
        names = (rep.get("info") or {}).get("TeamNames") or []
        opp_name = names[opp] if len(names) > opp and names[opp] else None
        if not opp_name:
            # the harness names replays scratch_vs_<opponent>_seed<N>.json
            stem = Path(path).stem
            opp_name = stem.split("_seed")[0]
            if "_vs_" in opp_name:
                opp_name = opp_name.split("_vs_", 1)[1]
        seed = rep.get("info", {}).get("seed")
        if seed is None:
            seed = (rep.get("info") or {}).get("EpisodeId")
        rv, nt = _seat_flow(rep, me, window)
        ov, on = _seat_flow(rep, opp, window)
        out.append((opp_name, seed, rv, nt, ov, on))
    return out


def _median(xs):
    return statistics.median(xs) if xs else 0.0


def report(label, rows):
    if not rows:
        print(f"=== {label}: no games ===")
        return {}
    per_opp = defaultdict(list)
    for opp, _seed, rv, nt, ov, on in rows:
        per_opp[opp].append((rv, nt, ov, on))
    print(f"=== {label}   {len(rows)} games, {len(per_opp)} opponents ===")
    print(f"   {'opponent':44s} {'n':>3s} {'our rev':>10s} {'opp rev':>10s} {'rev x':>6s}"
          f" {'our net':>10s} {'opp net':>10s} {'net x':>6s} {'net>0':>6s}")
    rev_ratios, net_ratios, wins = [], [], 0
    for opp in sorted(per_opp):
        g = per_opp[opp]
        rv, nt = _median([x[0] for x in g]), _median([x[1] for x in g])
        ov, on = _median([x[2] for x in g]), _median([x[3] for x in g])
        wins += sum(1 for x in g if x[1] > x[3])
        rr = rv / ov if ov else float("nan")
        nr = nt / on if on else float("nan")
        rev_ratios.append(rr)
        net_ratios.append(nr)
        print(f"   {opp[:44]:44s} {len(g):3d} {rv:10,.0f} {ov:10,.0f} {rr:6.2f}"
              f" {nt:10,.0f} {on:10,.0f} {nr:6.2f} {wins:6d}")
    tot_rev = _median([r[2] for r in rows])
    tot_net = _median([r[3] for r in rows])
    tot_orev = _median([r[4] for r in rows])
    tot_onet = _median([r[5] for r in rows])
    print(f"   {'-- median across opponents --':44s} {'':3s} "
          f"{_median([_median([x[0] for x in g]) for g in per_opp.values()]):10,.0f} "
          f"{_median([_median([x[2] for x in g]) for g in per_opp.values()]):10,.0f} "
          f"{_median(rev_ratios):6.2f} "
          f"{_median([_median([x[1] for x in g]) for g in per_opp.values()]):10,.0f} "
          f"{_median([_median([x[3] for x in g]) for g in per_opp.values()]):10,.0f} "
          f"{_median(net_ratios):6.2f} {wins:4d}/{len(rows)}")
    print(f"   pooled game medians: our rev {tot_rev:,.0f} vs {tot_orev:,.0f}   "
          f"our net {tot_net:,.0f} vs {tot_onet:,.0f}   "
          f"net-positive games {sum(1 for r in rows if r[3] > 0)}/{len(rows)}   "
          f"net beats opponent in {sum(1 for r in rows if r[3] > r[5])}/{len(rows)}")
    print()
    return {"rev_x": _median(rev_ratios), "net_x": _median(net_ratios),
            "our_rev": tot_rev, "opp_rev": tot_orev,
            "our_net": tot_net, "opp_net": tot_onet,
            "net_beats": sum(1 for r in rows if r[3] > r[5]), "n": len(rows)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="11-20")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--compare", default=None)
    ap.add_argument("--label", default=None)
    a = ap.parse_args(argv)
    window = parse_days(a.days)
    rows = scan(a.dir, window, a.glob)
    ra = report(a.label or Path(a.dir).name, rows)
    if a.compare:
        rows_b = scan(a.compare, window, a.glob)
        report(Path(a.compare).name, rows_b)
        # PAIRED, like `arm_diff`. Comparing per-arm medians is NOT the same thing and
        # MEASURED it reverses the sign: the round-7 portfolio read +$7.5k of revenue on
        # unpaired medians and **−$4.7k paired** (median of per-game deltas), with the
        # season at −$14,004. Always read these two lines, never the table above.
        ka = {(r[0], r[1]): r for r in rows}
        kb = {(r[0], r[1]): r for r in rows_b}
        keys = sorted(set(ka) & set(kb))
        if keys:
            dr = sorted(kb[k][2] - ka[k][2] for k in keys)
            dn = sorted(kb[k][3] - ka[k][3] for k in keys)
            dv = sorted((kb[k][3] - kb[k][5]) - (ka[k][3] - ka[k][5]) for k in keys)
            def _med(v):
                return statistics.median(v) if v else 0.0
            print(f"=== PAIRED over {len(keys)} matched (opponent, seed) pairs ===")
            print(f"   our revenue   median delta {_med(dr):+12,.0f}   "
                  f"better in {sum(1 for x in dr if x > 0)}/{len(dr)}")
            print(f"   our trade net median delta {_med(dn):+12,.0f}   "
                  f"better in {sum(1 for x in dn if x > 0)}/{len(dn)}")
            print(f"   net ADVANTAGE median delta {_med(dv):+12,.0f}   "
                  f"better in {sum(1 for x in dv if x > 0)}/{len(dv)}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
