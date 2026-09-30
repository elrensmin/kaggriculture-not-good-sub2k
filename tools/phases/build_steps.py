#!/usr/bin/env python
"""build_steps -- one row per (game, STEP): the state and the action, causally paired.

WHY STEP RESOLUTION, AND WHY THIS PAIRING
-----------------------------------------
The day-resolution fit had **reverse causation** built into it. `fit_graph.build` sampled the
observation at `steps[day*24+23]` -- the END of the day -- and labelled it with the ops performed
across that same day. So the state called "cause" was largely the CONSEQUENCE of the ops called
"effect", and the +0.613 R2 it scored was the model re-learning "the ops moved the state": true,
trivial, and useless for control.

The engine guarantees the correct pair. A kaggle_environments step records the action that
*produced* its observation, so the action decided FROM `steps[t].observation` lives at
`steps[t+1].action`. That is a real decision made from a real state, at every one of the ~720 steps
of a game -- which is both the causal pairing AND 24x the data.

    features = f(steps[t][seat].observation)      the state the decision was made from
    labels   = ops in steps[t+1][seat].action     the decision

The 720 steps then buy 720 INDEPENDENT weight sets, one per step: each is fit on one row per game
(359 games -> 287 train / 72 held-out under an 80/20 split BY GAME), against only the handful of
nodes that LICENSE the op (`NODES[node].ops`), so each bucket has ~50-140 observations per
parameter. Finer resolution is affordable HERE because the buckets are fit independently -- it is
NOT the same as one joint 720-bucket fit, which would indeed be unidentified.

Features carry both signs, because a graph edge is causal in both directions: `def_<node>` is the
deficiency (pressure - 1, clipped at 0 -- "we are behind, act") and `exc_<node>` is the excess
(1 - pressure -- "we are ahead, stop"). Non-negative weights then stay interpretable: a `def_`
weight is "how hard a shortfall drives this op".

Usage
-----
  PYTHONPATH=. python -m tools.phases.build_steps --ref-from replays/Boey/v1 --out artifacts/boey_steps.parquet
  PYTHONPATH=. python -m tools.phases.build_steps --ref-from replays/Boey/v1 --ref-max 20 --out /tmp/s.parquet
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import multiprocessing as mp
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments.envs.kaggriculture.kaggriculture import (      # noqa: E402
    ANIMALS, CROPS, PRODUCTS)

DAY = 24
MOVES = frozenset(("NORTH", "SOUTH", "EAST", "WEST"))
# UNIT ops (the crew) and MARKET ops (the funding order) are both decisions of the graph, so both
# are labels. The market half is where the price curve can actually show up as a response.
UNIT_OPS = ("WATER", "FERTILIZE", "HARVEST", "PLANT", "DIG", "FEED", "CARE",
            "COLLECT_FERTILIZER", "PLACE", "BUILD_PASTURE", "BUILD_COOP", "PICKUP")
MARKET_OPS = (tuple(f"SELL_{p}" for p in PRODUCTS)
              + tuple(f"BUY_PRODUCT_{p}" for p in PRODUCTS)
              + tuple(f"BUY_SEED_{c}" for c in CROPS)
              + tuple(f"BUY_ANIMAL_{a}" for a in ANIMALS)
              + ("BUY_LAND", "HIRE"))
OPS = UNIT_OPS + MARKET_OPS


def _ops_in_action(act):
    """Every op in one step's action, farmer + hands + market, counted."""
    c = collections.Counter()
    if not isinstance(act, dict):
        return c
    for cmd in ([act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])):
        if not cmd:
            continue
        op = cmd[0] if isinstance(cmd, (list, tuple)) else str(cmd)
        c["MOVE" if op in MOVES else str(op)] += 1
    # MARKET ORDERS: the kind is at index 0, NOT 1. Measured shape from the reference's own
    # replays: [['BUY_PRODUCT', 'WHEAT', 3], ['HIRE'], ['BUY_SEED', 'WHEAT', 4], ...]. Reading
    # index 1 as the kind produced garbage labels ("WHEAT_3") and silently DROPPED every HIRE,
    # which is the op the crew ramp is actually made of -- so the market half of the decision
    # surface was mislabelled and part of it missing.
    for order in (act.get("market") or []):
        if isinstance(order, (list, tuple)) and order:
            kind = str(order[0])
            c[f"{kind}_{order[1]}" if len(order) >= 2 else kind] += 1
    return c


