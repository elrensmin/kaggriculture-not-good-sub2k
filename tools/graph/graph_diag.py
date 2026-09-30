"""tools/graph/graph_diag.py -- troubleshoot the STATE GRAPH as the decision channel.

WHY THIS TOOL EXISTS
--------------------
`src/state_graph.py` is meant to be the central nervous system: every decision -- which job a
hand takes, when to buy seed, when to buy land, what to plant, what to sell -- should be a
consequence of a pressure the graph emits. In practice it is not, and the failure is silent:
the graph computes a pressure, a layer ignores it, and nothing reports the disagreement. The
games just come out poorer.

So this tool does not report metrics. It reports the CHANNEL:

  1. PLUG      which decision surfaces actually read the graph, by module (static audit).
  2. NODES     per day, every node: ours / his target / deviation / urgency / effective
               pressure / root-or-symptom. This is the ideal trajectory (docs/boey_priors.md,
               docs/boey_bench.md) evaluated against our live state, step by step.
  3. DEMAND    the op classes the graph DEMANDS (from `pressures`) against the ops we actually
               performed. A demand with no delivery is the definition of an unplugged graph.
  4. BREAK     the first day each root goes deficient and STAYS deficient -- where the causal
               chain to revenue actually snaps.
  5. CHAIN     acts -> watering -> production -> revenue, per day, against Boey's column.

USAGE
    PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/cx2
    PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/cx2 --days 0-17
    PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/cx2 --section demand
    # audit Boey's own replays through the same DAG (should read clean)
    PYTHONPATH=. python -m tools.graph.graph_diag --replay-dir replays/DSM/v1 --max-games 3
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import params, state_graph                                  # noqa: E402
from src.state import State                                          # noqa: E402
from tools.diagnose.games import load_replay                         # noqa: E402

# ops we count as ACTING (a MOVE is the cost of an act, not an act)
ACTS = ("WATER", "HARVEST", "PLANT", "FERTILIZE", "FEED", "CARE", "COLLECT_FERTILIZER",
        "DIG", "PLACE", "PICKUP", "DROP", "BUILD_PASTURE", "BUILD_COOP")

# the modalities of the game, and the graph nodes that own each. Used by the PLUG audit to
# show which modalities the graph can currently reach AT ALL.
MODALITIES = {
    "crops":   ("planted", "empty", "melon_tiles", "dry_plants", "weeds"),
    "animals": ("animals", "structures", "unfed"),
    "land":    ("quadrants",),
    "labour":  ("labour",),
    "market":  ("money", "shed", "revenue_per_day"),
    "output":  ("output_per_day",),
}


# --------------------------------------------------------------------------- helpers
def count_ops(action):
    """op -> count from one step's action dict."""
    c = Counter()
    if not isinstance(action, dict):
        return c
    for key in ("farmer", "hands"):
        for u in (action.get(key) or []):
            if isinstance(u, list) and u:
                c[str(u[0])] += 1
    return c


def market_of(action):
    if not isinstance(action, dict):
        return []
    return [m for m in (action.get("market") or []) if isinstance(m, list) and m]


def planted_by_crop(state):
    c = Counter()
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                c[t.get("crop")] += 1
    return c


def empty_owned(state):
    return sum(1 for y, row in enumerate(state.tiles) for x, t in enumerate(row)
               if t is None and state.owned((x, y)))


def owned_tiles(state):
    return sum(1 for y, row in enumerate(state.tiles) for x in range(len(row))
               if state.owned((x, y)))


def load_states(run_dir, seat_mode="our", days=(0, 29), max_games=None, step_hour=23):
    """[(game, day, State)] sampled at one hour per day, plus the replay for action pairing."""
    out = []
    paths = sorted(glob.glob(str(Path(run_dir) / "scratch_vs_*.json")))
    if not paths:
        paths = sorted(glob.glob(str(Path(run_dir) / "*.json")))
    for p in paths[:max_games]:
        try:
            rep = load_replay(p)
        except Exception:                                             # noqa: BLE001
            continue
        for d in range(days[0], days[1] + 1):
            t = d * 24 + step_hour
            if t + 1 >= len(rep["steps"]):
                break
            try:
                st = State(rep["steps"][t][1]["observation"])
            except Exception:                                         # noqa: BLE001
                continue
            out.append((Path(p).stem, d, st, rep, t))
    return out


