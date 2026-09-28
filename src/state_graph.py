"""state_graph — the causal DAG evaluated IN-STATE: which root is holding us back right now.

`tools/phases/dag.py` and `divergence`/`propagate` do this for a REPLAY -- after the fact.
This does it for the live state, which is what turns the benchmark from a report into a
control loop:

  read(state)      the live value of every node we can observe from one observation
  targets          `src/benchmark.py` -- his own day-wise p25/p50/p75 for that metric
  deviation(state) ours vs target, per node
  roots(state)     deficient nodes with NO deficient ancestor: the cause, not the symptom
  pressures(state) root -> op-class multiplier, via CONTROLS and `_OP_FOR_NODE`

The pressures are what `crew.steer` returns and what `crew.job_value` multiplies into a job's
dollar value, so a day drifting off his surface pushes harder on exactly the work that closes
it -- no new constant, no new arm.

TWO DELIBERATE LIMITS, both stated rather than hidden:

1. **Stock nodes only.** The agent is stateless -- it cannot remember a day's accumulated
   flows -- so the flow nodes (`water_ops`, `feed_ops`, `harvests`) are not evaluated. The
   live proxies used instead are the leading indicators that PREDICT those flows: a plant dry
   tonight (`dry_plants`) becomes a death, an animal unfed tonight (`unfed`) an escape.
2. **REVENUE IS IN THE SAME LOOP.** `end_money` is a node. If survival pressure starts costing
   revenue, the money node goes deficient and its own pressure rises, pushing back on
   SELL/HARVEST. That is what keeps the machine pointed at his revenue curve rather than just
   at his defect surface -- the two pull on the same controller.
"""
from __future__ import annotations

import collections

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import benchmark as _bench
from . import priors as _priors
from . import state_graph_data as D

# ============================================================================ THE GRAPH
# Nodes ARE the heuristics from `docs/boey_bench.md` / `docs/boey_priors.md` -- not the
# structural DAG with a table bolted on the side. Each node carries its own target source,
# the direction it improves in, the ops that move it, its DEADLINE CLASS (which is what gives
# the graph its time dimension) and the day window in which it is live at all.
#
#   deadline   tonight  the loss is realised at `_end_of_day` -> urgency ramps through the
#                       day, because at hour 22 there is no tomorrow to fix it
#              never    the loss just accumulates (a weed blocks a tile, it does not expire)
#              season   the deadline is the bell; urgency grows as the days run out
#              window   the deadline is a CROP PLANTING/WATER WINDOW, which closes on a day
#   window     (first_day, last_day) -- outside it the node is not steering-relevant. The
#              graph therefore GROWS and SHRINKS with the game: `quadrants` is live d0-12,
#              `structures` d0-20, and the endgame relaxes the rest because his own targets
#              rise after d20 (he stops servicing the farm on purpose).
Node = collections.namedtuple("Node", "source metric better ops deadline window")

