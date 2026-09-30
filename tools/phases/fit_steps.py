#!/usr/bin/env python
"""fit_steps -- 720 INDEPENDENT graph-weight sets, one per step, from the step parquet.

The idea this implements: a game is 720 steps, and the decision at step t depends on the STATE at
step t and the position in the season. So fit step t separately -- every game contributes exactly
one observation to each bucket -- and keep 720 weight vectors instead of 5.

Why this is not the overfitting that a "finer partition" argument would predict
-------------------------------------------------------------------------------
The buckets are fit INDEPENDENTLY, so the parameter count that matters is per bucket, not the total.
Each bucket sees 359 games (287 train under an 80/20 split BY GAME) against only the handful of
nodes that LICENSE the op (`NODES[node].ops`), so ~50-140 observations per parameter per bucket.
That is a *better* ratio than the 5-window day fit, and it is why step resolution is affordable
here while a joint 720-bucket fit would not be.

The honest readout
------------------
A per-step intercept already predicts "what he does at this point in the season" -- his opening is
near-deterministic, so early steps have almost no variance to explain. The number that says whether
the GRAPH carries signal is therefore `d_r2`: the held-out gain over the intercept-only model at the
same step. `r2` alone is mostly the tape.

Usage
-----
  PYTHONPATH=. python -m tools.phases.fit_steps --data artifacts/boey_steps.parquet
  PYTHONPATH=. python -m tools.phases.fit_steps --data ... --codegen src/graph_steps.py
  PYTHONPATH=. python -m tools.phases.fit_steps --data ... --smooth 5      # rolling weights
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np                                                          # noqa: E402

from src import state_graph as sg                                           # noqa: E402
from tools.phases.build_steps import MARKET_OPS, UNIT_OPS                   # noqa: E402

OPS = UNIT_OPS + MARKET_OPS
MIN_D_R2 = 0.05


def features_for(op):
    """The feature columns the graph LICENSES for this op, both signs, plus the price ratios.

    Licensing is the whole point: `NODES[node].ops` is the DAG's own statement of which node may
    drive which op. A fit that reaches outside it learns the season (measured: 8 of WATER's 9
    learned edges were unlicensed, and the crew allocation driven by that table cost -$42,606).
    The price ratios are included for every op because a price IS a cause: it is public, it moves
    every step, and `sell high / buy back low` is the whole trading policy.
    """
    feats = []
    for node in sorted(sg.NODES):
        if op in (getattr(sg.NODES[node], "ops", None) or ()):
            for pre in ("def_", "exc_"):
                feats.append(f"{pre}{node}")
    if op.startswith(("SELL_", "BUY_PRODUCT_")):
        item = op.split("_", 2)[-1]
        feats.append(f"pxr_{item}")
    feats += [f"pxr_{p}" for p in ("WHEAT", "FERTILIZER")]
    # de-dup, keep order
    return list(dict.fromkeys(feats))


def main(argv=None):
    import pandas as pd
    from scipy.optimize import nnls

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="artifacts/boey_steps.parquet")
    ap.add_argument("--train-frac", type=float, default=0.8)
    ap.add_argument("--smooth", type=int, default=0,
                    help="rolling window (in steps) applied to the fitted weights before eval")
    ap.add_argument("--codegen", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--ops", default=None, help="comma list; default = the unit ops")
    a = ap.parse_args(argv)

    df = pd.read_parquet(a.data)
    ops = a.ops.split(",") if a.ops else list(UNIT_OPS)
    games = sorted(df["game"].unique())
    cut = max(1, min(len(games) - 1, int(round(len(games) * a.train_frac))))
    train_g, test_g = set(games[:cut]), set(games[cut:])
    n_steps = int(df["step"].max()) + 1
    print(f"# fit_steps  {len(df):,} rows, {len(games)} games, {n_steps} steps")
    print(f"   split BY GAME {a.train_frac:.0%}/{1 - a.train_frac:.0%} = "
          f"{len(train_g)} train / {len(test_g)} held-out")
    if a.smooth:
        print(f"   rolling weight smoothing: {a.smooth} steps")

    is_tr = df["game"].isin(train_g).to_numpy()
    is_te = df["game"].isin(test_g).to_numpy()
    by_step = df.groupby("step").indices        # {step: positional index array}

    W, report = {}, {}
    print(f"\n   {'op':<20}{'steps':>7}{'R2 med':>9}{'dR2 med':>9}{'%dR2>0':>8}{'params':>8}")
    for op in ops:
        ycol = f"n_{op}"
        if ycol not in df.columns:
            continue
        feats = [f for f in features_for(op) if f in df.columns]
        if not feats:
            report[op] = {"note": "no licensed features present in the parquet"}
            print(f"   {op:<20}{'-':>7}{'-':>9}{'-':>9}{'-':>8}{'-':>8}   no licensed features")
            continue
        y = df[ycol].to_numpy(float)
        # belt-and-braces: a feature column that is absent for a step is no signal, not NaN
        Xall = df[feats].fillna(0.0).to_numpy(float)
        raw = np.zeros((n_steps, len(feats) + 1))
        r2s, dr2s, nfit = [], [], 0
        for step in range(n_steps):
            idx = by_step.get(step)
            if idx is None:
                continue
            itr, ite = idx[is_tr[idx]], idx[is_te[idx]]
            if len(itr) < 20 or len(ite) < 10:
                continue
            Xtr = np.hstack([Xall[itr], np.ones((len(itr), 1))])
            Xte = np.hstack([Xall[ite], np.ones((len(ite), 1))])
            ytr, yte = y[itr], y[ite]
            if yte.var() <= 0:
                continue
            scale = np.where(Xtr[:, :-1].max(axis=0) > 0, Xtr[:, :-1].max(axis=0), 1.0)
            Xtr_s = np.hstack([Xtr[:, :-1] / scale, Xtr[:, -1:]])
            w, _ = nnls(Xtr_s, ytr)
            pred = np.hstack([Xte[:, :-1] / scale, Xte[:, -1:]]) @ w
            r2 = 1.0 - ((yte - pred) ** 2).sum() / ((yte - yte.mean()) ** 2).sum()
            wb, _ = nnls(Xtr[:, -1:], ytr)
            r2b = 1.0 - ((yte - Xte[:, -1:] @ wb) ** 2).sum() / ((yte - yte.mean()) ** 2).sum()
            raw[step] = np.append(w[:-1] / scale, w[-1])
            r2s.append(r2)
            dr2s.append(r2 - r2b)
            nfit += 1
        if a.smooth and nfit:
            k = a.smooth
            pad = np.pad(raw, ((k // 2, k - 1 - k // 2), (0, 0)), mode="edge")
            raw = np.stack([pad[i:i + k].mean(axis=0) for i in range(n_steps)])
            r2s, dr2s = [], []
            for step in range(n_steps):
                idx = by_step.get(step)
                if idx is None:
                    continue
                ite = idx[is_te[idx]]
                if len(ite) < 10 or y[ite].var() <= 0:
                    continue
                Xte = np.hstack([Xall[ite], np.ones((len(ite), 1))])
                scale = np.where(Xall[is_tr].max(axis=0) > 0, Xall[is_tr].max(axis=0), 1.0) \
                    if is_tr.any() else np.ones(len(feats))
                pred = np.hstack([Xte[:, :-1] / scale, Xte[:, -1:]]) @ raw[step]
                yte = y[ite]
                r2s.append(1.0 - ((yte - pred) ** 2).sum() / ((yte - yte.mean()) ** 2).sum())
                dr2s.append(np.nan)
        med_r2 = float(np.median(r2s)) if r2s else float("nan")
        med_d = float(np.nanmedian(dr2s)) if dr2s else float("nan")
        pct = 100.0 * float(np.mean([d > MIN_D_R2 for d in dr2s if not np.isnan(d)])) if dr2s else 0.0
        W[op] = {int(s): {f: round(float(raw[s][i]), 4) for i, f in enumerate(feats)
                          if raw[s][i] > 0} for s in range(n_steps)
                 if raw[s][:len(feats)].sum() > 0}
        report[op] = {"steps_fitted": nfit, "median_r2": round(med_r2, 3),
                      "median_d_r2": round(med_d, 3), "pct_steps_d_r2_gt_0.05": round(pct, 1),
                      "params": len(feats) + 1, "features": feats}
        print(f"   {op:<20}{nfit:>7}{med_r2:>9.3f}{med_d:>9.3f}{pct:>7.1f}%{len(feats) + 1:>8}")

    good = {o: r for o, r in report.items() if r.get("median_d_r2", 0) > MIN_D_R2}
    print(f"\n   ops whose step-weights BEAT the per-step intercept on held-out games "
          f"(dR2 > {MIN_D_R2}): {len(good)}/{len(report)}")
    for o, r in sorted(good.items(), key=lambda kv: -kv[1]["median_d_r2"]):
        print(f"      {o:<20} dR2 {r['median_d_r2']:+.3f}   on {r['pct_steps_d_r2_gt_0.05']:.0f}% "
              f"of steps   ({r['params']} params: {', '.join(r['features'][:6])})")

    if a.out_json:
        Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_json).write_text(json.dumps({"report": report}, indent=1))
        print(f"\nwrote {a.out_json}")
    if a.codegen:
        L = ['"""graph_steps -- node->op weights LEARNED PER STEP (720 buckets) from the reference replays.',
             '',
             'GENERATED by `tools/phases/fit_steps.py` from `artifacts/boey_steps.parquet`.',
             'Features are the graph\'s OWN licensed edges (`NODES[node].ops`), so a weight is "how hard',
             'this shortfall drives this op at this step", never "is this edge real" -- that is the DAG\'s',
             'call. `def_` = deficient against target, `exc_` = ahead of target.',
             '',
             'CAUSAL PAIRING: fitted on state(steps[t]) -> action(steps[t+1]), the pair the engine',
             'guarantees, NOT the reverse. See tools/phases/build_steps.py.',
             '"""',
             'from __future__ import annotations', '', 'W = {']
        for op, blk in W.items():
            L.append(f'    {op!r}: {{')
            for s, ff in sorted(blk.items()):
                L.append(f'        {s}: {{' + ', '.join(f'{n!r}: {v}' for n, v in ff.items()) + '},')
            L.append('    },')
        L += ['}', '', 'def weights_for(op, step):',
              '    """The learned weights for this op at this step."""',
              '    return W.get(op, {}).get(int(step), {})', '']
        Path(a.codegen).write_text("\n".join(L))
        n_entries = sum(len(f) for blk in W.values() for f in blk.values())
        print(f"wrote {a.codegen}  ({len(W)} ops, {sum(len(b) for b in W.values())} step-buckets, "
              f"{n_entries} weights)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
