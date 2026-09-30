#!/usr/bin/env python
"""arm_diff -- matched-pair diff of two run directories, judged on `result`, not on a mean.

Why this exists
---------------
`tools/diagnose` draws RANDOM seeds when `--seed` is not given, so two arms run without an explicit
seed are **not comparable** -- and the failure is silent: both runs produce plausible-looking
`games.csv` files, and a careless diff of their pooled means reports a difference that is pure seed
noise. This tool refuses to do that: it joins on `(opponent, seed)`, and when the seed sets are
disjoint it says so and stops rather than printing a number.

What it reports, and why in this order
--------------------------------------
1. **`result` (WIN/LOSS) and the verdict flips.** AGENTS.md: the ladder pays for wins, so a change
   can raise the median bank and still lose more games. Count wins first.
2. **The margin delta ladder + a sign test.** The ladder is the readout; the sign test is the
   verdict on whether the direction is real at this sample size.
3. **Per-opponent table.** Aggregate per opponent, then average -- never the reverse: a pooled rate
   folds between-opponent spread into sigma and flatters the result by ~4pt.
4. **A defect watchlist**, so a bank change can be attributed to a *mechanism* instead of accepted
   on faith. Each row names the mechanism it belongs to.

Usage
-----
  PYTHONPATH=. python -m tools.report.arm_diff --a diag-replays/arm-a --b diag-replays/arm-b
  PYTHONPATH=. python -m tools.report.arm_diff --a A --b B --quiet     # verdict lines only
"""
from __future__ import annotations

import argparse
import csv
import statistics as st
from math import comb
from pathlib import Path

# The watchlist: each defect is a *mechanism*, not a metric. A change that moves the bank must move
# one of these or it is not understood. `lower` says which direction is the good one.
#
# DELIBERATELY ABSENT, both documented in AGENTS.md as untrustworthy:
#   `unwatered_eod`    -- counts every crop without watered_today at hour 23, including plants
#                         outside their water window that will never need water again (median 622
#                         on the SHIPPED arm). Chase `plants_died` and `weeds_peak` instead.
#   `land_cost_total`  -- the purchase order is re-issued every turn and re-charged, so it reports
#                         $10,000 against a real $7,000 ceiling.
WATCH = (
    ("idle_share_pct", "labour efficiency", True),
    ("idle_units_ready_total", "missed-harvest idling", True),
    ("plants_died", "crop lifecycle", True),
    ("weeds_peak", "weed encroachment", True),
    ("animal_escapes", "herd loss", True),
    ("at_risk_of_escape", "near-miss unfed", True),
    ("shed_overflow_days", "shed overflow", True),
    ("discarded_units_total", "overflow discards", True),
    ("floor_sales", "dumping at the floor", True),
    ("stranded_at_bell", "endgame hygiene", True),
    ("missed_harvest_eod", "harvest timing", True),
    ("premium_below_base_frac", "market timing", True),
    ("sell_revenue_total", "throughput", False),
    ("harvests", "throughput", False),
)


def load(run_dir):
    p = Path(run_dir) / "games.csv"
    if not p.exists():
        raise SystemExit(f"no games.csv in {run_dir}")
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            out[(r["opponent"], r["seed"])] = r
    return out


def num(row, col):
    try:
        return float(row[col])
    except (KeyError, TypeError, ValueError):
        return None