NODES = {
    # ---- defects: lower is better -----------------------------------------
    "weeds":      Node("bench", "weeds_max", "lower", ("DIG",), "never", (0, 29)),
    "dry_plants": Node("bench", "plants_died", "lower", ("WATER",), "tonight", (0, 24)),
    "unfed":      Node("bench", "animals_escaped", "lower", ("FEED", "PICKUP"),
                       "tonight", (0, 24)),
    "shed":       Node("bench", "max_shed_total", "lower", ("DROP",), "tonight", (0, 29)),
    # ---- revenue: higher is better, deadline the bell ----------------------
    "money":      Node("bench", "end_money", "higher", ("SELL", "HARVEST"), "season", (0, 29)),
    # ---- the build: standing state from the priors -------------------------
    "planted":    Node("priors", "planted", "higher", ("PLANT",), "season", (0, 26)),
    # `empty` is a RENT, and TWO op classes close it: sow it (PLANT) or buy the seed to sow it
    # (BUY_SEED). Naming both lets the market layer be steered by the same node as the crew.
    "empty":      Node("priors", "empty", "lower", ("PLANT", "BUY_SEED"), "season", (0, 26)),
    "animals":    Node("priors", "total_animals", "higher",
                       ("PLACE", "BUILD_PASTURE", "BUILD_COOP", "PICKUP"), "season", (0, 24)),
    "structures": Node("priors", "structs", "higher",
                       ("BUILD_PASTURE", "BUILD_COOP"), "season", (0, 20)),
    "quadrants":  Node("priors", "n_quadrants", "higher", ("BUY_LAND",), "window", (0, 12)),
    # ---- THE MELON CALENDAR ------------------------------------------------------------
    # Melon's planting window shuts at d2 and `first_yield_day` is 10, so the d0-d2 block IS
    # the d10-d12 revenue event. MEASURED: we hold 4 age-10 melon tiles at d10 against his 7,
    # and d10 is a **$9k step** (bank $8 vs $9,054). As a node it is a deficiency the graph can
    # act on while there is still time, instead of a surprise at d10.
    "melon_tiles": Node("priors", "melon", "higher", ("PLANT",), "window", (0, 3)),
    # ---- THE REVENUE CHAIN --------------------------------------------------------------
    # `money` alone is a STOCK that starts near zero, so its ratio is binary and its pressure
    # saturates (measured: `1 + 9054/9054` = 2.0 at d10). The chain gives the gradient back and
    # lets `roots` blame the HEAD (capacity) rather than the tail (the bank).
    #   capacity -> output_per_day -> revenue_per_day -> money
    "output_per_day": Node("derived", "output_per_day", "higher",
                           ("PLANT", "FERTILIZE", "WATER", "HARVEST"),
                           "season", (1, 26)),
    "revenue_per_day": Node("bench", "money_delta", "higher",
                            ("SELL", "HARVEST"), "season", (0, 28)),
    # ---- LABOUR --------------------------------------------------------------
    # The crew is a BENCHMARK quantity, not a ground constant: `owned_tiles // TILES_PER_HAND`
    # = 6 hands on the opening quadrant against the reference's 5.8 EARLY but 9.6 by d6 and 12.4
    # by d10 on the SAME 25 tiles, because the herd's 3 ops/animal/day dominate the workload.
    # Node `labour` compares our crew to his measured unit-turn curve; `plan.hand_target` reads
    # the same number, so diagnosis and actuation cannot drift apart.
    "labour": Node("bench", "unit_turns", "higher", ("HIRE",), "season", (0, 29)),
}

# How hard urgency ramps for each deadline class. The numbers are the CONTROL GAIN: a
# tonight node is worth 2.5x at hour 23 what it is worth at hour 0, because the action has to
# happen today or the loss is permanent.
HOUR_RAMP = 1.5
DAY_RAMP = 0.8

# The causal edges, kept from the measured DAG and re-pointed at these nodes. (cause, effect)
# A deficient cause makes the effect a SYMPTOM, which is how `roots` avoids chasing leaves.
#
# NOTE the revenue guard is NOT an edge. `("money", "dry_plants")` was tried and is WRONG: it
# says money causes dry plants, which makes dry plants a SYMPTOM of money and `roots` then
# skips it -- measured, WATER pressure came back `None` and deaths rose to 62. Revenue is a
# COMPETING CLAIM, not a cause: it works by money's own pressure raising SELL/HARVEST, which
# then competes with WATER inside the same priority multiplication.
EDGES = (
    ("empty", "planted"),
    ("planted", "money"),
    ("animals", "money"),
    ("structures", "animals"),
    ("quadrants", "planted"),
    ("unfed", "animals"),
    ("dry_plants", "planted"),
    ("weeds", "planted"),
    ("shed", "money"),
    # the revenue chain, so a deficient BANK points at its head rather than at the selling
    ("quadrants", "melon_tiles"),
    ("melon_tiles", "revenue_per_day"),
    ("planted", "output_per_day"),
    ("animals", "output_per_day"),
    ("output_per_day", "revenue_per_day"),
    ("revenue_per_day", "money"),
)

