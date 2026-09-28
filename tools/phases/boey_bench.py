#!/usr/bin/env python
"""boey_bench — the day-wise target: his defect and throughput surface, p25/p50/p75.

Why this exists
---------------
"48 plants died, 2.4 % idle, 0.62 premium-below-base" is not a scorecard, it is a number
with nothing to compare against. Steering needs the reference's OWN day-wise surface: what
does he lose, where, and how tight is it across his 359 games? Without it every arm is
judged against a guess -- which is exactly how the last several rounds went.

This runs the harness's own analysis (`replay_to_record` -> `build_frames` -> `build_days`,
the same code that writes our `days_seed*.csv`) over the reference's replays and aggregates
each day to p25 / p50 / p75 across games, so the columns are IDENTICAL to ours and the
comparison is like-for-like.

Read it with the endgame in mind: after ~d24 he stops servicing the farm, so rising
`plants_died` / `weeds_max` there is OPTIMAL play, not a defect. The table shows that
directly, which is the point of having it per day rather than as one season average.

Columns whose source is 'requested' (no market audit in a leaderboard replay) are marked;
everything derived from the observation -- deaths, weeds, idle, escapes, discards, shed,
money -- is exact and trustworthy.

Usage
-----
  PYTHONPATH=. python -m tools.phases.boey_bench --ref-max 60 --workers 8
  PYTHONPATH=. python -m tools.phases.boey_bench --all --workers 8      # full 359
  PYTHONPATH=. python -m tools.phases.boey_bench --ours diag-replays/ga-flood \
      --glob 'days_seed*.csv' --metrics plants_died,weeds_max,idle_share_pct
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob as globmod
import json
import multiprocessing as mp
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import team as team_mod                                       # noqa: E402
from tools.diagnose.analysis import (_day_columns, _flatten, build_days,  # noqa: E402
                                     build_frames, replay_to_record)

# The surface to steer on. Defects first, because they are where the money leaks.
GROUPS = {
    "MONEY": ["end_money", "money_delta", "revenue", "expenses", "seed_cost",
              "animal_cost", "product_cost", "hire_cost", "land_cost"],
    "LABOUR": ["unit_turns", "idle_units", "idle_share_pct", "idle_units_ready",
               "n_move", "n_pass", "hands_end", "hires"],
    "DEFECT": ["plants_died", "weeds_max", "weeds_end", "animals_escaped",
               "discarded_units", "max_shed_total", "end_shed_total",
               "premium_below_base_frac"],
    "PRODUCE": ["plants_watered", "plants_fertilized", "animals_fed", "animals_cared",
                "fertilizer_collected", "wheat_fed", "feed_surplus"],
    "CROPS": ["plants_planted_WHEAT", "plants_planted_MELON",
              "plants_planted_STRAWBERRY", "plants_harvested_WHEAT",
              "plants_harvested_MELON", "plants_harvested_STRAWBERRY"],
}
DEFAULT_METRICS = [m for g in GROUPS.values() for m in g]


def _worker(task):
    path, = task
    try:
        rep = json.load(open(path))
    except Exception as exc:                                        # noqa: BLE001
        return {"file": Path(path).name, "error": repr(exc)}
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    if not steps or len(steps[0]) < 2:
        return None
    names = (rep.get("info") or {}).get("TeamNames") or []
    if len(names) >= 2 and names[0] == names[1]:
        return None
    seat = team_mod.seat_of_names(names, fallback=0)
    try:
        days = build_days(build_frames(replay_to_record(rep, seat), seat))
    except Exception as exc:                                        # noqa: BLE001
        return {"file": Path(path).name, "error": repr(exc)}
    return {"file": Path(path).name, "days": {d["day"]: _flatten(d) for d in days}}


def _pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * (len(v) - 1)))]


def _aggregate(rows, metrics):
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        for d, flat in r["days"].items():
            for m in metrics:
                v = flat.get(m)
                if isinstance(v, (int, float)):
                    per[d][m].append(float(v))
    out = {}
    for d in sorted(per):
        out[str(d)] = {m: {"p25": _pct(per[d][m], .25), "p50": _pct(per[d][m], .50),
                           "p75": _pct(per[d][m], .75), "n": len(per[d][m])}
                       for m in metrics if per[d][m]}
    return out


def emit_md(bench, metrics, games, out_path):
    L = [f"# Boey day-wise benchmark (auto) — {games} games", "",
         "p25 / p50 / p75 across games, per day. `p50` is the target to steer to.", ""]
    for name, ms in GROUPS.items():
        ms = [m for m in ms if m in metrics]
        if not ms:
            continue
        L += [f"## {name}", "", "| metric | " + " | ".join(
            f"d{d}" for d in (0, 3, 5, 7, 9, 10, 12, 15, 18, 21, 24, 26, 28)) + " |",
            "|" + "---|" * 14]
        for m in ms:
            row = [m]
            for d in (0, 3, 5, 7, 9, 10, 12, 15, 18, 21, 24, 26, 28):
                cell = bench.get(str(d), {}).get(m)
                row.append("-" if not cell else f"{cell['p25']:.0f}/{cell['p50']:.0f}/"
                                                f"{cell['p75']:.0f}")
            L.append("| " + " | ".join(row) + " |")
        L.append("")
    L += ["## Notes", "",
          "* `premium_below_base_frac`, `revenue*`, `sell_qty*` derive from SELL ORDERS "
          "because a leaderboard replay carries no market audit -- treat as requested, not "
          "filled.", "* `plants_died`, `weeds_max`, `idle_*`, `animals_escaped`, "
          "`discarded_units`, `shed_*`, `end_money` are observation-derived and exact.",
          "* After ~d24 he stops servicing the farm; rising deaths and weeds there are "
          "optimal, not a defect."]
    Path(out_path).write_text("\n".join(L) + "\n")


def _our_days(dirpath, glob):
    """Our own per-day rows, from the harness CSVs (same columns as the benchmark)."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for p in sorted(globmod.glob(str(Path(dirpath) / glob))):
        for row in csv.DictReader(open(p)):
            try:
                d = int(row.get("day"))
            except (TypeError, ValueError):
                continue
            for k, v in row.items():
                try:
                    per[d][k].append(float(v))
                except (TypeError, ValueError):
                    continue
    return per


