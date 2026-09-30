#!/usr/bin/env python
"""cause_trace — from a broken graph node to the CAUSE, not a hypothesis.

Why this exists
---------------
`graph_diag --section break` says WHERE the chain snaps (`empty` breaks d1 and stays
broken). It does not say WHY. Guessing why is the infinite loop: the first wrong guess
costs a full A/B round. This tool closes that loop by tracing the broken node to its
REMEDY op and then checking the remedy op's PRECONDITIONS against the measured per-day
state — so the answer is "PLANT was not done although seed=8, empty=7 and idle=44 turns
all allowed it", not "maybe the band restriction".

The trace is:
    node deficient -> remedy ops (from src/state_graph REMEDY) -> each remedy's
    preconditions, measured at the break day -> the precondition that is NOT met (or
    the op that was simply not performed despite all preconditions being met) is the
    cause.

Usage
-----
    PYTHONPATH=. python -m tools.graph.cause_trace --run-dir diag-replays/d2-base --node empty
    PYTHONPATH=. python -m tools.graph.cause_trace --run-dir diag-replays/d2-base --node planted
    PYTHONPATH=. python -m tools.graph.cause_trace --run-dir diag-replays/d2-base            # all broken nodes
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

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS  # noqa: E402

from src import state_graph as sg                                   # noqa: E402
from src import state_graph_data as sgd                             # noqa: E402
from tools.phases.phase_map import extract_replays, _seat_of        # noqa: E402
from tools.phases.state_sheet import _augment                       # noqa: E402
from tools.diagnose.games import load_replay                        # noqa: E402

DAY = 24


def _node_series(rep, seat):
    """{day: {node: value}} read through the REAL `state_graph._LIVE` readers.

    The trace used to reimplement each node's reader over the extracted rec, which silently
    drifted: `unfed` and `dry_plants` are not in that rec at all, so they read 0 and the
    node printed "not deficient" while `graph_diag --section break` showed `unfed` deficient
    on 9/25 days. Building a real `State` from the observation and calling the same readers
    the live agent calls removes the whole drift class -- there is now one implementation.
    """
    from src.state import State
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    out = {}
    for t in range(len(steps)):
        frame = steps[t]
        if len(frame) <= seat:
            continue
        obs = frame[seat].get("observation")
        if not obs or int(obs.get("hour", 0)) < 23:
            continue                      # day-end reading only, as the graph uses
        try:
            st = State(obs)
            out[t // DAY] = {k: float(fn(st)) for k, fn in sg._LIVE.items()}
        except Exception:                 # noqa: BLE001
            continue
    return out


def _load(run_dir, glob, max_games):
    """List of games, each {day: rec} with flow (ops) + stock + seeds + money + nodes."""
    paths = sorted(globmod.glob(str(Path(run_dir) / glob)))
    if max_games:
        paths = paths[:max_games]
    games = []
    for p in paths:
        rep = load_replay(p)
        seat = _seat_of(rep, "auto")
        base = extract_replays([p], seat)[0]          # {day: rec with flow+stock+money}
        extra = _augment(rep, seat)                   # seeds, shed_items, owned_animals
        nodes = _node_series(rep, seat)               # the REAL node readers
        for d, rec in base.items():
            rec.update(extra.get(d, {}))
            rec["nodes"] = nodes.get(d, {})
        games.append(base)
    return games


def _series(games, fn):
    """{day: median} of fn(rec) across games."""
    per = collections.defaultdict(list)
    for g in games:
        for d, rec in g.items():
            v = fn(rec)
            if isinstance(v, (int, float)):
                per[d].append(float(v))
    return {d: st.median(vs) for d, vs in sorted(per.items()) if vs}


# --- precondition readers: (label, fn(rec) -> value) per remedy op -----------------
# Each row answers one yes/no gate on the op happening that day. The tool prints the
# median at the break day so the missing one is obvious.
def _planted(rec): return rec["stock"].get("planted", 0)
def _empty(rec): return rec["stock"].get("empty", 0)
def _idle(rec): return rec.get("pass", 0)
def _uturns(rec): return rec.get("unit_turns", 0)
def _seeds(rec): return sum((rec.get("seeds") or {}).values())
def _animals(rec): return rec["stock"].get("animals", 0)
def _structs(rec): return rec["stock"].get("structures", 0)
def _money(rec): return rec.get("money_end", 0)
def _weeds(rec): return rec["stock"].get("weed", 0)
def _shed_wheat(rec): return (rec.get("shed_items") or {}).get("WHEAT", 0)


PRECONDITIONS = {
    "PLANT": [
        ("seed held (total)", _seeds),
        ("empty owned tiles", _empty),
        ("idle unit-turns", _idle),
        ("PLANT ops done", lambda r: r["flow"].get("PLANT", 0)),
    ],
    "BUY_SEED": [
        ("cash", _money),
        ("empty owned tiles", _empty),
        ("BUY_SEED ordered", lambda r: r["flow"].get("BUY_SEED", 0)),
    ],
    "WATER": [
        ("plants needing water", lambda r: r["stock"].get("dry_plants", 0)),
        ("idle unit-turns", _idle),
        ("WATER ops done", lambda r: r["flow"].get("WATER", 0)),
    ],
    "FEED": [
        ("unfed animals", lambda r: r["stock"].get("unfed", 0)),
        ("wheat in shed", _shed_wheat),
        ("FEED ops done", lambda r: r["flow"].get("FEED", 0)),
    ],
    "BUILD_PASTURE": [
        ("animals owned", _animals),
        ("structures built", _structs),
        ("cash", _money),
        ("BUILD ops done", lambda r: r["flow"].get("BUILD_PASTURE", 0)
                                   + r["flow"].get("BUILD_COOP", 0)),
    ],
    "BUILD_COOP": [
        ("animals owned", _animals),
        ("structures built", _structs),
        ("cash", _money),
        ("BUILD ops done", lambda r: r["flow"].get("BUILD_PASTURE", 0)
                                   + r["flow"].get("BUILD_COOP", 0)),
    ],
    "PLACE": [
        ("animals owned (board)", _animals),
        ("structures built", _structs),
        ("PLACE ops done", lambda r: r["flow"].get("PLACE", 0)),
    ],
    "BUY_ANIMAL": [
        ("cash", _money),
        ("animals owned", _animals),
        ("wheat tiles (feed gate)", lambda r: r["stock"].get("plant_WHEAT", 0)),
        ("structures built", _structs),
    ],
    "DIG": [
        ("weeds standing", _weeds),
        ("idle unit-turns", _idle),
        ("DIG ops done", lambda r: r["flow"].get("DIG", 0)),
    ],
    "HARVEST": [
        ("ripe tiles", lambda r: r["flow"].get("HARVEST", 0)),   # proxy: what we did
        ("idle unit-turns", _idle),
    ],
    "PICKUP": [
        ("wheat in shed", _shed_wheat),
        ("PICKUP ops done", lambda r: r["flow"].get("PICKUP", 0)),
    ],
    "SELL": [
        ("shed value", lambda r: r["stock"].get("shed_total", 0)),
        ("SELL ordered", lambda r: r["flow"].get("SELL", 0)),
    ],
}


def _break_day(series, node, days):
    """First day in window the node is deficient (per its direction) and stays deficient."""
    spec = sg.NODES[node]
    tgt = sg.target_of(node, 0) if False else None  # not used; we use direction only
    # approximate target via the node's own benchmark/prior target where cheap
    return None  # replaced below


def _deficient(node, ours, day):
    """Is the node deficient on this day, vs its target (from state_graph.target_of)."""
    t = sg.target_of(node, day)
    if t is None:
        return False, t
    if spec(node).better == "lower":
        return ours > t * (1.0 + 0.15), t
    return ours < t * (1.0 - 0.15), t


def spec(node):
    return sg.NODES[node]


def _break_profile(games, node, lo, hi):
    """How the node fails: PERSISTENT (breaks and stays), FLAPPING, or none.

    The old version required 3 consecutive deficient days and returned None otherwise, so a
    node deficient on 9 of 25 days (`unfed`) printed "not deficient" and the trace walked
    past a real defect. `graph_diag --section break` calls that case "a priority race"; the
    tracer has to see it too, or it mis-directs the next hypothesis (measured: an A2 feed
    hypothesis was skipped this way).
    """
    ours = _series(games, _live_of(node))
    def_days = []
    for d in range(lo, hi + 1):
        if d not in ours:
            continue
        bad, t = _deficient(node, ours[d], d)
        if bad:
            def_days.append((d, ours[d], t))
    if not def_days:
        return None
    for i, (d, v, t) in enumerate(def_days):
        run = len([x for x in def_days if d <= x[0] <= d + 2])
        if run >= 3:
            return dict(kind="PERSISTENT", day=d, ours=v, target=t,
                        n_def=len(def_days), n_days=len(ours))
    d, v, t = def_days[0]
    return dict(kind="FLAPPING", day=d, ours=v, target=t,
                n_def=len(def_days), n_days=len(ours))


def _live_of(node):
    def fn(rec):
        nodes = rec.get("nodes") or {}
        if node in nodes:
            return nodes[node]           # the REAL reader (state_graph._LIVE)
        return _live_value(node, rec)    # fallback when nodes were not sampled
    return fn


def _live_value(node, rec):
    """Recompute the node's live value from the extracted rec (mirrors src _LIVE)."""
    s = rec["stock"]
    flow = rec["flow"]
    m = {
        "weeds": s.get("weed", 0),
        "planted": s.get("planted", 0),
        "empty": s.get("empty", 0),
        "animals": s.get("animals", 0),
        "structures": s.get("structures", 0),
        "quadrants": s.get("quadrants", 0),
        "melon_tiles": s.get("plant_MELON", 0),
        "shed": s.get("shed_total", 0),
        "dry_plants": s.get("dry_plants", 0),
        "unfed": s.get("unfed", 0),
        "money": rec.get("money_end", 0),
        "output_per_day": flow.get("REVENUE", 0),
        "revenue_per_day": flow.get("REVENUE", 0),
        "labour": rec.get("unit_turns", 0),
    }
    return m.get(node, 0)


