"""diagnose.grid — sweep the agent.py E1_PARAMS space with hedged paired verdicts.

The E1 sell-gate's parameter space is searched per opponent (same seed) so no
combo is accepted on a pooled mean; guard metrics reject overflow/escapes/
revenue regression. Games run in parallel via ``diagnose.parallel``. ``--workers``
is read live from ``diagnose.config`` (the CLI mutates it before calling in).
"""
from __future__ import annotations

import os
from pathlib import Path

from diagnose.analysis import game_summary
from diagnose.config import EPISODE_STEPS, TEST_SEAT, EXPERIMENTS
import diagnose.config as _cfg
from diagnose.paired import _paired_verdict
from diagnose.parallel import run_parallel_tasks
from diagnose.runbook import _make_seeds

def _parse_param_space(spec: str) -> dict:
    """Parse 'k=[a,b];k2=[c,d]' into {k:[...], k2:[...]}. Values are int/float."""
    space = {}
    for part in spec.split(";"):
        if "=" not in part:
            continue
        k, vals = part.split("=", 1)
        k = k.strip()
        vals = vals.strip().strip("[]")
        parsed = []
        for v in vals.split(","):
            v = v.strip(" ")
            if not v:
                continue
            try:
                parsed.append(int(v))
            except ValueError:
                parsed.append(float(v))
        if k and parsed:
            space[k] = parsed
    return space



def _paired_deltas(old_summaries, new_summaries, key, opponent=None):
    # old/new are dicts keyed by (opponent, seed) -> summary row.
    diffs = []
    for opair in sorted(set(old_summaries) | set(new_summaries)):
        opp, seed = opair
        if opponent is not None and opp != opponent:
            continue
        o = old_summaries.get(opair)
        n = new_summaries.get(opair)
        if o is None or n is None:
            continue
        diffs.append(n[key] - o[key])
    return diffs



