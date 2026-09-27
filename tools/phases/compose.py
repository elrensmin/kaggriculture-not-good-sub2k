"""tools/phases/compose.py — the portfolio / interaction evaluator.

Non-composability is the reason hill-climbing lies here: E[M] is linear, but the thing
we score is a ratio (Pr[win] ≈ Φ(μ/σ)) and revenue is concave in the shared inventory.
A change measured alone can reverse sign when a second change lands, and the DAG warns
about exactly this (a ROOT with a big blast radius is a hypothesis, not a verdict).

`arm_diff` compares two arms. This tool compares a **portfolio**: it runs the baseline,
each candidate `SCRATCH_PARAMS` arm, and every combination (2^k, k <= 3), all on the
same seeds, and reports

  * each arm's paired median margin delta vs baseline,
  * each combination's **interaction term**  I = margin(AB) - margin(A) - margin(B) + margin(base)
    on matched (opponent, seed) pairs, with a sign test,
  * a verdict per combination: additive / synergy / antagonism.

Each arm runs in its own subprocess because `src.params` reads `SCRATCH_PARAMS` at import
and the harness's in-process `load_agent(fresh=True)` does NOT re-execute `src.params`
(see tools/readme.md). Subprocess isolation is what makes the measurement honest.

Usage:
  PYTHONPATH=. python -m tools.phases.compose --pa 1-12 --batch 4 --seed 4362837462 \
      --spec 'hold=RING_DYNAMIC=1' \
      --spec 'herd=OPENING_HERD_COW=4;OPENING_HERD_GOOSE=2'
"""
from __future__ import annotations

import argparse
import csv
import itertools
import os
import statistics as st
import subprocess
import sys
from pathlib import Path

PY = sys.executable


def _margin(row):
    try:
        return float(row["final_money"]) - float(row["opponent_final"])
    except (KeyError, TypeError, ValueError):
        return None


def run_arm(label, params, pa, batch, seed, root):
    """Run one arm in a fresh subprocess (env is read at import). Return its run dir."""
    out = Path(root) / label
    if (out / "games.csv").is_file():
        print(f"   [cached] {label}")
        return out
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    if params:
        env["SCRATCH_PARAMS"] = params
    else:
        env.pop("SCRATCH_PARAMS", None)
    cmd = [PY, "-m", "tools.diagnose", "--scratch", "--pa", str(pa),
           "--batch", str(batch), "--seed", str(seed), "--run-dir", str(out)]
    print(f"   [run]    {label}: SCRATCH_PARAMS={params or '(baseline)'}")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"arm {label} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return out


def paired(run_dir):
    """{(opponent, seed): margin} for one arm."""
    path = Path(run_dir) / "games.csv"
    out = {}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            m = _margin(row)
            if m is not None:
                out[(row.get("opponent", ""), str(row.get("seed", "")))] = m
    return out


def median_delta(base, arm):
    diffs = [arm[k] - base[k] for k in base.keys() & arm.keys()]
    return (st.median(diffs) if diffs else 0.0), diffs


def sign_test(diffs):
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    n = pos + neg
    if n == 0:
        return pos, neg, 1.0
    # exact two-sided binomial p for the smaller tail
    from math import comb
    k = min(pos, neg)
    p = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n) * 2
    return pos, neg, min(1.0, p)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pa", default="1-12")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--root", default="diag-replays/compose")
    ap.add_argument("--spec", action="append", default=[],
                    help="LABEL=SCRATCH_PARAMS (repeat; 1-3 specs)")
    a = ap.parse_args()
    if not 1 <= len(a.spec) <= 3:
        raise SystemExit("pass 1-3 --spec")

    specs = {}
    for s in a.spec:
        if "=" not in s:
            raise SystemExit(f"bad --spec {s!r}; want LABEL=PARAMS")
        label, params = s.split("=", 1)
        specs[label] = params

    labels = list(specs)
    combos = []
    for k in range(2, len(labels) + 1):
        combos += ["+".join(c) for c in itertools.combinations(labels, k)]

    runs = {"base": run_arm("base", "", a.pa, a.batch, a.seed, a.root)}
    for lab in labels:
        runs[lab] = run_arm(lab, specs[lab], a.pa, a.batch, a.seed, a.root)
    for combo in combos:
        params = ";".join(specs[x] for x in combo.split("+"))
        runs[combo] = run_arm(combo.replace("+", "__"), params, a.pa, a.batch, a.seed, a.root)

    base = paired(runs["base"])
    print(f"\n=== COMPOSE  base={len(base)} paired games, root={a.root} ===")
    print(f"{'arm':<28}{'median d':>12}{'sign':>10}")
    for lab in labels:
        d, diffs = median_delta(base, paired(runs[lab]))
        pos, neg, p = sign_test(diffs)
        print(f"{lab:<28}{d:>12,.0f}   {pos}/{pos+neg} better  p={p:.3f}")

    print("\n=== interactions (I = AB - A - B + base, per matched pair) ===")
    for combo in combos:
        parts = combo.split("+")
        add = [paired(runs[x]) for x in parts]
        comb = paired(runs[combo])
        keys = set(base)
        for d in add + [comb]:
            keys &= set(d)
        if not keys:
            print(f"{combo:<28} no matched keys")
            continue
        inter = []
        for k in keys:
            i = comb[k] - sum(d[k] for d in add) + (len(parts) - 1) * base[k]
            inter.append(i)
        med = st.median(inter)
        pos, neg, p = sign_test(inter)
        verdict = "additive" if p > 0.2 else ("synergy" if med > 0 else "antagonism")
        print(f"{combo:<28}{med:>12,.0f}   {pos}/{pos+neg} positive  p={p:.3f}  -> {verdict}")


if __name__ == "__main__":
    main()
