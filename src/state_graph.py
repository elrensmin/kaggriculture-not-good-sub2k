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
import math

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import benchmark as _bench, params
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
    # MARKET-ONLY OPS. `money` is a STOCK that starts at 0 and `revenue_per_day` a FLOW, so both
    # are deficient by construction on every early day -- this file already said so. Licensing
    # HARVEST gave them a permanent, unearned ~2.2x boost to a CREW op, and the measured
    # consequence was the exact inversion of the priority kernel:
    #     d10  money eff 2.20 -> HARVEST 2.2x   |   dry_plants eff 1.00 -> WATER 1.0x
    # The crew harvested instead of watering, plants died 74 vs 59, revenue fell $99k -> $66k and
    # the arm lost half its bank ($58,899 -> $25,731 on PA=1). A crew job cannot be justified by a
    # bank balance; a bank balance justifies SELLING. HARVEST already exists for every ripe tile
    # and is priced by `crew`/`roots`, so it loses nothing by being removed here.
    "money":      Node("bench", "end_money", "higher", ("SELL",), "season", (0, 29)),
    # ---- the build: standing state from the priors -------------------------
    "planted":    Node("priors", "planted", "higher", ("PLANT",), "season", (0, 26)),
    # `empty` is a RENT, and TWO op classes close it: sow it (PLANT) or buy the seed to sow it
    # (BUY_SEED). Naming both lets the market layer be steered by the same node as the crew.
    "empty":      Node("priors", "empty", "lower", ("PLANT", "BUY_SEED"), "season", (0, 26)),
    "animals":    Node("priors", "total_animals", "higher",
                       ("PLACE", "BUILD_PASTURE", "BUILD_COOP", "PICKUP", "BUY_ANIMAL"),
                       "season", (0, 24)),
    # ---- CAPITAL DEPLOYMENT (see params.DEPLOY_NODE) ------------------------------------
    # The inverse of `money` for the investment phase: holding MORE cash than the reference's
    # trail means capital that was never turned into capacity. "lower" is correct -- the
    # deficiency is EXCESS cash -- and the ops are the acquisition set, so the graph presses
    # buying early instead of only ever pressing SELL.
    "deploy":     Node("priors", "cash_hold", "lower",
                       ("BUY_ANIMAL", "BUY_LAND", "BUY_SEED"), "season", (0, 12)),
    "structures": Node("priors", "structs", "higher",
                       ("BUILD_PASTURE", "BUILD_COOP"), "season", (0, 20)),
    "quadrants":  Node("priors", "n_quadrants", "higher", ("BUY_LAND",), "window", (0, 12)),
    # ---- THE MELON CALENDAR ------------------------------------------------------------
    # Melon's planting window shuts at d2 and `first_yield_day` is 10, so the d0-d2 block IS
    # the d10-d12 revenue event. MEASURED: we hold 4 age-10 melon tiles at d10 against his 7,
    # and d10 is a **$9k step** (bank $8 vs $9,054). As a node it is a deficiency the graph can
    # act on while there is still time, instead of a surprise at d10.
    # metric must be a `priors.CROPS` KEY. It read "melon", which was never a key -- `crop_target`
    # therefore returned its `0.0` default on every day, and with `better="higher"` the test
    # `ours >= 0` is always true, so the node was pinned at p == 1.0 and could never press PLANT.
    # The sibling keys are `wheat_tiles` / `straw_tiles`; `melon_tiles` follows them.
    "melon_tiles": Node("priors", "melon_tiles", "higher", ("PLANT",), "window", (0, 3)),
    # ---- THE REVENUE CHAIN --------------------------------------------------------------
    # `money` alone is a STOCK that starts near zero, so its ratio is binary and its pressure
    # saturates (measured: `1 + 9054/9054` = 2.0 at d10). The chain gives the gradient back and
    # lets `roots` blame the HEAD (capacity) rather than the tail (the bank).
    #   capacity -> output_per_day -> revenue_per_day -> money
    "output_per_day": Node("derived", "output_per_day", "higher",
                           ("PLANT", "FERTILIZE", "WATER", "HARVEST"),
                           "season", (1, 26)),
    # `revenue_per_day` had NO live reader, so it never evaluated, SELL and HARVEST never
    # received a pressure, and the chain `output_per_day -> revenue_per_day -> money` was severed
    # in the MIDDLE: a deficient bank could not blame production and production could never push
    # the market. It is DERIVED (source "derived") so `target_of` reaches it before the bench
    # branch, and its live reader is the sellable value actually on hand at the LIVE book.
    "revenue_per_day": Node("derived", "sellable_value", "higher",
                            ("SELL",), "season", (0, 28)),
    # ---- LABOUR --------------------------------------------------------------
    # The crew is a BENCHMARK quantity, not a ground constant: `owned_tiles // TILES_PER_HAND`
    # = 6 hands on the opening quadrant against the reference's 5.8 EARLY but 9.6 by d6 and 12.4
    # by d10 on the SAME 25 tiles, because the herd's 3 ops/animal/day dominate the workload.
    # Node `labour` compares our crew to his measured unit-turn curve; `plan.hand_target` reads
    # the same number, so diagnosis and actuation cannot drift apart.
    # `labour` was ALSO dead (no live reader), so HIRE had no pressure source at all -- and the
    # crew is wiped nightly, so the whole crew is rebuilt every morning and `MAX_ORDERS` truncates
    # the tail. DERIVED, with the benchmark unit-turn curve as its target.
    "labour": Node("derived", "units", "higher", ("HIRE",), "season", (0, 29)),
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
    ("animals", "structures"),
    ("quadrants", "planted"),
    ("quadrants", "empty"),
    ("labour", "empty"),
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

