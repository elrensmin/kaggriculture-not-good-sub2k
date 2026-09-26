#!/usr/bin/env python
"""shadow_prices — what is one more unit of each scarce resource worth?

The problem this solves
-----------------------
`phase_map` gives the DAG *quantities*: "0 animals on board", "54% idle". A root
with a big blast radius is not automatically worth fixing — that is exactly how the
opening herd got built and lost $15,020 (the DAG's #1 phase-1 root, measured
negative). Resources are **jointly scarce**, so counting descendants cannot rank
them. What ranks them is a **price**: the marginal value of one more unit.

How the price is measured
-------------------------
Finite differences on a paired, same-seed design. For every (opponent, seed) we run

    baseline                    -> (NAV_d5, terminal)
    baseline + one perturbation -> (NAV_d5, terminal)

and take the paired difference. Two objectives are reported, deliberately:

  * **dNAV_d5** — the phase-1 objective (d5 state marked by `state_value`). It is
    low-variance because cash and shed are observed, not predicted, so a real
    opening effect is visible on a handful of games. This is the *shadow price at
    the cut*.
  * **dterm** — the season objective. It is what actually scores, and it has
    sigma ~= $10k on 12 games.

When the two disagree in sign, that disagreement is the finding: the d5 state price
is a bad proxy for the season (measured for the #1: d5 state explains R^2 = 0.07 of
his terminal bank). A perturbation that buys d5 NAV and sells terminal bank is a
*paper* improvement.

Perturbations are `SCRATCH_PARAMS` overrides (see `src/params.py`), so nothing is
edited to run this. Each one is a separate process because a param change must
re-execute `src/` from scratch.

Usage
-----
    # the default opening menu: cash, herd, wheat tiles, hands, movement, ramp
    PYTHONPATH=. python -m tools.phases.shadow_prices --pa 1-3 --batch 4

    # custom: LABEL|KEY=VAL;KEY=VAL|unit|unit-name   (unit optional)
    PYTHONPATH=. python -m tools.phases.shadow_prices --pa 1,2 --batch 6 \\
        --perturb 'herd|HERD_ENABLED=1||' \\
        --perturb 'cheap-water|CASH_RESERVE=1000|500|dollar of spendable cash'
"""
from __future__ import annotations

import argparse
import math
import multiprocessing as mp
import os
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.phases.phase_map import _make_seeds, _parse_pa_arg      # noqa: E402
from tools.phases import state_value as SV                         # noqa: E402

# label | SCRATCH_PARAMS | unit delta | unit name
DEFAULT_PERTURBATIONS = (
    # one more dollar of opening liquidity: spend $250 less by reserving less
    ("liquidity+250", "CASH_RESERVE=1250", 250, "dollar of d0 spendable cash"),
    # one more tile committed to the opening wheat block
    ("wheat_tile+1", "WHEAT_OPENING_TILES=1", 1, "opening tile"),
    # one more hand per 12 tiles
    ("hands+25%", "TILES_PER_HAND=3", None, "extra hand"),
    # the opening herd (the DAG's phase-1 root, measured negative)
    ("herd_on", "HERD_ENABLED=1", None, "herd enabled"),
    # movement: is the walk itself a resource?
    ("walk_free", "MOVE_WEIGHT=0", None, "movement weight 0"),
    # the planting ramp / queue
    ("no_ramp", "PLANT_RAMP=0", None, "ramp off"),
    # fertilizing is a labour AND a sellable good at the opening
    ("no_fert", "FERTILIZE_FROM_DAY=99", None, "fertilizing off"),
)


def _parse(spec):
    parts = spec.split("|")
    while len(parts) < 4:
        parts.append("")
    label, params, unit, unit_name = parts[:4]
    return (label.strip(), params.strip(),
            float(unit) if unit.strip() else None, unit_name.strip())


def _fresh_agent():
    """Drop every `src.*` module and re-import, so params take effect."""
    for m in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[m]
    import src
    return src.agent