def one_game(job):
    """-> list of dicts, one per step. Runs in a worker process."""
    path, seat_mode, step_cap = job
    from src import market as mk
    from src import state_graph as sg
    from src.state import State
    from tools import team as team_mod
    from tools.diagnose.games import load_replay

    try:
        rep = load_replay(path)
    except Exception:                                                      # noqa: BLE001
        return []
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    if not steps or len(steps[0]) < 2:
        return []
    names = (rep.get("info") or {}).get("TeamNames") or []
    seat = (team_mod.seat_of_names(names, fallback=0) if seat_mode == "auto"
            else int(seat_mode))
    if len(steps[0]) <= seat:
        return []
    game = Path(path).stem.replace("episode-", "").replace("-replay", "")
    out = []
    n = min(len(steps) - 1, step_cap)
    for t in range(n):
        try:
            obs = steps[t][seat].get("observation")
            act = steps[t + 1][seat].get("action")
        except Exception:                                                  # noqa: BLE001
            continue
        if not obs or act is None:
            continue
        try:
            st = State(obs)
        except Exception:                                                  # noqa: BLE001
            continue
        row = {"game": game, "step": t, "day": t // DAY, "hour": t % DAY, "seat": seat}
        # context the graph is allowed to see
        try:
            row["money"] = float(st.money)
            row["units"] = int(st.unit_count())
            row["shed_total"] = int(st.shed_total())
            row["hires_today"] = int(getattr(st, "hires_today", 0) or 0)
            row["has_yarn"] = int(bool(st.has_yarn()))
            row["has_milk_shop"] = int(bool(st.has_milk_shop()))
        except Exception:                                                  # noqa: BLE001
            pass
        # THE PRICE CURVE -- the graph must be able to react to it, so it is a feature, not a
        # hidden input. Both the level and the level relative to base (the level alone is a season
        # clock; the RATIO is the signal -- "is this good money for this good right now").
        for prod in mk.PRODUCTS:
            try:
                p = float(st.prices[prod])
                row[f"px_{prod}"] = p
                row[f"pxr_{prod}"] = round(p / float(mk.base(prod)), 3)
            except Exception:                                              # noqa: BLE001
                continue
        # THE GRAPH'S OWN DEVIATION VECTOR, both signs.
        #
        # PRE-FILLED WITH ZERO. `deviation()` skips a node that is not `active` (melon_tiles is
        # inactive from d4, quadrants from d13, structures from d21, ...), so the node is simply
        # ABSENT from the vector rather than zero. Left as absent it became a NaN column -- 87% of
        # rows for melon_tiles -- and NNLS refuses NaN. Zero is also the correct meaning: an
        # inactive node is not deficient and not in excess, so it emits no pressure either way.
        for node in sg.NODES:
            row[f"def_{node}"] = 0.0
            row[f"exc_{node}"] = 0.0
        try:
            for node, _ours, _tgt, pressure, _u in sg.deviation(st):
                p = float(pressure)
                row[f"def_{node}"] = max(0.0, p - 1.0)
                row[f"exc_{node}"] = max(0.0, 1.0 - p)
        except Exception:                                                  # noqa: BLE001
            pass
        # LABELS
        c = _ops_in_action(act)
        for op in OPS:
            row[f"n_{op}"] = int(c.get(op, 0))
        out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=0, help="0 = all")
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--step-cap", type=int, default=720)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=0, help="0 = all cores")
    a = ap.parse_args(argv)

    import pandas as pd
    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.ref_glob)))
    if a.ref_max:
        paths = paths[:a.ref_max]
    print(f"# build_steps  {len(paths)} replays from {a.ref_from}")

    jobs = [(p, a.ref_seat, a.step_cap) for p in paths]
    rows = []
    nw = a.workers or None
    with mp.Pool(nw) as pool:
        for i, chunk in enumerate(pool.imap_unordered(one_game, jobs, chunksize=4), 1):
            rows.extend(chunk)
            if i % 25 == 0 or i == len(jobs):
                print(f"   {i}/{len(jobs)} games, {len(rows):,} step-rows")

    if not rows:
        print("no rows -- nothing written")
        return 1
    df = pd.DataFrame(rows)
    df = df.sort_values(["game", "step"]).reset_index(drop=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(a.out, index=False)
    feat = [c for c in df.columns if c.startswith(("def_", "exc_", "px_", "pxr_"))]
    lab = [c for c in df.columns if c.startswith("n_")]
    print(f"\nwrote {a.out}")
    print(f"   {len(df):,} rows = {df['game'].nunique()} games x {df['step'].nunique()} steps")
    print(f"   {len(feat)} feature cols, {len(lab)} label cols")
    print("   label means per step (nonzero only):")
    nz = [(c, df[c].mean()) for c in lab if df[c].mean() > 0.005]
    for i in range(0, len(nz), 6):
        print("     " + "  ".join(f"{c[2:]}={m:.3f}" for c, m in nz[i:i + 6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