# ============================================================================ ANTICIPATION
# The graph above is a SNAPSHOT: `deviation` compares today's value to today's target, so it can
# only ever react. It has no way to say "act now for a board change three days out", which is
# exactly the measured defect -- Boey buys a quadrant and sows it the SAME day (19 plants on d6,
# `empty` 0 every day) while we buy on d6/d8 with no seed for the ground and leave it bare 1-2
# days. The `empty` node only jumps the day the land lands, and a snapshot graph asks for the
# seed a day late by construction.
#
# A LEAD EDGE fixes that generally. Every action that CHANGES the board on a knowable future day
# declares what it changes, how long before the change the remedy must be in hand, and the sign of
# the effect. Nothing here is a day offset for a specific decision: the lead day is DERIVED from
# `LAND_TARGET_DAY` and from whether the purchase is still on time.
#
#   (effect node, lead days, sign)   sign +1 = the action makes a "lower is better" node WORSE
TRANSFORMS = {
    "BUY_LAND": (("empty", 1, +1), ("quadrants", 0, +1)),
    "BUY_SEED": (("empty", 0, -1),),
}

# Reverse of NODES[node].ops: the ops that can actually CLOSE a deficient node. Used to project a
# remedy backwards from a scheduled change. `BUY_SEED` is not a NODES op for `planted` because it
# does not plant anything -- it is the PRECONDITION, which is the whole point of pre-positioning.
REMEDY = {
    "empty": ("BUY_SEED", "PLANT"),
    "planted": ("PLANT",),
    "animals": ("PLACE",),
}


def schedule(state, horizon=6):
    """Board changes the plan intends to make in the next `horizon` days -- DERIVED, no table.

    Today the only scheduled change is the land buy: `LAND_TARGET_DAY` supplies the target day
    and `budget`'s own affordability rule decides whether it is still on time, so a purchase we
    cannot fund drops off the schedule and the pre-positioning stops with it. Everything
    downstream (the seed lead) is a *consequence* of this, which is why the day the seed is
    bought is derived rather than hand-set.
    """
    from . import params as _p
    out = []
    unlocked = set(getattr(state, "unlocked", None) or [])
    for q in ("NE", "SW", "SE"):
        if q in unlocked:
            continue
        due = int(_p.LAND_TARGET_DAY.get(q, 99))
        off = due - int(state.day)
        if -2 <= off <= horizon:               # on time, or late and catching up
            out.append(("BUY_LAND", max(0, off), q))
        break                                   # one quadrant in flight at a time
    return out


def projected_empty(state):
    """`empty` as the board will be, not as it is: today's bare tiles PLUS every quadrant the
    schedule says is arriving.

    THIS is the "in-state graph that shows the path from here to the benchmark". A snapshot
    `empty` reads 0 the day before a $1,000 quadrant lands and 25 the day after, so any decision
    made from the snapshot is a day late by construction -- which is precisely the measured
    defect. Projecting the scheduled change into the node makes the seed claim appear while there
    is still time to act on it, and it is the reason the seed buy needs no day offset of its own.
    """
    live = read(state)
    gap = float(live.get("empty", 0.0))
    for op, _off, _arg in schedule(state):
        for node, _lead, sign in TRANSFORMS.get(op, ()):
            if node == "empty" and sign > 0:
                gap += 25.0                      # a quadrant is 5x5 of bare ground
    return gap


def seed_lead_days(state):
    """Days until the remedy for the next scheduled board change must be IN HAND -- DERIVED.

    Replaces the hand-set `SEED_LEAD_DAYS`. It is `schedule`'s offset minus the transform's own
    lead, so it moves on its own when the land day moves, and it returns None when nothing is
    scheduled (no land in flight means no lead obligation, whatever the day number says).
    """
    best = None
    for op, off, _arg in schedule(state):
        for node, lead, sign in TRANSFORMS.get(op, ()):
            if node == "empty" and sign > 0:
                left = max(0, off - lead)
                best = left if best is None else min(best, left)
    return best


