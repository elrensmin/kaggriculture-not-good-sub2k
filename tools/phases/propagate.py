#!/usr/bin/env python
"""propagate — compose a structural change through the graph WITHOUT running a game.

Why this exists
---------------
`phase_map`/`divergence` say what is behind and when. They do not say what a change
COMPOSES to: "+8 wheat tiles" opens the herd gate, which buys ~5 animals, which is +5
FEED +5 CARE +5 COLLECT every day, which is ~180 acts, which is ~320 crew-turns against a
budget that is already full. That chain is arithmetic over known mechanics, not a
simulation, and running a game to discover it is the expensive way to learn a fact we can
compute.

The model lives in ``propagation_rules.py`` (data, editable like ``dag.py``). Every edge is
either an engine rule or a measured rate with a source. This file is only the resolver:
day-stepped, threshold-aware, capacity-checked.

It is deliberately NOT a simulator. Non-goals: revenue, prices, the shop draw, and any
market feedback. A number that depends on those must come from a measured arm.

Usage
-----
  # what does +8 wheat tiles from d6 compose to?
  PYTHONPATH=. python -m tools.phases.propagate --dir /tmp/w1-base --set wheat_tiles2=+8 --from-day 6
  # what would it take to reach the reference's d17 state, and does it fit the crew?
  PYTHONPATH=. python -m tools.phases.propagate --dir /tmp/w1-base --to-target
  # honesty check: feed a RECORDED arm's measured upstream delta in and score the prediction
  PYTHONPATH=. python -m tools.phases.propagate --validate /tmp/w1-base /tmp/w3-herd
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.diagnose.runbook import _make_seeds, _parse_pa_arg          # noqa: E402
from tools.phases.dag import PHASES                                     # noqa: E402
from tools.phases.phase_map import extract_games, extract_replays       # noqa: E402
from tools.diagnose.window import describe, in_window, parse_days    # noqa: E402
from tools.phases.propagation_rules import (CAPACITY, NODES, RULES,     # noqa: E402
                                            THRESHOLDS)

NON_ACT = ("MOVE", "PASS", "REVENUE", "TRADE_NET")


def load_series(dirpath, glob="*.json", max_games=0, seat=1, pa=None, batch=4,
                seed=4362837462, phase="phase2"):
    """{day: {metric: median-across-games}} for one arm, plus the crew meta."""
    if dirpath:
        paths = sorted(globmod.glob(str(Path(dirpath) / glob)))
        if max_games:
            paths = paths[:max_games]
        games = extract_replays(paths, seat=seat)
        n = len(paths)
    else:
        spec = PHASES[phase]
        games = extract_games(_parse_pa_arg(pa), _make_seeds(batch, seed),
                              steps=spec["steps"])
        n = len(games)
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for g in games:
        for d, rec in g.items():
            per[d]["unit_turns"].append(rec["unit_turns"])
            per[d]["moves"].append(rec["flow"].get("MOVE", 0))
            per[d]["pass"].append(rec.get("pass", 0))
            per[d]["hands"].append(rec.get("hands_max", 0))
            per[d]["acts"].append(sum(v for k, v in rec["flow"].items()
                                      if not k.startswith("__") and k not in NON_ACT))
            for key, (_lbl, src, _b) in NODES.items():
                kind, _, k = src.partition(":")
                if kind == "stock":
                    per[d][key].append(rec["stock"].get(k, 0))
                else:
                    per[d][key].append(rec["flow"].get(k, 0))
    return {d: {k: st.median(vs) for k, vs in dd.items() if vs} for d, dd in per.items()}, n


def propagate(base, injections, days):
    """Day-stepped fixed point. Returns {node: {day: delta}}.

    Jacobi iteration: each pass writes a FRESH dict. Accumulating in place double-counted
    every flow edge once per pass (a +8 wheat injection predicted +1,889 HARVEST instead
    of ~+19).
    """
    inj = {k: {d: 0.0 for d in days} for k in NODES}
    for node, amount, frm in injections:
        if node not in NODES:
            raise SystemExit(f"unknown node {node!r}; known: {sorted(NODES)}")
        for d in days:
            if d >= frm:
                inj[node][d] += amount
    total = {k: dict(inj[k]) for k in NODES}
    for _ in range(6):                      # resolve lag chains
        nxt = {k: dict(inj[k]) for k in NODES}      # RESET to injections: a pass adds
        for (src, dst, coef, lag, mode, _kind, _note) in RULES:   # rule effects to the
            for d in days:                                        # injections, never to
                if mode == "oneoff":                              # their own output
                    prev = total[src].get(d - lag - 1)
                    sv = total[src].get(d - lag, 0.0) - (prev if prev is not None else 0.0)
                else:
                    sv = total[src].get(d - lag, 0.0)
                if sv:
                    nxt[dst][d] += coef * sv
        # thresholds: FILL a gated node to its cap (the herd does buy up to the gate)
        for th in THRESHOLDS:
            node = th["node"]
            for d in days:
                cap = th["fn"](base.get(d, {}).get(node, 0.0),
                               base.get(d, {}).get("wheat_tiles2", 0.0),
                               nxt["wheat_tiles2"][d], d)
                if cap is None:
                    continue
                base_v = base.get(d, {}).get(node, 0.0)
                allowed = max(0.0, cap - base_v)
                if th.get("ceiling"):
                    allowed = min(allowed, max(0.0, th["ceiling"] - base_v))
                if th.get("fill"):
                    nxt[node][d] = max(nxt[node][d], allowed)
                else:
                    nxt[node][d] = min(nxt[node][d], allowed)
        total = nxt
    return total


def _act_nodes():
    return ("plant_ops2", "water_ops2", "harvests2", "feed_ops2", "care_ops2",
            "collect_ops2", "place_ops2")


def _print_table(base, delta, days, injections):
    inj_txt = ", ".join(f"{n}{a:+.0f}@{f}" for n, a, f in injections)
    print(f"# propagation  injections: {inj_txt}")
    print(f"   {'node':<24}{'d6':>7}{'d8':>7}{'d10':>7}{'d12':>7}{'d14':>7}{'d17':>7}")
    ds = [d for d in days if d in (6, 8, 10, 12, 14, 17)] or days
    for key in NODES:
        b = base.get(days[0], {}).get(key, 0.0)
        row_b = "".join(f"{base.get(d, {}).get(key, 0.0):>7.0f}" for d in ds)
        row_d = "".join(f"{base.get(d, {}).get(key, 0.0) + delta[key][d]:>7.0f}" for d in ds)
        tot = sum(delta[key][d] for d in days)
        if abs(tot) < 0.5:
            continue
        print(f"   {key:<24}{row_b}")
        print(f"   {'  -> with delta':<24}{row_d}   total {tot:+.0f}")
    return ds


def _capacity(base, delta, days):
    print("\n   -- crew-turn capacity (why a structurally-sound change can still fail) --")
    print(f"   {'day':>4}{'acts':>7}{'d_acts':>8}{'moves/act':>11}"
          f"{'extra_turns':>12}{'spare':>8}   ")
    over = []
    for d in days:
        b = base.get(d, {})
        d_acts = sum(delta[k][d] for k in _act_nodes())
        acts = b.get("acts", 0.0) + d_acts
        mpa = b["moves"] / b["acts"] if b.get("acts") else 0.0
        extra = d_acts * (1 + mpa)
        spare = b.get("pass", 0.0) + CAPACITY["avoidable_move_frac"] * b.get("moves", 0.0)
        flag = "OVER" if extra > spare else ""
        if flag:
            over.append(d)
        print(f"   {d:>4}{acts:>7.0f}{d_acts:>8.0f}{mpa:>11.2f}{extra:>12.0f}{spare:>8.0f}   {flag}")
    if over:
        print(f"   ! extra turns exceed the spare on days {over} -- free walking (move "
              f"share) before adding this work, per docs/DSM-vs-us(v0).md S3.5")
    else:
        print("   - fits inside the avoidable walking.")
    return over


def _validate(base_dir, arm_dir, glob, max_games, seat, win):
    b, nb = load_series(base_dir, glob, max_games, seat)
    a, na = load_series(arm_dir, glob, max_games, seat)
    days = [d for d in sorted(set(b) & set(a)) if in_window(d, win)]
    print(f"# validate: {base_dir} ({nb} games) -> {arm_dir} ({na} games), "
          f"{describe(win)}")
    # mean per-day delta per node over the window
    meas = {k: {d: a[d].get(k, 0.0) - b[d].get(k, 0.0) for d in days} for k in NODES}
    mean = {k: (st.mean(meas[k].values()) if days else 0.0) for k in meas}
    drivers = sorted({r[0] for r in RULES} & set(NODES),
                     key=lambda k: -abs(mean[k]))

    def _fit(src):
        inj = {k: {d: 0.0 for d in days} for k in NODES}
        for d in days:
            inj[src][d] = meas[src][d]
        total = {k: dict(inj[k]) for k in NODES}
        for _ in range(6):
            nxt = {k: dict(inj[k]) for k in NODES}
            for (s2, dst, coef, lag, mode, _kind, _note) in RULES:
                for d in days:
                    if mode == "oneoff":
                        prev = total[s2].get(d - lag - 1)
                        sv = total[s2].get(d - lag, 0.0) - (prev if prev is not None else 0.0)
                    else:
                        sv = total[s2].get(d - lag, 0.0)
                    if sv:
                        nxt[dst][d] += coef * sv
            total = nxt
        reach = {src}
        stack = [src]
        while stack:
            n = stack.pop()
            for (a2, dst2, _c, _l, mode2, *_r) in RULES:
                if mode2 != "level":
                    continue     # one-off edges do not define a per-day fit
                if a2 == n and dst2 not in reach:
                    reach.add(dst2)
                    stack.append(dst2)
        errors = []
        for k in NODES:
            if k == src or k not in reach:
                continue        # only score what this driver can actually reach
            pred = st.mean([total[k][d] for d in days]) if days else 0.0
            m = mean[k]
            if abs(m) < 0.1:
                continue
            errors.append((k, pred, m, (pred - m) / m * 100))
        return total, errors

    # Try each candidate driver and keep the best fit: the model is being asked "given
    # this arm moved, do the EDGES reproduce the rest?", so the driver is not assumed.
    best = None
    for cand in drivers:
        if abs(mean[cand]) < 0.1:
            continue
        delta, errors = _fit(cand)
        if not errors:
            continue
        score = st.median([abs(e[3]) for e in errors])
        if best is None or score < best[0]:
            best = (score, cand, errors)
    if best is None:
        print("   no candidate driver moved >=0.1/day with a modelled downstream node")
        return []
    score, src, errors = best
    print(f"# best fit driven by {src} {mean[src]:+.2f}/day (searched "
          f"{len([d for d in drivers if abs(mean[d]) >= 0.1])} candidate drivers)")
    print(f"   {'node':<24}{'pred/day':>10}{'meas/day':>10}{'error':>9}")
    errs = []
    for k, pred, m, e in sorted(errors, key=lambda t: -abs(t[2])):
        errs.append(abs(e) if e == e else 999.0)
        print(f"   {k:<24}{pred:>10.2f}{m:>10.2f}{e:>8.0f}%")
    print(f"\n   median |error| {score:.0f}%   (a model that cannot "
          f"reproduce a recorded arm must not gate a decision)")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="baseline run dir (replays)")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--seat", type=int, default=1)
    ap.add_argument("--pa", default=None, help="run live instead of --dir")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--set", action="append", default=[],
                    help="node=+N (repeatable), e.g. --set wheat_tiles2=+8")
    ap.add_argument("--from-day", type=int, default=6)
    ap.add_argument("--days", default="11-20", help="window to report/propagate (default d11-20)")
    ap.add_argument("--to-target", action="store_true",
                    help="report the gap to the reference and what closing it implies")
    ap.add_argument("--ref-dir", default="replays/Boey/v1")
    ap.add_argument("--ref-max", type=int, default=40)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--validate", nargs=2, metavar=("BASE", "ARM"), default=None)
    a = ap.parse_args(argv)

    if a.validate:
        from tools.diagnose.window import parse_days as _pd
        _validate(a.validate[0], a.validate[1], a.glob, a.max_games, a.seat,
                  _pd(a.days))
        return 0
    if not a.dir and not a.pa:
        ap.error("need --dir or --pa")

    base, n = load_series(a.dir, a.glob, a.max_games, a.seat, a.pa, a.batch, a.seed)
    from tools.diagnose.window import in_window, parse_days, describe
    win = parse_days(a.days)
    days = [d for d in sorted(base) if in_window(d, win) and d >= a.from_day]
    print(f"# baseline: {a.dir or ('pa=' + a.pa)}  {n} games  {describe(win)}")

    if a.to_target:
        ref, rn = load_series(a.ref_dir, a.glob, a.ref_max, a.ref_seat)
        print(f"# reference: {a.ref_dir}  {rn} games")
        rd = sorted(set(days) & set(ref))
        print(f"   {'node':<24}{'ours(med)':>11}{'Boey(med)':>11}{'need':>9}")
        need = {}
        for k in NODES:
            o = st.median([base[d][k] for d in rd if k in base[d]])
            r = st.median([ref[d][k] for d in rd if k in ref[d]])
            need[k] = r - o
            print(f"   {k:<24}{o:>11.1f}{r:>11.1f}{need[k]:>+9.1f}")
        # inverse the herd gate: what wheat area does the reference herd need?
        want = ref[max(rd)]["animals2"]
        want_wheat = 1.7 * (want + 1)
        print(f"\n   herd gate inverse: animals {want:.0f} needs WHEAT tiles "
              f">= {want_wheat:.1f}; ours {base[max(rd)]['wheat_tiles2']:.0f} "
              f"-> wheat delta {want_wheat - base[max(rd)]['wheat_tiles2']:+.1f}")
        injections = [("wheat_tiles2", want_wheat - base[max(rd)]["wheat_tiles2"], days[0])]
        delta = propagate(base, injections, days)
        _print_table(base, delta, days, injections)
        _capacity(base, delta, days)
        return 0

    injections = []
    for spec in a.set:
        name, _, val = spec.partition("=")
        injections.append((name.strip(), float(val), a.from_day))
    if not injections:
        ap.error("need --set or --to-target")
    delta = propagate(base, injections, days)
    _print_table(base, delta, days, injections)
    _capacity(base, delta, days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