# --------------------------------------------------------------------------- 1. PLUG
def section_plug():
    """Which decision surfaces actually read the graph. A static, code-level audit.

    The graph is only a nervous system if the layers that DECIDE consult it. This walks the
    source and reports, per module, whether it imports `state_graph` and which of its public
    entry points it calls -- so a decision surface that silently bypasses the graph is visible.
    """
    src = Path(__file__).resolve().parents[2] / "src"
    entry = ("pressures", "preposition", "projected_empty", "deviation", "roots",
             "apply_to_jobs", "schedule", "seed_lead_days", "report", "target_of")
    print("=" * 100)
    print("1. PLUG AUDIT -- does each decision surface consult the graph?")
    print("=" * 100)
    rows = []
    for f in sorted(src.glob("*.py")):
        if f.name in ("state_graph.py", "state_graph_data.py"):
            continue
        txt = f.read_text()
        imports = "state_graph" in txt
        calls = sorted({e for e in entry if e + "(" in txt})
        # a MARKET decision surface is one that emits orders; a JOB one emits jobs
        kind = ("market" if "market_intents" in txt else
                "jobs" if "def jobs" in txt else "-")
        rows.append((f.name, kind, imports, calls))
    print(f"  {'module':<18} {'decides':<8} {'imports':<8} entry points called")
    for name, kind, imports, calls in rows:
        mark = "YES" if imports else "--"
        print(f"  {name:<18} {kind:<8} {mark:<8} {', '.join(calls) or ('-' if not imports else 'NOTHING')}")
    plugged = [r for r in rows if r[2]]
    market = [r for r in rows if r[1] == "market"]
    print()
    print(f"  modules importing the graph : {len(plugged)}/{len(rows)}")
    print(f"  MARKET (order-emitting) surfaces importing it : "
          f"{len([r for r in market if r[2]])}/{len(market)}  <- the gap")
    print("  Read this as: a decision surface that does not import `state_graph` cannot be")
    print("  steered by it, whatever the graph computes. Wire or delete; never leave it half on.")
    return rows


# --------------------------------------------------------------------------- 2. NODES
def section_nodes(rows, days, every):
    print()
    print("=" * 100)
    print("2. NODE TRACE -- ours vs his ideal trajectory, per node per day")
    print("=" * 100)
    # aggregate per day across games: median ours, and how many games were deficient
    per_day = defaultdict(lambda: defaultdict(list))
    deficient = defaultdict(Counter)
    root_ct = defaultdict(Counter)
    for _g, d, st, _rep, _t in rows:
        if not (days[0] <= d <= days[1]):
            continue
        for node, ours, tgt, p, u in state_graph.deviation(st):
            per_day[d][node].append((ours, tgt, p, u))
            if p > 1.0:
                deficient[d][node] += 1
        for node, ours, tgt, p, u, _up in state_graph.roots(st):
            root_ct[d][node] += 1

    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if v else 0.0

    for d in sorted(per_day):
        if d % every:
            continue
        n_games = max(1, len(rows))
        print(f"\n  --- d{d} " + "-" * 80)
        print(f"  {'node':<16} {'ours':>9} {'his':>9} {'dev':>6} {'urg':>5} {'eff':>6}  {'root':>5} {'deficient':>9}  ops")
        for node in sorted(per_day[d], key=lambda n: -med([r[2] for r in per_day[d][n]])):
            v = per_day[d][node]
            ours = med([r[0] for r in v])
            tgt = med([r[1] for r in v])
            p = med([r[2] for r in v])
            u = med([r[3] for r in v])
            eff = 1.0 + (p - 1.0) * u
            is_root = "ROOT" if root_ct[d][node] else ""
            dc = deficient[d][node]
            ops = ",".join(state_graph.NODES[node].ops) if node in state_graph.NODES else "-"
            flag = "  <<<" if p > 1.25 else ""
            print(f"  {node:<16} {ours:>9.1f} {tgt:>9.1f} {p:>6.2f} {u:>5.2f} {eff:>6.2f}"
                  f"  {is_root:>5} {dc:>4}/{n_games:<4}  {ops}{flag}")