def preposition(state):
    """op -> pressure for actions that must happen BEFORE a scheduled board change.

    For each scheduled `BUY_LAND` the land adds 25 `empty` tiles, and `empty` is a "lower is
    better" node, so the remedy for it (`BUY_SEED`) is pressured TODAY and the pressure decays
    with the distance to the event. On the day before the purchase, `left == 0` and the remedy is
    at full pressure; six days out it barely registers. That is the whole lead-time mechanism, and
    the lead day comes from `schedule`, not from a knob.
    """
    out = {}
    for op, off, _arg in schedule(state):
        for node, lead, sign in TRANSFORMS.get(op, ()):
            if sign <= 0:
                continue
            spec = NODES.get(node)
            if spec is None or spec.better != "lower":
                continue
            left = max(0, off - lead)           # days until the remedy must be IN HAND
            for remedy in REMEDY.get(node, ()):
                if remedy == op:
                    continue
                out[remedy] = max(out.get(remedy, 1.0), 1.0 + 1.0 / (1.0 + left))
    return out


def _empty_plantable(s):
    """Bare owned tiles OUTSIDE the reserved animal ring.

    ``empty`` is meant to be "land doing nothing" (a rent). A bare tile inside
    ``layout.holdback_tiles`` is RESERVED for future herd housing, not wasted -- it is
    exactly the tile ``scheduler`` refuses to sow by construction. Counting it here made
    ``empty`` break on d1 in the opening (7 reserved ring tiles) and mis-flag the whole
    opening as under-planted, when the crew had in fact sown every plantable tile.
    """
    from . import layout
    held = layout.holdback_tiles(s)
    return sum(1 for y, row in enumerate(s.tiles) for x, t in enumerate(row)
               if t is None and s.owned((x, y)) and (x, y) not in held)


_LIVE = {
    "weeds": lambda s: sum(1 for row in s.tiles for t in row
                           if isinstance(t, dict) and t.get("kind") == "WEED"),
    "planted": lambda s: sum(1 for row in s.tiles for t in row
                             if isinstance(t, dict) and t.get("kind") == "PLANT"),
    # NOT `not watered_today` -- see `_dying_today`. That reader counted every plant on the farm
    # at hour 0, so this node was maximally deficient every morning and broke on d1 in 16/17 games.
    "dry_plants": lambda s: _dying_today(s),
    "unfed": lambda s: sum(1 for row in s.tiles for t in row
                           if isinstance(t, dict) and "animal" in t
                           and t.get("consecutive_unfed", 0) >= 1),
    "animals": lambda s: s.herd_count(),
    "structures": lambda s: sum(1 for row in s.tiles for t in row
                                if isinstance(t, dict)
                                and t.get("kind") in ("COOP", "PASTURE")),
    "empty": _empty_plantable,
    "shed": lambda s: s.shed_total(),
    "money": lambda s: s.money,
    "quadrants": lambda s: len(s.unlocked),
    "melon_tiles": lambda s: sum(1 for row in s.tiles for t in row
                                 if isinstance(t, dict) and t.get("crop") == "MELON"),
    "output_per_day": lambda s: _output_per_day(s),
    "revenue_per_day": lambda s: _sellable_value(s),
    "labour": lambda s: float(s.unit_count()),
    # the deployment reader is registered even when the node is off, so the DAG never carries a
    # reader-less node (a node in NODES with no _LIVE entry is DEAD and silently never presses).
    "deploy": lambda s: float(s.money),
}


def _dying_today(state):
    """Watering still OUTSTANDING that still PAYS: plants in their water window, not watered
    today, and not yet harvestable.

    WHY THIS IS NOT `not watered_today` ALONE. Reading every unwatered plant was measured wrong: at
    hour 0 EVERY plant satisfies it, the node saturated against the pressure cap every morning, and
    the crew was pinned to watering while PLANT / HARVEST / FERTILIZE starved. The fix at the time
    was to count only plants past their window -- but that selects the EMPTY SET, and the node has
    therefore never fired. MEASURED over 36,051 plant-tile observations: only **11** are past their
    window and **all 11 are harvest-ready**, so the `plant_ready` guard below absorbs every one of
    them. `dry_plants` reported p == 1.000 on every one of 259,559 reference state-rows and 28,760
    of ours, while 43.6 % of plant-tiles were in fact dry.

    (It also read `t.get("age", 0)` -- a key the tile schema does NOT have, so even the empty set was
    reached via a defaulted 0. That is fixed to `crop_age`.)

    The honest risk set is the one the engine actually charges for: a plant **inside its water
    window** that has not been watered today loses yield tonight, and the work to prevent it is a
    WATER op. Plants younger than the window are safe (water adds nothing yet) and ripe plants want
    HARVEST, so both are excluded. Measured: 7,690 of 36,051 plant-tiles (~21 %), against 0 for the
    previous definition -- so the node can now carry information instead of being constant.
    """
    n = 0
    for row in state.tiles:
        for t in row:
            if not isinstance(t, dict) or t.get("kind") != "PLANT":
                continue
            if t.get("watered_today"):
                continue
            try:
                if state.plant_ready(t):
                    continue                       # harvest is the right op, not water
                win = state.water_window(t)
            except Exception:                      # noqa: BLE001
                continue
            if win is None:
                continue                           # ongoing crop: water adds yield, does not save
            age = int(state.crop_age(t))           # NOT t.get("age") -- the tile has no `age`
            if params.at("FIX_DEAD_NODES", state.day):
                if int(win[0]) <= age <= int(win[1]):
                    n += 1
            elif age >= int(win[1]):               # the OLD definition: selects the empty set
                n += 1
    return n