_LIVE = {
    "weeds": lambda s: sum(1 for row in s.tiles for t in row
                           if isinstance(t, dict) and t.get("kind") == "WEED"),
    "planted": lambda s: sum(1 for row in s.tiles for t in row
                             if isinstance(t, dict) and t.get("kind") == "PLANT"),
    "dry_plants": lambda s: sum(1 for row in s.tiles for t in row
                                if isinstance(t, dict) and t.get("kind") == "PLANT"
                                and not t.get("watered_today")),
    "unfed": lambda s: sum(1 for row in s.tiles for t in row
                           if isinstance(t, dict) and "animal" in t
                           and t.get("consecutive_unfed", 0) >= 1),
    "animals": lambda s: s.herd_count(),
    "structures": lambda s: sum(1 for row in s.tiles for t in row
                                if isinstance(t, dict)
                                and t.get("kind") in ("COOP", "PASTURE")),
    "empty": lambda s: sum(1 for y, row in enumerate(s.tiles) for x, t in enumerate(row)
                           if t is None and s.owned((x, y))),
    "shed": lambda s: s.shed_total(),
    "money": lambda s: s.money,
    "quadrants": lambda s: len(s.unlocked),
    "melon_tiles": lambda s: sum(1 for row in s.tiles for t in row
                                 if isinstance(t, dict) and t.get("crop") == "MELON"),
    "output_per_day": lambda s: _output_per_day(s),
}


def _output_per_day(state):
    """Dollars the standing farm can pay out per day, from the engine's own rates.

    THE MIDDLE LINK of the revenue chain, and it is COMPUTED rather than measured: every
    standing tile earns `recipes.units_per_tile_day(crop) x price`, the herd earns
    `1/interval x price` per animal, and feeding costs one wheat per animal per day. This is the
    capacity number the bank is a lagging function of.
    """
    from . import crew, recipes
    pr = crew.prices(state)
    total = 0.0
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                total += recipes.units_per_tile_day(t["crop"]) * pr.get(t["crop"], 0.0)
    for row in state.tiles:
        for t in row:
            if isinstance(t, dict) and "animal" in t:
                total += value.animal_output_per_day(t["animal"]) * pr.get(
                    {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}[t["animal"]], 0.0)
                total -= pr.get("WHEAT", 0.0)          # one wheat per animal per day
    return max(0.0, total)

# Farm-relative widths for the zero-target metrics, so the gain carries information instead
# of saturating on the first unit.
_WIDTH = {"dry_plants": ("planted", 0.05), "weeds": ("planted", 0.05),
          "unfed": ("animals", 0.10), "shed": (None, 0.10), "empty": ("planted", 0.10),
          "structures": ("animals", 0.20)}


def read(state):
    out = {}
    for name, fn in _LIVE.items():
        try:
            out[name] = float(fn(state))
        except Exception:                                     # noqa: BLE001
            continue
    return out


def target_of(node, day):
    spec = NODES.get(node)
    if not spec:
        return None
    if spec.source == "bench":
        return _bench.target(spec.metric, day)
    if spec.metric == "total_animals":
        return _priors.total_animals(day)
    if spec.metric == "n_quadrants":
        return float(_priors.land_target(day))
    if spec.metric == "output_per_day":
        # DERIVED from his own targets: his planted tiles at his recipe rate, plus his herd.
        # Not a tuned constant -- the same formulas applied to HIS capacity.
        from . import recipes as _r
        planted = _priors.crop_target(day, "planted")
        animals = _priors.total_animals(day)
        rate = _r.units_per_tile_day("WHEAT")          # wheat is the sustaining line
        return planted * rate * 25.0 + animals * 100.0
    return _priors.crop_target(day, spec.metric)