def _one(task):
    """Run baseline + perturbation for one (opponent, seed). Returns paired deltas."""
    pa, seed, label, params = task
    from tools.diagnose.agents import load_public_agent
    opp = load_public_agent(pa)

    os.environ.pop("SCRATCH_PARAMS", None)
    base_agent = _fresh_agent()
    env_b, snap_b = SV.rollout(base_agent, opp, seed, cont="live")
    vb = SV.price_d5(snap_b, SV.TEST_SEAT)
    vb["term_live"] = SV._terminal(env_b, SV.TEST_SEAT)

    os.environ["SCRATCH_PARAMS"] = params
    pert_agent = _fresh_agent()
    env_p, snap_p = SV.rollout(pert_agent, opp, seed, cont="live")
    vp = SV.price_d5(snap_p, SV.TEST_SEAT)
    vp["term_live"] = SV._terminal(env_p, SV.TEST_SEAT)
    os.environ.pop("SCRATCH_PARAMS", None)

    return {
        "opponent": pa, "seed": seed, "label": label,
        "dnav": vp["nav"] - vb["nav"],
        "dterm": vp["term_live"] - vb["term_live"],
        "nav_b": vb["nav"], "nav_p": vp["nav"],
    }


def _sign_p(k, n):
    """Two-sided sign-test p, normal approximation (no scipy)."""
    if n == 0:
        return 1.0
    z = abs(k - n / 2) / math.sqrt(n / 4)
    return max(0.0, min(1.0, 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pa", default="1-3")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=SV.DEFAULT_SEED)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--perturb", action="append", default=None,
                    help="LABEL|KEY=VAL;KEY=VAL|unit|unit-name (repeatable)")
    ns = ap.parse_args(argv)

    specs = ([_parse(p) for p in ns.perturb] if ns.perturb
             else list(DEFAULT_PERTURBATIONS))
    pa_indices = _parse_pa_arg(ns.pa)
    seeds = _make_seeds(ns.batch, ns.seed)

    tasks = [(pa, s, lab, par) for pa in pa_indices for s in seeds
             for (lab, par, _u, _un) in specs]
    print(f"shadow_prices — {len(pa_indices)} opponent(s) x {len(seeds)} seed(s) "
          f"x {len(specs)} perturbation(s) = {len(tasks)} paired games")
    print(f"   each task = 2 full 720-step roll-outs (baseline + one perturbation), "
          f"fresh process state per param set")

    w = int(ns.workers or os.cpu_count() or 1)
    if w <= 1 or len(tasks) <= 1:
        rows = [_one(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_one, tasks))

    print(f"\n############ shadow prices — per-unit marginal value ############")
    print(f"   {'perturbation':<18}{'n':>4}{'dNAV d5':>12}{'dterm':>12}"
          f"{'dterm sign':>11}   {'$/unit (dNAV)':>16}   unit")
    print("   " + "-" * 96)
    for lab, par, unit, uname in specs:
        rs = [r for r in rows if r["label"] == lab]
        if not rs:
            continue
        n = len(rs)
        dnav = st.median(r["dnav"] for r in rs)
        dterm = st.median(r["dterm"] for r in rs)
        # Report the sign test for `dterm`, the DECISION variable, not just `dnav`.
        # A midgame-only change leaves d5 untouched, so dnav is exactly 0 for every pair
        # and the old column read "0/0" -- no evidence at all about the thing being
        # decided. `sign` is now dterm-positive/dterm-decided.
        pos = sum(1 for r in rs if r["dterm"] > 0)
        neg = sum(1 for r in rs if r["dterm"] < 0)
        k = min(pos, neg)
        p = _sign_p(k, pos + neg)
        sign = f"{pos}/{pos + neg}"
        per = f"{dnav / unit:>16,.1f}" if unit else f"{'-':>16}"
        print(f"   {lab:<18}{n:>4}{dnav:>12,.0f}{dterm:>12,.0f}{sign:>10}   {per}   "
              f"{uname or par}"
              + (f"   (p={p:.3f})" if p < 0.2 and pos + neg >= 4 else ""))

    agree = [r for r in rows if r["dnav"] * r["dterm"] < 0]
    print(f"\n   sign disagreement (dNAV vs dterm): {len(agree)}/{len(rows)} pairs "
          f"— where high, the d5 price is not a proxy for the season")
    print(f"   baseline d5 NAV median: ${st.median(r['nav_b'] for r in rows):,.0f}   "
          f"under perturbation: ${st.median(r['nav_p'] for r in rows):,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