def _sellable_value(state):
    """Revenue the farm could bank TODAY from what it already holds, at the LIVE book.

    The live reader `revenue_per_day` never had. Stateless by construction: the shed and the
    standing crop are both in the observation and the price comes from the live book, so nothing
    is carried across turns. A deficit against his daily output value means we are failing to
    convert production into sellable goods, which is what should pressure SELL and HARVEST.
    """
    from . import crew
    try:
        pr = crew.prices(state)
    except Exception:                              # noqa: BLE001
        return 0.0
    v = 0.0
    for item, qty in (getattr(state, "shed", None) or {}).items():
        if item in pr:
            v += float(qty) * float(pr[item])
    for row in state.tiles:
        for t in row:
            if not isinstance(t, dict) or t.get("kind") != "PLANT":
                continue
            try:
                if state.plant_ready(t):
                    v += float(t.get("yield_units", 0)) * float(pr.get(t.get("crop"), 0.0))
            except Exception:                      # noqa: BLE001
                pass
    return v


def _output_per_day(state):
    """Dollars the standing farm can pay out per day, from the engine's own rates.

    THE MIDDLE LINK of the revenue chain, and it is COMPUTED rather than measured: every
    standing tile earns `recipes.units_per_tile_day(crop) x price`, the herd earns
    `1/interval x price` per animal, and feeding costs one wheat per animal per day. This is the
    capacity number the bank is a lagging function of.
    """
    from . import crew, recipes, value
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
          "structures": ("animals", 0.20),
          # `deploy` compares our cash to the reference's trail, which is ~$27 at d8 -- so a
          # ratio deviation saturates instantly and the acquisition ops jump the whole market
          # queue. MEASURED: without a width, DEPLOY_NODE=1 lost median -$15,500 (0/4). The
          # width grades it against roughly ONE DAY OF INCOME (~$2.5k), so a $2.3k excess reads
          # as a real but not maximal deficiency. `(None, frac)` means width = frac * 100.
          "deploy": (None, 25.0)}


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
    if spec.metric == "melon_tiles" and not params.at("FIX_DEAD_NODES", day):
        return 0.0                                 # the OLD target: p == 1.0 forever
    if spec.metric == "total_animals":
        return _priors.total_animals(day)
    if spec.metric == "n_quadrants":
        return float(_priors.land_target(day))
    if spec.metric == "sellable_value":
        # our sellable stock vs HIS daily production value: the conversion gap, in dollars
        return target_of("output_per_day", day)
    if spec.metric == "cash_hold":
        # the reference's own cash trail: EXCESS above it is the deployment deficiency.
        return float(_priors.CASH.get(int(day), 0.0))
    if spec.metric == "units":
        # `hands_end` is his crew SIZE directly, so the node compares like with like.
        # (The earlier unit_turns/24 was the same idea with a rounding step in the middle.)
        try:
            t = _bench.target("hands_end", day)
            if t:
                return float(t)
        except Exception:                              # noqa: BLE001
            pass
        return float(priors.hire_target(day))
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
    _deploy_on = bool(params.at("DEPLOY_NODE", day))
    for node, ours in live.items():
        if not active(node, state):
            continue
        if node == "deploy" and not _deploy_on:
            continue          # gated so the node A/Bs without editing code
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
    """op class -> pressure, from the deficient ROOTS, with the time dimension applied.

    Merged with `preposition`, so an op can be pressured either because the state is deficient
    NOW (reactive, ramped by the hour) or because a scheduled board change will make it deficient
    in `lead` days (anticipatory). The two are the same currency -- a pressure on an op class --
    which is what lets the seed buy be decided by the graph instead of by a day offset.
    """
    out = {}
    _lw = None
    if params.at("GRAPH_WEIGHTS", state.day):
        try:
            from . import graph_weights as _gw
            _lw = _gw.W
        except Exception:                                      # noqa: BLE001
            _lw = None
    # WHICH NODES MAY PRESS. Without learned weights: only ROOTS (a symptom must not press its own
    # cause). WITH them: every live node, because the FIT learned its edges against `deviation`
    # (all nodes) and the strongest learned edges land on SYMPTOMS -- `output_per_day` and
    # `revenue_per_day` are not roots, so iterating `roots()` applied none of the learned weights
    # and the normalised set measured byte-identical. The licensing boundary (`NODES[node].ops`)
    # still prevents an unrelated op firing.
    _src = deviation(state) if _lw is not None else roots(state)
    for row in _src:
        node, _o, _t, p, u = row[0], row[1], row[2], row[3], row[4]
        gain = (p - 1.0) * u
        for op in NODES[node].ops:
            # LEARNED EDGE STRENGTH: the fitted weight says whether this node->op edge carries
            # signal at all, and how much. `NODES[node].ops` stays the LICENSING boundary, so a
            # learned weight can never make an unrelated op fire.
            g = gain * float(_lw.get(op, {}).get(node, 0.0)) if _lw is not None else gain
            if g <= 0.0:
                continue
            out[op] = max(out.get(op, 1.0), min(cap, 1.0 + g))
    for op, p in preposition(state).items():
        out[op] = max(out.get(op, 1.0), min(cap, p))
    return out