def sign_test(deltas):
    """Exact two-sided binomial p for `#positive` out of the nonzero deltas. No scipy needed."""
    n = sum(1 for d in deltas if d != 0)
    if n == 0:
        return 0, 0, 1.0
    k = sum(1 for d in deltas if d > 0)

    def pmf(i):
        return comb(n, i) * 0.5 ** n

    p0 = pmf(k)
    return k, n, min(1.0, sum(pmf(i) for i in range(n + 1) if pmf(i) <= p0 + 1e-12))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, help="baseline run dir")
    ap.add_argument("--b", required=True, help="candidate run dir")
    ap.add_argument("--quiet", action="store_true", help="verdict lines only")
    a = ap.parse_args(argv)

    A, B = load(a.a), load(a.b)
    keys = sorted(set(A) & set(B))
    if not keys:
        shared = {o for o, _s in A} & {o for o, _s in B}
        print("no matched (opponent, seed) pairs -- arms are not comparable")
        if shared:
            print(f"  the opponents overlap ({len(shared)}) but the SEED SETS are disjoint: "
                  f"A has {len({s for _o, s in A})} seeds, B has {len({s for _o, s in B})}, "
                  f"none shared.")
            print("  Cause: `tools.diagnose` defaults `--seed` to None and then draws RANDOM seeds. "
                  "Re-run BOTH arms with the same explicit `--seed N`.")
        else:
            print("  the arms share no opponent at all -- check `--pa`.")
        return 2

    print(f"A = {a.a}\nB = {a.b}\nmatched pairs: {len(keys)}")
    d = [num(B[k], "final_money") - num(A[k], "final_money") for k in keys]

    wins_a = sum(1 for k in keys if A[k]["result"] == "WIN")
    wins_b = sum(1 for k in keys if B[k]["result"] == "WIN")
    flips = [k for k in keys if A[k]["result"] != B[k]["result"]]
    print(f"\nRESULT   A {wins_a}W-{len(keys) - wins_a}L   ->   B {wins_b}W-{len(keys) - wins_b}L")
    print(f"verdict flips: {len(flips)}")
    for k in flips:
        print(f"    {k[0][:44]:<46}{k[1]:>11}  {A[k]['result']:>4} -> {B[k]['result']:<4}"
              f"  {num(A[k], 'final_money'):>10,.0f} -> {num(B[k], 'final_money'):,.0f}")

    k_pos, n_nz, p = sign_test(d)
    print("\nMARGIN (B - A) -- the readout, not the score")
    q = st.quantiles(d, n=4) if len(d) >= 2 else [d[0]] * 3
    print(f"   min {min(d):>+11,.0f}   p25 {q[0]:>+11,.0f}   median {st.median(d):>+11,.0f}"
          f"   p75 {q[2]:>+11,.0f}   max {max(d):>+11,.0f}")
    print(f"   mean {st.mean(d):>+11,.0f}   B better in {k_pos}/{n_nz} nonzero"
          f"   sign-test p = {p:.4f}{'  ** SIGNIFICANT' if p < 0.05 else '  (not significant)'}")

    if a.quiet:
        return 0

    per = {}
    for k, dd in zip(keys, d):
        per.setdefault(k[0], []).append(dd)
    print("\nPER OPPONENT (median within opponent, then median across opponents)")
    for opp in sorted(per):
        w = sum(1 for k in keys if k[0] == opp and B[k]["result"] == "WIN")
        n = len(per[opp])
        print(f"   {opp[:44]:<46} n={n:<3} d_med {st.median(per[opp]):>+11,.0f}   B wins {w}/{n}")
    print(f"   {'MEDIAN ACROSS OPPONENTS':<46}      "
          f"{st.median([st.median(v) for v in per.values()]):>+11,.0f}")

    print("\nDEFECT WATCHLIST (paired median A -> B)")
    moved = 0
    for col, why, lower in WATCH:
        va = [num(A[k], col) for k in keys]
        vb = [num(B[k], col) for k in keys]
        if any(x is None for x in va) or any(x is None for x in vb):
            continue
        ma, mb = st.median(va), st.median(vb)
        tol = max(1.0, 0.2 * abs(ma))
        if abs(mb - ma) <= tol:
            print(f"   {col:<26}{ma:>12,.1f} -> {mb:>12,.1f}   {why}")
            continue
        moved += 1
        verdict = "BETTER" if (mb < ma) == lower else "WORSE"
        print(f"   {col:<26}{ma:>12,.1f} -> {mb:>12,.1f}   {why:<22} <<< {verdict}")
    print(f"   {moved} of {len(WATCH)} defect metrics moved materially.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