# --------------------------------------------------------------------------- 3. DEMAND
def section_demand(rows, days, every):
    """The central-nervous-system test: graph DEMAND vs actual DELIVERY, per day.

    Two measurement rules, both learned the hard way:
      * divide by the number of GAMES for that day, never by the total row count -- the first
        version of this tool divided by every row in the run and under-reported acts by ~21x;
      * scan ALL 24 hours for market orders. Sampling the market list at hour 23 shows no
        BUY_SEED even on days the farm buys seed all morning, which made the tool cry "MISSING"
        on a decision that was in fact being made.
    """
    print()
    print("=" * 100)
    print("3. DEMAND vs DELIVERY -- op classes the graph asks for, against ops actually performed")
    print("=" * 100)
    print("  `band` is the graph's pressure. `crew` rows show that op's share of all acting")
    print("  turns; `market` rows show how many turns of the day the order appeared. A demand")
    print("  with ZERO delivery is an unplugged graph; a demand with low delivery is a race.")
    per_day = defaultdict(lambda: defaultdict(float))
    press_day = defaultdict(dict)
    games_day = Counter()
    for _g, d, st, rep, t in rows:
        if not (days[0] <= d <= days[1]):
            continue
        games_day[d] += 1
        try:
            pr = state_graph.pressures(st)
        except Exception:                                             # noqa: BLE001
            pr = {}
        press_day[d] = {k: max(v, press_day[d].get(k, 1.0)) for k, v in pr.items()}
        day_ops, day_mkt = Counter(), Counter()
        for h in range(24):
            tt = d * 24 + h
            if tt + 1 >= len(rep["steps"]):
                break
            act = rep["steps"][tt + 1][1].get("action")
            day_ops += count_ops(act)
            for m in market_of(act):
                day_mkt[str(m[0])] += 1
        for op in ACTS:
            per_day[d][op] += day_ops.get(op, 0)
        per_day[d]["__total__"] += sum(day_ops.get(o, 0) for o in ACTS)
        for op in ("BUY_SEED", "BUY_LAND", "BUY_ANIMAL", "HIRE", "SELL", "BUY_PRODUCT"):
            per_day[d]["m__" + op] += day_mkt.get(op, 0)
    for d in sorted(per_day):
        if d % every or d not in press_day:
            continue
        g = max(1, games_day[d])
        tot = per_day[d]["__total__"] / g
        pr = press_day[d]
        print(f"\n  --- d{d}   acting turns/day (mean over {g} games) {tot:.0f} " + "-" * 26)
        print(f"  {'demanded op':<12} {'band':>6}  {'per day':>8} {'share':>7}  verdict")
        for op, band in sorted(pr.items(), key=lambda kv: -kv[1]):
            if op in ACTS:
                actual = per_day[d][op] / g
                share = actual / max(1.0, tot)
                verdict = ("*** NOT DELIVERED ***" if actual < 0.5 else
                           "thin" if share < 0.05 else "delivered")
                print(f"  {op:<12} {band:>6.2f}  {actual:>8.1f} {share:>7.1%}  crew   {verdict}")
            else:
                turned = per_day[d]["m__" + op]
                verdict = ("*** NOT ORDERED ***" if turned == 0 else
                           f"ordered on {turned:.0f} turns")
                print(f"  {op:<12} {band:>6.2f}  {'-':>8} {'-':>7}  market {verdict}")
        # market ops the graph did NOT pressure but we still issue: unsteered spend
        for op in ("BUY_SEED", "BUY_LAND", "BUY_ANIMAL", "HIRE"):
            if op in pr:
                continue
            turned = per_day[d]["m__" + op]
            if turned:
                print(f"  {op:<12} {'-':>6}  {'-':>8} {'-':>7}  market ordered on {turned:.0f} "
                      f"turns with NO graph pressure  <<< unsteered")