def deploy_pressure(state):
    """Capital-deployment pressure: > 1 when we hold cash the reference already turned into
    capacity (see NODES["deploy"]). THE ONE NUMBER every acquisition veto consults.

    The graph could already COMPUTE this and nothing acted on it: the pressure reached
    `apply_to_market` (which only orders the market list), while the real vetoes sat downstream
    in the layers' own gates. MEASURED: ungraded it destroyed -$15,500 (0/4) by jumping the whole
    queue; graded it was byte-identical (+$0) because the gates still said no. Pressure and
    permission have to move together, so they read the same function.
    """
    if not params.at("DEPLOY_NODE", state.day):
        return 1.0
    try:
        # `deviation` yields 5-tuples (node, ours, tgt, pressure, urgency); `roots` yields 6. An
        # earlier 6-field unpack here raised on every call and the bare `except` returned 1.0, so
        # BOTH pressure-aware gates were dead and the graded node read byte-identical (+$0).
        for node, _o, _t, p, _u in deviation(state):
            if node == "deploy":
                # CLAMP AT 1.0: this is a "lower is better" node, so holding LESS than the
                # reference (d12: priors $14.5k, ours $5.5k) is not a deficiency. Unclamped the
                # raw ratio goes negative (-3.44 measured), which is meaningless as a pressure.
                return max(1.0, float(p))
    except Exception:                                          # noqa: BLE001
        pass
    return 1.0


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
    cap = float(params.at("GRAPH_STEER_CAP", state.day) or 1.0)
    return [j._replace(priority=j.priority * min(cap, mul.get(j.op, 1.0))) for j in jobs]


def report(state):
    lines = []
    for node, ours, tgt, p, u in deficient(state):
        eff = 1.0 + (p - 1.0) * u
        op = ",".join(NODES[node].ops) or "-"
        lines.append(f"      {node:<12} ours {ours:>8.1f}  his {tgt:>9.1f}  "
                     f"dev {p:>4.2f}  urg {u:>4.2f}  eff {eff:>4.2f}  -> {op}")
    return lines


# ============================================================================ THE MARKET CHOKE POINT
# Order-emitting layers: budget (land+hires), crop_plan (seed), herd_plan (animals+feed),
# sell_policy (sells), trade, endgame. MEASURED (tools/graph/graph_diag.py --section plug):
# only 4 of 27 modules imported this graph at all, and NONE of those market surfaces did -- the
# graph could steer the crew's job priority and nothing else. Rewriting seven layers to consult
# the graph would be seven chances to drift apart again, so instead every market list passes
# through ONE adapter on its way out. That is the difference between the graph being a report
# and being the decision engine.
_INFLOW = ("SELL",)


def apply_to_market(market, state):
    """Order the market list by the graph's pressures -- one choke point, every layer.

    Sells stay FIRST and are never reordered: they are the only cash inflow and an unfunded order
    is a silent no-op, so demoting them would zero the turn. Everything after that is ordered by
    the pressure the graph puts on its op class, stable within equal pressure so a layer's own
    intent survives.

    This is what makes "seed before land" a CONSEQUENCE rather than a rule. `emit` truncates at
    `MAX_ORDERS=10` and drops the tail silently, so the order of this list IS the funding priority.
    A $10 seed the graph demands outranks a $1,000 quadrant it does not, and no layer has to know
    that.
    """
    if not market:
        return market
    try:
        pr = pressures(state)
    except Exception:                                          # noqa: BLE001
        return market
    if not pr:
        return market

    def key(pair):
        i, o = pair
        if not isinstance(o, list) or not o:
            return (3, 0.0, i)
        op = str(o[0])
        if op in _INFLOW:
            return (0, 0.0, i)
        # higher pressure first; stable within a pressure by original position
        return (1, -float(pr.get(op, 1.0)), i)

    return [o for _i, o in sorted(enumerate(market), key=key)]