def urgency(node, state):
    """How much of the day / season is left for this node -- THE TIME DIMENSION.

    A `tonight` node's loss is realised at `_end_of_day`, so the same deviation is worth far
    more at hour 22 than at hour 3: there is no tomorrow to fix it. A `season` node's deadline
    is the bell. A `never` node (a weed) just blocks, so it does not ramp. This is what stops
    the graph being static -- the steering within a single day is now a function of the hour.
    """
    spec = NODES.get(node)
    if not spec:
        return 1.0
    hour = int(getattr(state, "hour", 0))
    day = int(state.day)
    if spec.deadline == "tonight":
        return 1.0 + HOUR_RAMP * (hour / 23.0) ** 2
    if spec.deadline == "season":
        left = max(0, 29 - day)
        return 1.0 + DAY_RAMP * (1.0 - left / 29.0)
    if spec.deadline == "window":
        last = spec.window[1]
        left = max(0, last - day)
        return 1.0 + DAY_RAMP * (1.0 - min(1.0, left / max(1, last)))
    return 1.0


def active(node, state):
    spec = NODES.get(node)
    if not spec:
        return False
    return spec.window[0] <= int(state.day) <= spec.window[1]


def deviation(state):
    """[(node, ours, his_p50, raw_pressure, urgency)] for every live, active node."""
    live = read(state)
    day = int(state.day)
    rows = []
    for node, ours in live.items():
        if not active(node, state):
            continue
        spec = NODES[node]
        tgt = target_of(node, day)
        if tgt is None:
            continue
        if spec.better == "higher":
            p = 1.0 if ours >= tgt else 1.0 + min(2.0, (tgt - ours) / max(1.0, abs(tgt)))
        else:
            w = _WIDTH.get(node)
            width = None
            if w:
                base, frac = w
                width = max(1.0, frac * max(1.0, live.get(base, 0.0) if base else 100.0))
            p = _bench.pressure(spec.metric, day, ours, width=width) \
                if spec.source == "bench" else 1.0 + min(2.0, (ours - tgt) / max(1.0, width or 1.0))
        rows.append((node, ours, tgt, p, urgency(node, state)))
    return rows


def deficient(state, tol=0.0):
    return [r for r in deviation(state) if r[3] > 1.0 + tol]


def roots(state, tol=0.0):
    """Deficient nodes with no deficient ancestor -- the cause, not the symptom."""
    bad = {r[0] for r in deficient(state, tol)}
    causes = {}
    for a, b in EDGES:
        causes.setdefault(b, set()).add(a)
    out = []
    for node, ours, tgt, p, u in deficient(state, tol):
        if not (causes.get(node, set()) & bad):
            out.append((node, ours, tgt, p, u, sorted(causes.get(node, set()))))
    return out


def pressures(state, cap=6.0):
    """op class -> pressure, from the deficient ROOTS, with the time dimension applied."""
    out = {}
    for node, _o, _t, p, u, _up in roots(state):
        eff = min(cap, 1.0 + (p - 1.0) * u)
        for op in NODES[node].ops:
            out[op] = max(out.get(op, 1.0), eff)
    return out


def apply_to_jobs(jobs, state):
    """Re-weight job PRIORITIES by the graph. This is what makes the graph force play.

    The dollar kernel lost every arm it was tried in, so the graph must steer the kernel that
    works -- `src/roots.apply`'s idea, fed by the benchmark rather than by a hand-rolled
    urgency. Multiplicative on the existing priority, so the shape of the plan is unchanged
    and only the ORDER within a class moves.
    """
    mul = pressures(state)
    if not mul:
        return jobs
    return [j._replace(priority=j.priority * mul.get(j.op, 1.0)) for j in jobs]


def report(state):
    lines = []
    for node, ours, tgt, p, u in deficient(state):
        eff = 1.0 + (p - 1.0) * u
        op = ",".join(NODES[node].ops) or "-"
        lines.append(f"      {node:<12} ours {ours:>8.1f}  his {tgt:>9.1f}  "
                     f"dev {p:>4.2f}  urg {u:>4.2f}  eff {eff:>4.2f}  -> {op}")
    return lines
