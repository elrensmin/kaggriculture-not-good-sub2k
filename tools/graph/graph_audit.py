#!/usr/bin/env python
"""graph_audit -- WHAT IS WRONG WITH THE GRAPH, node by node, in one table.

Written after `tools/graph/cause_trace.py` was found to be BROKEN -- it imports
`tools.phases.state_sheet`, which no longer exists (deleted alongside `boey_priors`, `boey_model`
and `boey_bench`), so the tool AGENTS.md tells you to diagnose with cannot run at all. This is
self-contained: it imports `src.state_graph` and a replay directory, and nothing else.

The question it answers is not "is this node deficient". Every other diagnostic asks that, and they
all passed while the graph was silently inert. It asks the three questions that actually have to
hold before a node can change ANY behaviour:

  1. CAN IT PRESS?   a reader that returns a constant, or a target that makes `p > 1` unreachable,
                     leaves the node pinned at 1.0 forever without ever raising.
                     MEASURED: `dry_plants` (read `t.get("age")`, a key the tile schema lacks) and
                     `melon_tiles` (metric `"melon"` is not a `priors.CROPS` key) both reported
                     p == 1.000 on every one of 259,559 reference state-rows.
  2. DOES IT?        a node that can press but never does is a report, not a decision.
  3. IS IT HEARD?    a pressure reaches a decision ONLY through a code path that is actually
                     ENABLED. This is the column that was missing, and it is the one that matters:
                     fixing `dry_plants` and `melon_tiles` changed the agent BYTE-IDENTICALLY across
                     a matched 4-game A/B, because WATER and PLANT are not market ops and every
                     crew-side path (`BENCH_STEER`, `VALUE_KERNEL`, `TURN_BUDGET`, `WORK_ORDERS`) is
                     off by default.

Usage
-----
  PYTHONPATH=. python -m tools.graph.graph_audit --run-dir diag-replays/q-base
  PYTHONPATH=. python -m tools.graph.graph_audit --run-dir diag-replays/q-base --quiet
"""
from __future__ import annotations

import argparse
import collections
import glob
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import params, state_graph as sg                                   # noqa: E402
from src.state import State                                                 # noqa: E402
from tools.diagnose.games import load_replay                                # noqa: E402

MARKET_OPS = ("SELL", "BUY_PRODUCT", "BUY_SEED", "BUY_ANIMAL", "BUY_LAND", "HIRE")
ALL_OPS = MARKET_OPS + ("WATER", "PLANT", "FEED", "CARE", "HARVEST", "FERTILIZE", "DIG",
                        "COLLECT_FERTILIZER", "PICKUP", "DROP", "PLACE", "BUILD_COOP",
                        "BUILD_PASTURE")

# ============================ THE LIVE PATHS =====================================================
# Every place in `src/` that consumes a graph pressure, the param that gates it, and the ops it can
# carry. Provenance is the grep, not a guess:
#   emit.py:46            apply_to_market(market, state)   under GRAPH_MARKET
#   plan.py:83,288        pressures()["BUY_SEED"]          unconditional
#   scheduler.py:719      crew.steer(state)                under BENCH_STEER
#   state_graph.py:942    deficit_jobs()                   under GRAPH_DEFICIT_JOBS -- DIG ONLY
#   scheduler.py:497      value_kernel(jobs, state)        under VALUE_KERNEL
#   scheduler.py:485      allocate(jobs, state)            under TURN_BUDGET
#   scheduler.py:496      work_orders(state, jobs)         under WORK_ORDERS
# `deficit_jobs` is verified DIG-only by reading its body: it early-returns unless
# `pressures()["DIG"] > 1.0` and then emits a single `Job(P_DIG, ..., "DIG", ...)` on a WEED tile.
LIVE_PATHS = (
    ("emit.apply_to_market", "GRAPH_MARKET", MARKET_OPS, "market sequencing (the funding order)"),
    ("plan.seed_intents", None, ("BUY_SEED",), "the seed ask"),
    ("state_graph.deficit_jobs", "GRAPH_DEFICIT_JOBS", ("DIG",), "one DIG job per turn, max"),
    ("crew.steer", "BENCH_STEER", ALL_OPS, "job priority multiplier"),
    ("state_graph.value_kernel", "VALUE_KERNEL", ALL_OPS, "replaces the crew's ranking"),
    ("state_graph.allocate", "TURN_BUDGET", ALL_OPS, "per-op crew share"),
    ("state_graph.work_orders", "WORK_ORDERS", ALL_OPS, "issues missing jobs"),
)


