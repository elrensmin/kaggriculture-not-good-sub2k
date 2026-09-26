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
MOVE_WEIGHT = 30.0
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
    if day >= 2:
        return 6
    return 4


# ---- land schedule. Re-issue BUY_LAND every turn until filled. ---------------
LAND_TARGET_DAY = {"NE": 6, "SW": 9, "SE": 10}
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
SEED_PARTIAL_FILL = False
# land buys keep this much cash in reserve afterwards (never spend to zero pre-revenue).
CASH_RESERVE = 1500
# one hand per ~this many owned tiles (hands+ground lockstep).
TILES_PER_HAND = 4
# The engine hires ONE hand per HIRE order and caps the market list at
# MAX_ORDERS=10, so requesting a whole day's crew in one turn silently truncates
# everything after it (animals, feed, seeds). Order the list by priority and spread
# the hires; the day has 24 turns and the crew only has to be complete by the end.
# The truncation defect is real, but capping hires was measured inside a
# net-negative package; left at the old value until it can be isolated.
MAX_HIRE_PER_TURN = 99
# stop planting after this hour: a crop planted late can't be watered the same
# day and dies that night (consecutive_unwatered 1 -> 2 = weed).
PLANT_CUTOFF_HOUR = 18


# ---- sell policy (the market layer) ------------------------------------------
# knife-edge goods: crash to $1 within ~50-100 units above I0 -> hard stop.
CEILING_GOODS = ("STRAWBERRY", "MILK", "WOOL")
CEILING = 100  # never sell a ceiling good when inventory >= I0 + CEILING
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
# ongoing-only -$2,730. So one-shot fertilizing is worth +$2,730 and ONGOING
# (strawberry/tomato) fertilizing is worth **-$4,684** -- the opposite of the
# "doubles the fruit" intuition, and the reason the naive `FERTILIZE_ONGOING_ONLY`
# made things worse.
FERTILIZE_ONESHOT_ONLY = False
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
SAME_TILE_FIRST = False

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


SLICE_PENALTY = 1000



# Priority floor for the same-tile reservation (see scheduler's pre-pass). 0 = reserve
# unconditionally (MEASURED HARMFUL: assignments 6,629 -> 3,769). The guard makes the
# reservation fire only for jobs at least this urgent, so a unit does not take a DIG or a
# bonus-water under its feet instead of the best job available. Priority bands: HARVEST 100,
# PICKUP_WHEAT 101, FEED 100, WATER_SURVIVAL 90, PLANT 85, CARE 70, COLLECT_FERT 55,
# FERTILIZE 54 (now disabled), WATER_BONUS 50, BUILD 45, DIG 20.
SAME_TILE_MIN_PRIORITY = 70  # inert while SAME_TILE_FIRST is False



USE_SLICES = True

BAND_MONOCROP = True

P_CARE = 70

P_BUILD = 95

P_FEED = 100

P_WATER_SURVIVAL = 90

FERT_RESERVE = 5
# Do not FERTILIZE during the opening: sell the fertilizer instead. Measured on the
# #1's own d0-d5 orders, his fertilize ops are ZERO and he runs `SELL FERTILIZER`
# 3-5 units a day from d1 -- it is his earliest cash, and it pays for bought feed and
# the NE quadrant before any crop revenue lands. Fertilizing a wheat tile converts
# ~$50 of fertilizer into ~$50 of extra wheat, so early on the cash is worth more
# than the yield, and it also costs a PICKUP + FERTILIZE pair out of a 6-hand crew.
# NEVER fertilize: 99 disables both the FERTILIZE job and the fertilizer PICKUP
# (`_worth_fertilizing` gates on this day), so every unit the herd produces is sold.
#
# MEASURED (36 paired games, `--perturb 'nofert|FERTILIZE_FROM_DAY=99'`): **dterm +$2,294
# median, 36/36 games better, p=0.000**. Selling the fertilizer beats spending it. The
# arithmetic: 1 fertilizer is ~$67 on the market, and FERTILIZE is our most
# movement-expensive act at **4.35 moves/op** (the #1's is 0.10), to add roughly one
# unit to one crop. For wheat (~$30/unit) that is plainly negative; only a high-value
# crop like melon could pay. A crop-value-gated version is the better long-term fix --
# this is the blunt one, and it is measured.
FERTILIZE_FROM_DAY = 99
_FERTILIZE_FROM_DAY_WAS = 6

# Crop-value gate for fertilizing. Only fertilize a crop whose BASE price is at least
# this, because 1 fertilizer is ~$67 ON THE MARKET and FERTILIZE is our most
# movement-expensive act (4.35 moves/op vs the #1's 0.10). With `FERTILIZE_FROM_DAY=99`
# the trade is closed entirely (+$2,294, 36/36); this is the targeted version, to see
# whether the high-value crops still pay. Base prices: MELON ~267, STRAWBERRY ~141,
# TOMATO ~63, CARROT ~35, WHEAT ~30. 0 = no gate (every eligible crop).
FERTILIZE_MIN_PRICE = 0

# trickle: cap units per SELL order so a large order does not walk the curve down.
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

CROP_PLAN = {
    "MELON":      {"start": 0,  "end": 2,  "target": 10, "peak": 1},
    "STRAWBERRY": {"start": 2,  "end": 19, "target": 30, "peak": 16},
    "WHEAT":      {"start": 0,  "end": 24, "target": WHEAT_TARGET, "peak": WHEAT_PEAK},
    "TOMATO":     {"start": 9,  "end": 21, "target": 16, "peak": 18},
    "CARROT":     {"start": 17, "end": 25, "target": 23, "peak": 24},
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
HERD = {
    "COW":   {"target": 9, "buy": 11},
    "SHEEP": {"target_yarn": 10, "target_noyarn": 3, "buy": 4},
    "GOOSE": {"target_yarn": 6, "target_noyarn": 8, "buy": 7},
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
#                       #1's exact mix, and open_dist 13 -> 5)
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
HERD_BUY_UNTIL = 12
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
# A wheat tile turns over ~4 units per 5 days (0.8 units/day) and an animal eats
# 1/day, so the farm needs about this many standing wheat tiles per animal before
# it can afford to buy the next one. DSM: ~32 wheat tiles / 19 animals = 1.7.
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
        except ValueError:
            pass


_apply_env_overrides()

# re-sync the wheat ramp from its scalars, so a SCRATCH_PARAMS override of WHEAT_TARGET /
# WHEAT_PEAK actually reaches CROP_PLAN (which was built before the overrides ran).
CROP_PLAN["WHEAT"]["target"] = WHEAT_TARGET
CROP_PLAN["WHEAT"]["peak"] = WHEAT_PEAK

# re-sync the wheat ramp from its scalars, so a SCRATCH_PARAMS override of WHEAT_TARGET /
# WHEAT_PEAK actually reaches CROP_PLAN (which was built before the overrides ran).
CROP_PLAN["WHEAT"]["target"] = WHEAT_TARGET
CROP_PLAN["WHEAT"]["peak"] = WHEAT_PEAK
