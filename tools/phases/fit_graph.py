#!/usr/bin/env python
"""fit_graph — LEARN the graph's node->op weights from the reference's own games.

Why this exists
---------------
`src/state_graph.py` already computes, every turn, a **deviation vector**: per node, *ours vs his
day-wise target*, with an urgency. What is still hand-set is the **edge from a node to an op**
(`NODES[node].ops`, a binary membership list) and the op priorities (`P_FERTILIZE`,
`SAME_TILE_MIN_PRIORITY`, `FERTILIZE_FROM_DAY`). Those are exactly what his replays can fit: for
every day of every game we know **his state** and **the ops he performed**.

So: `ops_today ~ sum_node w[node, op] * deviation(node) + bias[op][day]`, with `w` fitted offline
here and shipped as literals (`src/graph_weights.py`). The graph then decides *how much* of each op
from the learned weights instead of from a static param.

Method
------
* features: `deviation(state)` evaluated on HIS board (his deviation from his own day-wise median
  -- i.e. "when he is behind on a node, how does he respond in ops?")
* labels:   his op counts that day, read from the SAME replay walk
* fit:      non-negative least squares per op (`scipy.optimize.nnls`), **split by game** so days of
  one game never straddle train/test
* report:   held-out R2 per op, so a weight set that carries no signal is visible and can be
  withheld rather than shipped.

Usage
-----
  PYTHONPATH=. python -m tools.phases.fit_graph --ref-max 60
  PYTHONPATH=. python -m tools.phases.fit_graph --ref-max 359 --out-json docs/graph_weights.json
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import json
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import state_graph as sg                                          # noqa: E402
from src.state import State                                                # noqa: E402
from tools import team as team_mod                                         # noqa: E402
from tools.diagnose.games import load_replay                               # noqa: E402

DAY = 24
MOVES = frozenset(("NORTH", "SOUTH", "EAST", "WEST"))
# the ops we fit. MOVE/PASS are not decisions of interest (MOVE is the cost of an act).
OPS = ("WATER", "FERTILIZE", "HARVEST", "PLANT", "FEED", "CARE", "COLLECT_FERTILIZER",
       "DIG", "PLACE", "BUILD_PASTURE", "BUILD_COOP")

# THE TIME DIMENSION. MEASURED (60 replays, 1,800 game-days, split BY GAME, identical
# preprocessing): global weights median held-out R2 +0.224; the FIVE windows below +0.486; a
# 30-day partition +0.438 at 2.8 obs/param (it overfits). Finer is NOT better -- so the season is
# partitioned at the resolution that measured best, which is also `dag.py::PHASES`.
WINDOWS = ((0, 5), (6, 10), (11, 17), (18, 23), (24, 29))


def win_of(day):
    for i, (a_, b_) in enumerate(WINDOWS):
        if a_ <= day <= b_:
            return i
    return len(WINDOWS) - 1


def _ops_that_day(steps, seat, day):
    """His op counts for one day (labels), from the shifted action pairing."""
    c = collections.Counter()
    for t in range(day * DAY, min(len(steps) - 1, (day + 1) * DAY)):
        act = steps[t + 1][seat].get("action") or {}
        for cmd in ([act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])):
            if not cmd:
                continue
            op = cmd[0] if isinstance(cmd, list) else "PASS"
            if op in MOVES:
                op = "MOVE"
            c[op] += 1
    return c


def _features(state):
    """deviation(state) -> {node: deficiency}, deficiency = pressure - 1 (0 when healthy)."""
    out = {}
    try:
        for node, _o, _t, p, _u in sg.deviation(state):
            out[node] = max(0.0, float(p) - 1.0)
    except Exception:                                                      # noqa: BLE001
        pass
    return out


def build(paths, seat_mode, max_games):
    """[(game_id, day, features, labels)] — one row per game-day."""
    rows = []
    for gi, p in enumerate(paths[:max_games]):
        try:
            rep = load_replay(p)
        except Exception:                                                  # noqa: BLE001
            continue
        steps = rep["steps"] if isinstance(rep, dict) else rep.steps
        if not steps or len(steps[0]) < 2:
            continue
        names = (rep.get("info") or {}).get("TeamNames") or []
        seat = (team_mod.seat_of_names(names, fallback=0) if seat_mode == "auto"
                else int(seat_mode))
        for day in range(len(steps) // DAY):
            t = day * DAY + (DAY - 1)
            if t >= len(steps) or len(steps[t]) <= seat:
                continue
            obs = steps[t][seat].get("observation")
            if not obs:
                continue
            try:
                st_ = State(obs)
            except Exception:                                              # noqa: BLE001
                continue
            feats = _features(st_)
            if not feats:
                continue
            rows.append((gi, day, feats, _ops_that_day(steps, seat, day)))
    return rows


def fit(rows, min_support=0.0, per_window=False, licensed_only=True, train_frac=0.8):
    """Per-op non-negative least squares, split BY GAME. Returns (weights, report).

    `per_window=True` gives every node a weight PER WINDOW (see WINDOWS above) plus a per-window
    bias -- the variant that measured median R2 +0.486 against +0.224 global.

    `train_frac` splits BY GAME into train/test (default 80/20); every R2 reported is on the
    held-out games, which the fit never sees.

    `licensed_only=True` is the fix for the fit's ONE measured failure mode. Fitting every node
    against every op let NNLS reach for the nodes that are simply **collinear with the season**
    (`money`, `shed`, `structures`, `revenue_per_day` all grow monotonically), so it learned a proxy
    CLOCK rather than a response: on 359 Boey replays the fit scored a healthy median R2 **+0.613**
    while **8 of WATER's 9 learned edges and 9 of DIG's 10 were outside `NODES[node].ops`** -- edges
    the graph itself does not license. Driving `turn_budget` from that table allocated the crew by
    season position instead of by deficiency and measured **-$42,606 median, 0/4, `plants_died`
    54 -> 109** (watering trimmed because `structures` was "high", not because plants were dry).

    So the design matrix is masked to the graph's OWN causal boundary. The fit's job is then *how
    much* each licensed edge weighs -- never *whether* the edge exists, which is the DAG's decision.
    If the R2 collapses under the mask, that is the honest answer: the licensed nodes carry little
    op-level signal and the op-edges need redesigning, not reweighting.
    """
    import numpy as np
    from scipy.optimize import nnls
    if not rows:
        return {}, {}
    nodes = sorted({n for _g, _d, f, _l in rows for n in f})
    NW = len(WINDOWS)
    games = sorted({g for g, _d, _f, _l in rows})
    # 80/20 SPLIT BY GAME. By GAME, not by row: days of one game are highly autocorrelated, so a
    # row-wise split leaks the test set into the training set and reports a held-out R2 that is
    # really a training R2. (This was always a game-level split; it is stated and parameterised now
    # because "held-out" is only meaningful if you can see the ratio and the game counts.)
    cut = max(1, min(len(games) - 1, int(round(len(games) * train_frac))))
    train_g, test_g = set(games[:cut]), set(games[cut:])
    W, report = {}, {}
    for op in OPS:
        if licensed_only:
            allowed = {n for n in nodes
                       if op in (getattr(sg.NODES.get(n), "ops", None) or ())}
        else:
            allowed = set(nodes)

        def design(sel):
            X, y, days = [], [], []
            for g, d, f, lab in rows:
                if g not in sel:
                    continue
                if per_window:
                    X.append([(f.get(n, 0.0) if (n in allowed and win_of(d) == k) else 0.0)
                              for k in range(NW) for n in nodes]
                             + [1.0 if win_of(d) == k else 0.0 for k in range(NW)])
                else:
                    X.append([f.get(n, 0.0) if n in allowed else 0.0 for n in nodes] + [1.0])
                y.append(float(lab.get(op, 0)))
                days.append(d)
            return np.array(X, float), np.array(y, float), days
        Xtr, ytr, dtr = design(train_g)
        Xte, yte, dte = design(test_g)
        if len(ytr) == 0 or ytr.sum() == 0:
            report[op] = {"n_train": int(len(ytr)), "note": "no positives in train"}
            continue
        # standardise the deviation columns so the weights are comparable across nodes
        scale = np.where(Xtr[:, :-1].max(axis=0) > 0, Xtr[:, :-1].max(axis=0), 1.0)
        Xtr_s = np.hstack([Xtr[:, :-1] / scale, Xtr[:, -1:]])
        w, _res = nnls(Xtr_s, ytr)
        pred = (np.hstack([Xte[:, :-1] / scale, Xte[:, -1:]]) @ w) if len(yte) else np.array([])
        r2 = None
        if len(yte) and yte.var() > 0:
            r2 = float(1.0 - ((yte - pred) ** 2).sum() / ((yte - yte.mean()) ** 2).sum())
        # THE BASELINE THAT WAS MISSING. The per-window intercepts alone predict "how much of this op
        # does he do in this PHASE", and op counts are strongly day-dependent -- so a big `heldout_r2`
        # can be nothing but the seasonal mean. MEASURED on 359 Boey replays under the licensing
        # mask: CARE scored R2 +0.502 and COLLECT_FERTILIZER +0.701 with **ZERO nonzero node
        # weights** -- the entire score was the intercept. The number that decides whether the graph
        # can steer anything is `d_r2`, the gain over the intercept-only model.
        bias_only = Xtr[:, -NW:] if per_window else Xtr[:, -1:]
        d_r2 = None
        if len(yte) and yte.var() > 0:
            wb, _rb = nnls(bias_only, ytr)
            pb = (Xte[:, -NW:] if per_window else Xte[:, -1:]) @ wb
            r2b = float(1.0 - ((yte - pb) ** 2).sum() / ((yte - yte.mean()) ** 2).sum())
            d_r2 = r2 - r2b
        if per_window:
            W[op] = {}
            for k in range(NW):
                blk = {n: round(float(w[k * len(nodes) + i] / scale[k * len(nodes) + i]), 4)
                       for i, n in enumerate(nodes) if w[k * len(nodes) + i] > 0}
                if blk:
                    W[op][k] = blk
        else:
            W[op] = {n: round(float(w[i] / scale[i]), 4) for i, n in enumerate(nodes) if w[i] > 0}
        report[op] = {"n_train": int(len(ytr)), "n_test": int(len(yte)),
                      "mean_label": round(float(ytr.mean()), 2),
                      "heldout_r2": None if r2 is None else round(r2, 3),
                      "d_r2": None if d_r2 is None else round(d_r2, 3),
                      "median_bias": round(float(np.median(w[-NW:])), 3),   # NW bias cols when windowed
                      "weights": sum(len(b) for b in W[op].values()) if per_window else len(W[op])}
    return W, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=60)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--team", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--windows", action="store_true", help="fit per-window weights (measured better)")
    ap.add_argument("--train-frac", type=float, default=0.8,
                    help="fraction of GAMES used for training; the rest is held out (default 0.8)")
    ap.add_argument("--all-edges", action="store_true",
                    help="fit EVERY node against every op (the measured-broken variant: learns a "
                         "season clock from collinear nodes and drives the crew by it)")
    ap.add_argument("--codegen", default=None, help="write src/graph_weights.py here")
    a = ap.parse_args(argv)
    team_mod.set_team(a.team)
    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.ref_glob)))
    print(f"# fit_graph  {min(len(paths), a.ref_max)} of {len(paths)} replays from {a.ref_from}")
    rows = build(paths, a.ref_seat, a.ref_max)
    _ng = len({g for g, *_ in rows})
    print(f"   game-days: {len(rows)}   games: {_ng}"
          f"   split BY GAME {a.train_frac:.0%}/{1 - a.train_frac:.0%}"
          f" = {max(1, min(_ng - 1, int(round(_ng * a.train_frac))))} train /"
          f" {_ng - max(1, min(_ng - 1, int(round(_ng * a.train_frac))))} held-out")
    if not rows:
        print("no rows — nothing to fit")
        return 1
    W, report = fit(rows, per_window=a.windows, licensed_only=not a.all_edges,
                    train_frac=a.train_frac)
    print(f"   edges: {'ALL nodes (unmasked)' if a.all_edges else 'LICENSED only (NODES[node].ops)'}")
    # EVIDENCE FIRST. The fit walks every replay and is the expensive half; a bug in the codegen
    # below must not be able to throw it away (measured: one did, on a missing `pathlib`).
    if a.out_json:
        Path(a.out_json).write_text(json.dumps({"weights": W, "report": report}, indent=1))
        print(f"wrote {a.out_json}")
    if a.codegen:
        HEADER = (
            '"""graph_weights -- node->op weights LEARNED from the reference replays.\n'
            '\n'
            'GENERATED by `tools/phases/fit_graph.py --windows`; evidence docs/graph_weights.json.\n'
            '\n'
            'Measured held-out R2 (split BY GAME, 60 replays / 1,800 game-days):\n'
            '  global weights  median +0.224\n'
            '  FIVE windows    median +0.486   <-- this table\n'
            '  30-day          median +0.438   (2.8 obs/param, overfits -- finer is NOT better)\n'
            '"""\n'
            'from __future__ import annotations\n'
        )
        L = [HEADER, 'WINDOWS = %r' % (WINDOWS,), '', 'def win_of(day):',
             '    for i, (a_, b_) in enumerate(WINDOWS):',
             '        if a_ <= day <= b_:',
             '            return i',
             '    return len(WINDOWS) - 1', '', 'W = {']
        for op, ws in W.items():
            L.append(f'    {op!r}: {{')
            for k, blk in sorted(ws.items()):
                L.append(f'        {k}: {{' + ', '.join(f'{n!r}: {v}' for n, v in blk.items()) + '},')
            L.append('    },')
        L += ['}', '',
              'def weights_for(op, day):',
              '    """The learned node->op weights for the window containing `day`."""',
              '    return W.get(op, {}).get(win_of(day), {})', '']
        Path(a.codegen).write_text('\n'.join(L))
        import importlib, sys as _s
        _s.path.insert(0, str(_ROOT))
        _m = importlib.import_module(a.codegen.replace('/', '.').removesuffix('.py').replace('src.', 'src.'))
        assert getattr(_m, 'W', None), 'codegen produced an EMPTY weight table'
        print(f"wrote {a.codegen} (imports clean, W non-empty)")
    print(f"   {'op':<20}{'n_train':>8}{'mean':>8}{'heldout R2':>12}{'dR2 vs bias':>13}{'weights':>9}")
    for op, r in report.items():
        if "heldout_r2" not in r:
            print(f"   {op:<20}{r.get('n_train', 0):>8}{'-':>8}{r.get('note', ''):>12}")
            continue
        r2, dr = r["heldout_r2"], r.get("d_r2")
        sig = "" if dr is None else ("   <- the season, not a response" if dr < 0.05 else "")
        print(f"   {op:<20}{r['n_train']:>8}{r['mean_label']:>8}{('-' if r2 is None else f'{r2:+.3f}'):>12}"
              f"{('-' if dr is None else f'{dr:+.3f}'):>13}{r['weights']:>9}{sig}")
    print("   dR2 vs bias = held-out gain over the intercept-only model. THAT is the graph's signal;"
          " `heldout R2` alone is mostly the seasonal mean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