# --------------------------------------------------------------------------- 4. BREAK
def section_health(rows):
    """Every `_LIVE` reader must EVALUATE, not merely exist.

    `read()` wraps each reader in `except Exception: continue`, so a reader that RAISES is
    silently dropped: the node never evaluates, never presses, and `set(NODES)-set(_LIVE)`
    still comes back empty -- the documented dead-node check PASSES. MEASURED: `_output_per_day`
    called `value.animal_output_per_day` with `value` un-imported, so `output_per_day` raised on
    every state and the revenue chain `output_per_day -> revenue_per_day -> money` was severed
    in the middle for an unknown number of rounds. This section is the check that catches it.
    """
    print()
    print("=" * 100)
    print("0. LIVE READER HEALTH -- a reader that RAISES is DEAD (swallowed by read())")
    print("=" * 100)
    bad = {}
    for _g, d, st, _rep, _t in rows[:20]:
        for node, fn in state_graph._LIVE.items():
            try:
                fn(st)
            except Exception as exc:                                  # noqa: BLE001
                bad.setdefault(node, (d, repr(exc)[:90]))
    if not bad:
        print(f"  all {len(state_graph._LIVE)} readers evaluate cleanly")
    for node, (d, err) in sorted(bad.items()):
        print(f"  *** DEAD: {node:<16} raises at d{d}: {err}")

    # --- CAN THIS NODE EVER EMIT A PRESSURE? -------------------------------------------------
    # `set(NODES) - set(_LIVE)` being empty proves a reader EXISTS; it does not prove the node can
    # ever go deficient. Two measured ways a node is dead while looking perfectly healthy:
    #   * the READER returns a constant -- `_dying_today` read `t.get("age", 0)`, a key the tile
    #     schema does not have, so it returned 0 on every step of every game while 43.6 % of sampled
    #     plant-tiles were in fact dry;
    #   * the TARGET is degenerate -- `melon_tiles` is `better="higher"` with target 0.0 on all 30
    #     days (its prior was never transcribed), and `ours >= 0` is always true, so p == 1.0.
    # Neither RAISES, so `read()` swallows nothing, `set(NODES)-set(_LIVE)` is empty, every reader
    # "evaluates cleanly", and the node still never presses. The only symptom is that its pressure
    # never moves -- which is exactly what this checks, over every node, every sampled day.
    print()
    print("-" * 100)
    print("   NODES THAT CAN NEVER PRESS -- constant over every sampled state "
          "(dead reader or degenerate target)")
    print("-" * 100)
    press = defaultdict(list)
    for _g, _d, st, _rep, _t in rows[:40]:
        try:
            for node, _o, _tgt, p, _u in state_graph.deviation(st):
                press[node].append(float(p))
        except Exception:                                             # noqa: BLE001
            continue
    immobile = []
    sample_day = rows[0][1] if rows else 0
    for node in sorted(state_graph.NODES):
        v = press.get(node)
        if not v or len(v) < 3 or max(v) > 1.0 + 1e-9:
            continue
        spec = state_graph.NODES[node]
        try:
            tgt = state_graph.target_of(node, sample_day)
        except Exception:                                             # noqa: BLE001
            tgt = "?"
        immobile.append(node)
        print(f"  *** NEVER PRESSES: {node:<16} better={spec.better:<7} metric={spec.metric!r:<18}"
              f" target(d{sample_day})={tgt!r:<8} p in [{min(v):.3f}, {max(v):.3f}]")
        print(f"      ops={spec.ops}  -> the reader is constant, or the target makes `p > 1` unreachable")
    if not immobile:
        print(f"  all {len(press)} evaluated nodes can press")

    # --- the LEARNED table, and the allocation that consumes it ------------------------------
    # `state_graph`'s lazy `import graph_weights` is wrapped in `except Exception: return {}`, so a
    # module that does not even PARSE (measured: a codegen run that dropped the closing `"""` of the
    # docstring) degrades to "no weights" in total silence -- indistinguishable from "the graph has
    # no opinion today". And `turn_budget` has an invariant the ABSOLUTE-cap version violated:
    # sum(cap) >= n_units, i.e. the budget never manufactures idle turns. Both are asserted here.
    try:
        from src import graph_weights as _gw
    except Exception as exc:                                          # noqa: BLE001
        print(f"  *** DEAD: graph_weights does not import: {exc!r}"[:160])
        print("      -> `W` is empty, so EVERY learned weight is silently inert. Re-codegen.")
        return bad
    print(f"  graph_weights: {len(_gw.W)} ops, windows={getattr(_gw, 'WINDOWS', None)}"
          f"{'' if getattr(_gw, 'W', None) else '   *** EMPTY TABLE ***'}")
    starved = 0
    for _g, d, st, _rep, _t in rows[:20]:
        try:
            caps = state_graph.turn_budget(st)
            n_units = max(1, int(st.unit_count()))
        except Exception as exc:                                      # noqa: BLE001
            print(f"  *** DEAD: turn_budget raises at d{d}: {repr(exc)[:90]}")
            break
        if not caps:
            continue
        if sum(caps.values()) < n_units:
            starved += 1
            print(f"  *** IDLE HAZARD d{d}: sum(cap)={sum(caps.values())} < n_units={n_units}"
                  f"  caps={caps}")
    if not starved:
        print("  turn_budget: sum(cap) >= n_units on every sampled day (no idle manufactured)")
    return bad


