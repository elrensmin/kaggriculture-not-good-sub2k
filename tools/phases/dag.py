"""The phase model: metrics, the #1's per-day reference, and the causal DAG.

Everything here is DATA. Edit this file, not the engine, to change what a phase is
measured on or how the graph connects.

Three pieces:

  * ``PHASES``    — the day range of each phase and the step count to truncate at.
  * ``DSM_DAILY`` — the #1's measured per-day structural state (median per game).
                    Source: docs/dsm_v1.md §3 (hands/quad/shed/animals/structs/
                    weeds/feed/care/water/fert, all 30 days) and the ds m_profile
                    DSM block for crop tiles. Every metric's TARGET is this table
                    aggregated over the phase's days by the metric's own ``agg``,
                    so ours and his are reduced the same way.
  * ``METRICS``   — the nodes: one structural measurement each, with where it comes
                    from, which way is better, the tolerance that makes it OK, and
                    the code site that owns it.
  * ``EDGES``     — the causal arrows: ``(upstream, downstream, mechanism)``. The
                    mechanism text is what you read when the tool says "this is a
                    root": it names the dependency you would have to break.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Phases — the day ranges the report uses, and the step to truncate the game at.
# The agent is stateless and never looks at the horizon, so a game stopped at day
# N has the same d0..N behaviour as a full game; truncating is a cheap way to read
# the structural state at the boundary.
# ---------------------------------------------------------------------------
PHASES = {
    "phase1": {"name": "opening",  "days": (0, 5),  "steps": 144,
               "question": "did we commit the land, the crew and the first production?"},
    "phase2": {"name": "midgame",  "days": (6, 17), "steps": 432,
               "question": "is the farm big, watered, fed and harvested?"},
    "phase3": {"name": "endgame",  "days": (18, 29), "steps": 720,
               "question": "did we convert the farm into sold goods and release the herd?"},
}

# ---------------------------------------------------------------------------
# The #1's per-day reference (median per game). Keys match METRICS' ``target_key``.
#   day: hands quad shed_max cow sheep goose structs wheat straw carrot tomato melon
#        weeds feed care water fert
# ---------------------------------------------------------------------------
_DSM_ROWS = [
    # hands quad shed cow sheep goose str  wheat straw carr toma melon weed feed care water fert
    (4, 1,  8, 2, 3, 0, 10,  9,  0,  0,  0,  6,  0,  4,  4, 15,  0),
    (4, 1,  4, 2, 3, 0, 10, 10,  0,  0,  0, 10,  0,  5,  6,  5,  0),
    (6, 1,  5, 2, 3, 0, 10,  4,  4,  0,  0, 10,  0,  3,  7, 18,  0),
    (6, 1, 12, 2, 3, 0, 10,  0, 10,  0,  0, 10,  0,  5,  7, 14,  0),
    (5, 1, 13, 2, 3, 0, 10,  0, 10,  0,  0, 10,  0,  5,  5, 11,  0),
    (6, 1,  8, 2, 3, 0, 10,  0, 10,  0,  0, 10,  0,  5,  6, 11,  0),
    (8, 2, 10, 6, 3, 2, 24,  7, 15,  0,  0, 10,  0,  6,  7, 23,  0),
    (9, 2,  6, 8, 3, 2, 26, 11, 16,  0,  0, 10,  0, 13, 13, 23,  0),
    (9, 2, 16, 8, 3, 2, 26, 10, 16,  0,  0, 10,  0, 10, 11, 37,  0),
    (10, 3, 25, 9, 3, 4, 32, 21, 19,  0,  2, 10,  0, 13, 13, 42,  1),
    (12, 4, 47, 9, 3, 6, 34, 29, 22,  0,  2,  4,  0, 19, 19, 46,  3),
    (11, 4, 74, 9, 3, 7, 35, 32, 25,  0,  4,  0,  0, 18, 18, 52, 11),
    (11, 4, 64, 9, 3, 7, 37, 29, 26,  0,  5,  0,  0, 19, 19, 59,  9),
    (11, 4, 81, 9, 3, 7, 37, 27, 28,  0,  7,  0,  0, 21, 21, 62,  8),
    (12, 4, 88, 9, 3, 7, 37, 26, 28,  0,  8,  0,  0, 21, 21, 55, 10),
    (12, 4, 93, 9, 3, 7, 39, 23, 30,  0, 10,  0,  0, 19, 19, 60, 13),
    (12, 4, 93, 9, 3, 7, 37, 21, 30,  0, 11,  0,  0, 20, 19, 56, 10),
    (12, 4, 89, 9, 3, 7, 37, 20, 30,  2, 12,  0,  0, 20, 20, 62, 10),
    (12, 4, 89, 9, 4, 7, 37, 21, 27,  3, 15,  0,  0, 15, 14, 54, 12),
    (12, 4, 86, 9, 4, 7, 37, 24, 21,  4, 16,  0,  0, 19, 18, 58, 13),
    (12, 4, 88, 8, 4, 7, 37, 26, 20,  6, 15,  0,  1, 15, 15, 58, 14),
    (12, 4, 92, 8, 4, 7, 37, 27, 20,  7, 14,  0,  1, 16, 15, 62, 17),
    (12, 4, 90, 7, 4, 7, 35, 30, 17,  8, 13,  0,  1, 13, 13, 58, 14),
    (12, 4, 92, 7, 4, 6, 34, 32, 15, 10, 11,  0,  2, 17, 16, 60, 15),
    (12, 4, 93, 7, 4, 6, 32, 33, 15, 14,  8,  0,  2, 12, 11, 63, 17),
    (12, 4, 93, 7, 4, 6, 30, 32, 13, 18,  7,  0,  2, 14, 14, 61, 15),
    (11, 4, 94, 7, 3, 6, 28, 29, 12, 23,  6,  0,  2, 11, 11, 63, 15),
    (11, 4, 93, 7, 3, 6, 28, 28,  9, 21,  5,  0,  3, 11, 11, 58, 15),
    (11, 4, 93, 6, 3, 6, 28, 15,  8, 10,  5,  0,  6,  3,  2, 48, 14),
    (10, 4, 85, 6, 0, 5, 28,  2,  4,  0,  4,  0, 10,  1,  1, 24,  1),
]
_DSM_KEYS = ("hands", "quad", "shed_max", "cow", "sheep", "goose", "structs",
             "wheat", "straw", "carrot", "tomato", "melon", "weeds",
             "feed", "care", "water", "fert")
DSM_DAILY = {d: dict(zip(_DSM_KEYS, row)) for d, row in enumerate(_DSM_ROWS)}
# idle% per day is only measured on sampled days (dsm_profile's "structural per
# day" table); the rest stay absent so the aggregation just skips them.
# d0/d2/d4/d6/d8 from day_gap's per-day idle% table; the rest from dsm_profile.
_DSM_IDLE = {0: 8.0, 2: 24.0, 4: 41.0, 6: 1.0, 8: 3.0,
             9: 0.4, 12: 0.0, 15: 0.0, 18: 0.0, 21: 0.0, 24: 0.0, 27: 0.0}
for _d, _v in _DSM_IDLE.items():
    DSM_DAILY[_d]["idle_pct"] = _v
# CORRECTION: dsm_v1.md's "structs" column reads 10 for d0-d5, but his replays show
# 5 pastures at d5 — all five occupied — with 20 plants, i.e. 25 tiles exactly full.
# Verified directly on replays/DSM/v1 (3 replays, identical) and reconfirmed at n=12
# by `phase_map --replay-dir replays/DSM/v1`. He builds housing TO ORDER, so the
# structure count tracks the herd. Trust `--ref-from replays/DSM/v1` over this table
# wherever they disagree; the table is the fast fallback.
for _d, _row in DSM_DAILY.items():
    _row["structs"] = _row["cow"] + _row["sheep"] + _row["goose"]
# standing crops = the five crop columns
for _d, _row in DSM_DAILY.items():
    _row["crops"] = sum(_row[k] for k in ("wheat", "straw", "carrot", "tomato", "melon"))
    _row["water_per_tile"] = (_row["water"] / _row["crops"]) if _row["crops"] else 0.0
# NOTE (historical, kept as prose only): the #1's day-5 state is IDENTICAL in 40/40 of
# his replays -- 2 COW + 3 SHEEP, 10 MELON + 10 STRAWBERRY planted, 25 owned tiles, 1
# quadrant, cash $746-883 -- so his opening is an unconditional SCRIPT (the wool response
# is a midgame re-specialisation; see docs/dsm_v1.md). A `open_dist` DAG metric used to
# measure the L1 distance from that vector; it was DELETED because Boey's optimal opening
# (10 MELON + 4 STRAWBERRY + ~8 animals) is non-zero against it by construction, so
# scoring it penalises the stronger arm. The opening is now judged on the tile budget
# (`empty_tiles` / `planted tiles`) and `idle_pct`. Do not re-add it as a target.

DSM_DAILY_SOURCE = ("docs/dsm_v1.md §3 (all 30 days; median per game) + "
                    "dsm_profile's per-day idle%/crop tiles")

# ---------------------------------------------------------------------------
# The metric registry — the DAG's nodes.
#   src    "stock:<key>"  standing state at the END of the day, or
#          "flow:<op>"    per-day count of that unit op, or
#          "derived:<key>" a computed per-day value
#   agg    how the phase's per-day series collapses to one number
#   target_key  which DSM_DAILY column to reduce the same way
#   better "higher" | "lower" | "range"
#   tol    how far off target still counts as OK. Convention: a value >= 1 is an
#          ABSOLUTE allowance (counts); a value < 1 is a FRACTION of the target.
# ---------------------------------------------------------------------------
def M(label, phase, src, agg, target_key, better, tol, owner, desc, descriptive=False):
    """One DAG node.

    ``descriptive=True`` means REPORT the number but never judge it. It exists for
    metrics that are diagnostic readouts of a mechanism rather than objectives --
    gross sell revenue is the case in point: it rewards churn (Boey's is 4x ours while
    his NET is within a few hundred dollars), so it must be visible beside `trade_net`
    without ever being a target.
    """
    return dict(label=label, phase=phase, src=src, agg=agg, target_key=target_key,
                better=better, tol=tol, owner=owner, desc=desc,
                descriptive=descriptive)


METRICS = {
    # ---- phase 1: opening ---------------------------------------------------
    "cash_commit": M("opening cash committed", 1, "derived:cash_commit", "last", "none",
                     "higher", 0.15, "src/herd_plan.py::market_intents + src/crop_plan.py::market_intents",
                     "Fraction of the $3,000 opening bank spent by end of day 0. The #1 ends d0 at $6."),
    "quadrants": M("quadrants unlocked", 1, "stock:quadrants", "max", "quad",
                   "higher", 0.5, "src/budget.py::market_intents",
                   "Land is the ceiling on every crop ramp and on the herd."),
    "owned_tiles": M("owned tiles", 1, "stock:owned", "last", "owned",
                     "higher", 10, "src/budget.py::market_intents",
                     "Owned ground: the binding constraint on the whole opening."),
    "hands": M("hands", 1, "stock:hands", "last", "hands",
               "range", 0.25, "src/budget.py::market_intents (target_hands, TILES_PER_HAND)",
               "Hands are hired to ground: target = min(schedule, owned//TILES_PER_HAND)."),
    "animals": M("animals on board", 1, "stock:animals", "max", "animals",
                 "higher", 1.0, "src/herd_plan.py::market_intents",
                 "Daily feed/care/collect work is what fills the odd opening days."),
    # The herd COMBINATION, extracted from Boey's replays (medians, 40 games): 3 COW +
    # 2 SHEEP on d0 with no GOOSE (coops come with the d2 goose), reaching 4 COW + 3 SHEEP
    # + 2 GOOSE by d4. A total alone cannot tell a correct herd from a GOOSE-heavy one.
    "cows": M("COW on board", 1, "stock:animal_COW", "max", "cow",
              "higher", 2, "src/opening.py::_herd_target",
              "The d0 commitment: 3 COW at $400, bought before the crop payment."),
    "sheep": M("SHEEP on board", 1, "stock:animal_SHEEP", "max", "sheep",
               "higher", 2, "src/opening.py::_herd_target",
               "2 SHEEP on d0 at $500; wool from d6."),
    "geese": M("GOOSE on board", 1, "stock:animal_GOOSE", "max", "goose",
               "higher", 1, "src/opening.py::_herd_target",
               "Coops arrive on d2; eggs are the earliest daily revenue (d4)."),
    "structures": M("animal structures", 1, "stock:structures", "max", "structs",
                    "higher", 4, "src/herd_plan.py::jobs",
                    "Built only to house animals we already own."),
    "melon_tiles": M("MELON tiles", 1, "stock:plant_MELON", "max", "melon",
                     "higher", 3, "src/params.py::CROP_PLAN",
                     "The d0-d2 crop and the d10-11 cash engine."),
    "straw_tiles": M("STRAWBERRY tiles", 1, "stock:plant_STRAWBERRY", "last", "straw",
                     "higher", 4, "src/params.py::CROP_PLAN",
                     "Highest value per tile; the d12-17 earner."),
    "feed_ops": M("FEED ops", 1, "flow:FEED", "sum", "feed",
                  "higher", 6, "src/herd_plan.py::jobs",
                  "One per animal per day; the daily work that a crop-only farm lacks."),
    "care_ops": M("CARE ops", 1, "flow:CARE", "sum", "care",
                  "higher", 6, "src/herd_plan.py::jobs",
                  "Free, daily, and it banks the production bonus."),
    "water_ops": M("WATER ops", 1, "flow:WATER", "sum", "water",
                   "higher", 15, "src/crop_plan.py::jobs",
                   "Watering is gated by the crop water windows (wheat 2-4, melon 6-12)."),
    "plant_ops": M("PLANT ops", 1, "flow:PLANT", "sum", "none",
                   "higher", 8, "src/crop_plan.py::plant_queue + src/scheduler.py::_plant_jobs",
                   "Seeding rate; throttled by the CROP_PLAN ramp."),
    "idle_pct": M("idle share %", 1, "derived:idle_pct", "median", "idle_pct",
                  "lower", 10, "src/scheduler.py::plan",
                  "Unit-turns that PASS. Structural: a crop-only farm has no odd-day work."),
    "empty_tiles": M("empty owned tiles", 1, "stock:empty", "median", "none",
                     "lower", 8, "src/crop_plan.py::plant_queue",
                     "Land doing nothing. High early = the ramp is throttling the tiles."),
    # Revenue is gross CHURN and must be read beside its net: Boey's d0-d5 gross sales are
    # 4x ours while his product-trade NET is within a few hundred dollars of ours, because
    # he recycles the same float ~4x. `TRADE_NET` is the exact ledger quantity
    # (d_money + fixed spend = sells - product buys), so that is the node to optimise.
    "revenue": M("sell revenue", 1, "flow:REVENUE", "sum", "none",
                 "higher", 0.25, "src/market.py (quote) + src/sell_policy.py",
                 "GROSS opening sales. DESCRIPTIVE: it measures turnover, not profit -- "
                 "read it beside trade_net, never as a target.", descriptive=True),
    "trade_net": M("trade net $", 1, "flow:TRADE_NET", "sum", "none",
                   "higher", 0.30, "src/trade.py + src/sell_policy.py",
                   "Sells minus product buys, exact from the money ledger. This is what "
                   "funds the herd; gross revenue above is only the turnover."),

    # ---- phase 2: midgame ---------------------------------------------------
    # REVENUE IN THE MIDGAME. Phase 1 had a revenue node; phase 2 did not, which is how
    # the midgame was worked for a whole round on structure alone. Both halves are here
    # for the same reason as phase 1: gross sales measure turnover and reward churn,
    # `TRADE_NET` is the ledger identity (`d_money + fixed spend = sells - product buys`)
    # and is the one to judge. Read them together, always.
    "revenue2": M("sell revenue", 2, "flow:REVENUE", "sum", "none",
                  "higher", 0.25, "src/sell_policy.py + src/market.py",
                  "GROSS midgame sales. DESCRIPTIVE: turnover, not profit -- read it "
                  "beside trade net, never as a target.", descriptive=True),
    "trade_net2": M("trade net $", 2, "flow:TRADE_NET", "sum", "none",
                    "higher", 0.30, "src/trade.py + src/sell_policy.py",
                    "Sells minus product buys over d6-17, exact from the money ledger."),
    "quadrants2": M("quadrants unlocked", 2, "stock:quadrants", "last", "quad",
                    "higher", 0.5, "src/budget.py::market_intents",
                    "All four by d10 is the #1's schedule."),
    "owned_tiles2": M("owned tiles", 2, "stock:owned", "last", "owned",
                      "higher", 10, "src/budget.py::market_intents",
                      "100 tiles by d12 is what makes the crop and herd ramps possible."),
    "hands2": M("hands", 2, "stock:hands", "last", "hands",
                "range", 0.25, "src/budget.py::market_intents",
                "Crew size, ground-locked."),
    "animals2": M("animals on board", 2, "stock:animals", "max", "animals",
                  "higher", 3, "src/herd_plan.py::market_intents",
                  "The herd is tile-blocked: it can only grow as land and wheat allow. "
                  "MEASURED 2026-09-28: this is NOT the feed GATE. herd_gate (16 games) "
                  "shows the gate failing every day d11-d17 at 17 animals / 22-26 wheat "
                  "tiles / need 30.6 with $18,546 idle at d17, and opening it "
                  "(HERD_SHED_WHEAT_CREDIT) makes every metric WORSE -- animals 16 -> 15.5. "
                  "The binding quantity is wheat OUTPUT per tile: 0.51 units/tile-day "
                  "against the reference's 0.70, at a theoretical unfertilised max of 0.60. "
                  "See S3.1j and tools/labour/production.py."),
    "structures2": M("animal structures", 2, "stock:structures", "max", "structs",
                     "higher", 6, "src/herd_plan.py::jobs",
                     "Housing follows owned animals."),
    "wheat_tiles2": M("WHEAT tiles", 2, "stock:plant_WHEAT", "max", "wheat",
                      "higher", 6, "src/params.py::CROP_PLAN + src/crop_plan.py::plant_queue",
                      "Feed reserve AND a sale line; the #1 peaks ~32."),
    "straw_tiles2": M("STRAWBERRY tiles", 2, "stock:plant_STRAWBERRY", "max", "straw",
                      "higher", 6, "src/params.py::CROP_PLAN",
                      "Peak ~30 at d15-18 in the #1's farm."),
    "tomato_tiles2": M("TOMATO tiles", 2, "stock:plant_TOMATO", "max", "tomato",
                       "higher", 4, "src/params.py::CROP_PLAN",
                       "The third rotation, from d9."),
    "feed_ops2": M("FEED ops", 2, "flow:FEED", "sum", "feed",
                   "higher", 25, "src/herd_plan.py::jobs",
                   "Scales with herd size; gated by wheat."),
    # DESCRIPTIVE, and this is a deliberate DAG correction. Fertilizer we do not apply
    # is SOLD ($100 base, and the opening's earliest cash engine), so 0 FERTILIZE is a
    # portfolio choice, not a deficiency. MEASURED on the current tree (16 paired games):
    # `FERTILIZE_FROM_DAY=6` closes this node (42 ops) and cuts `plants died` by 8 --
    # and costs **-$4,474 median margin (4/16, p=0.077)** with **-$6,549 revenue
    # (12/16 worse)**. The attrition gain does not pay for the output it consumes.
    # PROMOTED FROM DESCRIPTIVE 2026-09-29. It used to read "MEASURED NEGATIVE: we sell
    # the fertilizer instead", from a `FERTILIZE_FROM_DAY=6` arm that lost -$4,474. That
    # arm was measuring our APPLICATION COST, not the value of the op: `crop_cycle` shows
    # our FERTILIZE at 4.35 moves/op (a shed-pickup round trip) against the reference's
    # 0.09, while the reference fertilizes 1,390 wheat tiles in d6-17 and its fertilized
    # wheat yields 5.35 against 3.17 unfertilized at age 3. Same op, opposite sign once
    # the delivery is free. MEASURED (8 paired games): one-shot fertilize +$7,434 median.
    "fert_ops2": M("FERTILIZE ops", 2, "flow:FERTILIZE", "sum", "fert",
                   "higher", 10, "src/crop_plan.py::jobs + src/scheduler.py::_pick",
                   "The yield multiplier. The reference runs 1,390 wheat ops in d6-17; we "
                   "run 0. What made our arms lose was the shed-pickup delivery (4.35 "
                   "moves/op vs 0.09), so judge this node WITH `FERTILIZE moves/op` "
                   "(`tools/labour/crop_cycle.py`), never alone."),
    "collect_ops2": M("COLLECT_FERTILIZER ops", 2, "flow:COLLECT_FERTILIZER", "sum", "none",
                      "higher", 10, "src/herd_plan.py::jobs",
                      "1 per animal per day; the fertilizer supply."),
    "water_ops2": M("WATER ops", 2, "flow:WATER", "sum", "water",
                    "higher", 60, "src/crop_plan.py::jobs",
                    "Demand scales with planted tiles."),
    # THE PHASE-2 BOTTLENECK, as a node. Boey converts 51 % of his unit-turns into acts
    # and 42 % into walking; we convert 38 % and 60 %. With the same crew that is a
    # 1.65x work deficit, and it is upstream of WATER/HARVEST/COLLECT/FEED at once.
    "move_pct2": M("move share %", 2, "derived:move_pct", "median", "none",
                   "lower", 12, "src/scheduler.py::_pick + src/layout.py",
                   "Walking is the cost. Every point of it is an act we did not do. "
                   "TUNING IS EXHAUSTED: 14 scheduler/layout arms (DIST_CAP 2/3/5 with "
                   "CRITICAL_FREE_WALK_FRAC=0, radial and even bands, animal banding, "
                   "EXACT_ASSIGN, HANDS 14/16, hire 2/3) all trade move share for plant "
                   "deaths and net revenue. STILL EXHAUSTED after the 2026-09-29 conversion "
                   "round: 7 more arms -- SAME_TILE_CROP_CHAIN, COMPLETE_TILE, both, both "
                   "with SAME_TILE_MIN_PRIORITY=0, USE_SLICES=0, USE_SLICES=0+COMPLETE_TILE, "
                   "and a loosened herd gate -- moved moves/act 1.81 -> 1.62 at best and "
                   "cost $2.8k-$10.6k median every time. The remaining work is structural "
                   "(tile geography, the shed round-trip, herd/crop mix) or a GLOBAL "
                   "per-day assignment, not another per-turn priority knob. See S3.5."),
    # ---------------------------------------------------------------------
    # THE FLOW LAYER. Added 2026-09-28 after re-tracing phase 2 against Boey's replays:
    # the node set above is STOCK plus five op counts, and the four largest phase-2 gaps
    # were in the ops it did not measure. MEASURED, d6-17 per game (ours vs Boey, 4-game
    # tree vs 60 reference replays):
    #   MOVE    1839 vs 1319  (1.39x)      DROP    99 vs 32   (3.06x)
    #   PICKUP   152 vs   91  (1.67x)      PLACE    8 vs 43   (0.18x)
    #   unit-turns 3122 vs 2933, acts 1197 vs 1462, REVENUE 40,577 vs 54,059.
    # We have MORE turns and do FEWER acts: the whole gap is conversion, and a graph built
    # on stocks kept reporting "tiles 1.0x, animals 0.76x" while the flow rotted.
    # ---------------------------------------------------------------------
    "move_ops2": M("MOVE ops", 2, "flow:MOVE", "sum", "none",
                   "lower", 200, "src/scheduler.py::_pick + src/layout.py",
                   "The absolute sibling of `move share`: a share can fall while the count "
                   "rises. 1839 vs Boey's 1319 -- 520 turns a game spent walking."),
    "acts2": M("acts per unit-turn", 2, "derived:acts_per_turn", "median", "none",
               "higher", 0.08, "src/scheduler.py::plan",
               "The conversion rate the whole section reduces to. Ours 0.384, Boey 0.498: "
               "we have MORE unit-turns and do FEWER acts."),
    # ---- THE CONVERSION NODES (added 2026-09-29, from `op_patterns` + `turn_budget`).
    # MEASURED d6-17, 8 games each: unit-turns 3,077 vs 3,044 (EQUAL), acts 1,068 vs 1,670,
    # moves 1,900 vs 1,294, moves/act 1.78 vs 0.77. The crew-hours are identical; the whole
    # gap is that our turns are walks. `turn_budget` prices the closure: the reference's
    # 1,641 acts/game at our 1.78 moves/act needs 4,653 turns (16.2 hands) against the 3,077
    # we have, and fits at <=0.8 moves/act. These four nodes are how that gets tracked per
    # day instead of read off a one-off tool run.
    "moves_per_act2": M("moves per act", 2, "derived:moves_per_act", "median", "none",
                        "lower", 0.25, "src/scheduler.py::plan (preop) + src/scheduler.py::_pick",
                        "The conversion rate itself. 1.78 vs Boey's 0.77. A move is an act we "
                        "did not do, and the two arms have the same turns, so this ratio IS "
                        "the phase-2 gap."),
    "chain_fert2": M("FERTILIZE chained %", 2, "derived:chain_FERTILIZE", "median", "none",
                     "higher", 20, "src/scheduler.py::plan (preop chain exemption)",
                     "Share of FERTILIZE ops whose very next op is another ACT (no walk). "
                     "3.1 % vs Boey's 93.3 %. Root cause is the same-tile pre-pass floor "
                     "`SAME_TILE_MIN_PRIORITY=70` against `P_FERTILIZE=54`, so a unit waters "
                     "a tile and leaves before fertilizing it (3.00 vs 0.02 moves/op)."),
    "chain_water2": M("WATER chained %", 2, "derived:chain_WATER", "median", "none",
                      "higher", 8, "src/scheduler.py::plan (preop) + src/layout.py",
                      "8.3 % vs Boey's 17.4 %. WATER is 40 % of all our walks; a water that "
                      "is followed by another act is a tile finished in place."),
    "runs_ge3_2": M("acts in act-runs >=3 %", 2, "derived:runs_ge3_share", "median", "none",
                    "higher", 15, "src/scheduler.py::plan (preop) + src/scheduler.py::_pick",
                    "Dwelling vs commuting. 24.3 % vs Boey's 47.1 %, and 6.3 % vs 29.4 % for "
                    "runs of >=4 -- his signature is the whole tile stack in one stop."),
    "drop_ops2": M("DROP ops", 2, "flow:DROP", "sum", "none",
                   "lower", 20, "src/scheduler.py::_deposit_op",
                   "3.06x Boey's. HARVEST puts produce in the UNIT'S INVENTORY and DROP is "
                   "the only mid-day exit -- but `_drop_inventories_to_shed` clears every "
                   "unit for free at `_end_of_day`, so a mid-day trip is only needed to free "
                   "the hands or to reach the bell. We drop once per harvest (98 HARVEST -> "
                   "99 DROP); Boey drops once per five (160 -> 32)."),
    "pickup_ops2": M("PICKUP ops", 2, "flow:PICKUP", "sum", "none",
                     "lower", 30, "src/scheduler.py::_pick + src/herd_plan.py::jobs",
                     "1.67x Boey's -- the inbound half of the same shed round trip. `PICKUP` "
                     "is refused while the unit holds anything (`_eligible`), which is what "
                     "forces the pair: harvest -> deposit -> fetch -> walk back."),
    "place_ops2": M("PLACE ops", 2, "flow:PLACE", "sum", "none",
                    "higher", 10, "src/herd_plan.py::jobs",
                    "0.18x Boey's. An animal bought into the shed is not an animal on the "
                    "board until it is walked out and placed; this is the herd gap appearing "
                    "as a flow, and it is why `animals` can sit at 16 with structures built."),
    "plant_ops2": M("PLANT ops", 2, "flow:PLANT", "sum", "none",
                    "higher", 25, "src/crop_plan.py::plant_queue + src/scheduler.py::_plant_jobs",
                    "Turnover, not tile count. `planted_tiles2` matches Boey at 1.0x and this "
                    "is the same crop turning over half as often."),
    "harvest_per_planted2": M("HARVEST per planted tile", 2, "derived:harvest_per_planted",
                              "mean", "none", "higher", 0.2, "src/scheduler.py::_pick",
                              "The honest volume metric: output per unit of standing crop."),
    "watered_per_tile": M("WATER ops per planted tile", 2, "derived:water_per_tile", "mean", "water_per_tile",
                          "range", 0.3, "src/scheduler.py::_pick",
                          "If this is low the crew is not reaching the crops it owns."),
    "plants_died2": M("plants died", 2, "derived:plants_died", "sum", "none",
                      "lower", 15, "src/scheduler.py::_pick (water prioritisation)",
                      "A plant becomes a WEED after two unwatered nights (C5)."),
    "harvests2": M("HARVEST ops", 2, "flow:HARVEST", "sum", "none",
                   "higher", 40, "src/scheduler.py::_pick",
                   "Throughput; the #1 runs 597/season."),
    "weeds2": M("weeds", 2, "stock:weed", "max", "weeds",
                "lower", 4, "src/crop_plan.py::jobs (DIG)",
                "Weed count reads out how much land we stopped watering."),
    "shed2": M("shed peak", 2, "stock:shed_total", "max", "shed_max",
               "range", 0.25, "src/sell_policy.py + src/scheduler.py (DROP)",
               "The shed is a transit buffer: the #1 pins it at 100."),
    "idle_pct2": M("idle share %", 2, "derived:idle_pct", "median", "idle_pct",
                   "lower", 5, "src/scheduler.py::plan",
                   "The #1 is at ~0 from d12 on."),
    "planted_tiles2": M("planted tiles", 2, "stock:planted", "max", "crops",
                        "higher", 12, "src/crop_plan.py::plant_queue",
                        "Standing crops; the #1 runs ~100 tiles of farm at peak."),

    # ---- phase 3: endgame ---------------------------------------------------
    "animals3": M("animals at the bell", 3, "stock:animals", "last", "animals",
                  "range", 0.5, "src/herd_plan.py (release) + src/endgame.py",
                  "The release is deliberate: feed stops and the herd walks away."),
    "weeds3": M("weeds", 3, "stock:weed", "max", "weeds",
                "range", 5, "src/endgame.py (RETIRE_DAY)",
                "The #1's weeds 0 -> 10 are the retirement plan, not neglect."),
    "water_ops3": M("WATER ops", 3, "flow:WATER", "sum", "water",
                    "range", 80, "src/crop_plan.py::jobs",
                    "Falls 63 -> 24 in the #1's last four days: production is switched off."),
    "fert_ops3": M("FERTILIZE ops", 3, "flow:FERTILIZE", "sum", "fert",
                   "range", 40, "src/crop_plan.py::jobs",
                   "Descriptive: see fert_ops2 -- the fertilizer is a sold product here.",
                   descriptive=True),
    "harvests3": M("HARVEST ops", 3, "flow:HARVEST", "sum", "none",
                   "higher", 40, "src/scheduler.py::_pick",
                   "The last days are harvesting and selling."),
    "shed3": M("shed at the bell", 3, "stock:shed_total", "last", "shed_max",
               "range", 25, "src/sell_policy.py",
               "End-of-day shed is ~4-8 for the #1: full and ROTATING, not stored."),
    "idle_pct3": M("idle share %", 3, "derived:idle_pct", "median", "idle_pct",
                   "lower", 5, "src/scheduler.py::plan",
                   "The #1 is at 0 through the endgame."),
    "harvested_per_planted": M("HARVEST per planted tile", 3, "derived:harvest_per_planted", "mean", "none",
                               "range", 0.35, "src/scheduler.py::_pick",
                               "Are the standing crops actually being brought in?"),
}

# ---------------------------------------------------------------------------
# The causal DAG. Each edge is (upstream, downstream, mechanism).
# Read a mechanism as "if upstream is short, downstream is short BECAUSE ...".
# ---------------------------------------------------------------------------
EDGES = [
    # opening: the cash triangle. Land, herd and seed all draw on one $3,000 bank.
    ("cash_commit", "quadrants", "the same opening bank buys land; the #1 spends to $6 and takes NE on d6"),
    ("cash_commit", "animals", "the same bank buys the opening herd -- you cannot fund both fully"),
    ("cash_commit", "melon_tiles", "the d0-d2 MELON block is bought with opening cash"),
    ("quadrants", "owned_tiles", "a quadrant is 25 tiles"),
    ("owned_tiles", "hands", "hands are hired to ground: min(schedule, owned//TILES_PER_HAND)"),
    ("owned_tiles", "empty_tiles", "more ground with the same crew leaves tiles bare"),
    ("owned_tiles", "animals", "ANIMAL TILE = CROP TILE at 25 tiles: measured, a 6-tile holdback + a 6-animal herd cost $15,020 vs 25-tile crops (margin, matched pairs, p=0.0001)"),
    ("animals", "structures", "housing is built only for animals already owned"),
    ("animals", "feed_ops", "one wheat per animal per day"),
    ("animals", "care_ops", "care is free and daily, and it banks the bonus"),
    ("melon_tiles", "water_ops", "melon's water window is ages 6-12, so it drives early demand"),
    ("straw_tiles", "water_ops", "ongoing crops need watering to keep producing"),
    ("plant_ops", "water_ops", "a newly planted tile must be watered the same day or it weeds that night"),
    ("animals", "idle_pct", "feed/care/collect are DAILY work; a crop-only farm has nothing to do on the odd days"),
    ("plant_ops", "idle_pct", "planting is the only other filling work"),
    ("owned_tiles", "straw_tiles", "the ramp can only claim tiles we own"),
    ("idle_pct", "empty_tiles", "idle crew + bare tiles = the ramp is throttling planting"),
    # phase 1 -> phase 2
    ("quadrants", "quadrants2", "land is bought in order, one quadrant at a time"),
    ("quadrants", "owned_tiles2", "NE at d6 is worth 25 tiles for the whole strawberry ramp"),
    ("owned_tiles2", "hands2", "hands are capped by ground"),
    ("owned_tiles2", "wheat_tiles2", "tiles are the ceiling on every crop ramp (C4)"),
    ("owned_tiles2", "straw_tiles2", "the strawberry ramp peaks at 30 tiles"),
    ("owned_tiles2", "tomato_tiles2", "the third rotation also needs room"),
    ("owned_tiles2", "animals2", "the herd is tile-blocked: an animal tile is a crop tile"),
    ("animals", "animals2", "phase 1's herd is the floor for phase 2's herd"),
    ("wheat_tiles2", "feed_ops2", "home-grown wheat is the cheap feed (C2)"),
    ("animals2", "feed_ops2", "one per animal per day"),
    ("animals2", "collect_ops2", "one fertilizer per animal per day"),
    ("animals2", "fert_ops2", "fertilizer supply gates FERTILIZE"),
    ("animals2", "structures2", "housing follows animals"),
    ("collect_ops2", "fert_ops2", "the pickup -> fertilize chain"),
    ("fert_ops2", "harvests2", "fertilizer doubles one-shot yield and ongoing fruit"),
    ("straw_tiles2", "water_ops2", "watering demand scales with standing crops"),
    ("wheat_tiles2", "water_ops2", "wheat's window is ages 2-4"),
    ("planted_tiles2", "water_ops2", "every planted tile is watering demand"),
    ("water_ops2", "plants_died2", "an unwatered plant weeds after two nights (C5)"),
    ("water_ops2", "weeds2", "watering is what keeps a tile from becoming a weed"),
    ("plants_died2", "weeds2", "a dead plant IS a weed"),
    ("weeds2", "harvests2", "weed tiles have to be dug before they can be replanted"),
    ("plants_died2", "harvests2", "a dead plant is a harvest that never happens"),
    ("hands2", "water_ops2", "the crew is the watering capacity"),
    # MOVE SHARE IS A ROOT, and it is not a restatement of `hands`. MEASURED 2026-09-27:
    # the crew is re-hired from scratch every night (`_end_of_day` clears `farm["hands"]`
    # and `hires_today`), so `MAX_HIRE_PER_TURN` was paying a 12-hand crew back at one
    # hand per turn; raising it (phase-scoped) bought +14 % acts with NO extra walking.
    # Independently, an animal tile offers FEED/CARE/COLLECT and we were taking one op per
    # visit -- `SAME_TILE_ANIMAL_CHAIN` took FEED chaining 21 % -> 56 % against Boey's 66 %.
    # Both raised the act count; neither shortened a walk, so `move share` is still 59.5 %
    # against Boey's 41.6 % and every act class below it is still reachable only by
    # converting a walk into an act (moves/act 1.52 vs 1.09, walks 3,073 vs 2,895 at a
    # mean of 2.39 vs 1.95 tiles -- tools/labour/walk_runs.py, d6-17, 4 games each).
    # REVENUE IS DOWNSTREAM OF THROUGHPUT, and the midgame had no money node at all
    # until 2026-09-28 -- a whole round of phase-2 work was done on structure alone.
    # MEASURED (tools/report/phase_revenue.py, 96 games x 12 public opponents): we net
    # $37k in d6-17 against the field's $61k (0.60x, and Boey's own reference is $61k).
    # `TRADE_NET` is ledger-exact and therefore the only fair cross-seat number; the
    # `REVENUE` estimator is capped by the shed and under-counts an opponent that
    # over-orders (a public agent issued 579 units of SELL orders from a shed of 262).
    ("harvests2", "trade_net2", "the midgame earns what it harvests and sells"),
    ("collect_ops2", "trade_net2", "fertilizer is a midgame revenue line"),
    ("animals2", "trade_net2", "milk/wool/egg are the herd's revenue"),
    # THE DISPLACEMENT. The crew is fixed; every field-work metric competes with the animal
    # chain for the same turns, and MEASURED the animal chain pays better on every turn.
    # `P_DIG_P3=90` holds the endgame farm at 32-36 planted tiles against a collapse to 3
    # and still loses $4,708 (0/16, p=0.0000), because phase-3 FERTILIZER collection falls
    # 1,885 -> 668 units and every other line falls with it. See S3.1r.
    ("collect_ops2", "weeds2", "digging is done by the units that would collect fertilizer"),
    # THE FLOW EDGES. These are the dependencies the stock graph could not express, and
    # they are what makes the turnover defect visible as a CHAIN rather than a ratio.
    ("harvests2", "drop_ops2", "HARVEST fills the unit's inventory; DROP is the only "
                               "mid-day exit and the end-of-day clear is free"),
    ("collect_ops2", "drop_ops2", "with FERTILIZE disabled the only exit for a carried "
                                  "fertilizer is the shed"),
    ("shed2", "drop_ops2", "a carried unit with no job in band deposits rather than "
                           "walking to the nearest job"),
    ("drop_ops2", "move_ops2", "every deposit is a walk to the shed and back"),
    ("pickup_ops2", "move_ops2", "every fetch is the other half of that round trip"),
    ("animals2", "place_ops2", "buying an animal creates the placement job"),
    ("place_ops2", "animals2", "a shed animal is not a board animal until it is placed"),
    ("plant_ops2", "harvests2", "nothing is harvested that was not planted"),
    ("plant_ops2", "harvest_per_planted2", "turnover, not standing crop, is the volume"),
    # MEASURED 2026-09-29. The sell side is NOT the midgame's binding constraint.
    # WHEAT is the deepest, most liquid line (near-flat log curve: $25 at I0, $20 at
    # +500, $18 at +8,000), so there is no scarcity spike to HOLD for. Boey treats it
    # as a trade: over d6-17 he REQUESTED 3,249 wheat sells and 1,838 wheat buys per
    # game against our 239 and 324 (13.6x / 5.7x), and the harness audit shows the
    # sells execute -- we sold 164 units, he ~2,000.
    # The decisive experiment: `WHEAT_SELL_RESERVE_P2=5` (phase-2 only) buys exactly
    # the right midgame number -- revenue 64,516 -> 70,053, wheat sold 164 -> 308 --
    # and still LOSES the season, 46,088 -> 44,672. Selling the reserve borrows from
    # phase 3, which then buys feed back at retail. So volume is bounded UPSTREAM.
    ("wheat_tiles2", "revenue2", "wheat is the deep liquid line, but only what the "
                                 "tiles GROW is sellable; thinning the reserve in P2 "
                                 "borrows from P3 (MEASURED: +$5.5k revenue, -$1.4k final)"),
    ("plant_ops2", "revenue2", "WHEAT is a one-shot crop: every harvest empties the "
                               "tile, so sale volume is a function of plant TURNOVER"),
    ("move_ops2", "acts2", "walking is the denominator of the conversion rate"),
    # THE CONVERSION CHAIN. `moves_per_act2` is the quantity; the chain nodes are its
    # causes. A unit that leaves a tile before finishing it pays a walk it did not need,
    # which is why the fix order is chaining -> moves/act -> acts -> the op counts.
    ("chain_fert2", "moves_per_act2", "a fertilize applied on the tile the unit already "
                                      "stands on costs 0 moves (3.00 -> 0.02 mv/op)"),
    ("chain_water2", "moves_per_act2", "one water per visit is one walk per water"),
    ("runs_ge3_2", "moves_per_act2", "dwelling in a tile stack is the inverse of commuting"),
    ("moves_per_act2", "acts2", "with unit-turns fixed, every move is a lost act"),
    ("moves_per_act2", "water_ops2", "the turns not spent walking are the turns that water"),
    ("moves_per_act2", "harvests2", "and the turns that harvest"),
    # THE FERTILIZATION CHAIN, added 2026-09-29 with `tools/labour/crop_cycle.py`.
    # (`fert_ops2 -> harvests2` already exists above; these are the two it did not have.)
    ("fert_ops2", "revenue2", "more units per standing tile on the deep liquid lines; the "
                              "reference's fertilized wheat is 5.35 units against 3.17"),
    ("fert_ops2", "plants_died2", "the fertilize turns compete with survival water for the "
                                  "same crew -- the trade to watch when the node moves"),
    ("move_pct2", "water_ops2", "walking is a turn not spent watering"),
    ("move_pct2", "harvests2", "walking is a turn not spent harvesting"),
    ("move_pct2", "collect_ops2", "walking is a turn not spent collecting"),
    ("move_pct2", "feed_ops2", "walking is a turn not spent feeding"),
    ("watered_per_tile", "plants_died2", "coverage, not raw watering, is what keeps plants alive"),
    ("hands2", "idle_pct2", "a crew bigger than the work idles"),
    ("animals2", "idle_pct2", "daily feed/care/collect work"),
    ("fert_ops2", "idle_pct2", "the fertilize/pickup chain is more daily work"),
    ("harvests2", "shed2", "harvests land in the shed"),
    ("animals2", "shed2", "milk/wool/egg/fertilizer also land in the shed (C1)"),
    ("shed2", "idle_pct2", "a full shed turns harvest into DROP/PICKUP walking"),
    # phase 2 -> phase 3
    ("animals2", "animals3", "the herd at the bell is the herd we fed to the end"),
    ("harvests2", "harvests3", "standing crops at d18 are what d18-29 can harvest"),
    ("weeds2", "weeds3", "weeds only accumulate"),
    ("water_ops2", "water_ops3", "the same watering demand carries into the last days"),
    ("fert_ops2", "fert_ops3", "the fertilizer chain carries over"),
    ("water_ops3", "weeds3", "retiring a tile means it weeds -- deliberately (rule #4)"),
    ("weeds3", "harvests3", "a weeded tile cannot be harvested"),
    ("harvests3", "harvested_per_planted", "throughput against what was standing"),
    ("harvested_per_planted", "shed3", "harvests that cannot be sold accumulate in the shed"),
    ("shed3", "idle_pct3", "carrying to a full shed costs turns"),
    ("animals3", "idle_pct3", "the herd is the daily work in the endgame too"),
]

# Metrics referenced by the table but without a DSM target ("none"): they are
# descriptive (a rate, a fraction, or a value the #1's table has no column for), so
# the tool reports them WITHOUT a status and they cannot be roots.


# ===========================================================================
# GRAPH ADDITIONS — time, evidence, controllability, latents
# ===========================================================================
# The three things a bare DAG could not say, and which cost us real money:
#   * WHEN    an edge acts (a lag in days), so an intervention can be BACK-SCHEDULED
#   * HOW MUCH it is worth (a shadow price), so a root is ranked by marginal value
#             rather than by how many descendants it has
#   * WHO owns it (controllable / derived / latent), so "where to act" is unique
# A root with no controllable ancestor is not actionable at all -- it is weather.

# --- two LATENT nodes: the shop draw is RNG-revealed, not chosen ---------------
# Shops unlock at the end of every 3rd day, and WHICH one is a function of the number
# of empty owned tiles that night (see the exogeneity note in tools/readme.md), so
# these nodes are observable but not controllable: the policy must REACT to them.
METRICS["shops"] = M("shops unlocked", 1, "stock:shops", "last", "none",
                     "higher", 1, "-  LATENT (RNG-revealed)",
                     "How many shops have unlocked by the phase end. Determines which "
                     "products have buyers.")
METRICS["yarn"] = M("YARN_STORE unlocked", 1, "stock:yarn", "max", "none",
                    "higher", 1, "-  LATENT (RNG-revealed)",
                    "1 if YARN_STORE is up. MEASURED: the #1's d5 herd is a CONSTANT "
                    "(2 COW + 3 SHEEP in 40/40 games) whatever the draw; the wool "
                    "response is a midgame re-specialisation, not an opening one.")
EDGES += [
    ("shops", "yarn", "YARN_STORE is one of the shops in the draw"),
    ("yarn", "animals", "MEASURED, LAGGED: at the season end YARN worlds hold SHEEP 7.5 / "
                        "GOOSE 2 while no-YARN worlds hold SHEEP 0 / GOOSE 6 -- but his d5 "
                        "mix is invariant, so this edge acts from d6 on, never in the opening"),
    ("yarn", "straw_tiles", "a shop also changes which crop pays"),
]

# --- edge metadata: (lag in days, evidence) -----------------------------------
# Lag is how many days after acting the downstream metric feels it. Unlisted edges
# default to lag 0 and evidence "assumed". Every entry here is something this
# session actually measured; "assumed" is an honest label, not a placeholder.
EDGE_META = {
    # opening: the cash triangle is same-day
    ("cash_commit", "quadrants"): (0, "measured: the #1 takes NE on d6, funded by d0-d5 trade"),
    ("cash_commit", "animals"): (0, "measured: 5 animals cost $2,300 of the $3,000 bank"),
    ("cash_commit", "melon_tiles"): (0, "the d0-d2 MELON block is bought with opening cash"),
    ("quadrants", "owned_tiles"): (0, "a quadrant is 25 tiles"),
    ("owned_tiles", "hands"): (0, "hands = min(schedule, owned//TILES_PER_HAND), same turn"),
    ("owned_tiles", "animals"): (0, "tile-blocked: an animal tile is a crop tile"),
    # the lags that matter -- these are why timing kept beating us
    ("animals", "feed_ops"): (0, "one wheat per animal per day, same day"),
    ("animals", "structures"): (0, "housing follows owned animals (measured: built to order)"),
    ("yarn", "animals"): (3, "the d3 unlock is only VISIBLE after the first shop draw"),
    ("shops", "yarn"): (3, "shops unlock at the end of every 3rd day"),
    # phase 1 -> 2: the coupling that costs days
    ("animals", "animals2"): (6, "a day-0 animal is only a midgame animal 6 days later"),
    ("quadrants", "wheat_tiles2"): (4, "NE at d6 is the ceiling on the d10 wheat ramp"),
    ("quadrants", "straw_tiles2"): (8, "strawberry takes first_yield_day=10 from planting"),
    ("wheat_tiles2", "feed_ops2"): (4, "wheat needs max_yield_day=4 to be harvestable feed"),
    ("animals2", "fert_ops2"): (1, "fertilizer is produced at the day boundary"),
    ("water_ops2", "plants_died2"): (2, "a plant weeds after TWO unwatered nights"),
    ("plants_died2", "weeds2"): (0, "a dead plant IS a weed"),
    ("weeds2", "harvests2"): (1, "a weed must be dug before the tile can be replanted"),
    ("animals2", "shed2"): (0, "milk/wool/egg/fert land in the shed the day they are collected"),
    # phase 2 -> 3
    ("animals2", "animals3"): (12, "the herd at the bell is the herd we kept feeding"),
    ("harvests2", "harvests3"): (0, "standing crops at d18 are what d18-29 harvest"),
    ("water_ops3", "weeds3"): (2, "retiring a tile weeds it after two nights"),
}

# --- controllability: WHO we would turn, and with what ------------------------
# "controllable" = we have a knob on it. "derived" = a consequence. "latent" = RNG.
CONTROLS = {
    "cash_commit": "src/crop_plan.py::market_intents + src/herd_plan.py::market_intents",
    "quadrants": "src/budget.py::LAND_TARGET_DAY + CASH_RESERVE",
    "animals": "src/params.py::HERD_BUY_FROM_DAY, HERD, WHEAT_TILES_PER_ANIMAL",
    "structures": "src/herd_plan.py::jobs (build-to-order) + params.STRUCTURE_HOLDBACK",
    "melon_tiles": "src/params.py::CROP_PLAN['MELON']",
    "straw_tiles": "src/params.py::CROP_PLAN['STRAWBERRY']",
    "wheat_tiles": "src/params.py::CROP_PLAN['WHEAT']",
    "tomato_tiles": "src/params.py::CROP_PLAN['TOMATO']",
    "water_ops": "src/scheduler.py::_pick + params.TILES_PER_HAND",
    "plant_ops": "src/crop_plan.py::plant_queue",
    "feed_ops": "src/herd_plan.py::jobs",
    "care_ops": "src/herd_plan.py::jobs",
    "fert_ops": "src/crop_plan.py::jobs + params.FERTILIZE_FROM_DAY",
    "collect_ops2": "src/herd_plan.py::jobs",
    "hands": "src/budget.py::market_intents (target_hands, TILES_PER_HAND, MAX_HIRE_PER_TURN)",
    "idle_pct": "src/scheduler.py::plan",
    "harvests": "src/scheduler.py::_pick",
    "shed_peak": "src/sell_policy.py + src/scheduler.py DROP",
    "weeds": "src/crop_plan.py::jobs (DIG)",
    "shops": "-  LATENT (RNG-revealed)",
    "yarn": "-  LATENT (RNG-revealed)",
}
KIND = {k: ("latent" if v.startswith("-") else "controllable") for k, v in CONTROLS.items()}


def lag_of(a, b):
    return EDGE_META.get((a, b), (0, "assumed"))[0]


def evidence_of(a, b):
    return EDGE_META.get((a, b), (0, "assumed"))[1]