def grid_search(pa_indices, n_seeds, run_dir, seed=None, spec=None, exp="floor"):
    """Sweep an experiment's param space (see diagnose.config.EXPERIMENTS): for
    each combo, run the 'new' agent against a single shared 'old' batch on the same
    seeds, get per-opponent paired verdicts on the experiment target plus guard
    metrics, write grid.csv and print a ranked accept/reject table. Never pools."""
    import agent as amod
    from itertools import product

    ex = EXPERIMENTS[exp]
    defaults = ex["defaults"]
    target = ex["target"]
    target_dir = ex["target_dir"]
    guards = ex["guards"]
    keys0 = ex["print_keys"]

    space = _parse_param_space(spec) if spec else dict(ex["space"])
    keys = list(space)
    combos = []
    for values in product(*[space[k] for k in keys]):
        full = dict(defaults)
        full.update(zip(keys, values))
        combos.append(full)

    run_dir = Path(run_dir)
    base_dir = run_dir / "grid"
    out_csv = []
    rows = []

    seeds = _make_seeds(n_seeds, seed)
    n_tasks = len(combos) + 1
    workers = int(_cfg._GRID_WORKERS or (os.cpu_count() or 1))
    print(f"Grid: {len(combos)} combo(s) over {pa_indices} x {n_seeds} seeds "
          f"(old batch shared across all combos; running {n_tasks} batches over {workers} workers).\n")

    # --- parallel game execution: old baseline (-1) + every combo ---------------
    tasks = [(-1, "old", None, pa_indices, seeds, base_dir / "baseline", TEST_SEAT, EPISODE_STEPS)]
    for idx, combo in enumerate(combos):
        tasks.append((idx, "new", combo, pa_indices, seeds, base_dir / f"combo{idx}", TEST_SEAT, EPISODE_STEPS))
    paths_by_idx = run_parallel_tasks(tasks, workers=_cfg._GRID_WORKERS)
    for ci in sorted(paths_by_idx):
        print(f"  [batch {ci}] wrote {len(paths_by_idx[ci])} replays")

    # --- per-combo analysis (serial; the heavy game runs are now parallel) -------
    summary_cache = {}

    def gs(p):
        s = summary_cache.get(p)
        if s is None:
            s = game_summary(p)
            summary_cache[p] = s
        return s

    old_paths = paths_by_idx[-1]
    old_summaries = {(gs(p)["opponent"], gs(p)["seed"]): gs(p) for p in old_paths}
    base_wins = sum(1 for p in old_paths if gs(p)["result"] == "WIN")

    for idx, combo in enumerate(combos):
        new_paths = paths_by_idx[idx]
        new_summaries = {(gs(p)["opponent"], gs(p)["seed"]): gs(p) for p in new_paths}
        wins = sum(1 for p in new_paths if gs(p)["result"] == "WIN")

        # Per-opponent target verdict: want mean Δ(target) moving toward target_dir.
        opps = {}
        for opp in {k[0] for k in old_summaries} | {k[0] for k in new_summaries}:
            d = _paired_deltas(old_summaries, new_summaries, target, opponent=opp)
            v = _paired_verdict(d)
            opps[opp] = (v["mean"], v["keep"])   # tuple: (mean_delta, keep)
        def _sign_ok(x): return (x > 0) if target_dir > 0 else (x < 0)
        target_ok = all(keep and _sign_ok(mean) for mean, keep in opps.values())
        worst_opp = max(opps.items(), key=lambda kv: kv[1][0])[0] if opps else "?"

        # Guard deltas (per-opponent mean) — reject any that regress.
        guard_fails = []
        guard_deltas = {}
        opp_pool = {k[0] for k in new_summaries} | {k[0] for k in old_summaries}
        for gkey, (limit, direction) in guards.items():
            for opp in opp_pool:
                d = _paired_deltas(old_summaries, new_summaries, gkey, opponent=opp)
                mean = sum(d) / len(d) if d else 0.0
                guard_deltas[(gkey, opp)] = mean
                if gkey == "sell_revenue_total":
                    # revenue is relative to that opponent's old baseline mean.
                    old_rows = [s for (o, s), s in old_summaries.items() if o == opp]
                    old_mean = sum(r["sell_revenue_total"] for r in old_rows) / max(1, len(old_rows))
                    if len(d) and old_mean > 0 and mean < -0.10 * old_mean:
                        guard_fails.append(f"revenue[{opp}]{mean:+,.0f}")
                elif direction == +1 and mean > limit:
                    guard_fails.append(f"{gkey}[{opp}]+{mean:.1f}")
        verdict = "REJECT"
        if not opps:
            reason = "no paired seeds"
        elif not target_ok:
            reason = f"target not KEEP-reducing on all opps (worst {worst_opp} mean={opps[worst_opp][0]:+,.1f})"
        elif guard_fails:
            reason = "guard regression: " + "; ".join(guard_fails)
        else:
            verdict = "ACCEPT"
            reason = f"target reduced on all opps; guards clean; wins {wins} vs old {base_wins}"

        row = {"combo": idx, **{f"p_{k}": combo[k] for k in keys}, "verdict": verdict, "reason": reason,
               "wins_new": wins, "wins_old": base_wins,
               "target_mean_all": sum(v[0] for v in opps.values()) / max(1, len(opps)),
               "target_ok": target_ok, "guard_reason": guard_fails}
        rows.append(row)
        out_csv.append(row)
        print(f"  combo {idx} " + "  ".join(f"{k}={combo.get(k)}" for k in keys0)
              + f"  -> {verdict}: {reason}")

    # Reset the injected params so the next --new/--compare uses defaults.
    amod.E1_PARAMS = dict(defaults)

    # Ranked table: accepted first, then by target reduction, then guard-margin.
    ranked = sorted(rows, key=lambda r: (r["verdict"] != "ACCEPT",
                                         -r["target_mean_all"], r["wins_new"]))
    if out_csv:
        cols = ["combo"] + [f"p_{k}" for k in keys] + ["verdict", "wins_new", "wins_old",
                                                        "target_mean_all", "guard_reason"]
        grid_csv = base_dir / "grid.csv"
        import csv as _csv
        with grid_csv.open("w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in out_csv:
                w.writerow({c: r.get(c) for c in cols})
        print(f"\n  grid.csv -> {grid_csv}  ({len(out_csv)} combos)")
        n_acc = sum(1 for r in out_csv if r.get("verdict") == "ACCEPT")
        print(f"  verdicts: {n_acc} ACCEPT  /  {len(out_csv)-n_acc} REJECT")
    return ranked


# ---------------------------------------------------------------------------
# --xray — per-move / per-step / per-day investigation of what a patch changes
# ---------------------------------------------------------------------------