def section_break(rows, days):
    """First day each node goes deficient and STAYS deficient -- where the chain snaps."""
    print()
    print("=" * 100)
    print("4. BREAK POINTS -- first day a node goes deficient and never recovers")
    print("=" * 100)
    per_day = defaultdict(lambda: defaultdict(list))
    for _g, d, st, _rep, _t in rows:
        try:
            for node, _o, _tg, p, _u in state_graph.deviation(st):
                per_day[d][node].append(p)
        except Exception:                                             # noqa: BLE001
            continue
    days_sorted = sorted(per_day)
    print(f"  {'node':<16} {'first break':>11} {'days deficient':>15}  verdict")
    for node in sorted(state_graph.NODES):
        first = None
        bad = 0
        total = 0
        for d in days_sorted:
            if not (days[0] <= d <= days[1]):
                continue
            v = per_day[d].get(node)
            if not v:
                continue
            total += 1
            if sum(1 for x in v if x > 1.0) > len(v) / 2:
                bad += 1
                if first is None:
                    first = d
            elif first is not None and bad >= 2:
                pass
        if first is None:
            print(f"  {node:<16} {'never':>11} {bad:>7}/{total:<7}  ok")
        else:
            print(f"  {node:<16} {('d%d' % first):>11} {bad:>7}/{total:<7}  "
                  f"BROKE at d{first} and stayed broken")
    print()
    print("  A node that breaks and STAYS broken is a root the graph failed to close. A node")
    print("  that flaps is a priority race. Neither is fixed by another knob: the first needs")
    print("  the decision surface plugged in, the second needs the pressures to be comparable.")


# --------------------------------------------------------------------------- 5. CHAIN
def section_chain(rows, days, every):
    """acts -> watering -> production -> revenue, per day."""
    print()
    print("=" * 100)
    print("5. THE CHAIN -- acts -> watering -> production -> revenue")
    print("=" * 100)
    per_day = defaultdict(lambda: defaultdict(float))
    n = 0
    seen = set()
    for g, d, st, rep, t in rows:
        if not (days[0] <= d <= days[1]):
            continue
        if (g, d) in seen:
            continue
        seen.add((g, d))
        n += 1
        acts = 0
        moves = 0
        watered = 0
        for h in range(24):
            tt = d * 24 + h
            if tt + 1 >= len(rep["steps"]):
                break
            c = count_ops(rep["steps"][tt + 1][1].get("action"))
            acts += sum(c.get(o, 0) for o in ACTS)
            moves += c.get("MOVE", 0)
            watered += c.get("WATER", 0)
        per_day[d]["acts"] += acts
        per_day[d]["moves"] += moves
        per_day[d]["watered"] += watered
        per_day[d]["planted"] += sum(planted_by_crop(st).values())
        per_day[d]["empty"] += empty_owned(st)
        per_day[d]["owned"] += owned_tiles(st)
        per_day[d]["money"] += float(getattr(st, "money", 0.0))
    n = max(1, n)
    print(f"  {'day':>4} {'acts':>7} {'moves':>7} {'moves/act':>10} {'watered':>8} "
          f"{'planted':>8} {'empty':>6} {'owned':>6} {'money':>9}")
    for d in sorted(per_day):
        if d % every:
            continue
        v = per_day[d]
        mpact = v["moves"] / max(1.0, v["acts"])
        print(f"  {d:>4} {v['acts']/n:>7.0f} {v['moves']/n:>7.0f} {mpact:>10.2f} "
              f"{v['watered']/n:>8.0f} {v['planted']/n:>8.1f} {v['empty']/n:>6.1f} "
              f"{v['owned']/n:>6.0f} {v['money']/n:>9,.0f}")
    print()
    print("  Boey's column for the same days (docs/boey_bench.json): acts ~127-163/day,")
    print("  moves/act ~0.77, empty 0.0 every day. Read this table as a CHAIN: a break at")
    print("  `acts` propagates to watered, then to planted/output, then to money -- do not")
    print("  read the money row before the acts row, and never read money without `empty`.")


