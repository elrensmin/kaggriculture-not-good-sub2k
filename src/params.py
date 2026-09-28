"""Tunable constants for the from-scratch agent. Single source of truth.

Everything a layer needs to tweak lives here; nothing else is hard-coded. This is
the "mutable knobs" file the plan promises: a movement/routing change edits this
module (cost weights) or routing.py, never the schedule/state layers.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS, CROPS, LAND_ORDER, LAND_PRICES, MARKET_PARAMS, PRICE_FLOOR,
    PRODUCTS, SHOPS,
)

BOARD = 10
TURNS_PER_DAY = 24
EPISODE_STEPS = 720
SHED_CAP = 100
MAX_ORDERS = 10
START_MONEY = 3000
I0 = 10000

# ===========================================================================
# PHASE-SCOPED PARAMS -- tune the midgame without touching the opening
# ===========================================================================
# Every knob used to be global, so a phase-2 experiment could regress phase 1 and the
# screen had to be thrown away. Measured example: `P_COLLECT_FERT=70` raised phase-2
# `COLLECT_FERTILIZER ops` 84 -> 108 and improved weeds (27 -> 24) and plants died, but
# it dropped the OPENING herd 8 -> 7, GOOSE 2 -> 1 and trade net 0.98x -> 0.90x. The
# change was good for the phase it targeted and had to be rejected for the phase it did
# not.
#
# Mechanism: a knob `X` keeps its shipped value (the phase-1 / season base) and
# `X_P2` / `X_P3` override it for days 6-17 / 18-29. `None` (the default) = no override,
# so phase 1 is bit-identical until someone asks otherwise. Layers that run in more than
# one phase must read the knob with `params.at("X", day)`, never `params.X`.
# Both `X` and `X_P2` are SCRATCH_PARAMS-settable.
PHASE1_LAST_DAY = 5      # the opening script's last day
PHASE2_LAST_DAY = 17     # the midgame's last day


def phase_of(day: int) -> int:
    """1 = opening (d0-5), 2 = midgame (d6-17), 3 = endgame (d18-29)."""
    if day <= PHASE1_LAST_DAY:
        return 1
    if day <= PHASE2_LAST_DAY:
        return 2
    return 3


def at(name: str, day: int):
    """Phase-scoped value of the knob `name`: `NAME_P2`/`NAME_P3` override `NAME`.

    Phase 1 returns `NAME` unchanged, which is what makes a phase-2-only experiment
    safe: with every `_P2` left at its `None` default the opening cannot move.

    `None` means "no override" and falls THROUGH to the base -- the `_P2` key exists
    with value None, so `globals().get(...)` alone would return None and every phase-2
    read would get None instead of the shipped value.
    """
    p = phase_of(day)
    base = globals().get(name)
    if p >= 2:
        override = globals().get(f"{name}_P{p}")
        return base if override is None else override
    return base


# Phase-2 priority-band overrides applied by the scheduler (see `job.phase_band`).
# `None` = keep the band the job was constructed with.
P_HARVEST_P2 = None
P_PICKUP_WHEAT_P2 = None
P_FEED_P2 = None
P_WATER_SURVIVAL_P2 = None
P_WATER_BONUS_P2 = None
WATER_ONGOING_PRODUCE_P2 = None
WATER_WINDOW_PRIORITY_P2 = None
BAND_ANIMALS_P2 = None
LAYOUT_RADIAL_P2 = None
LAYOUT_EVEN_BANDS_P2 = None
P_PICKUP_P2 = None
P_PLANT_P2 = None
P_CARE_P2 = None
P_PICKUP_ANIMAL_P2 = None
P_PLACE_P2 = None
P_COLLECT_FERT_P2 = None
P_FERTILIZE_P2 = None
P_BUILD_P2 = None
P_DIG_P2 = None
# Phase-2 overrides for the structural/tuning scalars we actually sweep in the midgame.
LAND_QUADRANT_MAX_P2 = None
# SHIPPED at the d10 state-clone step WITH FEED_STOCK_DAYS_P2 and STRAWBERRY_PEAK=11.
# MEASURED (8 paired games, current tree): the 4-part bundle is **+$10,218 median**
# (revenue +$11,498, plants_died -2.5). The parts are NOT separable: the herd gate
# alone with feed stocking is **-$5,448** without the earlier strawberry ramp -- the
# herd eats feed that only the earlier strawberry crop pays for. See S3.10.
WHEAT_TILES_PER_ANIMAL_P2 = 1.2
WHEAT_SELL_RESERVE_P2 = None
TRICKLE_P2 = None
TRICKLE_P3 = None
SELL_TRICKLE_FRACTION_P3 = None
WHEAT_SELL_RESERVE_P3 = None
WHEAT_TARGET_FROM_HERD_P2 = None
HERD_SHED_WHEAT_CREDIT_P2 = None
ANIMAL_FEED_RESERVE_DAYS_P2 = None
ANIMAL_FEED_RESERVE_DAYS_MATURE_P2 = None
ANIMAL_SHED_LIMIT_P2 = None
MOVE_WEIGHT_P2 = None
DIST_CAP_P2 = None
ON_TILE_BONUS_P2 = None
SLICE_PENALTY_P2 = None
SAME_TILE_MIN_PRIORITY_P2 = None
SAME_TILE_ANIMAL_CHAIN_P2 = 1
# ^ MEASURED on top of MAX_HIRE_PER_TURN_P2=6 (same 4-game screen): plants died
# 12.0 -> 10.0, weeds 14.0 -> 8.0, COLLECT_FERTILIZER 108 -> 133, WATER 318 -> 322,
# shed peak 21 -> 19.5. Nothing regressed.
PLANT_WATER_CAP_DIVISOR_P2 = None
WATER_READY_FALLBACK_P2 = None
FERTILIZE_FROM_DAY_P2 = 6
FERTILIZE_SHED_PICKUP_P2 = None
HARVEST_CRITICAL_P2 = None
ONGOING_HARVEST_ANY_P2 = None
ONGOING_HARVEST_MIN_P2 = None
PICKUP_WHEAT_QTY_P2 = None
STRUCTURE_HOLDBACK_P2 = None
WHEAT_PICKUP_QTY_P2 = None
DROP_HOUR_P2 = None
USE_SLICES_P2 = None
MARKET_HIRE_FIRST_HOURS_P2 = None
MAX_HIRE_PER_TURN_P2 = 6
# ^ PHASE-2 CREW RATE. The engine wipes `farm["hands"]` and `hires_today` every
# night, so the whole crew must be RE-HIRED daily, one hand per HIRE order. The
# phase-1 value is 1 (the tape's market list is already 10 slots wide and 5 HIREs
# at once pushed the MELON seed past MAX_ORDERS). Phase 1 does not care -- it runs
# 5 hands -- but phase 2 runs 12, so the cap was paying the crew back at ~1/day.
# MEASURED (phase_map --phase phase2 --pa 2,5 --batch 2, 4 games, ref 20 Boey
# replays): WATER ops 248 -> 322, HARVEST 79 -> 100, FEED 125 -> 137, COLLECT
# 85.5 -> 104, animals 12.5 -> 16, weeds 27 -> 14.5, shed peak 22.5 -> 20.
# 4 / 6 / 12 all land inside the 4-game noise band; 6 is the smallest that
# captures the gain, which keeps the phase-2 market list clear of the
# MAX_ORDERS=10 tail.

# --- phase 3 (d18-29) equivalents. Without a declaration a `X_P3=` in
# SCRATCH_PARAMS is silently ignored -- the phantom-knob trap.
ANIMAL_FEED_RESERVE_DAYS_P3 = None
ANIMAL_FEED_RESERVE_DAYS_MATURE_P3 = None
DIST_CAP_P3 = None
DROP_HOUR_P3 = None
FERTILIZE_FROM_DAY_P3 = None
FERTILIZE_SHED_PICKUP_P3 = None
HARVEST_CRITICAL_P3 = None
LAND_QUADRANT_MAX_P3 = None
MOVE_WEIGHT_P3 = None
ONGOING_HARVEST_ANY_P3 = None
ONGOING_HARVEST_MIN_P3 = None
ON_TILE_BONUS_P3 = None
PICKUP_WHEAT_QTY_P3 = None
PLANT_WATER_CAP_DIVISOR_P3 = None
P_BUILD_P3 = None
P_CARE_P3 = None
P_COLLECT_FERT_P3 = None
P_DIG_P3 = None
P_FEED_P3 = None
P_FERTILIZE_P3 = None
P_HARVEST_P3 = None
P_PICKUP_P3 = None
P_PICKUP_ANIMAL_P3 = None
P_PICKUP_WHEAT_P3 = None
P_PLACE_P3 = None
P_PLANT_P3 = None
P_WATER_BONUS_P3 = None
WATER_ONGOING_PRODUCE_P3 = None
WATER_WINDOW_PRIORITY_P3 = None
BAND_ANIMALS_P3 = None
LAYOUT_RADIAL_P3 = None
LAYOUT_EVEN_BANDS_P3 = None
P_WATER_SURVIVAL_P3 = None
SAME_TILE_MIN_PRIORITY_P3 = None
SAME_TILE_ANIMAL_CHAIN_P3 = None
# ^ NOT SHIPPED: the same bug class as `MAX_HIRE_PER_TURN_P3` (declared `_P2`, unset `_P3`)
# but MEASURED INERT -- the 96-game arm with `_P3=1` is byte-identical to the one without it
# (`docs/v0/step14-armdiff.txt` vs `step13b-armdiff.txt`), so the chain does not bind in
# phase 3 the way it does in phase 2. Kept as a knob, default off.
SLICE_PENALTY_P3 = None
STRUCTURE_HOLDBACK_P3 = None
USE_SLICES_P3 = None
MARKET_HIRE_FIRST_HOURS_P3 = None
# ^ NOT SHIPPED. It looked good on 16 games (cap alone +$7,052/14-16 -> cap + hire-first
# +$8,598/16-16) and is WORSE on 96: cap alone **+$6,758, 94/96** vs cap + hire-first
# **+$5,342, 95/96**. The 96-game pair is the one to trust; the 16-game gain was noise.
# Kept as a knob, default off.
MAX_HIRE_PER_TURN_P3 = 6
# ^ PHASE 3 WAS MISSING THIS AND IT COST THE SEASON. `_end_of_day` wipes the whole
# crew nightly and resets `hires_today`, so every morning is a rebuild. Round 0 set
# `_P2 = 6` and left `_P3` unset, so the endgame silently fell through to the base
# value of **1** -- twelve turns to re-hire twelve hands, every day, for d18-29.
# MEASURED (live probe of `budget.market_intents`, d20 h0): money $29,415,
# n_hire 12, cap 1, emitted 1. Mean units by hour over d6-29: us 1.0/4.3/7.0/7.8
# against Boey's 1.0/8.7/11.2/11.5 -- a complete crew at hour 12 against hour 2.
# See §3.1s.
WATER_READY_FALLBACK_P3 = None
WHEAT_PICKUP_QTY_P3 = None
WHEAT_TILES_PER_ANIMAL_P3 = None

# The four tiles that touch the shed. "Shed-adjacent" == standing on one of these.
SHED_ACCESS = [(4, 4), (5, 4), (4, 5), (5, 5)]
SHED_ACCESS_SET = set(SHED_ACCESS)


# ---- routing cost model (edit here for movement behaviour) -------------------
# Crossing a LOCKED (unowned) tile is legal since 1.32.3, but we prefer to avoid
# it. A large-but-finite penalty keeps the router on owned land while still
# allowing a crossing when it is the only route to a job.
LOCKED_PENALTY = 200.0
# Stepping onto an occupied tile (a plant/animal you are not targeting) costs no
# extra: movement is legal and free over any tile. Keep 1.0 so the cost model is
# purely distance + locked-avoidance.
OCCUPIED_PENALTY = 0.0
# Hour after which a carrying unit heads for the shed to deposit before day-end.
# CARRY_PASS_IN_FIELD -- a carrying unit with no job PASSES instead of walking to the shed.
# MEASURED (d6-17 per game, ours vs Boey's 60 replays): DROP 99 vs 32, MOVE 1,839 vs 1,319,
# PASS 86 vs 152. Idle turns are IDENTICAL (185 vs 184); the whole difference is that Boey's
# idle unit stands still and ours walks in and has to walk back out. The end-of-day clear
# (`_drop_inventories_to_shed`) already banks every carried item for free, so the mid-day
# trip only buys a same-day sale. Paired with `DROP_HOUR` (declared and never wired until
# now): after that hour the unit does deposit, so the bell still gets its produce.
CARRY_PASS_IN_FIELD = False
CARRY_PASS_IN_FIELD_P2 = None
CARRY_PASS_IN_FIELD_P3 = None
# PICKUP_WITH_PRODUCE -- the engine's PICKUP has no empty-handed rule; ours did, and it is
# the inbound half of the same shed loop. Allow a fetch while holding only PRODUCE.
# FEED_PICKUP_INFLIGHT -- cap the per-turn PICKUP WHEAT offer at what is still short once
# what other units already carry is counted. `herd_plan.jobs` sizes it from `_unfed_count`
# alone and is rebuilt every turn, so it re-offers the fetch on all 24 turns. MEASURED:
# WHEAT pickups 142.8/game vs Boey's 74.2, against ~11 feeds/day.
FEED_PICKUP_INFLIGHT = False
FEED_PICKUP_INFLIGHT_P2 = None
FEED_PICKUP_INFLIGHT_P3 = None
PICKUP_WITH_PRODUCE = False
PICKUP_WITH_PRODUCE_P2 = None
PICKUP_WITH_PRODUCE_P3 = None
DROP_HOUR = 20
# ---- job choice: walking is priced, not a tie-break --------------------------
# DSM works a *tile cluster*: he does the whole stack of ops a tile offers
# (HARVEST/FEED/CARE/COLLECT_FERTILIZER/DROP/PICKUP on one inner-ring animal tile)
# before stepping next door. Measured moves-per-act 0.76. Ordering jobs by
# (-priority, distance) instead lets a unit abandon three unfinished ops under its
# feet to chase the top-priority job across the farm: measured 2.65 moves/act, 61%
# of all unit-turns walking, and the first 4 hours of every day 71-93% pure
# travel. Pricing walking at MOVE_WEIGHT makes an op under our feet beat a
# higher-value op a few tiles away, which is the DSM behaviour.
MOVE_WEIGHT = 20.0
# Re-measured after the shed-ring reservation (A1) changed the farm shape. At the OLD
# shape 15 and 60 were both negative (-$2,709 / -$1,063); at the new shape 20 is a
# clear win: **+$4,375, 21/24, p=0.000** (24 paired games), and +$4,143, 12/12 in an
# independent screen. Cheaper walking means a unit will cross the farm for a
# higher-priority job instead of taking the nearest one.
# PHASE-2 DAG (what moved, and what it cost):
#   animals on board  10.0 -> 11.0   HARVEST ops  64 -> 70.5   planted tiles 70 -> 73
#   shed peak         16.0 -> 18.0   WATER ops   324 -> 318.5
#   plants died       16.5 -> 21.0   weeds        13 -> 17      <-- the trade
# The margin is positive because the extra harvest/coverage pays for the attrition:
# this lever reallocates the crew toward harvesting, not toward water coverage, so it
# does NOT reduce weeds. GROUP B's attrition metric is still open.
# ...but only for the first DIST_CAP tiles. Beyond that the walk cost is capped,
# so distance prices the *tile cluster* without ever letting local busywork (a
# weed DIG, a bonus water) starve a far high-value job. Uncapped W=30 was measured
# to produce a weed death-spiral: on one seed the crew kept digging locally while
# a survival water 8 tiles away was skipped, the farm died, weeds hit 58 and the
# day-21 liquidation ($6.7k) was lost.
# Walk-cost saturation distance. `_pick` keys on `dcost - priority` with
# `dcost = MOVE_WEIGHT * min(d, DIST_CAP)`, so this is the distance at which "how far
# is it" stops mattering and only priority decides.
#
# REVERTED TO 1 by explicit instruction: a MELON tile cannot be dropped. Melon is
# first_yield_day 10 / max_yield_day 12, a SINGLE harvest at ~$267/unit, 6 units/tile,
# and the whole block pays inside a 3-day window that no later play recovers. With the
# cover at 0 the 5th animal buys on d0 and takes the cash the d1 MELON top-up needs:
# MELON 9 -> 6 tiles, 54 -> 36 units, $9,798 -> $7,002 of melon revenue -- a permanent
# loss. The cover at 1 holds the 5th animal one day, which preserves the block. See
# `_script_seed_need` in herd_plan for why a FLAT reserve was the wrong instrument.
#
# MEASURED (24 paired games, `shadow_prices --perturb distcap1|DIST_CAP=1`):
#   dterm  +$5,576 median, **0/24 games worse**, p=0.000
#   dNAV_d5 -$2,568  (20/24 pairs have dNAV and dterm of OPPOSITE sign)
# i.e. a SMALLER distance cap plays the season better. The old value 2 made the
# scheduler over-local -- it hoarded units near their current tile while 40 % of all
# acts (WATER, 31,676 of 78,671) were followed by a walk. The `dNAV_d5` disagreement
# is the third independent instance of `state_value`'s `nav` being a gross mark rather
# than a value (see docs/DSM-vs-us(v0).md S2.9/S2.14); trust `dterm` here.
DIST_CAP = 1


# ---- hiring schedule (day -> target hands). DSM curve. -----------------------
# Hands for d10-25 (the midgame). `budget` also caps by GROUND
# (`owned // TILES_PER_HAND` = 100 // 4 = 25), so this schedule is the binding cap and
# 12 is not a ground limit -- it is a choice. Hiring is a PURCHASE with a computable
# return: each hand is 24 turns/day, of which ~30 % are productive, so an extra hand is
# ~86 extra acts over d6-17 against a fibonacci hire cost. The midgame is short ~47
# survival-waters out of 3,456 unit-turns, so throughput -- not priority -- is the
# binding constraint.
HANDS_MIDGAME = 12


def target_hands(day: int) -> int:
    # Opening crew, MEASURED from Boey's replays: 5 hands (max/day median) on d0 and
    # 5-6 through d5 -- he plants 20 tiles and waters 20 on d0 with 5. We ran 4 on d0
    # (24 unit-turns short, the exact size of the d0 sow gap) and 6 from d2 once the
    # duplicate HIRE was removed, so the opening schedule is flat at 5.
    if day >= 29:
        return 10
    if day >= 26:
        return 11
    if day >= 10:
        return HANDS_MIDGAME
    if day >= 9:
        return 10
    if day >= 6:
        return 8
    return 5


# ---- land schedule. Re-issue BUY_LAND every turn until filled. ---------------
LAND_TARGET_DAY = {"NE": 6, "SW": 9, "SE": 10}
# How many quadrants to buy in total (4 = the whole board = the old behaviour). W2
# geometry test: we own 100 tiles and plant ~53 in the midgame, Boey owns 75 and plants
# 55, and every extra unused tile is walking on each water op (moves/op 2.92 vs 1.17).
LAND_QUADRANT_MAX = 3
# LAND_CASH_RESERVE -- the feed reserve held back specifically from a LAND purchase.
# MEASURED 2026-09-29 (`tools/phases/boey_model.py`, 120 of his replays vs ours):
#   quadrants   ours d6/d8/d10 = 1/1/3      Boey = 1/2/3
#   empty tiles ours d10 = 25.5             Boey = 0 EVERY day
#   planted     ours d10 = 33.5             Boey = 53
#   money       ours d6 = $292              Boey = $99.5   (he is always spent)
# We hold `CASH_RESERVE=1500` against a $1,000 NE purchase, so NE waits for $2,500 while
# `LAND_TARGET_DAY["NE"] = 6`; the quadrant then lands together with SW around d9-d10 and
# 25 tiles sit bare for 4-6 days, which is what caps the wheat base and therefore the herd.
# This knob reserves against land ONLY, so the feed money is still protected on every other
# order. Do NOT set `CASH_RESERVE=0` (that is the closed, farm-starving experiment).
# `None` = fall back to `CASH_RESERVE` (the old behaviour).
LAND_CASH_RESERVE = None
# SHIPPED at the d10 state-clone step (2026-09-29). MEASURED on the checkpoint
# (`transplant --prefix ours --cut-day 10`, 12 eps): planted 43 -> 48, empty 19.5 -> 8,
# WHEAT 17 -> 22, within-1% 2/13 -> 3/13. COSTS -$7,586 median on the season (same 8-game
# screen as round 1) and does not move `target_check` (0/16). This is a deliberate
# state-parity-first choice per the 5-day checkpoint method; it is ONE param to revert.
LAND_CASH_RESERVE_P2 = 0
LAND_CASH_RESERVE_P3 = None
LAND_COST = {"NE": 1000, "SW": 2000, "SE": 4000}
# keep this many seeds in hand per active crop (re-bought as they are planted).
SEED_BUFFER = 6
# Cap that buffer by the tiles we could actually plant right now (plus this many
# for the plant-now margin). Seed inventory is cash that cannot buy land, and while
# the farm is tile-bound (empty tiles = 0 all through d6-d10) it buys nothing.
SEED_BUFFER_BY_FREE = True
SEED_BUFFER_MIN = 2
# Partial-fill the buffer when the full top-up is unaffordable. All-or-nothing was a
# real bug (a $600 strawberry top-up bought nothing on $300 of spendable cash), but it
# was measured inside a net-negative package; default off until isolated.
# Set 1 as part of the opening package (the Boey mix asks for 10 MELON + 4 STRAWBERRY,
# and an all-or-nothing buy can silently zero a crop for the whole script).
SEED_PARTIAL_FILL = False
# PLANT_CAP_BY_SEEDS -- cap the per-crop PLANT requests at the seeds actually held.
# The engine validates PLANT **collectively per crop**: if the turn's total requests for a
# crop exceed the seeds held, ALL of them become PASS. MEASURED 2026-09-29 (`boey_model`):
# our WHEAT PLANT commands are 51.5/game against 46.9 planted (**9 % wasted**) while the
# reference wastes 2.4 %, and the queue asks for a 15-22 tile wheat deficit while
# `crop_plan` holds only `SEED_BUFFER = 6` seeds per crop. This turns a wiped-out batch
# into a partial one. See docs/DSM-vs-us(v0).md S3.10.
PLANT_CAP_BY_SEEDS = False
PLANT_CAP_BY_SEEDS_P2 = None
PLANT_CAP_BY_SEEDS_P3 = None
# SEED_FILL_BUFFER -- size the seed ask to the crop's own deficit (capped by free tiles)
# instead of the flat `SEED_BUFFER`, and always allow a partial fill. MEASURED at the d10
# checkpoint (`transplant --prefix ours --cut-day 10`, 24 episodes): we hold 20 bare owned
# tiles and 43 planted against the reference's 1 and 54.5, with WHEAT 17 vs 28.
SEED_FILL_BUFFER = False
SEED_FILL_BUFFER_P2 = None
SEED_FILL_BUFFER_P3 = None
# land buys keep this much cash in reserve afterwards (never spend to zero pre-revenue).
CASH_RESERVE = 1500
# During the opening the bank is meant to be COMMITTED (DSM ends d0 at $6, Boey $30):
# holding $1,500 is what left `opening cash committed` at 0.81. Applies while
# day <= OPENING_HERD_UNTIL_DAY; set 0 in the opening package. Default = unchanged.
CASH_RESERVE_OPENING = 1500
# one hand per ~this many owned tiles (hands+ground lockstep).
TILES_PER_HAND = 4
# The engine hires ONE hand per HIRE order and caps the market list at
# MAX_ORDERS=10, so requesting a whole day's crew in one turn silently truncates
# everything after it (animals, feed, seeds). Order the list by priority and spread
# the hires; the day has 24 turns and the crew only has to be complete by the end.
# MEASURED: with the opening tape as the default, one turn's list is
# sells + trade + feed + seed + 3 animal orders + the hire block, and 5-at-once HIREs
# pushed the tape's bulk sells and the MELON/STRAWBERRY seeds past slot 10 -- the
# dropped orders are exactly the d2 revenue and the d1->d2 MELON top-up. One per turn.
# MARKET_HIRE_FIRST_HOURS -- put the hire block at the FRONT of the market list for the
# first N hours of the day. `budget.market_intents` already refuses a hand it cannot
# afford, so this can never overspend; it only stops `MAX_ORDERS=10` from truncating
# the crew rebuild.
#
# MEASURED (mean units by hour, d6-29, 16 games each): Boey reaches 11.5 units at hour
# 1 and holds it; we reach 12.1 only at hour 12 (1.0 / 4.3 / 7.0 / 7.8 / 8.3 at hours
# 0-4). Hires placed: Boey 7.7 then 2.5; us 3.3 then 2.7 then a trickle. The engine
# wipes `hands` every night, so that ramp is ~40 unit-turns lost EVERY day, ~960 a
# season -- the same order as the whole midgame gap. We are not cash-short: $18,542
# sits idle at hour 0 while we place 3.3 hires. The cause is the order list: sells and
# the land/seed blocks occupy slots ahead of the hires.
MARKET_HIRE_FIRST_HOURS = 0
MAX_HIRE_PER_TURN = 1
# stop planting after this hour: a crop planted late can't be watered the same
# day and dies that night (consecutive_unwatered 1 -> 2 = weed).
PLANT_CUTOFF_HOUR = 18


# ---- sell policy (the market layer) ------------------------------------------
# knife-edge goods: crash to $1 within ~50-100 units above I0 -> hard stop.
CEILING_GOODS = ("STRAWBERRY", "MILK", "WOOL")
CEILING = 100  # never sell a ceiling good when inventory >= I0 + CEILING
# Shed-drain lever: how much deeper into the above-base range a ceiling good may be
# sold. The sell path is the other half of the chaining change: CHAIN lifted harvests
# but pushed `shed_overflow_days` +1 and `discarded_units_total` +7.5 (96/96) because the
# extra produce could not leave the shed. 0 = today's behaviour; positive values sell
# further down the curve to convert stock into cash (watch the floor% / px tail).
SELL_CEILING_BOOST = 0
# melon's quadratic above-curve floors at ~158 net units: sell below that.
MELON_CEILING = 150
# endgame liquidation: from this day sell everything (ignore the scarcity hold).
LIQUIDATE_DAY = 27
# wheat is a scarcity asset: sell only when the market is short (below I0).
# R2 relaxes this to "at/above base" so the loop generates cash flow; R5 tightens
# it back to the DSM scarcity hold.
WHEAT_SELL_BELOW_I0 = True
WHEAT_SELL_MIN_PRICE = 25  # wheat base price; also refuse to sell below this
# Fertilizer is DUMPED: no shop buys it and the curve is linear/gentle (it only
# reaches $1 at I0+493), so surplus goes out the door for whatever it fetches. Keep
# only a small working stock for FERTILIZE.
#
# This was 25 -- a WAREHOUSE target, not a working stock -- so with a 3-5 animal
# opening herd we banked 25 units over 8+ days and sold none of it. Measured on the
# #1's own day-0..5 orders: he runs `SELL FERTILIZER` 3-5 units EVERY day from d1.
# That is his early cash engine, and it is what pays for bought feed and the NE
# quadrant before any crop revenue lands. We were sitting on it instead.
# Survival-watering priority (a plant that becomes a weed tonight is a TOTAL loss).
# It lives here so it is env-overridable: `job.py` reads it, and the value matters
# against P_HARVEST=100 / P_FEED=100 -- see the A/B note in docs/DSM-vs-us(v0).md S2.15.
# The `critical` flag already lets it ignore walk cost, but priority still decides
# against a SAME-TILE job, and against a nearer one.
# Feeding priority. This is the knob that decides whether a unit feeds the animal
# NEXT TO IT or crosses the farm for a plant that is about to become a weed.
#
# `_pick`'s key is `dcost - priority`, and a `critical` job gets `dcost = 0` at ANY
# distance. So survival-water (priority 90, critical) keys as `-90` everywhere, while
# a FEED one tile away keys as `30 - 100 = -70` -- the distant plant wins, every time.
# MEASURED consequence: FEED chains into another act only **7.0 %** of the time
# against the #1's **88.9 %**, and we do 78.7k acts to his 162.9k on the same crew.
# At 125 a feed at distance <=1 beats a distant survival-water (`30 - 125 = -95`),
# while a survival-water still wins at distance >=2 (`60 - 125 = -65`).
# Structure-build priority. A pending animal is a dead 20 % of the crew until it is
# placed: `P_PICKUP_ANIMAL` walks it out of the shed, finds no free structure, and
# DROPs it straight back. MEASURED with `tools/labour/unit_trace.py`: the farmer and
# hand 1 alternate PICKUP COW / DROP COW on the shed tile for the WHOLE of d0 --
# 2 of 5 units doing nothing -- because P_BUILD (45) lost to every routine chore.
# Housing for an animal we already own is therefore priced above routine watering.
# Structures that may be erected in one turn. Housing is what unlocks the herd's
# daily work, so a pending animal outranks a tile of crops -- but the tile is still
# finite, so this is a cap and not "build everything at once".
BUILD_PER_TURN = 3

# Care priority. CARE is free and it banks the production bonus, so it is pure
# margin -- MEASURED: the #1 runs 34 care ops over d0-d5 (p10 33, p90 36) against our
# 24, and it is the last phase-1 metric still reading BAD.
# MEASURED (24 paired games, `--perturb 'nomonocrop|BAND_MONOCROP=0'`):
#   dterm +$8,478 median for monocrop, 24/24 games better, p=0.000
# The structural move is SMALL (weeds 11->8, plants died 34->32) while the margin move
# is large -- a reminder that this metric set does not capture everything that scores.
# Keep each worker's band MONOCROPPED (see scheduler._band_crop). MEASURED: weeds
# 11 -> 8, plants died 34 -> 32, WATER ops 409 -> 421, idle 0.7 % -> 2.0 %. Price it
# with shadow_prices before believing it -- the structural move is small.
# Restrict field work (WATER/HARVEST/PLANT/DIG/FERTILIZE) to the worker's own layout
# band on the first `_pick` pass. The band is contiguous (snake order, ~8 tiles), so it
# should cut walking -- but it also FORCES a unit onto its own band's tile even when a
# nearer tile outside the band needs water, and watering is 50 % of all midgame moves at
# 2.55 moves/op against the #1's 1.22. Set False to assign purely by distance-priority
# with the `claimed` set preventing collisions.
# DEFAULT OFF -- measured structurally ADVERSE. With it on: weeds 8 -> 13,
# HARVEST ops 85 -> 77, plants died 32 -> 31, idle 1.95 % -> 0.34 %. The crew waters
# ripe tiles instead of harvesting others, which costs more harvests than the saved
# deaths are worth. Kept as a knob because the *reasoning* is sound (a missed harvest
# does become a weed) -- it just is not the binding constraint.
#
# [original note] Give a READY tile a survival-water fallback alongside its HARVEST job.
#
# MEASURED DEFECT: `crop_plan.jobs` is `if plant_ready: HARVEST elif needs_water: WATER`,
# so a ripe tile gets NO water job. If the crew does not harvest it that day,
# `consecutive_unwatered` reaches 2 and the engine turns it into a WEED -- the whole crop
# is lost, not merely delayed. `missed_harvest_eod` is a median of 69 per game, so this is
# a real population of losses, and HARVEST (100) still outranks the fallback (90) so the
# normal path is unchanged.
# DEFAULT OFF -- NEUTRAL, and the metric that motivated it was a WINDOW ARTEFACT.
# MEASURED: `dterm` +$230 over 24 pairs with 0/24 non-zero sign pairs -- i.e. noise.
# The "we sell 0 STRAWBERRY in d6-d17 vs his 64" figure is real but is a *timing* effect
# inside the window, not a permanent loss: the crop is sold later either way.
# [original] Harvest an ONGOING crop as soon as it has any yield, instead of
# only when `yield_units >= max_yield`.
#
# Why: the engine caps `yield_units` at `max_held`, so a tile parked at the cap destroys
# every production day that lands on it. MEASURED: we sell **0 STRAWBERRY units in d6-d17**
# (shed STRAWBERRY is 0 on every day of the window while the market sits at I0-150, i.e.
# sellable), against the #1's **64 units for $12,472** -- his single largest midgame line.
# Fertilize ONLY ongoing crops (STRAWBERRY / TOMATO), where the engine DOUBLES the fruit
# on a watered production day, and sell the fertilizer rather than spending it on one-shot
# crops (wheat/melon/carrot) where it buys a single extra unit.
#
# MEASURED: `FERTILIZE` is our most movement-expensive act at **4.35 moves/op** (the #1's
# is 0.10), we spend 44 fertilizer on it over d6-d17, and selling that fertilizer instead
# (`FERTILIZE_FROM_DAY=99`) is **+$1,954** on the season. This flag is the targeted version:
# keep the doubling, drop the rest.
FERTILIZE_ONGOING_ONLY = False
# The complement: fertilize ONLY one-shot crops. MEASURED as the best of the three
# (`dterm` vs the all-crops baseline): one-shot-only **+$2,730**, never +$1,954,
# ongoing-only -$2,730. That ordering still holds, and it is why the shipped phase-2
# policy turns ON one-shot only. RE-MEASURED 2026-09-29 with the original delivery:
# **+$4,786 mean / +$8,020 median, 5/8** on 8 pairs. The delivery experiments (shed
# pickup off, `P_FERTILIZE_P2=88`, `FERTILIZE_PRE_WINDOW`) all measured NEGATIVE and are
# not shipped. ONGOING (strawberry/tomato) is the second lever and is NOT shipped yet --
# the reference fertilizes strawberry 470 times in d6-17, so re-test it after the
# one-shot policy is confirmed on 96 games.
FERTILIZE_ONESHOT_ONLY = True
# BUY fertilizer, for the ONGOING crops only. Strawberry/Tomato gain +1 unit per fertilized
# production day (the engine gives `+2` instead of `+1`), and a strawberry or tomato unit is
# ~$120-141 against ~$95 of bought fertilizer -- the only route to the fertilizer doubling
# that does NOT require the herd (whose expansion is priced -$17,193). Wheat at ~$25/unit
# can never pay for it, hence ongoing-only.
BUY_FERTILIZER = False
FERTILIZER_BUY_QTY = 1


ONGOING_HARVEST_ANY = False
# Minimum `yield_units` before harvesting an ONGOING crop (STRAWBERRY / TOMATO). 0 =
# the old `y >= max_yield`. MEASURED: the #1 harvests strawberry at **age 12 for 2.0
# units/event** (139 events/season); `max_yield` (4) gives us age 16, 20 events, 0.16
# units/tile-day; `any` gives age 12 but only 1.0 unit/event. 2 matches him.
ONGOING_HARVEST_MIN = 2  # MEASURED: dterm +$1,691, 22/24, p=0.000

WATER_READY_FALLBACK = False

# DEFAULT OFF -- the UNCONDITIONAL version is HARMFUL. It fires for ANY same-tile job,
# including low-priority ones (DIG, WATER_BONUS), so units spend their turn on whatever is
# under them instead of the best job available. MEASURED with a `_pick` wrapper: total
# assignments 6,629 -> 3,769, WATER mean distance 2.10 -> 3.57, HARVEST 1.99 -> 4.76.
# The same-tile rate is a real defect (31 % overall, 22 % for CARE) and the ORDERING
# diagnosis stands, but the fix must be GUARDED -- take the same-tile job only when it
# is at least as good as the best job elsewhere, not unconditionally.
#
# [original] Let a unit standing ON a tile with pending work take that job BEFORE any other unit
# can claim it from a distance.
#
# MEASURED DEFECT: `_pick` runs per unit in index order, so an arbitrary unit can claim a
# job another unit is standing on, and the unit on the tile never gets to choose. The
# same-tile (d=0) assignment rate is only **31 % overall, 22 % for CARE** (mean distance
# 2.59), which is where the chaining numbers come from -- the #1 chains FEED at 0.07
# moves/op against our 2.00. This is a pure ordering fix and does not change any priority.
#
# ON, at the default `SAME_TILE_MIN_PRIORITY=70` -- and the threshold is the whole point.
# The first arm used `SAME_TILE_MIN_PRIORITY=0`, which let a unit standing on ANY local
# job chain instead of walking to a PLANT: PLANT 27 -> 28, MELON 9 -> 7, empty 3.5 -> 5,
# idle 0.78 -> 11.0 (docs/v0/sc-p1-chain.txt). At >=70 the chain is limited to the urgent
# local ops and the trade disappears: PLANT 27 -> 30, empty -> 3.0, cash 0.97 -> 1.00.
# Season A/B: margin +$5,061, revenue +$8,747, `plants_died` -5.5 (0/16 worse).
SAME_TILE_FIRST = True
# SAME_TILE_ANIMAL_CHAIN -- FINISH THE ANIMAL VISIT. An animal tile offers up to three
# ops (FEED / CARE / COLLECT_FERTILIZER) and all three are on the SAME tile, so the trip
# is only worth making if the unit clears the stack before it leaves. MEASURED
# (tools/labour/op_patterns.py, d6-17, 4 games vs 4 Boey replays): the #1 chains a FEED
# into another act **65.9 %** of the time; we chain 21.3 %, and `visit_trace` records
# `FEED -> CARE` split at **100 %** -- two round trips per animal per day instead of one.
#
# Why the generic threshold misses it: `SAME_TILE_MIN_PRIORITY=70` exists so local
# busywork cannot starve a survival water. CARE (70) clears it but COLLECT_FERTILIZER
# (54) does not, so the unit cares and then walks away rather than collecting the
# fertilizer it is standing on. This flag exempts exactly the three animal-tile ops from
# both the threshold and the rescuer hold-back -- cropping ops (DIG, WATER_BONUS, PLANT,
# FERTILIZE) keep the old gate, so the "local busywork starves a dying tile" failure
# measured for `SAME_TILE_MIN_PRIORITY=0` cannot come back through here.
SAME_TILE_ANIMAL_CHAIN = False
# While a critical job (tonight's weed / tonight's escape) is pending, the K units
# NEAREST to each such tile are held back from chaining a non-critical local op, so a
# dying tile still gets rescued. K=1 keeps almost all chaining; the first (too blunt)
# version blocked every unit whenever any critical existed and removed the entire
# CHAIN gain. Set SAME_TILE_PROTECT_CRITICAL=False to reproduce the unguarded arm.
SAME_TILE_PROTECT_CRITICAL = True
CRITICAL_RESCUE_K = 1

# ---------------------------------------------------------------------------
# BINDING-ROOT CONTROLLER (src/roots.py) -- state-derived priority multipliers.
#
# Fixed priorities cannot express "the farm is behind on water THIS turn but ahead on
# planting"; the DAG names the roots but the kernel never asked which one is binding.
# `roots.binding(state)` computes an urgency in [0,1] per op class from the observation
# (empty/owned, unwatered-in-window/planted, unfed/animals, needs-structure/animals,
# weeds/owned, ready/units, shed/100) and `roots.apply` scales each job:
#
#     priority_eff = priority * (1 + URGENCY_SLOPE * weight * urgency)
#
# so a class that is behind lifts, without changing the plan shape. The base priorities
# and every hardcoded constant stay where they are -- this only re-orders across classes.
# 0.0 disables it entirely (default = today's behaviour) so the two can be A/B'd.
URGENCY_SLOPE = 0.0
# Per-op weight on the urgency (1.0 = neutral). Set in code, not via SCRATCH_PARAMS.
URGENCY_WEIGHTS: dict = {}

# ---------------------------------------------------------------------------
# ON_TILE_BONUS -- FINISH THE VISIT. This is the tile-visit fix.
#
# `_pick` scores a job `dcost - priority`, where `dcost = MOVE_WEIGHT * min(d, DIST_CAP)`.
# With MOVE_WEIGHT=30 and DIST_CAP=1 every job at d>=1 costs the SAME 30, so a job on the
# tile the unit ALREADY OCCUPIES (d=0, dcost=0) still loses to a distant job more than 30
# priority points higher. Walking the actual bands:
#
#   CARE (70)          loses to a distant PICKUP_WHEAT (101)    -> splits FEED -> CARE
#   COLLECT_FERT (55)  loses to a distant PLANT (85)            -> splits CARE -> COLLECT
#   WATER_BONUS (50)   loses to a distant PLANT/HARVEST (85/100)-> splits the water sweep
#
# MEASURED with tools/labour/visit_trace.py (his 123 episodes vs our runs, phase 2):
#   ops per stop            DSM 1.90  |  US 1.31
#   stops with >=2 ops      DSM  54%  |  US  25%
#   stops with >=4 ops      DSM  10%  |  US   0%
#   split `PLANT -> WATER`  DSM  4%   |  US  54%
#   split `FEED  -> CARE`   DSM  5%   |  US 100%
#
# A unit is already standing on the tile, so finishing what is underfoot costs no movement
# at all, while walking away and coming back costs two trips. This makes the on-tile job
# win by construction rather than by priority arithmetic, and it only sharpens the SAME
# score the kernel already computes (no new rule, no separate pass). 0 = off.
#
# Sized so an on-tile WATER_BONUS (50) beats a distant HARVEST (100): bonus must exceed 50.
ON_TILE_BONUS = 0
# DEFAULT OFF -- reordering was a measured NO-OP (same-tile 31 % -> 31 %, WATER 28 % -> 28 %).
# The 31 % is a property of the STATE (after watering a tile it needs no more water until
# tomorrow), not an assignment failure.
#
# [original note] Order the per-unit assignment loop so a unit standing ON a tile with work gets to
# choose BEFORE a unit further away can claim it.
#
# Why: a `critical` job (survival WATER, at-risk FEED) gets `dcost = 0` at ANY distance,
# so its key is `-priority` for every unit and only the `d` tie-break separates them --
# but `_pick` runs per unit in INDEX order, so an earlier unit 5 tiles away takes the job
# before the unit standing on it ever chooses. MEASURED: same-tile (d=0) assignment rate
# 31 % overall and 22 % for CARE, WATER at 2.92 moves/op, and 25 wheat tiles dying per
# game against the #1's 1. Unlike `SAME_TILE_FIRST` this does NOT reserve anything -- it
# only reorders the units, so a unit with no local work is unaffected.
SAME_TILE_ORDER = False
# PLANT_BLOCK -- sow a band in ONE day, not one tile per day. 1 = off.
# MEASURED (consecutive watered tiles, d6-17, 8 games vs 40 Boey replays): ours are **1.72
# tiles apart, Boey's 1.07**, and WATER is 47.9 % of all our moves at 2.62 moves/op. A band
# filled one tile per turn carries six different water windows, so the day's thirsty tiles
# are never neighbours. The first attempt (round 1) over-planted the crop at the head of the
# queue and emptied WHEAT; this version consumes the per-crop deficit instead.
# WATER_OWNER_ONLY -- a non-critical water is visible only to the worker whose band
# contains it; critical (survival) waters keep the global fallback.
# MEASURED target: consecutive watered tiles 1.72 (ours) vs 1.07 (Boey); WATER is 47.9 % of
# all our moves at 2.62 moves/op. Requires USE_SLICES (needs a band to be local to).
# LAYOUT_BY_CROP_AGE -- order the per-worker bands by (crop, planted_day) instead of by
# row, so a band's crops share a water calendar. Targets the measured cause of the water
# scatter: a band of 5.13 tiles carries 2-3 distinct ages and only 2.35 thirsty tiles.
LAYOUT_BY_CROP_AGE = False
LAYOUT_BY_CROP_AGE_P2 = None
LAYOUT_BY_CROP_AGE_P3 = None
WATER_OWNER_ONLY = False
WATER_OWNER_ONLY_P2 = None
WATER_OWNER_ONLY_P3 = None
PLANT_BLOCK = 1
PLANT_BLOCK_P2 = None
PLANT_BLOCK_P3 = None
# Stop planting when the crew already has a survival-water backlog.
#
# THE ATTRITION FIX. We plant ~29 wheat tiles a day whose survival rule is "water every
# other day", against a crew that delivers 5.4 waters per tile where 6 is the floor -- so
# tiles are created faster than they can be kept alive and 25 wheat tiles die per game
# against the #1's 1. MEASURED with tools/labour/wheat_flow.py. Every one of those tiles
# was PAID FOR (seed bought) and returns nothing.
#
# `PLANT_WATER_CAP_DIVISOR` = N means: allow at most `n_units - pending_survival_waters / N`
# plant jobs this turn. 0 disables the gate.
PLANT_WATER_CAP_DIVISOR = 0
# EXACT PER-TURN ASSIGNMENT: replace `_pick`'s per-unit greedy (units in index order) with
# a global greedy over the (unit, job) cost edges, cheapest edge first.
#
# Why: a `critical` job pays NO walk cost at any distance (`dcost = 0`), so a survival-water
# keys identically for the unit standing on it and for a unit five tiles away; the old loop
# let whichever unit came first in INDEX order take it. With ~38 survival waters and 12
# units that produces long criss-crossing walks -- WATER costs 2.92 moves/op against the
# #1's 1.22 and is 64 % of all midgame movement, 70 % of unit-turns are moves, and 25 wheat
# tiles die per game against his 1. Pairing each job with its cheapest unit is the direct
# fix. `SLICE_PENALTY` replaces `_pick`'s two-pass band restriction with a finite penalty,
# so band-local work is still strongly preferred but no longer absolute.
EXACT_ASSIGN = False
# PLANT GLOBAL: do not bind a PLANT job to the worker's own slice. Measured defect in the
# opening -- with ~13 crop tiles and 6 bands, some workers have no empty tile in their
# band and plant nothing while the script still has a deficit. Global = nearest empty
# on the farm, still assigned one-per-worker.
PLANT_GLOBAL = False
# OPENING TAPE (src/opening.py): one owner for the opening market commitment. Buys the
# full seed basket right after the sells, ahead of hires/herd/feed, so a closing crop
# window (MELON ends d2) cannot be starved by the MAX_ORDERS=10 cap.
# ON since the d0-d5 structural audit moved the phase-1 roots: cash committed 0.81 -> 0.97,
# MELON 6 -> 10, STRAWBERRY 6 -> 4, idle 26.3 % -> 18.9 %, d0-d5 sell revenue ~$3.0k/game
# (median over 16 games, `revenue_<p>` summed over d0-d5 in diag-replays/sc-tape21).
# Season-margin confirmation on the 96-game field is still PENDING (see
# docs/DSM-vs-us(v0).md §2); it is not a claim, it is the next gate.
OPENING_TAPE = True
# The opening herd's daily loop (feed/care/collect/pickup) outranks discretionary field
# work while the tape runs, so the revenue engine actually runs.
OPENING_HERD_PRIORITY_BONUS = 40
# Units per opening SELL order (engine caps each order's qty only by stock; the default
# TRICKLE=6 throttled the opening cash engine). MEASURED, and it was a DEAD KNOB until
# now: `opening.market_intents` sells with `params.TRICKLE` (6), so the opening hoarded
# cash ($693 at d4) while the herd stalled. Wired into the sell line.
OPENING_SELL_CHUNK = 30
# Opening trade leg: buy wheat below base (market inventory above I0) with spare cash.
OPENING_TRADE_CASH_FLOOR = 700
OPENING_TRADE_CHUNK = 12
# THE TILE BUDGET, CLOSED. Boey's d0-d5 medians (40 replays, seat by name) fill all 25
# tiles EVERY day: crops(day) + herd(day) = 25. The old tape planned only 20 (12 crops +
# an 8-tile static ring) and built 4 structures, leaving 10 owned tiles empty on d0.
# `OPENING_TAPER_BOEY` selects the measured per-day crop table and a ring reservation
# that grows with the herd; OFF reproduces the old 12-crop/8-ring script for A/B.
OPENING_TAPER_BOEY = True
# The herd table: 3 COW + 2 SHEEP on d0 (no GOOSE -- coops arrive with the d2 goose),
# reaching 4 COW + 3 SHEEP + 2 GOOSE by d4. OFF reproduces the old 4/2/2 ratio ramp that
# topped out at 8 and bought cheapest-first (GOOSE first), which reached 5.
OPENING_HERD_BOEY = True
# Days of look-ahead when buying seed: the d1->d2 MELON top-up (7 -> 10) must be bought
# before MELON's window closes at d2, and the ask is derived from CROP_BY_DAY rather than
# a static basket so it cannot crowd the animal budget on d0.
OPENING_SEED_PREBUY_DAYS = 1
# The tape emits its own HIRE, and `budget.market_intents` hires to the SAME formula --
# two owners against one target produced 7 hands where Boey runs 5, which is exactly the
# idle share. OFF: budget is the single owner of hiring.
OPENING_HIRE_FROM_TAPE = False
# The tape's sell block (surplus WHEAT above a 2-day feed reserve, FERTILIZER, EGG) and
# `sell_policy.market_intents` BOTH emit opening sells. Collapsing them to one owner
# looked right but MEASURED SLIGHTLY WORSE: margin 0 in 12/16 pairs and -$1.1k mean
# over the 4 decided pairs, because sell_policy's per-item sells add liquidity the tape's
# single chunk does not. Kept as a knob; OFF ships.
OPENING_OWNS_SELLS = False
# Days of the herd's feed to hold back before selling surplus WHEAT. 2 is the measured
# balance (3 cost 8 pp of idle); 1 sells one more day's cover per turn, which is the
# difference between funding the last SHEEP ($500) and not: on d3 we hold 48 wheat and
# still end the opening ~$380 short of the 9-animal target.
OPENING_WHEAT_KEEP_DAYS = 2
# ---- the wheat carry (src/trade.py) -----------------------------------------
# Boey's opening recycles the bank through wheat ~4x and nets +$2,438 over d0-d5
# against our +$1,753; that $685 is exactly the extra animal spend ($4,000 vs $3,200)
# that buys his 9th-10th animal. The shared stock sits in a ~25-unit band around I0,
# which the wheat curve prices at $28-$30, so the edge is ~$2/unit cycled many times.
# Thresholds are PRICE-based so the leg cannot be inert the way the old
# `inventory > I0 + 50` gate was.
TRADE_ENABLED = True
TRADE_BUY_MARGIN = 4.0      # buy at or below base + this ($29); measured best
TRADE_SELL_MARGIN = 4.0     # sell at or above base + this ($29); measured best
TRADE_CHUNK = 25            # units per order (10/50 measure identical: not the binding cap)
TRADE_FEED_RESERVE = 4      # extra units of feed held back beyond the unfed count (8 kills the carry)
TRADE_CASH_FLOOR = 150.0    # never let the carry spend the opening below this
# d0 is the herd's and the seed basket's: the carry buys nothing until it is over.
# Measured -- a carry allowed on d0 spent the bank at step 0, so the step-1 animal order
# shrank and `animals` fell 8 -> 7 with GOOSE 2 -> 0.5, even though the buy is emitted
# after the animals in the same list (the cash it took was needed on the NEXT turn).
TRADE_FROM_DAY = 1
# Days of the MIDGAME herd's feed to reserve before the carry may buy.
TRADE_MIDGAME_FEED_DAYS = 3
# Run the carry d6-29 as well as d0-d5. MEASURED over the full season (`phase_map
# --days 0-29`, 8 games vs 60 Boey replays) ON vs OFF:
#   trade net   $64,970 vs $61,980   (+$2,990)   plants died 61 vs 64   weeds 56.5 vs 60
#   animals      12.0  vs  13.5      (-1.5)      <- the carry outbids herd EXPANSION
# Midgame herd expansion is itself measured positive (`HERD_BUY_UNTIL=12` +$3,013,
# 23/24), so the carry's net gain does not clearly pay for the herd it costs. The layer
# is built and callable for d6-29; it ships OFF until that trade-off is settled.
TRADE_MIDGAME = False
# Front-load the herd: from this day, if the day's animal target is unmet and
# unaffordable, LIQUIDATE the carry's wheat position to cash (down to the unfed count,
# at any price above base). The sell sits before the animal order, so the engine funds
# the herd from it the same turn. MEASURED: liquidating from d0 raises gross
# 5,023 -> 5,654 but costs net 0.97x -> 0.78x and buys no animal (our shed holds ~0
# wheat at d4 -- the herd eats it as it arrives), so it ships OFF.
OPENING_HERD_LIQUIDATE_DAY = 4
# Buffer animals in _buy_herd's feed cover. The cover is `(herd + buffer) * feed_days`
# units of cash held back so a new mouth can be fed; at d4-d5 that $240-$300 is what
# stands between $400 of liquid cash and the 9th animal.
OPENING_HERD_COVER_BUFFER = 0
# CLOSING-WINDOW PRIORITY. A crop whose planting window shuts soon (MELON ends d2) must
# have its seed bought and its tile planted before discretionary spend, or the crop is
# lost for the season -- the market list is ordered sells -> hires -> herd -> seeds and
# capped at MAX_ORDERS=10, so the seed ask is the first thing dropped. Enabled, the
# seed for a crop closing within WINDOW_URGENT_DAYS is moved up to just after the sells.
WINDOW_SEED_FIRST = False
WINDOW_URGENT_DAYS = 2
# A `critical` job (survival WATER, at-risk FEED) pays NO walk cost at any distance, so its
# key is `-priority` for every unit and only the `d` tie-break separates them -- inside one
# unit's choice. ACROSS units the per-unit loop order decides, so a unit five tiles away can
# take a survival-water that the unit standing on it should have. The exemption exists so
# "a local low-value job can never starve a tile about to die", but WATER_SURVIVAL (90)
# already outranks every routine chore except HARVEST (100) and PICKUP_WHEAT (101).
# MEASURED (24 paired games, `--perturb 'crit05|CRITICAL_FREE_WALK_FRAC=0.5'`):
#   dterm +$2,582 median, 24/24 games better, p=0.000
# and better on every phase-2 metric: WATER ops 445 -> 460, plants died 27 -> 26,
# weeds 12 -> 11, idle share 3.90 % -> 1.53 %, HARVEST 54 -> 55.
# 1.0 (pay in full) is WORSE than 0.0: plants died 38, idle 5.32 -- so the exemption is
# doing real work and only the *degree* of it was wrong.
# `CRITICAL_FREE_WALK_FRAC` scales how much of the walk cost a critical job still pays:
# 0.0 = the current exemption, 1.0 = pay in full like any other job.
CRITICAL_FREE_WALK_FRAC = 0.5
# Treat a ripe crop (HARVEST) as an IRREVERSIBLE loss in waiting, like survival water.
#
# `_decay_plants` strips **1 unit every 2 hours** once `step >= max_lifespan_step` (day
# `planted_day + max_yield_day + 1`), and `yield_units <= 0` turns the tile into a WEED --
# the crop is lost. So an un-harvested ripe tile is bleeding value continuously. Yet
# HARVEST is not `critical`, while survival water now pays only HALF a walk
# (`CRITICAL_FREE_WALK_FRAC`), so a survival water at any distance beats a ripe crop
# underfoot. MEASURED: `PASS-on-READY` 199 per game against the #1's 44, and `ready_idle`
# prices the standing crop at $166k a game against his $8.4k.
HARVEST_CRITICAL = False
# OWNER FIRST REFUSAL: never let a unit claim a job on a tile that ANOTHER unit is
# standing on. `_pick` runs per unit in index order, so a unit five tiles away can take
# the job under someone else's feet before that unit gets to choose -- which is why
# `PASS-on-READY` is 199/game against the #1's 44 even though a same-tile job always wins
# on `d`. This is the tile-level form of "the owner of a band gets first refusal"; it
# reserves nothing, it only defers.
OWNER_FIRST = False


# ONE-SHOT harvest timing (WHEAT / CARROT / MELON).
#
# THE BUG: for non-ongoing crops `yield_units` is accumulated by the WATER op, not daily --
# `yield_units += 2 if fertilized else 1` on each water at ages `(max_yield_day+1)//2 ..
# max_yield_day` (wheat: 2..4), capped at `max_yield`. So UNFERTILISED wheat peaks at
# **y = 3**, while `state.plant_ready` demanded `y >= _ONE_SHOT_PEAK["WHEAT"] = 4`. That
# condition can NEVER be satisfied without fertilizer, so wheat was harvested only by the
# `age > max_yield_day` fallback -- i.e. at age 5, one day AFTER `_decay_plants` starts
# stripping 1 unit every 2 HOURS.
#
# MEASURED consequence: wheat yield per tile-day 0.50 against the #1's 1.30, producing 307
# units on 587 tile-days against his 665 on 492 -- we farm MORE wheat tile-days and produce
# half as much. With this on, a one-shot crop is ready as soon as it has any yield and has
# reached `max_yield_day` (its peak, the day before decay).
ONESHOT_HARVEST_AT_PEAK = True

# HARVEST AGE OVERRIDE (days since planting), per one-shot crop. 0 = keep the
# `age >= max_yield_day` rule above. The peak-day rule is still a DAY too late for the
# two crops whose yield is already maximal when the last bonus-window water lands.
# MEASURED (`tools/labour/crop_cycle.py`, d6-17, 8 of our games vs 40 Boey replays):
#   WHEAT ours age 4.0, yield 2.93, 0.59 units/tile-day
#         Boey age 3.0, yield 4.41, 1.10 -- he banks the age-3 water and replants.
#   MELON ours age 12.0, 0.41 units/tile-day; Boey age 10.0, 0.54. Melon's water window
#         is ages 6-12 and it is already at its cap by age 10, so the two extra days
#         buy nothing.
#
# MEASURED NEGATIVE 2026-09-29, SO SHIPPED OFF (0). At `WHEAT=3;MELON=10` the agronomy
# works exactly as intended -- wheat HARVEST ops **253 -> 456**, harvest age 4.0 -> 3.0,
# missed window 1.07 -> 0.14, melon 12 -> 10, and `missed_harvest_eod` -17 (0/8 worse).
# And it LOSES: **-$2,361 mean / -$9,526 median margin, 3/8** over 8 paired games, with
# `sell_revenue_total` **-$10,984** and `unwatered_eod` +31 (7/8 worse). Doubling the
# wheat turnover converts low-value wheat tile-days (base $25) with crew turns that were
# earning STRAWBERRY/MILK/WOOL ($120-200) -- the crew is the constraint, not wheat yield.
# `state.plant_ready` is guarded on `watered_today`: without that guard the harvest fires
# before the day's window water and the tile turns over on ONE water (measured yield
# 4.03 -> 2.53, water/cycle 1.93 -> 1.00).
HARVEST_AGE_WHEAT = 0
HARVEST_AGE_MELON = 10
# ^ SHIPPED at the d10 state-clone step. The reference's melon harvest age is 10 (ours was
# 12); MEASURED on the checkpoint (`transplant --prefix ours --cut-day 10`, 12 eps):
# MELON 9 -> 5 vs his 5 (**0 %**), shed total -39.7 % -> -6.8 %, WHEAT -15.4 % -> -9.6 %,
# STRAWBERRY -15.8 % -> -10.5 %. The reference's own money jumps **+$9,570 on day 10** --
# that IS the melon harvest -- and we were holding 9 tiles through it.
# COST: -$5,299 median on the season (floor_sales +25: the block harvest sells into a glut;
# plants_died +6: the early harvest competes with watering). State-first trade, one param.


SLICE_PENALTY = 1000



# Priority floor for the same-tile reservation (see scheduler's pre-pass). 0 = reserve
# unconditionally (MEASURED HARMFUL: assignments 6,629 -> 3,769). The guard makes the
# reservation fire only for jobs at least this urgent, so a unit does not take a DIG or a
# bonus-water under its feet instead of the best job available. Priority bands: HARVEST 100,
# PICKUP_WHEAT 101, FEED 100, WATER_SURVIVAL 90, PLANT 85, CARE 70, COLLECT_FERT 55,
# FERTILIZE 54 (now disabled), WATER_BONUS 50, BUILD 45, DIG 20.
SAME_TILE_MIN_PRIORITY = 70  # inert while SAME_TILE_FIRST is False

# SAME_TILE_CROP_CHAIN / COMPLETE_TILE -- the crew-turn conversion fix.
# MEASURED 2026-09-29 (`tools/labour/stack_trace.py` + `hop_regret.py`, d6-17, 8 games vs
# Boey's replays): the two arms have the SAME unit-turns (3,077 vs 3,044) and our crew
# converts 0.34 of them to acts against his 0.53, because we do not finish the tile.
# `stack_trace` names the pairs split across visits -- `WATER -> FERTILIZE` 175 times --
# and `hop_regret` prices the total: 30 % of our walking is avoidable-by-nearest, 78 % of
# it in WATER + HARVEST.
#
# The gate is HERE: the same-tile pre-pass in `scheduler.plan` accepts a job underfoot only
# at `>= SAME_TILE_MIN_PRIORITY` (70) unless the ANIMAL chain exemption fires. `P_FERTILIZE`
# is 54, so a unit that just watered a tile walks off instead of fertilizing it -- MEASURED
# `FERTILIZE` chained 3.1 % vs Boey's 93.3 %, at 3.00 vs 0.02 moves/op.
#
#   SAME_TILE_CROP_CHAIN -- add FERTILIZE to the underfoot exemption (crop companion of a
#       water/harvest on the same tile). Phase-2 gated, like the animal chain.
#   COMPLETE_TILE -- accept ANY job underfoot the unit is eligible for, except explicit
#       busywork (DIG), regardless of priority. The narrow rescuer guard still holds the
#       unit back when it is the nearest hand to a tile about to die.
#
# MEASURED NEGATIVE 2026-09-29 (8 paired games each vs the shipped tree), so BOTH SHIP OFF:
#   crop-chain -$6,836 mean, COMPLETE_TILE -$8,028, both -$7,388, both + min-priority 0
#   -$8,213. The mechanism barely moved: moves/act 1.81 -> 1.70/1.62 and FERTILIZE chained
#   3.1 % -> 3.4 %. The reason is that FERTILIZE chaining is NOT gated by priority -- a unit
#   can only fertilize while CARRYING fertilizer, and it mostly is not carrying it at the
#   moment it stands on an unfetrilized in-window tile. `USE_SLICES_P2=0` was also measured
#   and is much WORSE (moves/act 2.35), so band locality is load-bearing. Leave these off;
#   the next lever is structural or a global assignment (see docs/DSM-vs-us(v0).md S3.5).
SAME_TILE_CROP_CHAIN = False
SAME_TILE_CROP_CHAIN_P2 = None
SAME_TILE_CROP_CHAIN_P3 = None
COMPLETE_TILE = False
COMPLETE_TILE_P2 = None
COMPLETE_TILE_P3 = None



USE_SLICES = True

# BAND_LOSS_TOL -- how many tiles farther an in-band job may be before a nearer
# out-of-band job of the SAME priority takes it. `None`/0 = off (hard band wall).
# MEASURED 2026-09-29 (`tools/labour/hop_regret.py --exclude-claimed`, d6-17, 8 games):
# 29.5 % of all walking is avoidable-by-nearest even after removing tiles another unit
# serves that turn -- WATER 1.64 tiles of regret per op, FERTILIZE 1.68, HARVEST 1.52.
# `scheduler._pick` pass 1 returns the best BAND-LOCAL job before it ever looks outside
# the band, so a unit passes a nearer thirsty tile that nobody is serving. Dropping the
# band entirely (`USE_SLICES_P2=0`) is measured WORSE (moves/act 1.81 -> 2.35), because
# priority then decides across the whole farm and distance is capped at DIST_CAP=1.
# This keeps the band a preference and lets nearness break it.
# CARRY_BAND_LOCAL -- the only_delivery `_pick` is called WITHOUT `prefer`, so a unit
# carrying fertilizer/feed/fruit re-picks GLOBALLY and walks out of its band to deliver.
# MEASURED on the transplant (d11-17, 4 games, Boey's own farm): COLLECT_FERTILIZER costs
# us **2.35 moves/op against his 0.78** (32 % of all our moves) and FERTILIZE **2.40 vs
# 0.03**. Same layout, same ops (154 vs 156 collects) -- so it is the ASSIGNMENT, not the
# geometry. This makes the delivery pass band-local with the usual global fallback.
CARRY_BAND_LOCAL = False
CARRY_BAND_LOCAL_P2 = None
CARRY_BAND_LOCAL_P3 = None
BAND_LOSS_TOL = None
BAND_LOSS_TOL_P2 = None
BAND_LOSS_TOL_P3 = None

# BAND_CRITICAL_BYPASS -- let a `critical` job (tonight's weed / tonight's escape) be# seen by a unit whose band does not contain it.
#
# THE BAND WALL WAS EATING THE RESCUES. `_pick` pass 1 skips every out-of-band job with
# `if restrict and not in_band and tol is None: continue` -- and that test runs BEFORE the
# `j.critical` test that zeroes the walk cost. So the promise in `job.py` ("the assignment
# kernel lets a critical job beat any walk cost, so a local low-value job can never starve
# a tile that is about to die") held only WITHIN a band: a survival WATER one tile away,
# out of band, lost to an in-band DIG (20) eight tiles away.
#
# MEASURED (`/tmp/pickwhy2`, d12 only, one transplant episode, every `_pick` call logged):
#   free (non-carrying) calls                              60
#   calls with an ELIGIBLE WATER candidate                 60   (100 %)
#   ... that actually chose WATER                          44
#   the other 16 chose BUILD_COOP 95 @ d=11, HARVEST 100, PICKUP 101, PLANT 85
# and the water candidates in those 16 were ALL critical survival jobs at d=1-5.
# Consequence on the transplant (d11-29, 4 games, Boey's own farm):
#   WATER **279 vs his 784**, `plants_died` **50 vs 9**, MOVE 3,135 vs 2,164,
#   final money $33-56k against his $85-145k with the SAME farm at d10.
# The farm at d12 has 42 unwatered tiles, all of them inside some band, and a stock of
# ~26 water jobs every turn that the crew simply walks past.
# ON: critical jobs ignore the band wall in pass 1 (they still pay the distance price
# unless `critical`, which zeroes it -- that is the pre-existing rule).
BAND_CRITICAL_BYPASS = False
BAND_CRITICAL_BYPASS_P2 = None
BAND_CRITICAL_BYPASS_P3 = None

# CARRY_DELIVERY_MARGIN -- soften `only_delivery` from a WALL into a PREFERENCE.
#
# THE WALL THAT STARVES THE FARM. In `scheduler.plan` a unit carrying a deliverable
# (WHEAT / FERTILIZER / an animal) is offered ONLY `_DELIVER_OPS` (FEED / PLACE /
# FERTILIZE) in step 1, and step 1 returns as soon as ANY such job exists -- general work
# is not looked at until step 3, which is therefore almost never reached.
# MEASURED (`/tmp/pickwhy2`, d12, one transplant episode, every `_pick` call logged):
#   `_pick` calls                                          201
#   ... with `only_delivery=True`                          141  (70 %)
#   ... with an ELIGIBLE WATER job                          60  (only the free calls)
#   water was the chosen op in                             44 of those 60
# and on the same turn the farm had **~26 WATER jobs outstanding** at the top of the
# priority table (WATER_BONUS 120 / WATER_SURVIVAL 90-critical) against a FERTILIZE pool
# of ~13 that `crop_plan` re-emits every turn at priority **54**. So a unit holding a
# strawberry and a spare fertilizer spent its day applying fertilizer five tiles away
# while the crop that pays for everything stood unwatered.
#
# CONSEQUENCE on the transplant (Boey's own farm at d10, 4 games, d11-19):
#   planted  ours 52.5 -> 25.5   his 53.0 -> 52.0      <-- we lose HALF the farm
#   WATER    ours 279            his 832
#   died     ours 50             his 9
#   money    ours $10.4k -> $30.8k (d11 -> d17)   his $10.5k -> $49.9k
# We are at exact parity at d11 ($10,405 vs $10,534) and diverge from d12 onward.
#
# Value = the priority penalty applied to a NON-delivery job inside the `only_delivery`
# pass, so the pass becomes "best job overall, with delivery preferred". `None` = the old
# hard wall (only delivery jobs considered). 40 keeps FEED/PLACE above a bonus water while
# letting a survival water beat a FERTILIZE five tiles away.
CARRY_DELIVERY_MARGIN = None
CARRY_DELIVERY_MARGIN_P2 = None
CARRY_DELIVERY_MARGIN_P3 = None

# HORIZON_FILTER -- never assign a job the unit cannot REACH before the day ends.
#
# The deadline is not a preference, it is a fact: hands are wiped at `_end_of_day` and
# re-hired at the shed, so a walk that does not arrive today is thrown away. `_pick`
# prices distance at `MOVE_WEIGHT * min(d, DIST_CAP)` with DIST_CAP=1, so at hour 22 a
# 6-tile walk costs the same 20 points as a 1-tile walk and gets chosen.
#
# MEASURED (4 transplant games, d11-29, "moves after the LAST act of a unit-day"):
#     HIS   mean 0.98 tiles,  13 unit-days with a 6+ walk
#     OURS  mean 2.17 tiles, **114 unit-days with a 6+ walk**
# i.e. 12 % of our unit-days end in a long walk that never reaches an act. That is
# ~2,100 of our 12,384 moves -- 17 % of ALL our walking, and his equivalent is 10 %.
# A unit that cannot arrive should take the best job it CAN reach (or hold), which is
# exactly what this rule does: `d > 24 - hour` candidates are dropped from the choice.
HORIZON_FILTER = False
HORIZON_FILTER_P2 = None
HORIZON_FILTER_P3 = None

# BONUS_WALK_WEIGHT -- price the walk to a BONUS op at its true marginal value.
#
# FERTILIZE is worth about one extra yield unit (~$25-140) and is never urgent: the tile
# lives without it. But it is scored like any other op -- `MOVE_WEIGHT * min(d, DIST_CAP)`
# with DIST_CAP=1, so a fertilize 5 tiles away costs the same 20 points as one underfoot
# and the crew commutes for it.
# MEASURED (crew_audit, d11-17, 4 transplant games):
#     FERTILIZE   ours 178 ops @ **2.36 moves/op** (9.2 % of all our moves)
#                 his  262 ops @ **0.13 moves/op**
#     conversion  FERTILIZE 818 intents, only 168 landed (21 %), 550 DIVERTED,
#                 **tiles/land 1.41** -- we walk 1.4 tiles per fertilize we actually apply
#     COLLECT_FERTILIZER is then **31.6 % of ALL our moves at 2.39 moves/op** (his 0.85),
#     because the unit collects the fertilizer and then commutes to spend it.
# With this set, `dcost = BONUS_WALK_WEIGHT * d` (LINEAR, uncapped) for the ops in
# `_BONUS_OPS`, so a fertilize 3 tiles away loses to any other job of similar priority
# and the application only happens when the unit is already there. 0/None = today's rule.
BONUS_WALK_WEIGHT = None
BONUS_WALK_WEIGHT_P2 = None
BONUS_WALK_WEIGHT_P3 = None

# SAME_TILE_COMPARE -- the underfoot reservation must WIN the comparison, not veto it.
#
# The pre-pass reserves the job on the tile a unit already occupies before any distant
# unit can claim it (see params.SAME_TILE_FIRST). It picks that job by `(-priority,)`
# among the ON-TILE jobs only -- it never compares against the best job elsewhere. So a
# unit standing on an animal tile chains FEED (100) / CARE (70) / COLLECT (55) while a
# survival WATER (90) or a bonus WATER (120) two tiles away is never considered, and the
# crop does not get watered. Measured as the `ON_TILE` diverts below.
# With this ON, the reservation is granted only when `_pick` would ALSO have chosen a job
# on the current tile; otherwise the unit is left to the ordinary kernel, which prices the
# underfoot job at d=0 (dcost 0) and lets it win on merit.
#
# WHY IT IS NEEDED -- MEASURED (`tools/labour/conversion.py`, d11-17, 4 transplant games):
#   40.6 % of all assigned intents are DIVERTED before they land, and of those
#     49 % are `ON_TILE` (the unit is pulled to work underfoot mid-walk)
#     45 % are `TAKEN_BY_OTHER` (two units on the same tile)
#   WATER   646 intents / 341 landed (53 %) / **tiles walked per landed water 0.72**
#   FEED   1279 intents / 157 landed (12 %) / 655 diverted
# Against the reference's own play on the SAME farm the water counts are 866 / 643 (74 %)
# at 0.02 tiles per landed water, and `P_WATER_SURVIVAL=P_WATER_BONUS` sweeps (110/130/140)
# change the delivered water count by <4 %, which is the proof that PRIORITY is not the
# binding constraint -- the reservation is.
SAME_TILE_COMPARE = False
SAME_TILE_COMPARE_P2 = None
SAME_TILE_COMPARE_P3 = None

# SAME_TILE_CRITICAL_BREAK -- the NARROW form of the above. `SAME_TILE_COMPARE` compared
# the underfoot job against the whole job list, so the reservation was granted only when
# `_pick` also chose an on-tile job -- which is almost never, and the arm collapsed
# (transplant median **-$106,370** against the -$53,402 baseline, i.e. identical to
# switching the pre-pass off altogether). The reservation is load-bearing for LOCALITY;
# what it costs is the rescue. This breaks it for exactly one case: an off-tile
# `critical` job (a tile that becomes a WEED or an animal that escapes tonight) that
# `_pick` would have chosen. Everything else keeps its reservation.
SAME_TILE_CRITICAL_BREAK = False
SAME_TILE_CRITICAL_BREAK_P2 = None
SAME_TILE_CRITICAL_BREAK_P3 = None

# FERT_DELIVER_RADIUS -- never COMMUTE to spend a fertilizer. Apply it where you stand.
#
# The `only_delivery` wall in `scheduler.plan` shows a carrying unit ONLY FEED/PLACE/
# FERTILIZE -- so the moment a unit does COLLECT_FERTILIZER it is committed to walking to
# a FERTILIZE tile, however far, and no other cost term can stop it (`BONUS_WALK_WEIGHT`
# measured byte-identical for exactly this reason: the competition is excluded, not
# outscored).
# MEASURED (`crew_audit`, d11-17, 4 transplant games, Boey's own farm):
#     COLLECT_FERTILIZER  **2.39 moves/op = 31.6 % of ALL our moves**   (his 0.85)
#     FERTILIZE           2.36 moves/op                                 (his 0.13)
#     FERTILIZE conversion: 818 intents, 168 landed (21 %), 550 DIVERTED, tiles/land 1.41
# and the crew's position histogram over d11-29 --
#     standing on an ANIMAL tile:  ours 67.4 %   his 48.8 %
#     standing on a THIRSTY CROP:  ours 12.1 %   his 25.6 %
# -- so the crew is trapped in the animal ring by a bonus errand, while water delivery is
# proportional to time spent on thirsty tiles (4.3 unit-turns per water, identical for
# both). With this set, a FERTILIZE job farther than the radius is not offered to the
# delivery pass; the fertilizer stays in hand and is spent opportunistically, only when the
# unit is already there. `None` = today's wall.
# NOTE: fertilizer has no other exit -- `_drop_inventories_to_shed` banks it at day end and
# `FERTILIZE_SHED_PICKUP` (ON) will re-fetch it. Keep the radius >= 1 so a unit on an
# animal tile can still serve the crop tile beside it, which is the reference's pattern.
FERT_DELIVER_RADIUS = None
FERT_DELIVER_RADIUS_P2 = None
FERT_DELIVER_RADIUS_P3 = None

BAND_MONOCROP = True

P_CARE = 70

# The remaining priority bands, moved here from `job.py` so every band is A/B-able from
# SCRATCH_PARAMS. Defaults reproduce the shipped behaviour exactly.
P_HARVEST = 100
# Feed-critical: the highest band in the system, ABOVE harvest and survival water. With a
# 13-animal herd on bought wheat the pickup->feed chain fires continuously and preempts
# watering, which is the phase-2 attrition root -- so this is a W2 candidate.
P_PICKUP_WHEAT = 101
P_PICKUP = 88
P_PLANT = 85
P_PICKUP_ANIMAL = 60
P_PLACE = 60
P_DIG = 20

P_BUILD = 95

P_FEED = 100

P_WATER_SURVIVAL = 90

# Window ("bonus") watering: the +1-yield water at ages 2-4 (wheat) / 6-12 (melon).
# It sat as a bare constant 50 in `job.py` until now, which is why every A/B of it
# measured nothing. 50 is BELOW P_CARE (70), P_PLANT (85) and P_PICKUP (88), so the
# yield water is the first field job to be dropped -- wheat then gets only the
# survival water and yields 1 unit instead of 3, and the opening buys its feed
# ($1,322 over d0-d5) instead of eating its own crop.
#
# MEASURED (16-game phase screen vs 60 Boey replays, with SAME_TILE_FIRST on):
#   50 -> WATER 62, animals 7, idle 9.78      85 -> WATER 63, animals 7
#  100 -> WATER 63, animals 7                120 -> WATER 66, animals 8, idle 5.08
#  140/160 -> identical to 120 (saturates above P_HARVEST=100). Alone (no chain) 120
#  gives WATER 58 / animals 7, so the two changes are synergistic, not additive.
P_WATER_BONUS = 120
# WATER_ONGOING_PRODUCE -- water an ONGOING crop (STRAWBERRY, TOMATO) on a production day.
#
# `state.water_window()` returns **None for an ongoing crop**, so `in_water_window` is
# False at every age and the WATER_BONUS branch in `crop_plan.jobs` NEVER fires for them.
# The only water a mature strawberry ever received was the SURVIVAL one -- the day before
# it would die -- so it was watered roughly every other day and never on a production day.
# The engine pays the doubled fruit only on a production day the tile WAS watered, so half
# of every strawberry's output was never claimed.
#
# MEASURED (tools/labour/ready_by_crop.py, d6-17, 8 games): 16.2 strawberry tiles stand
# per day and only **0.32** are ripe at the start of a day; 30 strawberry harvest ops in
# the whole midgame against Boey's 107, with our standing STRAWBERRY count at 1.04x his.
#
# `P_WATER_PRODUCE` is the band this job is emitted at. It defaults to P_WATER_BONUS (120,
# above HARVEST) because a missed production-day water loses that day's fruit outright;
# set it below P_HARVEST to make harvesting win the ordering instead.
WATER_ONGOING_PRODUCE = False
# WATER_WINDOW_PRIORITY -- an in-window water carries P_WATER_BONUS even when the tile is
# also survival-critical. See crop_plan.jobs.
WATER_WINDOW_PRIORITY = False
# BAND_ANIMALS -- the holdback ring joins the per-worker bands, so FEED/CARE/COLLECT
# resolve locally instead of through the global pass. See layout.slice_partition.
BAND_ANIMALS = False
# LAYOUT_RADIAL -- order the per-worker bands by SHED DISTANCE instead of by row, so a
# band is a piece of one ring around the shed. See layout.slice_partition.
LAYOUT_RADIAL = False
# LAYOUT_EVEN_BANDS -- distribute the owned tiles evenly so no worker's band is empty.
# MEASURED WORSE (plants died 10.0 -> 17.5, net -$1,250); see layout.slice_partition.
LAYOUT_EVEN_BANDS = False
P_WATER_PRODUCE = 120

P_COLLECT_FERT = 55

P_FERTILIZE = 54

FERT_RESERVE = 5
# Do not FERTILIZE during the opening: sell the fertilizer instead. Measured on the
# #1's own d0-d5 orders, his fertilize ops are ZERO and he runs `SELL FERTILIZER`
# 3-5 units a day from d1 -- it is his earliest cash, and it pays for bought feed and
# the NE quadrant before any crop revenue lands.
#
# The SEASON default stays OFF; **phase 2 is now ON** via `FERTILIZE_FROM_DAY_P2 = 6`.
# CORRECTED 2026-09-29: the old note here ("never fertilizing is +$2,294, 36/36") was
# used to close the `FERTILIZE ops 0 vs 64` DAG node as "descriptive". It is stale on
# the current tree, and it measured the wrong thing -- the reference DOES fertilize.
# MEASURED (`tools/labour/crop_cycle.py`, d6-17, 8 of our games vs 40 Boey replays):
#   Boey : 1,390 wheat FERTILIZE ops, 57 % of wheat harvests fertilized, fertilized
#          yield 5.35 vs 3.17 unfertilized, harvest age 3.0, 1.10 units/tile-day
#   ours : 0 FERTILIZE ops, yield 2.93 (only 2s and 3s), harvest age 4.0, 0.59 /tile-day
# What made our old arms lose was the APPLICATION COST: our FERTILIZE measured **4.35
# moves/op** (a shed-pickup round trip per 6 units) against the reference's **0.09**.
# MEASURED (8 paired games x2, current tree), with the ORIGINAL delivery still in place:
# `FERTILIZE_FROM_DAY_P2=6;FERTILIZE_ONESHOT_ONLY=True` is **+$4,786 mean / +$8,020
# median margin, 5/8**, wheat yield 2.93 -> 3.49, fertilized share 0 -> 79 %,
# `plants_died` **-8 (2/8 worse)**, `missed_harvest_eod` **-8.5**,
# `shed_overflow_days` **-1 (0/8 worse)**. CONFIRM ON 96 BEFORE TRUSTING IT -- 8-game
# screens flipped sign 3x this session; the guards are the reason to keep it.
# Tried and MEASURED NEGATIVE (8 games each), so NOT shipped: turning the shed pickup off
# (`FERTILIZE_SHED_PICKUP_P2=False`), raising `P_FERTILIZE_P2` to 88, and pre-window
# application. They all measured worse than the original delivery (-$8k to -$16k mean),
# and did not move FERTILIZE moves/op (3.3 vs 3.2), so the movement lever is NOT the
# shed pickup -- it is that the crop tiles are far from the animal tiles the fertilizer
# comes from. That is the layout problem, before the op can be optimised.
FERTILIZE_FROM_DAY = 99
_FERTILIZE_FROM_DAY_WAS = 6

# PRE-WINDOW application. Fertilizer lasts `day..day+2`. One-shot crops are only eligible
# inside the bonus window, and WATER_BONUS (120) outranks FERTILIZE, so the window's first
# water lands BEFORE the fertilize and banks only +1; the +2 starts the next day (wheat: 4
# units at age 3 instead of 5). With this on, a one-shot crop is also eligible on
# `window_start - 1`, the day before the window opens.
# MEASURED NEGATIVE (8 paired games, packaged with the shed-pickup-off delivery):
# -$8k mean, so SHIPPED OFF. The theory is sound but the crew does not reliably carry
# fertilizer to the pre-window tile, so the application lands late anyway.
FERTILIZE_PRE_WINDOW = False

# Crop-value gate for fertilizing. Only fertilize a crop whose BASE price is at least
# this. Base prices: MELON ~267, STRAWBERRY ~141, TOMATO ~63, CARROT ~35, WHEAT ~30.
# 0 = no gate (every eligible crop).
FERTILIZE_SHED_PICKUP = True
FERTILIZE_MIN_PRICE = 0

# trickle: cap units per SELL order so a large order does not walk the curve down.
# SELL_TRICKLE_FRACTION -- sell this share of the shed each turn, above TRICKLE.
SELL_TRICKLE_FRACTION = 0.0
TRICKLE = 6
# a good is sold only at/above this fraction of its base price (loose guard).
MIN_SELL_FRAC = 0.85


# ---- crop calendar (structural). Overlapped and ROTATED, not stacked. --------
# DSM rule #3: "Crops rotate (melon -> strawberry -> carrot) rather than
# stacking." Measured, that is a *planting-rate* statement, not just an ordering
# one: he buys 191 WHEAT / 49 STRAWBERRY / 48 CARROT / 23 MELON / 18 TOMATO seeds
# and sows them steadily across the crop's whole viable window, so the harvest
# reaching the shed is a continuous diversified basket. This agent instead filled
# each crop's tile target as fast as it had hands -- 10 strawberry in one day, 16
# carrot in one day -- and each wave then ripened simultaneously, collided with
# the next wave's planting, and lost a large share of itself to decay (measured
# 118 plants died/game, CARROT converting only 97 of 186 expected units, deaths
# spiking 13/11/20 on days 21/22/27).
#
# So a crop is now throttled by a RAMP: the standing count is capped at
# ``target * (day - start + 1) / (peak - start + 1)`` and only tops up to
# ``target`` once the ramp completes. ``peak`` is DSM's measured peak day.
# ``end`` is the last day a planting can still yield before the day-30 bell
# (ongoing: 29 - first_yield_day; one-shot: 29 - max_yield_day - 1).
# WHEAT ramp shape, as scalars so `SCRATCH_PARAMS` can A/B it: the cap is
# `target * min(1, (day - start + 1) / (peak - start + 1))`, so `peak` is the day the
# ramp reaches `target` and stays there. Measured curve on the shipped agent: d8 = 5
# tiles against the #1's 11, then 32 against his 22-24 for d12-d18 -- i.e. late then
# ~40 % overshoot. Lowering both moves tiles from the plateau into the d8-d10 window.
WHEAT_TARGET = 32
WHEAT_PEAK = 11
# STRAWBERRY ramp shape, as scalars so SCRATCH_PARAMS can A/B it.
#
# An ongoing crop's FIRST YIELD is `first_yield_day` after planting (STRAWBERRY 10,
# TOMATO 8) and it then yields at `interval` (STRAWBERRY 2) up to `max_yield` times (4) --
# STRAWBERRY production ages are 10/12/14/16 and then it decays into a weed. So a tile
# planted on day d produces nothing before d+10: **the midgame can only harvest the
# strawberry that was IN THE GROUND by d7**. The old ramp (`peak=16`) did not reach its
# 30-tile target until d16, which put most of the block past the end of the phase.
STRAWBERRY_TARGET = 30
# SHIPPED at the d10 state-clone step: reach the 30-tile strawberry target by d9 (the
# reference holds 20 tiles by d9) instead of d16. Only affects d6+ -- the opening is
# governed by OPENING_STANDING, not the ramp. Part of the +$10,218 herd bundle.
STRAWBERRY_PEAK = 11

# Every crop's ramp as scalars so SCRATCH_PARAMS can A/B it (the resync at the bottom of
# this file writes them back into CROP_PLAN -- without that they are phantom knobs).
# TOMATO is the interesting one: `first_yield_day=8` from a `start=9` planting means its
# first fruit lands d17, the LAST day of the midgame, and it soaks up a full share of the
# plant queue's round-robin slots and tiles the whole time. MEASURED (herd_gate, 16 games):
# the herd gate's `wheatT >= 1.7*(herd+1)` fails EVERY day from d11 to d17 with $18.5k of
# idle cash, because the wheat base sits at 22 against a 30.6 requirement.
MELON_TARGET = 10
MELON_PEAK = 1
# `end` = the last day a planting can still yield before the day-30 bell. MEASURED
# (tools/labour/water_geometry --days 18-29, 8 games): our phase-3 water demand is **46
# tiles against the reference's 189**, and `ready_by_crop` shows why -- the plant calendar
# closes at d19/d21/d24 and the farm ages out. Phase 3 is where the money is: the shipped
# arm grows $23,828 in d18-29 against $18,156 in d6-17.
STRAWBERRY_END = 19
WHEAT_END = 24
TOMATO_END = 21
CARROT_END = 25
MELON_END = 2
# SHIPPED at the d10 state-clone step: the reference runs NO midgame tomato (0 tiles at
# d10 in 120 replays), while our TOMATO_TARGET=16 planted 1-3 tiles whose first fruit lands
# d17 -- the last day of the phase. MEASURED on the checkpoint (`--prefix ours --cut-day 10`):
# TOMATO 2 -> 0 vs his 0 (**0 %**). TOMATO start=9, so the opening is untouched.
TOMATO_TARGET = 0
TOMATO_PEAK = 18
CARROT_TARGET = 23
CARROT_PEAK = 24

CROP_PLAN = {
    "MELON":      {"start": 0,  "end": MELON_END,  "target": MELON_TARGET, "peak": MELON_PEAK},
    "STRAWBERRY": {"start": 2,  "end": STRAWBERRY_END, "target": STRAWBERRY_TARGET,
                   "peak": STRAWBERRY_PEAK},
    "WHEAT":      {"start": 0,  "end": WHEAT_END, "target": WHEAT_TARGET, "peak": WHEAT_PEAK},
    "TOMATO":     {"start": 9,  "end": TOMATO_END, "target": TOMATO_TARGET, "peak": TOMATO_PEAK},
    "CARROT":     {"start": 17, "end": CARROT_END, "target": CARROT_TARGET, "peak": CARROT_PEAK},
}
# Throttle planting to the ramp above. False reproduces the old "fill the tile
# target as fast as we have hands" behaviour (per-day planting waves).
PLANT_RAMP = True
# Weight the plant queue by deficit/cap instead of the raw deficit, so one
# big-target crop cannot monopolise the crew and starve the higher-value ones.
# PLANT_QUEUE_SCALE is the number of slots the neediest crop gets.
# MEASURED NEGATIVE as part of the crop-side opening package (12 paired games,
# median -$3,501, 4/12, p=0.39) and it worsened plants_died/unwatered/missed_harvest
# -- more early wheat means more mouths to water. Kept as a knob, default off.
PLANT_QUEUE_BY_NEED_FRACTION = False
PLANT_QUEUE_SCALE = 12
# how many empty tiles to keep in reserve for a crop's own block (not consumed).
# (left as a knob for R3 slicing; R2 does not use it)
PLANT_ORDER = ("MELON", "STRAWBERRY", "TOMATO", "CARROT", "WHEAT")


# ---- herd (structural). ------------------------------------------------------
# Herd composition targets as scalars so SCRATCH_PARAMS can A/B them (resynced into HERD
# at the bottom of this file). MEASURED (round 5-6): in the 87 % of games with no YARN_STORE
# the target totals **20** (9 COW + 3 SHEEP + 8 GOOSE) -- i.e. the agent's own composition
# target is BELOW the objective's `animals 21`, so no amount of feed or cash could reach it.
HERD_COW_TARGET = 9
HERD_COW_BUY = 11
HERD_SHEEP_TARGET_YARN = 10
HERD_SHEEP_TARGET_NOYARN = 3
HERD_SHEEP_BUY = 4
HERD_GOOSE_TARGET_YARN = 6
HERD_GOOSE_TARGET_NOYARN = 8
HERD_GOOSE_BUY = 7
HERD = {
    "COW":   {"target": HERD_COW_TARGET, "buy": HERD_COW_BUY},
    "SHEEP": {"target_yarn": HERD_SHEEP_TARGET_YARN,
              "target_noyarn": HERD_SHEEP_TARGET_NOYARN, "buy": HERD_SHEEP_BUY},
    "GOOSE": {"target_yarn": HERD_GOOSE_TARGET_YARN,
              "target_noyarn": HERD_GOOSE_TARGET_NOYARN, "buy": HERD_GOOSE_BUY},
}
# R4 (herd) feature flag.
#
# ON, but ONLY as the OPENING herd: see OPENING_HERD / OPENING_HERD_UNTIL_DAY below.
# Measured as a package (`shadow_prices` 8 pairs, then the harness 36 pairs):
#   dNAV_d5  +$7,354   (d5 NAV $7,046 -> $14,400, above the #1's $13,132)
#   dterm    +$16,596  median, 35/36 paired games better, p=0.0000,
#                      positive against all 12 public opponents (min +$3,646)
# The season value comes from the OPENING commitment, not from herd growth: with the
# season ramp enabled (`HERD_BUY_UNTIL=18`) the same opening was -$15,230, and a 2x2
# prefix/continuation cross put the whole loss on the post-d5 policy (d_state +$7,410
# but d_policy -$16,775, the only difference being `HERD_BUY_FROM_DAY`). So the herd
# is a day-0 commitment, not a ramp -- see `HERD_BUY_UNTIL`.
HERD_ENABLED = True

# During these opening days CASH is the feed capacity, not the wheat base: we are
# deliberately committing the bank before any crop can feed the herd, and the feed
# cover in the purchase gate prices that. From day 3 the wheat-tile gate takes over.
HERD_OPENING_DAYS = 2
# Order species are bought in. For the opening the ranking is "when does it first
# pay, and how gently does its product sell": GOOSE yields on day 4 and EGG's curve
# is log-shaped so it can be sold freely; SHEEP yields day 6 and banks a big CARE
# bonus (6 units at once) which is the d6 cash that funds the NE quadrant; COW is
# the most expensive and yields last (day 8).
HERD_SPECIES_ORDER = ("GOOSE", "SHEEP", "COW")
# ---------------------------------------------------------------------------
# THE OPENING SCRIPT (d0-d5) -- measured from the #1's own replays.
#
# His d5 state is IDENTICAL in 40/40 games (and 25/25 in a second audit): 2 COW +
# 3 SHEEP, 10 MELON + 10 STRAWBERRY planted, 25 owned tiles, 1 quadrant. His day-0
# is equally fixed: he spends the whole $3,000 bank (ends at $6), plants 15 tiles
# (6 MELON + 9 WHEAT), builds 5 pastures, places the 5 animals and feeds/cares them
# the same day -- with 4 hands. The opening is therefore a SCHEDULE, not a reaction:
# the first shop draw is not visible until the end of d3, so there is nothing yet to
# react to.
#
# These are STANDING TILE COUNTS per day (not plant ops). `plant_queue` takes the
# deficit against them and `market_intents` buys the seed they imply, so the day's
# script is executed by the ordinary layers instead of by a special case.
#
# Measured trace (ours-before -> his):
#   day | ours (before)                | his (target)
#   d0  | 5 MELON  4 WHEAT   9 planted | 6 MELON  9 WHEAT  15 planted + 5 structs + 5 animals
#   d1  | 12 MELON 5 WHEAT  17 planted | 10 MELON 10 WHEAT 20 planted
#   d2  | 12 MELON 2 STRAW  8 WHEAT    | 10 MELON  4 STRAW  4 WHEAT
#   d3  | 12 MELON 4 STRAW  9 WHEAT    | 10 MELON 10 STRAW  0 WHEAT
#   d5  | 12 MELON 4 STRAW  9 WHEAT    | 10 MELON 10 STRAW  0 WHEAT   <- 9 tiles idle vs 0
# WHEAT falling 10 -> 4 -> 0 is not a re-plant: the schedule stops asking for it and
# the tiles go to STRAWBERRY as the standing wheat is harvested.
#
# ON. Set False to fall back to the pure ramp.
#
# MEASURED AS A STANDALONE CHANGE (8 paired games, `--perturb 'no_script|OPENING_SCRIPT=0'`):
#   dNAV_d5  +$3,410   (it is the instrument that reaches d5 crop_units 50/50, the
#                       #1's exact mix; the old open_dist metric read 13 -> 5 and has
#                       since been deleted -- see tools/phases/dag.py)
#   dterm    -$7,350   0/8, p=0.005
# => on its own it is a PAPER improvement: the sign-disagreement flag fired on 8/8.
# The reason is the coupling: the 9 WHEAT tiles are FEED for the 5 animals and the 10
# early STRAWBERRY are funded by the fertilizer those animals produce. Transplant the
# crop half alone and the wheat displaces melon (base $267 vs wheat $30) while the
# strawberry seed ($1,000) is sunk with no fertilizer income to pay for it.
#
# MEASURED IN THE COMBINATION (36 paired games, with OPENING_HERD + the fertilizer
# sales + HERD_BUY_UNTIL=5):
#   dterm    +$16,596 median, 35/36 better, p=0.0000, positive vs all 12 opponents
# So it ships WITH the herd and NOT without it -- the two halves are one change.
OPENING_SCRIPT = True
OPENING_STANDING = {
    0: {"MELON": 6, "WHEAT": 9},
    1: {"MELON": 10, "WHEAT": 10},
    2: {"MELON": 10, "WHEAT": 4, "STRAWBERRY": 4},
    3: {"MELON": 10, "STRAWBERRY": 10},
    4: {"MELON": 10, "STRAWBERRY": 10},
    5: {"MELON": 10, "STRAWBERRY": 10},
}
# Boey's opening mix: same melon block, a QUARTER of the strawberry, and the freed tiles
# go to the herd (Boey runs ~8 animals at d5 and fills all 25 tiles). Only the standing
# counts differ -- the script mechanism, ramp and seed ask are unchanged.
OPENING_STANDING_BOEY = {
    0: {"MELON": 6, "WHEAT": 9},
    1: {"MELON": 10, "WHEAT": 10},
    2: {"MELON": 10, "WHEAT": 4, "STRAWBERRY": 4},
    3: {"MELON": 10, "STRAWBERRY": 4},
    4: {"MELON": 10, "STRAWBERRY": 4},
    5: {"MELON": 10, "STRAWBERRY": 4},
}
# Master switch for the opening package (Boey mix + bigger opening herd + bought feed +
# committed cash + partial seed fill). OFF by default so every arm is A/B-able; applied
# AFTER _apply_env_overrides so OPENING_MIX_BOEY=1 from SCRATCH_PARAMS works.
OPENING_MIX_BOEY = False
# The opening seed ask is the script's need, not the usual small buffer: by the end
# of d0 the #1 has 9 wheat and 6 melon in the ground, which a 6-seed buffer cannot buy.
OPENING_SEED_BUFFER = 12
# ---------------------------------------------------------------------------
# THE OPENING HERD SCRIPT (d0-d5) -- the other half of the same measurement.
#
# The #1 builds 5 pastures and places 2 COW + 3 SHEEP on day 0, feeds and cares them
# the same day, and holds exactly that through d5 (invariant, 40/40 games). His herd
# is not a ramp: it is an opening commitment, and it is what his 9 WHEAT tiles feed
# and what his daily FERTILIZER sales (3-5/day from d1) pay for.
#
# The season `HERD` targets below are a RAMP, and ramping a herd from 0 with a
# 1-animal-per-turn buy over 24 market phases leaves the opening decided by cash
# gates instead of by a plan. So while `day <= OPENING_HERD_UNTIL_DAY` the targets
# are the opening standing counts, exactly like `OPENING_STANDING` for the crops.
OPENING_HERD = {"COW": 2, "SHEEP": 3}
# Scalar knobs so the opening herd can be A/B'd from SCRATCH_PARAMS (a dict cannot be).
# The h5 state is assembled from these AFTER _apply_env_overrides() at the bottom.
# Boey runs ~8 animals (4 COW + 2 SHEEP + 2 GOOSE on a 40-game d5 scan) and fills the
# 25-tile quadrant with them; our 5 leaves the reserved ring half-empty.
OPENING_HERD_COW = 2
OPENING_HERD_SHEEP = 3
OPENING_HERD_GOOSE = 0
# Allow the opening herd to be fed from BOUGHT wheat (Boey buys ~3.5k/game). Without
# this the `_wheat_tiles >= 1.7*herd` gate caps the opening at ~5 animals because our
# own wheat is not standing yet; the feed_cover reserve below is the real guard.
OPENING_BUY_FEED = False
# Reserve the seed cost of the WHOLE remaining script (not just today's) before the
# animal gate may spend. Fixes the MELON cap: with today-only, d0 animal buys left $23
# and the d1 melon top-up was unfunded before `CROP_PLAN['MELON'].end = 2` closed.
OPENING_SEED_RESERVE_HORIZON = False
OPENING_HERD_UNTIL_DAY = 5
# MEASURED (24 paired games, `shadow_prices --perturb
# 'both|OPENING_FEED_DAYS=0;OPENING_SEED_FLOOR=0'`): **dterm +$9,436 median,
# 24/24 games better, p=0.000**, and dNAV_d5 +$306 for once. The two `0`s are the
# whole fix: these two reserves were DOUBLE-COUNTED, and together they left the farm
# $527 short of its 5th animal for all of d0 (`tools/labour/unit_trace.py` +
# an instrumented purchase gate showed need=SHEEP required=1150 money=623, every turn
# from h02 to h23). Neither alone was enough -- feed=0 leaves $650 needed vs $623,
# seed_floor=0 leaves $1000 -- which is why single-knob screens kept reading "no
# effect". Result: animals [3,4,4,4,4,5] -> [4,5,5,5,5,5] and CARE 24 -> 29 against
# the #1's effective 30.
#
# Bought-feed cover during the opening, in days. The season value (5) prices a herd
# bought long before its own wheat lands; the #1 covers about ONE day from the market
# (4 wheat on d0) because his 9 wheat tiles yield from d2. Holding 5 days x 5 animals
# = $750 of cover is why our herd arm could not afford the 5 animals on d0 at all.
OPENING_FEED_DAYS = 1
# Fertilizer reserve while a herd is running. The season 5 is exactly what 5 animals
# produce per day, so it sold ZERO and threw away the #1's earliest cash engine
# (3-5 units/day at ~$95 from d1). With animals on, the reserve is empty.
FERT_RESERVE_WITH_HERD = 0
# The opening wants a WHEAT BURST, not the steady ramp: the #1 sows 9 wheat tiles on
# day 0, harvests them around d4-5 and feeds the herd from them, then hands those
# tiles to strawberry. The ramp alone allows only ~2.7 wheat tiles on d0, which is
# why the herd was buying every unit of feed. Cap = the bigger of the ramp and this.
# MEASURED NEGATIVE in the same package (the wheat burst plants more early crops than
# a 6-hand crew can water). Kept as a knob, default off; superseded by OPENING_STANDING.
WHEAT_OPENING_TILES = 0
WHEAT_OPENING_UNTIL_DAY = 2
# Buy animals from this day. DAY 0, because the opening is where our labour is
# free and unused: measured on the crops-only arm, day 1 is 116/116 unit-turns
# PASS (100% idle), day 5 is 146/162 PASS with only 5 productive ops, and ~56% of
# all d0-d7 turns do nothing. The cause is structural -- a crop-only farm has no
# work on the *odd* days, because wheat's water window is ages 2-4 and melon's is
# 6-12, so d1/d3/d5/d7 have nothing to water. Feeding, caring and collecting are
# DAILY work from the day an animal lands, and geese first yield on day 4.
HERD_BUY_FROM_DAY = 0
# Keep this many of the NEAREST-TO-SHED owned tiles out of the crop slices, so
# herd_plan has somewhere to build coops/pastures (it builds shed-outward). A
# *count*, not a radius: the old geometric ANIMAL_ZONE reserved 40 of 100 tiles
# and squeezed the crops badly in a 25-tile opening quadrant.
#
# THE RING RESERVATION -- this is what makes the herd payable.
# tools/report/ring_occupancy.py measured who claims the shed ring:
#   band 0 (4 shed-access tiles):  DSM 75% animals (3.0)  |  US 25% (1.0)
#   band 1 (12 tiles):             DSM 58% animals (7.0)  |  US 17% (2.0)
#   band 2 (20 tiles):             DSM 40% animals (8.0)  |  US  5% (1.0)
# 18 of his 20.5 animals live inside radius 2 and he puts animals on the shed-access
# tiles from day 0 (first plant in band 0: day 10). We planted the ring instead --
# band 2 held 16.4 crop tiles against 1 animal, and 2.9 of the 4 shed-access tiles.
# That is why every animal cost us 2.25 moves/op against his 1.12, and why herd
# expansion was unpayable.
#
# MEASURED (shadow_prices, 24 paired games, margins vs tree default):
#   STRUCTURE_HOLDBACK=12 alone                       dterm   -$913   12/24
#   STRUCTURE_HOLDBACK=20 + HERD_BUY_UNTIL=12         dterm -$18,324   0/12   (too much ring)
#   STRUCTURE_HOLDBACK=12 + HERD_BUY_UNTIL=12         dterm +$3,013   23/24  p=0.000
# against herd expansion ALONE at -$8,014 (0/24): the ring is worth ~+$11,000 of
# interaction and it is the first herd change that pays. 12 is the sweet spot --
# 20 starves the crop slices. (dNAV_d5 is negative: holding the ring back costs a
# little d5 state and buys the season; the two disagree in 35/48 pairs.)
STRUCTURE_HOLDBACK = 12

# (The geometric inner-ring reservation was replaced by STRUCTURE_HOLDBACK
# above, which reserves an exact tile count instead of a radius.)

# days the herd is fed/cared (d26+ retirement handled by endgame.py)
HERD_ACTIVE_UNTIL_DAY = 30
# DSM rule #4 has two independent halves (see endgame.py).
# (a) stop *investing* — no new PLANT/FERTILIZE/DIG. Watering is NEVER gated: it
#     is what delivers the late-season revenue. Default off because on the
#     crops-only farm a blanket retirement measured uniformly negative.
RETIRE_DAY = 99
# (b) release the herd — feed and care stop on this day, animals escape.
HERD_RETIRE_DAY = 28
# A job that prevents an IRREVERSIBLE loss (a plant that becomes a weed tonight,
# an animal that escapes tonight) is priced as if the unit were already standing
# on it: it pays no walk cost and so competes purely on priority. It does NOT get
# a large bonus — that was measured to be catastrophic. Every freshly planted tile
# is "at risk" for one turn, so a big bonus made the plant wave globally
# top-priority and starved HARVEST outright (revenue halved, $61.5k -> $28.1k).
FEED_EVERY_DAY = True
# Buy animals only up to this day. Set to the END OF THE OPENING SCRIPT: the herd is a
# day-0 commitment, not a ramp.
#
# MEASURED: post-opening expansion against the OLD layout was the single most expensive
# thing this agent did. From an identical d5 state, switching only `HERD_BUY_FROM_DAY`
# cost **$16,775** (`state_value --cross`), and `HERD_BUY_UNTIL=5` beat `18` by
# **+$16,596 median over 36 paired games (35/36, p=0.0000)**.
#
# THAT IS NOW SUPERSEDED by the ring reservation above. With `STRUCTURE_HOLDBACK=12`
# (the herd can actually occupy the shed ring), `HERD_BUY_UNTIL=12` measures
# **+$3,013, 23/24, p=0.000** over the tree default, against **-$8,014 (0/24)** for the
# same expansion with the ring left to the crops. Expansion was never intrinsically
# unprofitable -- it was unpayable at the old farm shape.
HERD_BUY_UNTIL = 20
# Post-opening herd EXPANSION may only happen once the wool buyer is revealed.
#
# Why this exists: post-opening expansion measured -$16,775 from an identical d5 state,
# and the season targets it aims at are 9 COW + 3 SHEEP + 8 GOOSE = 20 animals, which is
# unconditional -- it fires whether or not there is a buyer for the product. But the #1
# IS shop-responsive, just later than d5: measured on his 123 episodes, YARN worlds end
# with SHEEP 7.5 / GOOSE 2 and no-YARN worlds with SHEEP 0 / GOOSE 6. So the hypothesis
# this flag tests is that expansion is not bad, it is bad when UNCONDITIONAL.
# With True, a purchase after the opening requires `state.has_yarn()`; sheep then ride
# `HERD["SHEEP"]["target_yarn"]` and geese stay at their no-yarn count.
# MEASURED: see docs/DSM-vs-us(v0).md §2.12.
HERD_EXPAND_ON_YARN = False
# keep this much cash after an animal purchase (don't starve the crop ramp).
# Small on purpose: the opening bank is meant to be COMMITTED (DSM ends day 0 at
# $6 with 5 animals placed). The guard that matters is not a cash balance but the
# feed cover below.
ANIMAL_CASH_RESERVE = 0
# Never buy an animal we cannot feed until our own wheat ripens. An animal eats
# 1 wheat/day and carries 2 days of built-in tolerance, but bought feed is
# expensive (~$25-40/unit early), so cover this many days per animal at commit
# time. Without it the opening herd eats the bank and starves on day 2.
ANIMAL_FEED_RESERVE_DAYS = 5
# Feed cover once the standing WHEAT base already satisfies the herd's ration
# (`_wheat_tiles >= WHEAT_TILES_PER_ANIMAL * (herd+1)`). 5 days of bought-feed cash on
# top of a mature wheat base is double-counting, and it is what froze the midgame herd:
# d10-d12 ran 22 standing wheat tiles (gate open) with $691-1,345 against a $1,650-1,725
# cover, so the animal was affordable and the reserve refused it. See
# `tools/phases/herd_gate.py`. Keep 5 for the immature/base-short case.
ANIMAL_FEED_RESERVE_DAYS_MATURE = 1
FEED_PRICE_GUESS = 30
# Our own wheat lands around here (the opening burst is harvested d4-d5); bought feed
# is only needed until then, so the reserve shrinks to zero as the day approaches.
WHEAT_LANDS_DAY = 5
# Cash kept back while buying animals so the OPENING PLANTING still happens. Without
# it the herd is bought, seeds cannot be afforded, and the farm opens with bare tiles:
# measured, cash committed went to 1.00 but STRAWBERRY tiles stayed at 1 and 7 tiles
# sat empty.
OPENING_SEED_FLOOR = 0
# feed top-up: BUY_PRODUCT WHEAT when the shed reserve falls below this
FEED_WHEAT_RESERVE = 40
# max wheat units to buy in one top-up order (the feed chain needs to cover every
# unfed animal, not just six, when the herd is bought before its own wheat lands)
FEED_BUY_CHUNK = 12
# Phase-scoped so a midgame top-up cannot change the opening basket.
FEED_BUY_CHUNK_P2 = 40
FEED_BUY_CHUNK_P3 = None
# FEED_STOCK_DAYS -- buy wheat ahead instead of hand-to-mouth. 0 = the old behaviour
# (buy exactly `unfed - shed_wheat`). MEASURED 2026-09-29 (`tools/phases/boey_model.py`,
# 120 of his replays vs ours, d6-17 medians): Boey buys **27/34/68/30/18/13/22** wheat per
# day at d6..d17 against our **6/11/10/12/10/18/12** -- he runs a feed BUFFER, and his
# herd is 17 by d10 against our 8.5. Our herd gate (`WHEAT_TILES_PER_ANIMAL = 1.7`) is a
# standing-TILE proxy for feed; the induced gate from his own play has no such step (buy
# rate by wheat-ratio bucket: 95 % at 0.0-0.5 falling to 44 % at 2.0-2.5), i.e. he does
# not gate on standing wheat at all -- he gates on CASH and buys the feed.
# This is the other half of that clone: stock `herd * FEED_STOCK_DAYS` units so the herd
# can grow without the wheat base having to lead it.
FEED_STOCK_DAYS = 0
FEED_STOCK_DAYS_P2 = 2
FEED_STOCK_DAYS_P3 = None
# A wheat tile turns over ~4 units per 5 days (0.8 units/day) and an animal eats
# 1/day, so the farm needs about this many standing wheat tiles per animal before
# it can afford to buy the next one. DSM: ~32 wheat tiles / 19 animals = 1.7.
HERD_SHED_WHEAT_CREDIT = 0
# ANIMAL_SHED_LIMIT -- shed size at which the herd stops buying. See herd_plan.market_intents.
ANIMAL_SHED_LIMIT = 95
WHEAT_TARGET_FROM_HERD = False
WHEAT_TILES_PER_ANIMAL = 1.7
# wheat kept in the shed (beyond unfed animals) before any is sold for cash
WHEAT_SELL_RESERVE = 15
# how much wheat a feeder picks up in one shed trip (feeds this many animals)
WHEAT_PICKUP_QTY = 6


# ---- dev-only env override (A/B a knob on identical seeds without editing) ----
# SCRATCH_PARAMS='MOVE_WEIGHT=0;HERD_ENABLED=1' python -m tools.diagnose --scratch ...
# Lets a baseline arm be reproduced exactly while a candidate is measured, which
# is the only way to get a same-seed paired diff out of a code change.


def _apply_env_overrides() -> None:
    import os

    spec = os.environ.get("SCRATCH_PARAMS", "")
    for kv in spec.split(";"):
        if "=" not in kv:
            continue
        key, val = kv.split("=", 1)
        key, val = key.strip(), val.strip()
        if key not in globals() or key.startswith("_"):
            continue
        cur = globals()[key]
        try:
            if isinstance(cur, bool):
                globals()[key] = val.lower() in ("1", "true", "yes", "on")
            elif isinstance(cur, int):
                globals()[key] = int(val)
            elif isinstance(cur, float):
                globals()[key] = float(val)
            elif cur is None:
                # A `_P2`/`_P3` override declares itself with None, so the type has to
                # be inferred. Without this every phase-scoped knob would silently
                # ignore SCRATCH_PARAMS -- the same "phantom knob" failure that cost a
                # round on `P_WATER_BONUS`.
                if val.lower() in ("true", "false"):
                    globals()[key] = val.lower() == "true"
                else:
                    try:
                        globals()[key] = int(val)
                    except ValueError:
                        globals()[key] = float(val)
        except ValueError:
            pass


# ---- CROP_SCALE -- hold FEWER, better-watered tiles -------------------------
# GROUP B measured the field as a *capacity* limit, not a pricing one: `missed_work`
# shows WATER=1366 tile-days/season against FERT=571, HARVEST=483, DIG=320 while
# `idle-on-work` is only 79 unit-turns -- the crew never reaches the tiles, and we
# water ~58% of the standing crop against the 50% needed merely to survive. Every
# lever that buys capacity is closed (HANDS_MIDGAME=20 -$32,670) and every lever that
# cuts demand by *gating* is closed (PLANT_WATER_CAP_DIVISOR=2 -$10,107).
#
# The untested shape is the mirror of what the #1 does: plant FEWER tiles, water them
# properly, and let the herd's free fertilizer make each surviving tile count double
# (a fertilised WATER op pays +2 instead of +1, so one-shot yield goes 3 -> 6).
# This knob scales every CROP_PLAN target and peak by the same factor, so the whole
# crop portfolio shrinks at once instead of one crop starving another.
# Applied AFTER _apply_env_overrides() so SCRATCH_PARAMS='CROP_SCALE=0.6' works.
CROP_SCALE = 1.0

_apply_env_overrides()

# rebuild the opening-herd table from its scalars so SCRATCH_PARAMS reaches it, and
# select the requested opening mix.
OPENING_HERD = {"COW": OPENING_HERD_COW, "SHEEP": OPENING_HERD_SHEEP,
                "GOOSE": OPENING_HERD_GOOSE}
if OPENING_MIX_BOEY:
    OPENING_STANDING = OPENING_STANDING_BOEY

# re-sync every crop ramp from its scalars, so a SCRATCH_PARAMS override of
# `<CROP>_TARGET` / `<CROP>_PEAK` actually reaches CROP_PLAN -- which is built in a dict
# literal BEFORE the overrides run. Without this the override mutates the module global
# and the plan keeps the old value: a silent phantom knob. WHEAT had a bespoke line for
# this; STRAWBERRY_PEAK was added later WITHOUT one, and four A/B arms came back
# byte-identical before it was caught.
for _crop in list(CROP_PLAN):
    for _field, _suffix in (("target", "_TARGET"), ("peak", "_PEAK"),
                            ("end", "_END"), ("start", "_START")):
        _name = f"{_crop}{_suffix}"
        if _name in globals():
            CROP_PLAN[_crop][_field] = globals()[_name]
del _crop, _field, _suffix, _name

# re-sync the herd composition from its scalars (same phantom-knob reason as the crops).
HERD["COW"]["target"] = HERD_COW_TARGET
HERD["COW"]["buy"] = HERD_COW_BUY
HERD["SHEEP"]["target_yarn"] = HERD_SHEEP_TARGET_YARN
HERD["SHEEP"]["target_noyarn"] = HERD_SHEEP_TARGET_NOYARN
HERD["SHEEP"]["buy"] = HERD_SHEEP_BUY
HERD["GOOSE"]["target_yarn"] = HERD_GOOSE_TARGET_YARN
HERD["GOOSE"]["target_noyarn"] = HERD_GOOSE_TARGET_NOYARN
HERD["GOOSE"]["buy"] = HERD_GOOSE_BUY

if CROP_SCALE != 1.0:
    for _c, _v in CROP_PLAN.items():
        for _k in ("target", "peak"):
            _v[_k] = max(1, int(round(_v[_k] * CROP_SCALE)))
    del _c, _v, _k

