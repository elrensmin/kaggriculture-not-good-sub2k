#!/usr/bin/env python
"""arm_diff — matched-pair diff of two harness run dirs (A vs B).

The anti-goal is explicit: never trust a cross-game mean, and never compare two
arms unless the *seeds and opponents* are identical. A code change cannot be
A/B'd by a single run, so the workflow is:

    SCRATCH_PARAMS='...'  python -m tools.diagnose --scratch ... --run-dir diag-replays/arm-a
                          python -m tools.diagnose --scratch ... --run-dir diag-replays/arm-b
    PYTHONPATH=. python -m tools.report.arm_diff --a diag-replays/arm-a \
        --b diag-replays/arm-b --label-a 'old' --label-b 'new'

It joins the two `games.csv` on ``(opponent, seed)`` and reports, per pair and
per opponent:

  * ``final_money`` delta (B - A) — the low-noise readout;
  * WIN/LOSS for each arm (the actual objective) and how the verdict flipped;
  * a sign test over the deltas (how many pairs B won, and a binomial p);
  * the defect columns that must not regress (idle, floor sales, escapes,
    plants died, unwatered, discarded, stranded, premium below base, revenue).

Only pairs present in BOTH dirs are used; anything else is reported as unmatched
so a partial run can never silently flatter an arm.

Usage:
  PYTHONPATH=. python -m tools.report.arm_diff --a D1 --b D2 [--csv out.csv]
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics as st

MONEY = "final_money"
DEFECTS = [
    ("idle_share_pct", "worse"),
    ("idle_units_ready_total", "worse"),
    ("idle_units_total", "worse"),
    ("floor_sales", "worse"),
    ("discarded_units_total", "worse"),
    ("stranded_at_bell", "worse"),
    ("premium_below_base_frac", "worse"),
    ("animal_escapes", "worse"),
    ("plants_died", "worse"),
    ("unwatered_eod", "worse"),
    ("missed_harvest_eod", "worse"),
    ("shed_overflow_days", "worse"),
    ("sell_revenue_total", "better"),
]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _load(run_dir):
    path = os.path.join(run_dir, "games.csv")
    if not os.path.exists(path):
        raise SystemExit(f"no games.csv in {run_dir}")
    rows = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            key = (r.get("opponent", ""), str(r.get("seed", "")))
            rows[key] = r
    return rows


def _binom_p(k, n):
    """Two-sided sign-test p-value under p=0.5."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _q(xs, f):
    xs = sorted(xs)
    if not xs:
        return 0.0
    i = min(len(xs) - 1, max(0, int(round(f * (len(xs) - 1)))))
    return xs[i]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--csv", default=None, help="write the per-pair table here")
    args = ap.parse_args()

    A, B = _load(args.a), _load(args.b)
    keys = sorted(set(A) & set(B), key=lambda k: (k[0], k[1]))
    only_a, only_b = set(A) - set(B), set(B) - set(A)

    if not keys:
        # Diagnose the usual cause instead of only reporting the symptom. `tools.diagnose`
        # leaves `--seed` at None, which draws RANDOM seeds per run -- two arms of the same
        # command then share no (opponent, seed) key at all, and a whole sweep is wasted.
        # Always pass an explicit `--seed` to both arms.
        sa = {k[1] for k in A}
        sb = {k[1] for k in B}
        shared_opp = {k[0] for k in A} & {k[0] for k in B}
        msg = ["no matched (opponent, seed) pairs — arms are not comparable"]
        if shared_opp and not (sa & sb):
            msg.append(f"  the opponents overlap ({len(shared_opp)}) but the SEED SETS are "
                       f"disjoint: A has {len(sa)} seeds, B has {len(sb)}, none shared.")
            msg.append("  Cause: `tools.diagnose` defaults `--seed` to None and then draws "
                       "RANDOM seeds. Re-run BOTH arms with the same explicit `--seed N`.")
        elif not shared_opp:
            msg.append("  the opponent sets do not overlap either — check `--pa`.")
        raise SystemExit("\n".join(msg))

    print(f"arm A = {args.label_a}  ({args.a})  {len(A)} games")
    print(f"arm B = {args.label_b}  ({args.b})  {len(B)} games")
    print(f"matched pairs: {len(keys)}   unmatched: {len(only_a)} only-A, "
          f"{len(only_b)} only-B")
    if only_a or only_b:
        print("  !! partial run — verdict below uses matched pairs only")

    deltas, wa, wb, flips = [], 0, 0, []
    per_opp: dict[str, list] = {}
    rows_out = []
    for k in keys:
        a, b = A[k], B[k]
        da, db = _num(a[MONEY]), _num(b[MONEY])
        d = db - da
        deltas.append(d)
        ra, rb = a.get("result", ""), b.get("result", "")
        wa += ra == "WIN"
        wb += rb == "WIN"
        if ra != rb:
            flips.append((k, ra, rb, d))
        per_opp.setdefault(k[0], []).append(d)
        row = {"opponent": k[0], "seed": k[1], "a_money": da, "b_money": db,
               "delta": d, "a_result": ra, "b_result": rb}
        for col, _dir in DEFECTS:
            row[f"d_{col}"] = _num(b.get(col)) - _num(a.get(col))
        rows_out.append(row)

    n_up = sum(1 for d in deltas if d > 0)
    n_dn = sum(1 for d in deltas if d < 0)
    p = _binom_p(min(n_up, n_dn), n_up + n_dn)

    print(f"\n=== MARGIN (the low-noise readout, NOT the score) ===")
    print(f"  {args.label_a}: W{wa}  {args.label_b}: W{wb}   (of {len(keys)} pairs)")
    print(f"  delta money  median {st.median(deltas):+,.0f}   "
          f"mean {st.mean(deltas):+,.0f}   min {min(deltas):+,.0f}   "
          f"max {max(deltas):+,.0f}")
    print(f"  p10 {_q(deltas,.1):+,.0f}  p25 {_q(deltas,.25):+,.0f}  "
          f"p75 {_q(deltas,.75):+,.0f}  p90 {_q(deltas,.9):+,.0f}")
    print(f"  sign test: B better in {n_up}/{n_up+n_dn} decided pairs   p={p:.4f}")
    if flips:
        print(f"  verdict flips ({len(flips)}):")
        for (opp, seed), ra, rb, d in flips:
            print(f"     {opp[:44]:<44} seed {seed:<6} {ra:>4} -> {rb:<4} "
                  f"{d:+,.0f}")

    print(f"\n=== per opponent (median delta, wins A -> B) ===")
    for opp in sorted(per_opp):
        ds = per_opp[opp]
        w_a = sum(1 for k in keys if k[0] == opp and A[k].get("result") == "WIN")
        w_b = sum(1 for k in keys if k[0] == opp and B[k].get("result") == "WIN")
        print(f"  {opp[:44]:<44} n={len(ds):<2} median {st.median(ds):+9,.0f}  "
              f"W {w_a} -> {w_b}")

    print(f"\n=== defect columns (median delta; sign = B - A) ===")
    for col, good in DEFECTS:
        ds = [r[f"d_{col}"] for r in rows_out]
        med = st.median(ds)
        nbad = sum(1 for d in ds if (d > 0) == (good == "worse") and abs(d) > 1e-9)
        flag = ""
        if nbad > len(ds) / 2 and abs(med) > 1e-9:
            flag = "  <-- majority moved the WRONG way"
        print(f"  {col:<26} {med:+12,.3f}   ({nbad}/{len(ds)} worse){flag}")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows_out[0]))
            w.writeheader()
            w.writerows(rows_out)
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
