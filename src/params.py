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
def target_hands(day: int) -> int:
    if day >= 29:
        return 10
    if day >= 26:
        return 11
    if day >= 10:
        return 12
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
FERTILIZE_FROM_DAY = 6
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
CROP_PLAN = {
    "MELON":      {"start": 0,  "end": 2,  "target": 10, "peak": 1},
    "STRAWBERRY": {"start": 2,  "end": 19, "target": 30, "peak": 16},
    "WHEAT":      {"start": 0,  "end": 24, "target": 32, "peak": 11},
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
STRUCTURE_HOLDBACK = 0

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
# MEASURED: post-opening expansion is the single most expensive thing this agent does.
# From an identical d5 state, switching only `HERD_BUY_FROM_DAY` cost **$16,775**
# (`state_value --cross`), and `HERD_BUY_UNTIL=5` beat `18` by **+$16,596 median over
# 36 paired games (35/36, p=0.0000)** -- which is the entire difference between the
# opening package being -$15,230 and +$7,410. The season `HERD` targets above are
# therefore only reachable if a later experiment shows an expansion that pays.
HERD_BUY_UNTIL = 5
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