# ============================================================================ WORK ORDERS
# THE CREW ACTUATOR. `deficit_jobs` below is DIG-only; this is the general form, driven by the
# weights LEARNED from the reference's replays (`tools/phases/fit_graph.py` -> `graph_weights.W`).
_WO_OPS = ("WATER", "FERTILIZE", "HARVEST", "FEED", "COLLECT_FERTILIZER", "DIG")


def _wo_positions(state, op):
    """Positions where `op` CAN be performed -- the object already exists.

    This is the rule `deficit_jobs` measured the hard way: fabricating BUILD jobs for animals never
    bought cost 58,209 -> 27,622. An actuator may only act on something that is really there.
    """
    out = []
    for y, row in enumerate(state.tiles):
        for x, t in enumerate(row):
            if not isinstance(t, dict):
                continue
            if op == "WATER":
                if t.get("kind") == "PLANT" and state.needs_water(t):
                    out.append((x, y))
            elif op == "FERTILIZE":
                if t.get("kind") == "PLANT" and state.in_water_window(t):
                    out.append((x, y))
            elif op == "HARVEST":
                if state.plant_ready(t):
                    out.append((x, y))
            elif op == "DIG":
                if t.get("kind") == "WEED":
                    out.append((x, y))
            elif "animal" in t:
                if op == "FEED" and not t.get("fed_today"):
                    out.append((x, y))
                elif op == "COLLECT_FERTILIZER" and t.get("fertilizer_available"):
                    out.append((x, y))
    return out


def _wo_band(op):
    from .job import (P_COLLECT_FERT, P_DIG, P_FEED, P_FERTILIZE, P_HARVEST, P_WATER_BONUS)
    return {"WATER": P_WATER_BONUS, "FERTILIZE": P_FERTILIZE, "HARVEST": P_HARVEST,
            "FEED": P_FEED, "COLLECT_FERTILIZER": P_COLLECT_FERT, "DIG": P_DIG}[op]


def _op_weights(op, day):
    """`node -> weight` for one op at one day, tolerating BOTH codegen shapes.

    `fit_graph --windows` emits `W[op][window][node]`; a global fit emits `W[op][node]`. The
    windowed table is the one that measured better (median R2 +0.486 vs +0.224), so the day picks
    the window; the flat shape is kept working so an old table degrades to "one window" instead of
    to silence -- a wrong weight is visible, an empty `W` is not.
    """
    try:
        from . import graph_weights as _gw
    except Exception:                                          # noqa: BLE001
        return {}
    ws = _gw.W.get(op) or {}
    if not ws:
        return {}
    if hasattr(_gw, "weights_for"):
        try:
            return _gw.weights_for(op, day) or {}
        except Exception:                                      # noqa: BLE001
            return {}
    return ws


def turn_budget(state):
    """op -> how many CREW TURNS of that op class the graph licenses THIS TURN.

    The learned weights give a gain per op from the live deviations:

        gain(op) = sum_node W[win(day)][op][node] * max(0, pressure_node - 1) * urgency

    and the gains are scaled to the CREW, so the budget is a **share**, never an absolute ceiling:

        cap[op] = ceil(n_units * gain[op] / sum_op gain)

    WHY A SHARE AND NOT A CEILING. An absolute cap can only *remove* jobs, and the layers already
    emit one job per precondition object, so a cap strictly below demand manufactures idle turns --
    measured `TURN_BUDGET` + absolute caps: **-$32,378 with 40.4% idle**. Because the shares are
    scaled to the crew size, `sum_op cap[op] >= n_units`, so every crew turn still has a licensed
    job whenever a layer issued one; an op is trimmed only when it is *over-represented against the
    graph's own demand*, and the turns it gives up go to the ops that are under-served. That is an
    allocation, not a clip -- and it leaves `job.py`'s survival bands deciding WHO takes what.

    Ops with no learned weight, and every op when no gain is positive, are UNCAPPED: the graph
    bounds only what it has an opinion about.
    """
    try:
        dev = list(deviation(state))
        n_units = max(1, int(state.unit_count()))
    except Exception:                                          # noqa: BLE001
        return {}
    try:
        from . import graph_weights as _gw
    except Exception:                                          # noqa: BLE001
        return {}
    gains = {}
    for op in _gw.W:
        ws = _op_weights(op, state.day)
        if not ws:
            continue
        gain = 0.0
        for node, _o, _t, p, u in dev:
            w = float(ws.get(node, 0.0))
            if w > 0.0:
                gain += w * max(0.0, p - 1.0) * u
        if gain > 0.0:
            gains[op] = gain
    total = math.fsum(gains.values())
    if total <= 0.0:
        return {}
    return {op: max(1, int(math.ceil(n_units * g / total))) for op, g in gains.items()}


