#!/usr/bin/env python
"""fit_policy -- does the GRAPH's node set predict the reference's next decision, causally?

The question this answers, in one number per op: on held-out GAMES, how much better does a model
built from the graph's own licensed nodes predict what Boey does at step t+1 than a model that knows
only which step it is?

    features = state at step t          (the state the decision was made from)
    label    = op counts at step t+1    (the decision -- the pair the engine guarantees)

Three feature sets are fitted on IDENTICAL rows and the IDENTICAL 80/20 split BY GAME, so the
comparison is clean:

    bias      a per-step intercept -- "what he does at this point in the season"
    graph     the LICENSED nodes for that op (`NODES[node].ops`), both signs
    raw       the parsed board: prices, tile counts, seeds, shed, money, hands

`dR2` (feature set minus bias) is the only number that says the graph is learning anything: the
intercept already reproduces his opening tape and his daily rhythm, so a large `R2` on its own is
mostly the calendar. That was the trap in the earlier day-resolution fit, which also had the feature
and the label on the WRONG SIDES of the arrow (state sampled at the END of the day, laballed with
that day's ops) and so scored R2 +0.613 for re-learning that ops move the state.

Usage
-----
  PYTHONPATH=. python -m tools.phases.fit_policy --parsed artifacts/parsed
  PYTHONPATH=. python -m tools.phases.fit_policy --parsed artifacts/parsed --target market
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np                                                          # noqa: E402
import pandas as pd                                                         # noqa: E402

from src import state_graph as sg                                           # noqa: E402
from tools.phases.parse_replays import CROPS, ITEMS, PRODUCTS               # noqa: E402

# unit ops the graph licenses; MOVEs and PASS are the kernel's business, not the graph's
UNIT_TARGETS = ("WATER", "FERTILIZE", "HARVEST", "PLANT", "DIG", "FEED", "CARE",
                "COLLECT_FERTILIZER", "PICKUP", "DROP", "PLACE",
                "BUILD_PASTURE", "BUILD_COOP")
MARKET_TARGETS = ("SELL", "BUY_PRODUCT", "BUY_SEED", "BUY_ANIMAL", "HIRE", "BUY_LAND")
# the raw board: what any policy could read off the observation without the DAG
RAW_COLS = (["own_money", "own_hands", "own_hires_today", "own_quadrants", "riv_money",
             "riv_hands", "riv_quadrants", "n_shops", "day", "hour"]
            + [f"px_{p}" for p in PRODUCTS] + [f"inv_{p}" for p in PRODUCTS]
            + [f"seed_{c}" for c in CROPS] + [f"shed_{i}" for i in ITEMS]
            + [f"own_t_{k}" for k in ("empty", "locked", "weed", "plant", "dry",
                                      "unwatered_today", "fertilized", "coop", "coop_empty",
                                      "pasture", "pasture_empty", "unfed", "uncared",
                                      "fert_avail", "at_risk")]
            + [f"own_t_plant_{c}" for c in CROPS] + [f"own_t_animal_{a}" for a in ITEMS
                                                     if a not in PRODUCTS])


def licensed(op):
    return sorted(n for n in sg.NODES if op in (getattr(sg.NODES[n], "ops", None) or ()))


def design(df, feats):
    X = df.reindex(columns=feats).fillna(0.0).to_numpy(float)
    return np.hstack([X, np.ones((len(df), 1))])


def score(Xtr, ytr, Xte, yte):
    """-> (r2, r2_of_intercept_only). Standardises feature columns before NNLS."""
    from scipy.optimize import nnls
    if len(yte) < 10 or yte.var() <= 0 or len(ytr) < 20:
        return None, None
    sc = np.where(Xtr[:, :-1].max(axis=0) > 0, Xtr[:, :-1].max(axis=0), 1.0)
    A = np.hstack([Xtr[:, :-1] / sc, Xtr[:, -1:]])
    w, _ = nnls(A, ytr)
    pred = np.hstack([Xte[:, :-1] / sc, Xte[:, -1:]]) @ w
    r2 = 1.0 - ((yte - pred) ** 2).sum() / ((yte - yte.mean()) ** 2).sum()
    wb, _ = nnls(Xtr[:, -1:], ytr)
    r2b = 1.0 - ((yte - Xte[:, -1:] @ wb) ** 2).sum() / ((yte - yte.mean()) ** 2).sum()
    return float(r2), float(r2b)


def main(argv=None):
    from scipy.optimize import nnls                                          # noqa: F401
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parsed", default="artifacts/parsed")
    ap.add_argument("--target", default="unit", choices=["unit", "market"])
    ap.add_argument("--train-frac", type=float, default=0.8)
    ap.add_argument("--ops", default=None, help="comma list to restrict the ops fitted")
    a = ap.parse_args(argv)
    P = Path(a.parsed)

    S = pd.read_parquet(P / "states.parquet")
    S = S[S.is_ref == 1].copy()
    print(f"# fit_policy  {len(S):,} reference state-rows, {S.game.nunique()} games")

    if a.target == "unit":
        U = pd.read_parquet(P / "unit_ops.parquet")
        U = U[U.is_ref == 1]
        lab = (U.groupby(["game", "step", "seat", "op"]).size()
               .unstack(fill_value=0).reset_index())
        targets = [t for t in UNIT_TARGETS if t in lab.columns]
    else:
        O = pd.read_parquet(P / "market_orders.parquet")
        O = O[(O.is_ref == 1) & (O.kind != "NOOP")]
        lab = (O.groupby(["game", "step", "seat", "kind"]).size()
               .unstack(fill_value=0).reset_index())
        targets = [t for t in MARKET_TARGETS if t in lab.columns]
    if a.ops:
        targets = [t for t in targets if t in a.ops.split(",")]

    df = S.merge(lab, on=["game", "step", "seat"], how="inner")
    games = sorted(df.game.unique())
    cut = max(1, min(len(games) - 1, int(round(len(games) * a.train_frac))))
    tr_g, te_g = set(games[:cut]), set(games[cut:])
    is_tr = df.game.isin(tr_g).to_numpy()
    is_te = df.game.isin(te_g).to_numpy()
    by_step = df.groupby("step").indices
    print(f"   joined {len(df):,} rows; split BY GAME {a.train_frac:.0%}/{1 - a.train_frac:.0%} "
          f"= {len(tr_g)} train / {len(te_g)} held-out")
    print(f"   target: {a.target} ops -> {', '.join(targets)}\n")

    print(f"   {'op':<20}{'nodes':>6}{'bias R2':>9}{'graph R2':>10}{'dGraph':>9}"
          f"{'raw R2':>9}{'dRaw':>8}   verdict")
    rows = []
    for op in targets:
        y = df[op].to_numpy(float)
        lics = licensed(op)
        gfeat = [f"{p}{n}" for n in lics for p in ("dev_", "exc_") if f"{p}{n}" in df.columns]
        rfeat = [c for c in RAW_COLS if c in df.columns]
        # precompute the full feature arrays ONCE per op, then slice rows by index -- calling
        # `df.iloc[idx]` per step per op is ~19k fancy-index operations and dominates everything
        Xg = df.reindex(columns=gfeat).fillna(0.0).to_numpy(float) if gfeat else None
        Xr = df.reindex(columns=rfeat).fillna(0.0).to_numpy(float)
        acc = {k: [] for k in ("bias", "graph", "raw")}
        for step, idx in by_step.items():
            itr, ite = idx[is_tr[idx]], idx[is_te[idx]]
            if len(itr) < 20 or len(ite) < 10:
                continue
            ytr, yte = y[itr], y[ite]
            if yte.var() <= 0:
                continue
            r2b = score(np.ones((len(itr), 2)), ytr, np.ones((len(ite), 2)), yte)[1]
            if r2b is None:
                continue
            acc["bias"].append(r2b)
            for key, X in (("graph", Xg), ("raw", Xr)):
                if X is None:
                    continue
                r2, _ = score(np.hstack([X[itr], np.ones((len(itr), 1))]), ytr,
                              np.hstack([X[ite], np.ones((len(ite), 1))]), yte)
                if r2 is not None:
                    acc[key].append(r2 - r2b)
        if not acc["bias"]:
            print(f"   {op:<20}{len(lics):>6}   (no step had variance)")
            continue
        b = float(np.median(acc["bias"]))
        g = float(np.median(acc["graph"])) if acc["graph"] else float("nan")
        r = float(np.median(acc["raw"])) if acc["raw"] else float("nan")
        verdict = ("GRAPH" if g > 0.05 and g >= r else "RAW" if r > 0.05 else "-")
        print(f"   {op:<20}{len(lics):>6}{b:>9.3f}{b + g:>10.3f}{g:>+9.3f}"
              f"{b + r:>9.3f}{r:>+8.3f}   {verdict}")
        rows.append({"op": op, "nodes": lics, "bias_r2": round(b, 3),
                     "d_graph": round(g, 3), "d_raw": round(r, 3), "verdict": verdict,
                     "steps_scored": len(acc["bias"])})
    if rows:
        n_g = sum(1 for x in rows if x["verdict"] == "GRAPH")
        n_r = sum(1 for x in rows if x["verdict"] == "RAW")
        print(f"\n   graph nodes beat the intercept (dGraph>0.05) for {n_g}/{len(rows)} ops; "
              f"raw state for {n_r}/{len(rows)}; "
              f"{sum(1 for x in rows if x['verdict'] == '-')} ops have NO signal from either.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