def load(paths, cap=12):
    rows = []
    for p in sorted(glob.glob(str(Path(paths) / "*.json")))[:cap]:
        try:
            rep = load_replay(p)
        except Exception:                                                  # noqa: BLE001
            continue
        steps = rep["steps"] if isinstance(rep, dict) else rep.steps
        for t in range(0, len(steps), 6):
            for seat in (0, 1):
                try:
                    rows.append((t // 24, State(steps[t][seat]["observation"])))
                except Exception:                                          # noqa: BLE001
                    continue
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", default="diag-replays/q-base")
    ap.add_argument("--quiet", action="store_true", help="the verdict table only")
    a = ap.parse_args(argv)

    rows = load(a.run_dir)
    if not rows:
        print(f"no observations loaded from {a.run_dir}")
        return 1
    gates = {name: (None if g is None else bool(params.at(g, 10)))
             for name, g, _o, _d in LIVE_PATHS}

    def _on(name):
        """A path with no gate param is ALWAYS on -- `None` must not read as False."""
        return gates[name] is None or bool(gates[name])
    print(f"# graph_audit  {len(rows)} (day, state) samples from {a.run_dir}")
    def _gate_label(n, g):
        if g is None:
            return f"{n}(always on)"
        return f"{n}[{g}={'ON' if gates[n] else 'OFF'}]"
    print("   live paths: " + ", ".join(_gate_label(n, g) for n, g, _o, _d in LIVE_PATHS) + "\n")

    press = collections.defaultdict(list)
    raw = collections.defaultdict(list)
    for _d, _state in rows:
        try:
            for node, ours, _t, p, _u in sg.deviation(_state):
                press[node].append(float(p))
                raw[node].append(ours)
        except Exception:                                                  # noqa: BLE001
            continue

    print(f"   {'node':<16}{'win':>9}{'presses':>9}{'p50':>7}{'p95':>7}   {'ops licensed':<38}"
          f"{'heard by':<26}verdict")
    buckets = collections.Counter()
    for node in sorted(sg.NODES):
        spec = sg.NODES[node]
        v = press.get(node, [])
        if spec.window[0] > 29:
            verdict = "out of season"
        elif len(v) < 3:
            verdict = "DEAD (never evaluated)"
        elif max(v) <= 1.0 + 1e-9:
            verdict = "DEAD (pinned at 1.0)"
        else:
            frac = sum(1 for x in v if x > 1.0 + 1e-9) / len(v)
            heard = []
            for name, gate, ops, _desc in LIVE_PATHS:
                if any(o in ops for o in spec.ops):
                    heard.append(f"{name.split('.')[-1]}{'' if _on(name) else '(OFF)'}")
            live = [h for h in heard if not h.endswith("(OFF)")]
            if frac < 0.02:
                verdict = "reports, never presses"
            elif live:
                verdict = "HEARD"
            else:
                verdict = "*** MUTE ***"
            buckets[verdict] += 1
        vv = v or [1.0]
        win = f"{spec.window[0]}-{spec.window[1]}"
        frac_s = (f"{sum(1 for x in v if x > 1.0 + 1e-9) / len(v) * 100:.0f}%"
                  if v else "-")
        heard_s = ",".join(f"{n.split('.')[-1]}{'' if _on(n) else '(OFF)'}"
                           for n, g, ops, _ in LIVE_PATHS
                           if any(o in ops for o in spec.ops)) or "-"
        print(f"   {node:<16}{win:>9}{frac_s:>9}{st.median(vv):>7.2f}"
              f"{sorted(vv)[int(len(vv) * 0.95)] if vv else 1.0:>7.2f}   "
              f"{','.join(spec.ops):<38}{heard_s:<26}{verdict}")

    print()
    mute = [n for n in sorted(sg.NODES)
            if press.get(n) and max(press[n]) > 1.0 + 1e-9
            and not any(any(o in ops for o in sg.NODES[n].ops)
                        for name, gate, ops, _ in LIVE_PATHS if _on(name))]
    print(f"   {len(mute)} of {len(sg.NODES)} nodes can press but are MUTE -- nothing enabled reads "
          f"their pressure:")
    for n in mute:
        print(f"      {n:<16} -> {','.join(sg.NODES[n].ops)}"
              f"   (only reachable via: "
              f"{', '.join(f'{nm.split(chr(46))[-1]}[{g}]' for nm, g, ops, _ in LIVE_PATHS if any(o in ops for o in sg.NODES[n].ops))})")
    if not a.quiet:
        print("\n   A MUTE node is not a tuning problem. Changing its param, its target or its "
              "reader cannot change behaviour\n   until some enabled path consumes the pressure -- "
              "which is why the dry_plants/melon_tiles fix\n   measured byte-identical across a "
              "matched A/B.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