def allocate(jobs, state):
    """The graph's crew allocation: trim `jobs` to its per-op shares, but NEVER starve the crew.

    `turn_budget`'s shares say which op classes are *over-represented* against the graph's own
    demand. Applied as a bare clip they are a disaster -- the layers emit one job per precondition
    object, so a clip below demand manufactures idle turns (measured: absolute caps gave
    **-$32,378 with 40.4% idle**). So the clip is followed by a RESTORE:

        target = min(n_units, len(jobs))
        after the clip, if fewer than `target` jobs survive, the dropped jobs come back,
        ops furthest below their share first, and then in their original layer order.

    Two properties fall out, and they are the whole point:

    * **The crew is never idled by the graph.** `len(out) >= min(n_units, len(jobs))` always, so
      every unit that has any job at all still has one. The graph cannot create idle time.
    * **The graph re-allocates the SURPLUS, not the deficit.** Where an op class is over-subscribed
      relative to its learned share, its excess turns go to whatever the layers emitted for the
      other ops -- which is exactly the allocation decision that was missing, and it needs no
      fabricated jobs and no re-ranking of `job.py`'s survival bands.

    Ops with no learned weight are uncapped; when no gain is positive `turn_budget` is empty and
    this is the identity, so the graph is silent rather than wrong.
    """
    caps = turn_budget(state)
    if not caps or not jobs:
        return jobs
    try:
        n_units = max(1, int(state.unit_count()))
    except Exception:                                          # noqa: BLE001
        return jobs
    target = min(n_units, len(jobs))
    kept, dropped = [], []
    seen = collections.Counter()
    for i, j in enumerate(jobs):
        op = str(getattr(j, "op", ""))
        c = caps.get(op)
        if c is not None and seen[op] >= c:
            dropped.append((i, j, op))
            continue
        seen[op] += 1
        kept.append((i, j))
    if len(kept) < target:
        # furthest below share first, then the layers' own order -- never an invented job
        for i, j, op in sorted(dropped, key=lambda t: (seen[t[2]] - caps.get(t[2], 0), t[0])):
            if len(kept) >= target:
                break
            kept.append((i, j))
            seen[op] += 1
    kept.sort(key=lambda t: t[0])
    return [j for _i, j in kept]


def work_orders(state, jobs):
    """The graph's work orders: WHICH ops and HOW MANY, from the learned weights.

    quantity(op) = WO_SCALE * sum_node W[op][node] * (pressure_node - 1) * urgency
    shortfall    = quantity - what the layers already issued today
    and the shortfall is emitted on real precondition objects, within a crew-turn budget.
    """
    try:
        from . import graph_weights as _gw
        from .job import Job
    except Exception:                                          # noqa: BLE001
        return []
    have = collections.Counter(str(getattr(j, "op", "")) for j in jobs)
    try:
        dev = list(deviation(state))
    except Exception:                                          # noqa: BLE001
        return []
    try:
        turns = state.unit_count() * max(0, 24 - int(state.hour))
    except Exception:                                          # noqa: BLE001
        turns = 0
    budget = int(turns * float(params.at("WORK_ORDER_TURN_FRAC", state.day) or 0.0))
    scale = float(params.at("WO_SCALE", state.day) or 0.0)
    out = []
    for op in _WO_OPS:
        if budget <= 0:
            break
        pos = _wo_positions(state, op)
        if not pos:
            continue
        ws = _op_weights(op, state.day)
        gain = 0.0
        for node, _o, _t, p, u in dev:
            w = float(ws.get(node, 0.0))
            if w > 0.0:
                gain += w * max(0.0, p - 1.0) * u
        if gain <= 0.0:
            continue
        need = int(round(gain * scale)) - int(have.get(op, 0))
        if need <= 0:
            continue
        take = min(need, len(pos), budget)
        for pos_ in pos[:take]:
            out.append(Job(_wo_band(op), pos_, op, None))
        budget -= take
    return out