def compare(bench, dirpath, glob, metrics):
    per = _our_days(dirpath, glob)
    if not per:
        print(f"   no day rows under {dirpath}/{glob}")
        return
    days = sorted(per)
    print(f"\n   OURS vs HIS (p50), day-wise. ours/his ; gap = ours - his")
    print(f"   {'metric':<24}" + "".join(f"{('d'+str(d)):>13}" for d in days))
    for m in metrics:
        line = f"   {m:<24}"
        for d in days:
            ours = _pct(per[d].get(m, []), .50)
            his = (bench.get(str(d), {}).get(m) or {}).get("p50")
            if ours is None or his is None:
                line += f"{'-':>13}"
            else:
                line += f"{ours:>6.1f}/{his:<6.1f}"
        print(line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=60)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--metrics", default=None, help="comma list; default all groups")
    ap.add_argument("--ours", default=None, help="our run dir, for the day-wise compare")
    ap.add_argument("--glob", default="days_seed*.csv")
    ap.add_argument("--out-json", default="docs/boey_bench.json")
    ap.add_argument("--out-md", default="docs/boey_bench.md")
    ap.add_argument("--team", default=None)
    a = ap.parse_args(argv)
    team_mod.set_team(a.team or "Boey")
    metrics = a.metrics.split(",") if a.metrics else DEFAULT_METRICS
    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.ref_glob)))
    if not a.all:
        paths = paths[:a.ref_max]
    print(f"# boey_bench  {len(paths)} episodes")
    tasks = [(p,) for p in paths]
    w = int(a.workers or 0)
    if w <= 1 or len(tasks) <= 1:
        rows = [_worker(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_worker, tasks))
    rows = [r for r in rows if r and "days" in r]
    if not rows:
        print("no data")
        return 1
    bench = _aggregate(rows, metrics)
    Path(a.out_json).write_text(json.dumps(bench, indent=1, default=str))
    emit_md(bench, metrics, len(rows), a.out_md)
    print(f"   games aggregated {len(rows)}  days {min(int(d) for d in bench)}"
          f"-{max(int(d) for d in bench)}")
    print("   d10 targets (p25/p50/p75):")
    for m in ("plants_died", "weeds_max", "idle_share_pct", "animals_escaped",
              "discarded_units", "max_shed_total", "premium_below_base_frac",
              "unit_turns", "end_money"):
        c = bench.get("10", {}).get(m)
        if c:
            print(f"      {m:<26}{c['p25']:>9.1f} /{c['p50']:>9.1f} /{c['p75']:>9.1f}")
    if a.ours:
        compare(bench, a.ours, a.glob, metrics)
    print(f"wrote {a.out_json} and {a.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
