#!/usr/bin/env python
"""causal_panel -- what does a deficient node COST? A within-game, within-day paired design.

The problem this solves
-----------------------
Imitation cannot answer "what should we do", because the reference's state is the equilibrium of
his own policy: where his policy is good (watering, melon) he never deviates, so there is nothing to
imitate. MEASURED: `dry_plants` pressure is 1.000 on every one of his 259,559 state-rows.

But every replay contains TWO farms under IDENTICAL conditions -- same seed, same day, same market
prices, same shop draws. And the opponents are far worse: they DO let plants go dry, hold stock to
the bell, and under-plant. So the off-policy variation exists; it is just on the other farm.

The design
----------
For each game and each day, take the DIFFERENCE between the two farms:

    dX = deficiency(farm A) - deficiency(farm B)          at the start of day d
    dY = [money_A(d+k) - money_A(d)] - [money_B(d+k) - money_B(d)]

and regress dY on dX across all games, separately for each day. Differencing within the game removes
everything game-level -- the market, the weather, the shop RNG, the day itself -- so the season trend
and the market are absorbed by construction rather than modelled. Multiple deficiencies enter
together, so a coefficient is the effect of THAT deficiency holding the others fixed.

This is not a randomised experiment and the coefficients are not causal in the interventional sense.
The identifying assumption is that, conditional on the other measured deficiencies, which farm is
drier is not driven by an unobserved farm-specific shock that also moves money. That is a real
assumption and it is stated rather than hidden. It is nevertheless far stronger than the
cross-sectional alternative, and it is the only design available that can price a node the reference
never lets go deficient.

Outcome
-------
`money` is public for both farms (`farms[i].money`), which is what makes the pairing possible. The
shed is NOT public, so no shed-value outcome; tile-derived counts (plants, weeds, animals, unfed)
are public and are used as secondary outcomes.

Usage
-----
  PYTHONPATH=. python -m tools.phases.causal_panel --parsed artifacts/parsed
  PYTHONPATH=. python -m tools.phases.causal_panel --parsed artifacts/parsed --horizons 1,3,5
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

NODES = ("dry_plants", "unfed", "weeds", "planted", "empty", "animals", "structures",
         "money", "output_per_day", "revenue_per_day", "shed", "labour", "quadrants",
         "melon_tiles")
# money is the primary outcome; these are public per-farm tile counts, also paired
OUTCOMES = {"money": "own_money", "plants": "own_t_plant", "weeds_ct": "own_t_weed",
            "animals_ct": "own_t_coop", "dry_ct": "own_t_dry", "unfed_ct": "own_t_unfed"}


def build_panel(parsed):
    """-> wide frame, one row per (game, day), with _a / _b suffixed columns for the two farms."""
    S = pd.read_parquet(Path(parsed) / "states.parquet")
    keep = ["game", "step", "day", "hour", "seat"] + list(OUTCOMES.values()) \
        + [f"dev_{n}" for n in NODES if f"dev_{n}" in S.columns]
    S = S[[c for c in keep if c in S.columns]].copy()
    # END OF DAY, not start. `farms[i]["hands"]` is hand POSITIONS and the engine wipes hands at
    # `_end_of_day`, so at hour 0 EVERY farm has zero hands -- MEASURED: crew sizes are identical on
    # 30/30 days at hour 0 and differ on 15/30 at hour 23. Sampling hour 0 therefore made `labour`
    # constant by construction (its between-farm difference was exactly 0 on all 10,770 pairs) and
    # the state unrepresentative. End of day is also the settled position: day d's work is done, and
    # the outcome accrues over (d, d+k].
    S = S[S.hour == 23]
    # NAMESPACED. `money` is BOTH a graph node and an outcome (`own_money`), so renaming both to
    # bare names silently produced two columns called `money` and `W["money_a"]` blew up with
    # "cannot set a DataFrame with multiple columns to the single column". Nodes get `n_`,
    # outcomes get `y_`, and neither can collide with the other or with `day`.
    S = S.rename(columns={v: f"y_{k}" for k, v in OUTCOMES.items()})
    S = S.rename(columns={f"dev_{n}": f"n_{n}" for n in NODES})
    feats = [f"n_{n}" for n in NODES if f"n_{n}" in S.columns]
    out = [f"y_{k}" for k in OUTCOMES if f"y_{k}" in S.columns]

    # each seat's row describes ITS OWN farm, so seat IS the farm id -- no flipping required.
    # (Verified independently: `rdev_X` evaluated on seat 0's observation equals `dev_X` on seat 1's
    # own row for 13/13 nodes, 100 % of 258,121 pairs.)
    a = S[S.seat == 0].set_index(["game", "day"])
    b = S[S.seat == 1].set_index(["game", "day"])
    common = a.index.intersection(b.index)
    a, b = a.loc[common], b.loc[common]
    W = pd.DataFrame(index=common)
    for c in feats + out:
        W[f"{c}_a"], W[f"{c}_b"] = a[c], b[c]
    W["day"] = [i[1] for i in W.index]
    W.attrs["game_key"] = W.index.get_level_values(0)
    return W, feats, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parsed", default="artifacts/parsed")
    ap.add_argument("--horizons", default="1,3,5")
    ap.add_argument("--out-csv", default="artifacts/causal_prices.csv")
    ap.add_argument("--min-games", type=int, default=40)
    a = ap.parse_args(argv)
    horizons = [int(x) for x in a.horizons.split(",")]

    W, feats, out = build_panel(a.parsed)
    games = W.index.get_level_values("game").nunique()
    print(f"# causal_panel  {len(W):,} (game, day) pairs from {games} games, 2 farms each")
    print(f"   features: {', '.join(feats)}")
    print(f"   outcomes: {', '.join(out)}   horizons: {horizons} days\n")

    # THE ESTIMATOR, in two steps, because one is not enough:
    #   (1) demean each farm over ITS OWN season -- removes the permanent quality gap. Without this
    #       the between-farm difference is just "which farm is bigger", and the significant
    #       coefficients come back as the size proxies (`animals`, `output_per_day`,
    #       `revenue_per_day`) rather than as anything actionable;
    #   (2) difference the two farms within the game -- removes the market, the weather, the shop
    #       RNG and the day itself, which both farms share.
    # What identifies a coefficient is then a farm being MORE deficient than ITS OWN normal at the
    # same moment its rival is LESS deficient than its own normal. That is a shock, not a level.
    gk = W.index.get_level_values(0)
    def _demean(col):
        v = W[col].to_numpy(float)
        dm = pd.Series(v).groupby(pd.Series(gk.to_numpy())).transform(
            lambda x: x - np.nanmean(x))
        return dm.to_numpy(float)
    dX = {n: (_demean(f"{n}_a") - _demean(f"{n}_b")) for n in feats}
    # for the outcome, lead each farm's level to d+k, then difference the CHANGES
    rows = []
    for k in horizons:
        for o in out:
            # the CHANGE in each farm's level over (d, d+k], differenced between the two farms.
            # Shifting within `game` is what keeps the lead inside one episode.
            gkey = W.index.get_level_values(0)
            va, vb = _demean(f"{o}_a"), _demean(f"{o}_b")
            A = pd.DataFrame({"game": gkey, "v": va})
            B = pd.DataFrame({"game": gkey, "v": vb})
            dY = ((A["v"].groupby(A["game"]).shift(-k) - A["v"])
                  - (B["v"].groupby(B["game"]).shift(-k) - B["v"])).to_numpy(float)
            days = W["day"].to_numpy()
            for d in range(30 - k):
                m = (days == d) & np.isfinite(dY)
                for n in feats:
                    m = m & np.isfinite(dX[n])
                if m.sum() < a.min_games:
                    continue
                yy = dY[m]
                if yy.std() == 0:
                    continue
                # A REGRESSOR WITH NO VARIANCE IN THIS CELL MAKES X^T X SINGULAR. `np.linalg.inv`
                # then raises and the cell is dropped -- which is how the FIRST version of this
                # panel reported "no fitted cells" at all: `labour` was constant (see above), the
                # matrix was singular every time, and every `except LinAlgError: continue` fired.
                # So dead columns are dropped explicitly and the covariance uses `pinv`, which
                # cannot raise. A node with no variation in a cell simply gets no coefficient there.
                live = [i for i, n in enumerate(feats) if dX[n][m].std() > 0]
                if not live:
                    continue
                Xr = np.column_stack([dX[feats[i]][m] for i in live])
                sc = Xr.std(axis=0)
                Xs = np.hstack([Xr / sc, np.ones((int(m.sum()), 1))])
                coef, *_ = np.linalg.lstsq(Xs, yy, rcond=None)
                resid = yy - Xs @ coef
                dof = max(1, int(m.sum()) - Xs.shape[1])
                s2 = (resid ** 2).sum() / dof
                cov = s2 * np.linalg.pinv(Xs.T @ Xs)
                se = np.sqrt(np.maximum(np.diag(cov), 0.0))
                for j, i in enumerate(live):
                    n = feats[i]
                    rows.append({"day": d, "horizon": k, "outcome": o, "node": n,
                                 "coef_per_sd": coef[j], "se": se[j],
                                 "t": coef[j] / se[j] if se[j] > 0 else 0.0,
                                 "coef_per_unit": coef[j] / sc[j], "n": int(m.sum())})

    R = pd.DataFrame(rows)
    if R.empty:
        print("no fitted cells -- nothing to report")
        return 1
    Path(a.out_csv).parent.mkdir(parents=True, exist_ok=True)
    R.to_csv(a.out_csv, index=False)
    print(f"wrote {a.out_csv}  ({len(R):,} day x horizon x outcome x node cells)\n")

    print("=" * 100)
    print("WHAT A DEFICIENT NODE COSTS -- $ per +1sd of deficiency, differenced within game and day")
    print("=" * 100)
    print(f"   {'node':<18}{'outcome':<10}{'h':>3}{'$/sd':>12}{'se':>11}{'t':>8}"
          f"{'days +ve':>10}   verdict")
    for o in out:
        for k in horizons:
            sub = R[(R.outcome == o) & (R.horizon == k)]
            if sub.empty:
                continue
            for n in feats:
                g = sub[sub.node == n]
                if len(g) < 10:
                    continue
                med = float(g.coef_per_sd.median())
                pm = float((g.coef_per_sd > 0).mean() * 100)
                npos = float((g.coef_per_sd / g.se.replace(0, np.nan) > 2).mean() * 100)
                nneg = float((g.coef_per_sd / g.se.replace(0, np.nan) < -2).mean() * 100)
                # coef = $ per +1sd of DEFICIENCY, so NEGATIVE means the deficiency COSTS money.
                if nneg > 50:
                    verdict = "DEFICIENCY COSTS"
                elif npos > 50:
                    verdict = "deficiency PAYS (backwards -- check confounding)"
                else:
                    verdict = "no consistent sign"
                if o == "money" or abs(med) > 0.02:
                    print(f"   {n:<18}{o:<10}{k:>3}{med:>+12.1f}"
                          f"{float(g.se.median()):>11.1f}{med / max(1e-9, float(g.se.median())):>8.1f}"
                          f"{pm:>9.0f}%   {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