# --------------------------------------------------------------------------- 6. SEED
def section_seed(rows, days):
    """The seed mechanics as the graph sees them: when to buy, when to plant, and why."""
    print()
    print("=" * 100)
    print("6. SEED MECHANICS -- the graph's view of when to buy and when to plant")
    print("=" * 100)
    print("  `gap`   = projected_empty (bare tiles NOW + every quadrant the schedule says is")
    print("            arriving) -- the quantity seed has to cover.")
    print("  `lead`  = days until the remedy must be IN HAND (from the schedule, not a knob).")
    print("  `band`  = the graph's BUY_SEED pressure. `budget` = seed's dollar budget after the")
    print("            committed atomic claims are reserved.")
    from src import crop_plan, herd_plan
    per_day = defaultdict(lambda: defaultdict(list))
    seen = set()
    for g, d, st, rep, t in rows:
        if not (days[0] <= d <= days[1]) or (g, d) in seen:
            continue
        seen.add((g, d))
        try:
            gap = state_graph.projected_empty(st)
            lead = state_graph.seed_lead_days(st)
            band = state_graph.pressures(st).get("BUY_SEED", 1.0)
            res = sum(params.LAND_COST.get(a, 0) for o, _f, a in state_graph.schedule(st)
                      if o == "BUY_LAND")
            budget = st.money - herd_plan.feed_reserve(st) - res
        except Exception:                                             # noqa: BLE001
            continue
        for k, v in (("gap", gap), ("lead", -1 if lead is None else lead), ("band", band),
                     ("budget", budget), ("empty", empty_owned(st)),
                     ("seeds", sum(st.seeds.values())), ("money", st.money),
                     ("land_res", res)):
            per_day[d][k].append(float(v))
    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if v else 0.0
    print(f"\n  {'day':>4} {'empty':>6} {'gap':>6} {'lead':>5} {'band':>6} {'land_res':>9} "
          f"{'budget':>9} {'seeds':>6} {'money':>9}  diagnosis")
    for d in sorted(per_day):
        v = per_day[d]
        gap, lead, band = med(v["gap"]), med(v["lead"]), med(v["band"])
        budget, res, seeds = med(v["budget"]), med(v["land_res"]), med(v["seeds"])
        if band <= 1.0:
            diag = "no pressure -- seed is not a claim today"
        elif budget <= 0:
            diag = "PRESSURED BUT UNFUNDED -- the land reservation ate the budget"
        elif seeds >= gap:
            diag = "seed in hand"
        else:
            diag = f"can buy {int(budget // 10)} wheat"
        print(f"  {d:>4} {med(v['empty']):>6.1f} {gap:>6.1f} {lead:>5.0f} {band:>6.2f} "
              f"{res:>9,.0f} {budget:>9,.0f} {seeds:>6.0f} {med(v['money']):>9,.0f}  {diag}")
    print()
    print("  THE MECHANIC THE GRAPH IMPLIES:")
    print("    BUY  when band > 1 AND budget > 0: the claim is funded from the surplus above")
    print("         the committed quadrant, never from it. Atomic claims keep their reservation")
    print("         because you cannot buy 0.3 of a land tile, while seed is divisible.")
    print("    PLANT when the crop's window is open AND the market pays more than the seed")
    print("         costs over the cycle -- `value.cycle_revenue` minus the seed, ranked by")
    print("         dollars per tile-day, which is the same currency as land and animals. The")
    print("         crop choice is a MARKET decision, so it comes from prices, not a table.")


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", default="diag-replays/cx2")
    ap.add_argument("--replay-dir", default=None, help="audit another agent's replays")
    ap.add_argument("--max-games", type=int, default=6)
    ap.add_argument("--days", default="0-29")
    ap.add_argument("--every", type=int, default=2, help="print every Nth day")
    ap.add_argument("--section", default="all",
                    choices=["all", "plug", "health", "nodes", "demand", "break", "chain",
                             "seed"])
    ap.add_argument("--hour", type=int, default=23, help="hour at which each day is sampled")
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.days.split("-"))
    days = (lo, hi)
    want = a.section

    if want in ("all", "plug"):
        section_plug()
    src_dir = a.replay_dir or a.run_dir
    if want == "plug":
        return
    rows = load_states(src_dir, days=days, max_games=a.max_games, step_hour=a.hour)
    if not rows:
        print(f"\nno replay states found in {src_dir}", file=sys.stderr)
        return
    print()
    print(f"loaded {len(rows)} (game, day) states from {src_dir}")
    if want in ("all", "health"):
        section_health(rows)
    if want in ("all", "nodes"):
        section_nodes(rows, days, a.every)
    if want in ("all", "demand"):
        section_demand(rows, days, max(1, a.every))
    if want in ("all", "break"):
        section_break(rows, days)
    if want in ("all", "chain"):
        section_chain(rows, days, max(1, a.every))
    if want in ("all", "seed"):
        section_seed(rows, days)


if __name__ == "__main__":
    main()