def deficit_jobs(state, jobs):
    """CLOSE THE LOOP -- the graph issues a work order for a demand whose PRECONDITION EXISTS.

    MEASURED by `tools/graph/graph_diag.py --section demand`: `DIG` carried the single highest
    pressure in the whole graph (band 4.00 at d12) and the crew dug **1.0 tile a day**. The job
    existed but only under a condition that is itself the consequence of the demand --
    `crop_plan` emits DIG only for a tile that is ALREADY a weed, so nothing ever starts the
    chain. This is that actuator: a pressure IS a work order, and if no layer issued one, the
    graph issues it.

    ONLY WHERE THE OBJECT ALREADY EXISTS -- and the first version of this function is the
    evidence for why. It also fabricated BUILD_COOP/BUILD_PASTURE jobs whenever the
    `structures` node was deficient, and the arm went **$58,209 -> $27,622** with revenue
    $98k -> $71k. Diagnosis: `structures` is a SYMPTOM of `animals` in this graph's own edges,
    so building housing does not fix it -- it consumes the crop tiles the farm needs and houses
    animals that were never bought. `herd_plan` already carries the correct guard ("build only
    to house animals we ALREADY own") and its comment records the same failure measured before
    ("16 structures for 3 animals ... left the farm with 8 planted tiles instead of 25"). An
    actuator may only fire on a ROOT, and only when the thing it acts ON already exists:

      * DIG  -- a WEED tile exists, and it is the defect. Act.
      * BUILD -- the animal does not exist. Fabricating the housing first is what broke the arm;
        the correct order is BUY_ANIMAL (a market op the choke point already pressures) and then
        `herd_plan` builds to house it.

    Deliberately minimal: ONE job. The pressure multiplier in `apply_to_jobs` then decides
    whether it outranks the rest of the board.
    """
    try:
        pr = pressures(state)
    except Exception:                                          # noqa: BLE001
        return []
    if pr.get("DIG", 1.0) <= 1.0:
        return []
    if any(str(getattr(j, "op", "")) == "DIG" for j in jobs):
        return []                                              # a layer already issued one
    from .job import Job, P_DIG
    for y, row in enumerate(state.tiles):
        for x, t in enumerate(row):
            if isinstance(t, dict) and t.get("kind") == "WEED":
                return [Job(P_DIG, (x, y), "DIG", None)]
    return []


# ============================================================================ THE VALUE KERNEL
# MEASURED: multiplying `job.py`'s hand-tuned constants by graph pressures is harmful at EVERY
# cap -- 1.0 (off) $58,899 / 1.1 $50,716 / 1.25 $47,228 / 1.5 $37,175 on PA=1. The constants ARE
# a ranking, so layering a second, incomparable ranking on top destroys both: every node we are
# structurally behind on (`empty`, `planted`, `animals`) is deficient EVERY day, so its ops sit
# permanently boosted while a SATISFIED survival node (`dry_plants`) rides at 1.0x, and the crew
# plants and digs while the crops go dry.
#
# The fix is not a better cap. It is ONE CURRENCY. `crew.score` already computes dollars per
# unit-turn for every job and its own docstring calls it "the whole basis of the ranking" -- so
# the priority BECOMES that number, and the graph supplies only what a dollar figure cannot see:
# the URGENCY of the deadline behind the op. A plant that dies tonight forfeits its entire option
# value, and a weed blocks a tile for the rest of the season; neither fact is in the dollar value.
def _op_urgency(state):
    """op -> the urgency of the node that licenses it (max over licensing nodes).

    This is the graph's real contribution to the crew: `urgency` ramps a `tonight` node from
    1.0 at hour 0 to 2.5 at hour 23 and a `season` node toward the bell, so an op whose deadline
    is closing outranks a slightly richer one whose is not. See `urgency`.
    """
    out = {}
    for node, spec in NODES.items():
        if node not in _LIVE:
            continue
        try:
            u = urgency(node, state)
        except Exception:                                      # noqa: BLE001
            continue
        for op in spec.ops:
            out[op] = max(out.get(op, 1.0), u)
    return out


def value_kernel(jobs, state):
    """Replace the priority kernel: rank the crew by DOLLARS, time-ramped by the graph.

    `priority = 100 * job_value / best_job_value * urgency(op)`

    One currency, one ranking. `crew.job_value` already knows what every op is worth in dollars
    (and accepts the graph's own `steer_mul`), and the graph contributes the deadline ramp that
    the dollar value omits. Nothing here is a hand-set constant, so there is no second scale to
    disagree with the first.
    """
    if not jobs:
        return jobs
    from . import crew
    try:
        pr = crew.prices(state)
    except Exception:                                          # noqa: BLE001
        return jobs
    try:
        steer = pressures(state)
    except Exception:                                          # noqa: BLE001
        steer = {}
    urg = _op_urgency(state)
    vals = {}
    for i, j in enumerate(jobs):
        try:
            v = float(crew.job_value(state, j, pr, steer_mul=steer))
        except Exception:                                      # noqa: BLE001
            v = 0.0
        vals[i] = v * float(urg.get(str(j.op), 1.0))
    best = max(vals.values()) if vals else 0.0
    if best <= 0:
        return jobs
    return [j._replace(priority=100.0 * vals[i] / best) for i, j in enumerate(jobs)]
