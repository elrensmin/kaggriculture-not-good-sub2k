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
def M(label, phase, src, agg, target_key, better, tol, owner, desc):
    return dict(label=label, phase=phase, src=src, agg=agg, target_key=target_key,
                better=better, tol=tol, owner=owner, desc=desc)


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

    # ---- phase 2: midgame ---------------------------------------------------
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
                  "The herd is tile-blocked: it can only grow as land and wheat allow."),
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
    "fert_ops2": M("FERTILIZE ops", 2, "flow:FERTILIZE", "sum", "fert",
                   "higher", 10, "src/crop_plan.py::jobs + src/herd_plan.py::jobs",
                   "Requires animals (fertilizer) AND the pickup chain."),
    "collect_ops2": M("COLLECT_FERTILIZER ops", 2, "flow:COLLECT_FERTILIZER", "sum", "none",
                      "higher", 10, "src/herd_plan.py::jobs",
                      "1 per animal per day; the fertilizer supply."),
    "water_ops2": M("WATER ops", 2, "flow:WATER", "sum", "water",
                    "higher", 60, "src/crop_plan.py::jobs",
                    "Demand scales with planted tiles."),
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
                   "Stops dead on d29 in the #1's farm."),
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