def _parents(node):
    return [a for a, b in sg.EDGES if b == node]


# defect column -> the graph node it reads out, so an arm diff is printed as the RIPPLE
# across the graph rather than a list of unrelated numbers.
DEFECT_NODE = {
    "idle_share_pct": "labour",
    "idle_units_ready_total": "labour",
    "idle_units_total": "labour",
    "floor_sales": "shed",
    "discarded_units_total": "shed",
    "stranded_at_bell": "shed",
    "premium_below_base_frac": "revenue_per_day",
    "animal_escapes": "unfed",
    "plants_died": "dry_plants",
    "unwatered_eod": "dry_plants",
    "missed_harvest_eod": "output_per_day",
    "shed_overflow_days": "shed",
    "sell_revenue_total": "revenue_per_day",
}


def effects(base_dir, arm_dir):
    """The side-effects of a knob change, mapped to graph nodes.

    This is the "correlation" the trace otherwise lacks: FEED_STOCK_DAYS=2 read median
    +$1.4k while `stranded_at_bell` moved +993 (4/4 worse), and that fact lives here as a
    per-NODE ripple (`shed` moved worse), not as an isolated number.
    """
    from tools.report import arm_diff as ad
    A, B = ad._load(base_dir), ad._load(arm_dir)
    keys = sorted(set(A) & set(B))
    if not keys:
        print(f"no matched (opponent, seed) pairs between {base_dir} and {arm_dir}")
        return
    print(f"# effects  {base_dir} -> {arm_dir}   ({len(keys)} matched pairs)")
    md = _median([ad._num(B[k].get(ad.MONEY, 0)) - ad._num(A[k].get(ad.MONEY, 0))
                  for k in keys])
    print(f"  final_money -> money       {md:+,.0f} median")
    by_node = {}
    for col, direction in ad.DEFECTS:
        deltas = [ad._num(B[k].get(col, 0)) - ad._num(A[k].get(col, 0)) for k in keys]
        if not deltas:
            continue
        med = _median(deltas)
        worse = sum(1 for d in deltas
                    if (d > 0) == (direction == "worse")) if direction != "better" else \
                sum(1 for d in deltas if d < 0)
        node = DEFECT_NODE.get(col, "?")
        by_node.setdefault(node, []).append((col, med, worse, len(deltas)))
    for node, rows in sorted(by_node.items()):
        print(f"  node {node}:")
        for col, med, worse, n in rows:
            flag = " <<<" if (worse >= n * 0.75 and abs(med) > 0) else ""
            print(f"      {col:<24} {med:+9.1f}   ({worse}/{n} worse){flag}")


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def trace(games, node, lo, hi):
    """Print the full cause trace for one node."""
    spec = sg.NODES[node]
    prof = _break_profile(games, node, lo, hi)
    print(f"\n===== {node}  (better={spec.better}, deadline={spec.deadline}, "
          f"ops={','.join(spec.ops)}) =====")
    ctrl = getattr(sgd, "CONTROLS", {}).get(node)
    if ctrl:
        print(f"  KNOBS: {ctrl}")
    if prof is None:
        print(f"  not deficient in window d{lo}-{hi}")
        return
    d0, v, t = prof["day"], prof["ours"], prof["target"]
    if prof["kind"] == "FLAPPING":
        print(f"  FLAPPING: first d{d0}, deficient {prof['n_def']}/{prof['n_days']} days "
              f"(a priority race, not a persistent break)")
    else:
        print(f"  first break: d{d0}")
    print(f"  at d{d0}:  ours={v:.1f}  target={t if t is not None else '?'}")

    # 1. upstream causes: is this node a root or a symptom?
    parents = _parents(node)
    if parents:
        print(f"  upstream causes:")
        for p in parents:
            po = _series(games, _live_of(p))
            pv = po.get(d0)
            bad, pt = _deficient(p, pv, d0) if pv is not None else (False, None)
            tag = "DEFICIENT (symptom chain)" if bad else "ok"
            print(f"    {p:<16} {pv if pv is None else round(pv,1):>8}  {tag}")
    else:
        print(f"  no upstream causes -> {node} is a ROOT (a source in the DAG)")

    # 2. the remedy ops and their preconditions at the break day
    for op in spec.ops:
        print(f"  remedy op {op}:")
        for label, fn in PRECONDITIONS.get(op, []):
            s = _series(games, fn)
            vv = s.get(d0)
            print(f"      {label:<22} {vv if vv is None else round(vv,1):>8}")
    # 3. PER-CROP resolution. A global seed/plant knob is measured to starve the feed
    # budget (`SEED_FILL_BUFFER=1;SEED_FROM_EMPTY=1` -> -$16,524 median, idle +96 6/8,
    # sell_revenue -$3,572). The aggregate "seed held 8" hid that WHEAT held ~0 while
    # STRAWBERRY held 12 -- so the fix has to name the crop, and the tool has to show it.
    if node in ("empty", "planted"):
        held = _series(games, lambda r: (r.get("seeds") or {}).get("WHEAT", 0))
        straw = _series(games, lambda r: (r.get("seeds") or {}).get("STRAWBERRY", 0))
        melon = _series(games, lambda r: (r.get("seeds") or {}).get("MELON", 0))
        print(f"  per-crop seed held at d{d0}:  WHEAT={held.get(d0)}  "
              f"STRAWBERRY={straw.get(d0)}  MELON={melon.get(d0)}")
        print(f"  per-crop tiles  at d{d0}:  WHEAT={_series(games, lambda r: r['stock'].get('plant_WHEAT', 0)).get(d0)}  "
              f"STRAWBERRY={_series(games, lambda r: r['stock'].get('plant_STRAWBERRY', 0)).get(d0)}  "
              f"MELON={_series(games, lambda r: r['stock'].get('plant_MELON', 0)).get(d0)}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", default="diag-replays/d2-base")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=8)
    ap.add_argument("--node", action="append", default=None,
                    help="trace one node (repeatable; default: all)")
    ap.add_argument("--days", default="0-12")
    ap.add_argument("--effects", nargs=2, metavar=("BASE", "ARM"), default=None,
                    help="print the per-node side-effects of a knob change (dirs with games.csv)")
    a = ap.parse_args(argv)
    if a.effects:
        effects(a.effects[0], a.effects[1])
        return 0
    lo, hi = (int(x) for x in a.days.split("-"))
    games = _load(a.run_dir, a.glob, a.max_games)
    print(f"# cause_trace  {len(games)} games from {a.run_dir}  window d{lo}-{hi}")
    nodes = a.node if a.node else list(sg.NODES)
    for n in nodes:
        if n not in sg.NODES:
            print(f"unknown node {n}; known: {sorted(sg.NODES)}")
            continue
        trace(games, n, lo, hi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
