# TODO — Boey clone (goal round 1→2)

## ROUND 7 — LIMITING FACTORS: it is CASH INFLOW, and it always was

New tool: **`tools/phases/limiting.py`** — runs the same episodes in lockstep (`HIS` =
recorded actions, `OURS` = our agent in his seat from d0) and prints, per day, CASH / LAND /
LABOUR / ACTION plus a per-day verdict naming the binding factor. It prices the market
orders off the observation's own price table, so the flow is attributable without the audit.

```
PYTHONPATH=. python -m tools.phases.limiting --n 12 --days 0-11 --workers 4
```

### Revenue by product, d0–d11, summed (order value; ours vs his)

| product | OURS | HIS | ratio |
|---|---|---|---|
| FERTILIZER | 7,397 | **71,244** | 0.10 |
| WHEAT | 6,875 | **65,412** | 0.11 |
| MELON | 7,236 | **44,117** | 0.16 |
| CARROT | 0 | **17,760** | 0.00 |
| MILK | 5,517 | **16,186** | 0.34 |
| EGG | 861 | **11,133** | 0.08 |
| WOOL | 3,503 | **7,771** | 0.45 |
| **TOTAL** | **~31k** | **~233k** | **0.13** |

**He out-earns us ~8x every single day from d0**, and it is not one product — it is every
line. Our SELL orders on d6–d10 total 1,030 / 1,225 / 1,688 / 3,114 / 2,352 against his
14,643 / 10,070 / 27,326 / 22,670 / **68,364**.

### The other three factors are NOT binding

| day 7–10 | OURS | HIS |
|---|---|---|
| EMPTY owned tiles | 16 / 10 / 18 / 11 | 0 / 6 / 0 / 1 |
| unit-turns | 206 / 206 / 250 / 293 | 161 / 253 / 253 / 286 |
| PASS | 11 / 8 / 0 / 0 | 10 / 9 / 4 / 4 |
| moves per act | 1.80 / 1.78 / 1.62 / 1.52 | 1.08 / 0.90 / 0.78 / 0.93 |

* **LAND is not binding** — we hold 10–18 paid-for EMPTY tiles while he holds ~0–1.
* **LABOUR is not binding** — our unit-turns are *higher* than his and our PASS is *lower*.
* **ACTION (walking) is real but secondary** — moves/act 1.5–1.9 vs his 0.8–1.1. Fixing it
  cannot close an 8x revenue gap.

### Consequence for the plan

The herd is the engine (MILK+WOOL+EGG+FERTILIZER ≈ 106k of his 233k) and **feed is what
turns it**: his feed spend is 4–12x ours (d10: 10,960 vs 539). We buy fewer animals than
him AND lose the ones we buy (`structs` 12 vs 20 at d10, animals 9 vs 20), so the herd never
compounds. Cash -> feed -> herd -> animal products + fertilizer + surplus wheat -> cash. We
are not in that loop.

**Next, in order:**
1. Why is our SELL volume 10x low — do we lack the goods, or not sell them? `shed_total` at
   d10 is 38 ours vs 53 his, so we hold stock; measure per-product `shed` vs SELL orders.
2. Why does the herd not compound: animals bought is comparable (9.3k vs 12.7k of orders)
   but structs 12 vs 20 and animals 9 vs 20 at d10. Find the escape / unfed path.
3. Only then re-open the walking kernel (moves/act), which is a d11+ symptom.

## Next (round 6 — crew-turn kernel)

Reference = Boey (`replays/Boey/v1`). Fast screen `--pa 2,3 --batch 4` (8 games);
**confirm 96 games before shipping** — 8-game screens have flipped sign repeatedly.
Causal instruments: `tools/phases/{dag,divergence,boey_model,propagate,target_check,turn_budget}.py`,
`tools/labour/{crop_cycle,stack_trace,hop_regret}.py`.

## Open — d10 checkpoint worklist (ordered; 3/13 within 1 %)

- [ ] **#1 d10 REVENUE VARIANCE (new, from `--public`).** Against the 12 public opponents at
      d10 our money is **median 8, p10 0, p90 125 — a 1,562 % spread**, strawberry 48 % and
      wheat 35 %. Boey holds 9,653. Low median AND high spread: the state we reach on his
      replays is not the state we reach reliably. Fix variance before chasing the median.
- [ ] **#2 CASH unlocks 3 metrics.** money −99.9 %, animals −50 %, structs −40 % all move
      together and are gated on holding cash at d10 ($13 vs $9,555). The lead:
      `WHEAT_TILES_PER_ANIMAL_P2=1.2 + FEED_STOCK_DAYS_P2=2 + FEED_BUY_CHUNK=40` raises
      **sell revenue +$31,829 (0/8 worse)** but costs −$10,593 median because the bought feed
      costs more than the herd earns. **Fix the feed bill, not the herd.**
- [ ] **#3 FILL — planted 46.5 vs 54.5, empty 12 vs 1.** Crew-turn-gated. `P_PLANT_P2=120`
      buys planted 46.5→49 and empty 12→7.5 but pushes straw to +7.9 %; `PLANT_GLOBAL=1`
      makes it worse. Needs the kernel, not a priority knob.
- [ ] **#4 WHEAT 22.5 vs 28 (−19.6 %), STRAWBERRY 18.5 vs 20.5 (−9.8 %)** — 2–6 tiles, same
      crew limit. `WHEAT_TARGET=36` and `STRAWBERRY_TARGET=32` do not bind.
- [ ] **#5 `yarn` 0 vs 0.5** — shop-draw RNG our empty tiles move; not a policy defect.

## Shipped at the d10 checkpoint (state-first; each one param to revert)

- [x] `LAND_CASH_RESERVE_P2 = 0` — empty 19.5→8, wheat 17→22, planted 43→48. **−$7,586 season.**
- [x] `HARVEST_AGE_MELON = 10` — MELON 9→5 (**0 % vs his 5**), shed −39.7 %→−6.8 %.
      **−$5,299 season.**
- [x] `TOMATO_TARGET = 0` — TOMATO 2→0 (**0 %**, he runs none). Free.
- [x] **FEED-CHURN FIX + 4-part herd bundle — `+$10,218 median`.** The bugs:
      (a) `herd_plan` sized the feed stock from the SHED alone, so units carrying wheat made
      the shed look empty and it rebought every turn; (b) `sell_policy`'s wheat reserve did
      not include the feed stock, so it liquidated what the herd had just bought. Together
      they bought **+$45,029 of product and fed 24 more units**. Fixed → `product_cost`
      64,356 → **21,596**, final money 34,119 → **57,692**. Shipped with
      `WHEAT_TILES_PER_ANIMAL_P2=1.2`, `FEED_STOCK_DAYS_P2=2`, `FEED_BUY_CHUNK_P2=40`,
      `STRAWBERRY_PEAK=11` (NOT separable — the gate+stock alone is **−$5,448**).
- **Checkpoint status: 5/13 within 1 % at `--all` 357 episodes**
  (melon, tomato, carrot, quadrants, yarn). Remaining: money −99.9 %, animals −50 %,
  structs −35 %, empty +10, planted −16.4 %, wheat −19.2 %, straw −13.6 %, shed −13.7 %.
  **Whole d10 bundle vs the original tree: −$2,703 median** (the state-first trade), with the
  feed-churn fix recovering ~$8k of it.

## NEW INSTRUMENT — `tools/phases/checkpoint.py` (run this after EVERY change)

The old loop judged arms on "terminal money 19 days after a d10 transplant, 8–12 games".
That has a ±$8k noise band and the effects are ±$2k, so ~22 arms this session were read as
"no change" — and 20 of them were judged on **d11–29** while the objective is **d6–10**.
That is why the session stalled. This tool replaces it:

```
PYTHONPATH=. python -m tools.phases.checkpoint --n 24 --cut-day 10 --workers 4 \
    --metric money,animals,structs,planted,empty,wheat,straw,shed_total,cash_flow
```

It runs the same episodes twice in lockstep — `HIS` (recorded actions both seats) and
`OURS` (our agent in his seat from d0) — and prints each metric **per day**, plus **the
first day each gap exceeded 1 %**. `cash_flow` is derived (day-over-day money change) and
is the column that says *when* the revenue gap opens.

## THE DIAGNOSIS (measured 2026-09-30)

The d6–10 window, medians over 24 episodes:

| day | planted ours/his | animals ours/his | structs ours/his | empty ours/his | cash-flow ours/his |
|---|---|---|---|---|---|
| 5 | 15 / 15 | 7 / 10 | 8 / 10 | 2 / 0 | +347 / −1 |
| 6 | 15 / 15 | 8 / 10 | 8 / 10 | 2 / 0 | +96 / +10 |
| 7 | 16 / **34** | 9 / 14 | 9 / 14 | 0 / 2 | +543 / −16 |
| 8 | 24 / 35 | 9 / 15 | 9 / 15 | **16 / 0.5** | −872 / +5 |
| 10 | 40 / 54.5 | **9 / 20** | **11 / 20** | **19 / 0.5** | −343 / −349 |
| 11 | | 10 / 20 | | 10 / 1 | **−2 / +9,403** |
| 12 | | 11 / 20 | | 4 / 0 | +3,286 / +4,908 |

1. **The money gap at d10 is ONE DAY: d11.** He books **+$9,403**, we book **−$2**. That
   single day is the whole $9,547 gap. It is the MELON block.
2. **Mechanism, verified per-episode (4/4 identical):** at the d10 snapshot he holds
   **10 melon tiles, 7 of them at `planted_day 0` (age 10, yield 42)**; we hold 9, only
   **4 at `planted_day 0`**, the rest at `planted_day 1` (3) and `2` (2). On d11 the age-10
   tiles are harvested — 7 tiles (42 units, ~$9.4k) against our 4 (24 units).
3. **The opening table is already right** (`src/opening.py::CROP_BY_DAY` asks 7 MELON on
   d0, 7 on d1, 10 on d2). **The execution plants 4 / 3 / 2.** So this is an opening
   *execution* defect surfacing at d11 — not a schedule to re-tune, and not a midgame
   walking problem.
4. Independent, compounding: **animals 9 vs 20 and structs 11 vs 20 open at d3** and never
   close (he adds 10 animals d5→d10, we add 2); `quadrants` opens at d7 (land one day late);
   `empty` reaches 19 tiles vs his 0.5 by d10.

**Everything in the "crew-turn kernel" section below is a d11+ symptom and is NOT the
checkpoint blocker.** Keep it for later; do not spend more rounds on it now.

## Next
- [ ] Fix the d0 melon execution: why does the tape ask for 7 MELON on d0 and plant 4?
      (`src/opening.py` jobs vs the crew's ability to reach the tiles / the seed basket /
      the herd holding the near tiles). Verify with `checkpoint --days 0-3 --metric melon`.
- [ ] Then the d3 animals/structs gap (5/7 → 9/20).
- [ ] Every arm: `checkpoint` first, on the 13 metrics and the day they open.

### The ledger (new tools, 2026-09-30)

Two new diagnostic tools, both `python -m`:
`tools/labour/conversion.py` (does an assigned job ever LAND, and where the walk dies) and
`tools/labour/crew_audit.py` (one screen: turn budget, walks, day edges, hop regret,
conversion, cost sheet — comparable across arms).

`crew_audit --days 11-17 --max-games 4`, ours vs his play on HIS OWN d10 farm:

| metric | HIS | OURS |
|---|---|---|
| unit-turns | 7,678 | 8,217 |
| acts | 4,387 (57 %) | 3,672 (45 %) |
| moves | 3,114 (41 %) | 4,543 (55 %) |
| walk runs | 2,207 | 2,126 |
| **mean walk** | **1.41** | **2.14** |
| walks ≥6 tiles | 0.4 % | 8.1 % |
| first walk of day | 0.74 | 0.15 |
| **LAST walk of day** | **1.01** (≥6: 1.2 %) | **2.34** (≥6: **16.8 %**) |
| avoidable-by-nearest (claims excluded) | 22.1 % | **27.5 %** |
| WATER ops | **1,234 @ 1.01 mv/op** | **596 @ 1.59** |
| COLLECT_FERTILIZER mv/op | 0.85 | **2.39 (31.6 % of all our moves)** |
| FERTILIZE mv/op | 0.13 | **2.36** |

**Same number of walks; ours are 0.73 tiles longer.** 27.5 % of the walking was
avoidable-by-nearest; 19 % of it is the dead end-of-day walk.

### Conversion (OUR replays only — it re-derives `scheduler.plan`)

4,201 intents, 84 % carrying. **LANDED 28.7 %, DIVERTED 40.6 %**, OTHER_AT_TILE 23.7 %,
DAY_END 5.6 %, LOST 1.4 %.

Diversion reasons: **ON_TILE 49 %** (pulled to work underfoot mid-walk),
**TAKEN_BY_OTHER 45 %** (two units on the same tile), OTHER 3 %, HIGHER_PRIORITY 3 %.
Per op: WATER 646 ep / 341 landed (53 %) / 0.72 tiles per landed water;
FEED 1,279 ep / 157 landed (12 %) / 655 diverted.

### What is now CLOSED (measured, do not retry)

| arm | result |
|---|---|
| `BAND_CRITICAL_BYPASS_P2=1` | WATER 279→285, died 50→50 — **inert** |
| `CARRY_DELIVERY_MARGIN_P2=40` | transplant +$3.6k/12 eps, **but d10 checkpoint regresses** (planted 47→44, animals 10→9) |
| `HORIZON_FILTER_P2=1` (reachability) | moves 4,543→4,417, money −53,762 ≈ base. The dead end-of-day walks are **not** to far jobs |
| `BONUS_WALK_WEIGHT_P2=20` | **byte-identical** — FERTILIZE is not chosen by the score |
| `EXACT_ASSIGN=1;MOVE_WEIGHT=8;DIST_CAP=8;SLICE_PENALTY=15` | −50,818 (12 eps); regret 27.5→25.6 % only |
| `USE_SLICES_P2=0;MOVE_WEIGHT=8;DIST_CAP=8` | −53,786 |
| `BAND_LOSS_TOL_P2=0` | **−48,736 (8 eps) — best kernel arm so far, not yet re-run at 12** |
| `SAME_TILE_FIRST=0;SAME_TILE_ORDER=1` | **−111,456** (collapse) |
| `SAME_TILE_COMPARE_P2=1` (reservation must win) | **−106,370** (collapse — reservation is load-bearing for locality) |
| `SAME_TILE_MIN_PRIORITY_P2=100` | −71,101 |
| `P_WATER_SURVIVAL_P2` 110/130, `P_WATER_BONUS_P2=140` | −56.5k / −61.5k / −55.5k, **delivered water moves <4 %** |

**The last row is the finding: PRIORITY IS NOT THE BINDING CONSTRAINT.** Water is already
the top of the table (120/90) and raising it changes the delivered count by <4 %. The crew
physically cannot reach more thirsty tiles, and the reason is the assignment/visit
structure, not the ranking.

### THE DECISIVE NEGATIVE RESULT (2026-09-30)

Water is **already the top of the priority table** (BONUS 120, SURVIVAL 90) and:

* `P_WATER_SURVIVAL_P2` 110 / 130 and `P_WATER_BONUS_P2=140` move the delivered water
  count by **<4 %** and the margin by −$2k…−$8k. **Ranking is not the constraint.**
* Every rule that lets a unit abandon the work on its own tile to chase off-tile work
  **collapses the farm**: `SAME_TILE_FIRST=0;SAME_TILE_ORDER=1` → −$111,456;
  `SAME_TILE_COMPARE_P2=1` → −$106,370; `SAME_TILE_CRITICAL_BREAK_P2=1` → −$106,370
  (identical, because with 40+ thirsty tiles there is almost always a critical water
  off-tile, so the break fires for every unit). Baseline −$53,402. Walks fall 2,126 → 260.

So the crew must be **positioned** on the thirsty tile, not persuaded to walk to it. The
deficit is a day-structure problem: the reference *dwells* on a crop tile and its next
decision is made from there (`tiles/ep` 0.23 for WATER against our 1.20), while we make
every decision from wherever the last job left us. **The next change is a route/visit
plan — a state-derived work order that walks the crop rows — not another priority.**

### Next hypotheses, in order

1. **`TAKEN_BY_OTHER` 45 % of diversions.** Two units walk to the same tile across turns.
   `claimed` is per-turn only. Test a cross-turn, state-derived claim: a tile another unit
   is *adjacent to and eligible for* is not offered again this turn, or rank candidates by
   `d` with a real (uncapped) tie-break so the second unit picks its own nearest.
2. **`ON_TILE` 49 %.** The reservation's locality is load-bearing (disabling it costs
   $58k) but its priority blindness costs the water. Try: keep the reservation, but let a
   *critical* off-tile job break it (the earlier `BAND_CRITICAL_BYPASS` only covered the
   band wall, not the preop).
3. Re-measure `BAND_LOSS_TOL_P2=0` at 12 eps and on the d10 checkpoint — it is the only
   kernel arm that beat base, and it is exactly "nearest job wins among equals".

## Next (round 5)

- [x] **Kernel re-decomposed (2026-09-30). The old decomposition was wrong; this is the
      measured one.** On the transplant (`--save-dir` + `move_trace`, d11–17, control exact):

      | | his | ours |
      |---|---|---|
      | unit-turns | 7,678 | 8,216 |
      | acts | 4,387 (57 %) | 3,584 (44 %) |
      | moves | 3,114 (41 %) | 4,623 (56 %) |
      | **moves per act** | **0.71** | **1.29** |
      | ops per stop | 2.15 | 1.83 |

      **Every op costs us ~+0.6 moves, not one op.** WATER 1.03→1.75, COLLECT 0.87→2.46,
      FERTILIZE 0.09→2.61, CARE 0.40→0.79, PICKUP 0.93→1.19, DROP 0.46→1.25.
      Verified today: `pickwhy2.py` (every `_pick` call logged, d12, 1 episode) shows
      **26 WATER jobs outstanding per turn** (42 unwatered tiles, all inside some band) and
      **70 % of `_pick` calls (141/201) restricted to FEED/PLACE/FERTILIZE** — the
      `only_delivery` wall. Neither the band wall nor the feed pickup is the main driver.
- [x] **`BAND_CRITICAL_BYPASS`** — built, measured, **no effect** (WATER 279→285, died 50→50).
      The wall is real but not binding: 44/60 free calls already chose water.
- [x] **`CARRY_DELIVERY_MARGIN`** — built, measured, **do not ship**. Softens `only_delivery`
      from a wall to a penalty. Transplant d11–17, 12 eps: −$53,402 → −$49,814 (+$3.6k of a
      ~$50k gap), WATER 1,766→1,881, `died` 50→43.5. **But the d10 checkpoint gets WORSE**
      (planted 47→44, animals 10→9, 4/13 either way). A d11+ gain that costs d6–10.
- [ ] **THE ACTUAL BLOCKER, d6–10 and d11+ are the same defect: crop attrition.**
      From HIS OWN d10 state we are at exact parity at d11 ($10,405 vs $10,534) and then
      `planted` goes **52.5 → 25.5** by d17 while his goes 53 → 52; `died` **50 vs 9**;
      WATER **279 vs 832**. We lose half the farm. Everything downstream (money, shed,
      wheat, animals) follows from that.
- [ ] Current checkpoint: **4/13 within 1 %** at `--n 24`. Gap: animals 10 vs 20,
      structs 13 vs 20, planted 47 vs 54.5, empty 10 vs 1, wheat 21 vs 28, money $8 vs $9,555.
- [ ] **Next: why can't the crew cash the water it is offered?** 26 jobs outstanding, 12
      units, 15–25 waters/day delivered, each act costing 1.29 moves. Measure the
      pick→walk→act conversion (how many picks per executed water and where the walk is
      abandoned) before touching anything else.

## Closed (round 5)
- `CARRY_BAND_LOCAL_P2=1` (new, off) — COLLECT 2.35→2.18, final worse (−$60,791 vs −$53,402).
- shed-loop 3 knobs on the transplant — PICKUP 280→219, DROP 187→173, but MOVE rose 3,124→3,221.
- `FERTILIZE_ONESHOT_ONLY=0;FERTILIZE_ONGOING_ONLY=0` — FERTILIZE ops 42→72 of his 204; no gain.
- `SAME_TILE_CROP_CHAIN_P2=1` — FERTILIZE 2.70→2.61 mv/op, money −$79,494 (no change).
- `FEED_PICKUP_INFLIGHT_P2=1` — PICKUP 366→137 but MOVE 4,623→4,899, died 50→49.5. No gain.
- `BAND_CRITICAL_BYPASS_P2=1` — WATER 279→285, died 50→50. Inert.
- `CARRY_DELIVERY_MARGIN_P2` 0/20/40/80 — best on the transplant is 40 (+$3.6k / 12 eps),
  but it **regresses the d10 checkpoint** (planted 47→44, animals 10→9). NOT SHIPPED.

## Closed — do not retry

- `PLANT_CAP_BY_SEEDS_P2=1` — **inert**. `SEED_FILL_BUFFER_P2=1` — **harmful** (spent the land
  money: money 592→5.5, quadrant 3→2).
- `WHEAT_TILES_PER_ANIMAL_P2=1.2;FEED_STOCK_DAYS_P2=2` alone — no cash to buy; animals stayed 10.
- `PLANT_GLOBAL=1` — planted 46.5→43.5, worse.
- `TRADE_MIDGAME=1` at d10 — no cash effect, wheat worse.
- `P_PLANT_P2` 105/120 — moves planted/empty but costs straw; net no better than 5/13.
- `WHEAT_TARGET=36`, `STRAWBERRY_TARGET=32` — do not bind.

## Open (carried)

- [ ] **5-DAY CHECKPOINT METHOD (from 2026-09-29).** Clone the reference's state 5 days at a
      time: `PYTHONPATH=. python -m tools.phases.transplant --ref-from replays/Boey/v1 --n 24
      --cut-day N --mode treatment --prefix ours --workers 8`. Target **<1 % per metric**
      before advancing. **d5 PASSED** (planted 15=15, straw 4=4, quadrants 1=1).
- [ ] **d10 CHECKPOINT: 3/13 within 1 % (was 2/13).** Baseline vs his: planted 43/54.5,
      empty 20/1, WHEAT 17/28, animals 9/20, melon 9/5, money 632/9555.
      **Shipped `LAND_CASH_RESERVE_P2=0`** → planted 48, empty 8, wheat 22, within-1% 3/13.
      **Cost: −$7,586 median season, target_check still 0/16** — deliberate state-first trade,
      one param to revert.
- [ ] **The d10 wall is CASH.** After the land fix we hold **$22** at d10 against his $9,371,
      so the herd (9 vs 20), the feed stock and the 3rd-quadrant fill cannot be funded.
      `WHEAT_TILES_PER_ANIMAL_P2=1.3` + `FEED_STOCK_DAYS_P2=2` did **nothing** (animals stayed
      10) because there is no cash. The remaining d10 gap is the §3.8 revenue/kernel gap, not
      a scheduler knob.
- [ ] **`MELON` +80 % at d10 (9 vs 5).** We hold melon longer than he does. `HARVEST_AGE_MELON`
      (implemented, shipped off) is the untried lever here.
- [ ] **Seed path — CLOSED, do not retry.** `PLANT_CAP_BY_SEEDS_P2=1` is **inert** (the flat
      `SEED_BUFFER`, not the request count, limits planting); `SEED_FILL_BUFFER_P2=1` is
      **harmful** (money 592→5.5, quadrant 3→2: the seed spend starved the land buy).
- [ ] **THE GAP IS POLICY, NOT STATE — settled.** Handed Boey's own d10 state in his own game,
      our policy still loses **−$59,966 median (0/24)**. Control reproduces **24/24 exactly**.
      Cut sweep: −$67.5k @d6, −$60.0k @d10, −$52.9k @d14; the rate signature
      (`moves/act` 0.8→1.5–2.0, `died` 5–6×, `WATER` ~40 %, `FERTILIZE` ~20 %) is identical at
      every cut → steady-state kernel, not a re-plan. Phase 1 needs no changes (worth $152).
- [ ] **Round 3 target: the three policy numbers, on the fixed-state loop.** d11–17 medians
      (his → ours): `moves/act 0.80 → 1.50`, `WATER 784 → 307`, `FERTILIZE 204 → 40`,
      `died 9 → 52`, `HARVEST 470 → 283`, `PICKUP/DROP 118/73 → 272/194`. FEED/CARE are
      already at/above his (340 vs 309) — it is not a herd problem.
      **Evaluation loop:** `PYTHONPATH=. python -m tools.phases.transplant --ref-from
      replays/Boey/v1 --n 24 --cut-day 10 --workers 8` — one run is 24 fixed-state policy
      measurements, far lower noise than 8-game arm screens. Judge a change on
      `moves/act`/`WATER`/`died` moving toward his, then on the final-money delta.
- [ ] **Why is `moves/act` 1.5 on HIS compact farm?** His board is the one our band
      scheduler should be good at (animals in the ring, 54 planted). The first thing to
      check is whether our policy *immediately* diverges after the cut — e.g. replanting to
      our crop targets, re-hiring, or re-partitioning bands — rather than serving the farm
      it was handed. `transplant --cut-day 14` localises it: if the divergence shrinks with a
      later cut, it is a transient re-plan; if it stays, it is the steady-state kernel.
- [ ] **Shed churn is 2.3× his** (PICKUP 272 vs 118, DROP 194 vs 73) on the same state —
      the fetch/delivery loop, and the only lever left that *removes* turns.
- [ ] **Weed reaping.** Weeds 1→7→10→11 (Boey 0); `P_DIG=20` is the lowest band and
      `COMPLETE_TILE` excludes DIG, so a weedy tile blocks its own replant.
- [ ] **Herd gate is OURS, not his.** Induced buy-rate by wheat/(animals+1) bucket: Boey
      **95 %** at 0.0–0.5 falling to **44 %** at 2.0–2.5; he stocks feed (`BUY_PRODUCT
      WHEAT` up to 68/day vs our 10). Only relevant if state work restarts.

## Tried — measured negative, do not retry

| mechanism | mechanism moved | result |
|---|---|---|
| `BAND_LOSS_TOL_P2` 1 / 3 | regret 29.5→28.2 %, moves/act 1.81→1.79 | −$2,396 / −$2,190 |
| `LAND_CASH_RESERVE_P2` 700 / 0 | planted d8 16→32 | −$7,026 / −$7,586 |
| `FEED_STOCK_DAYS_P2=2;FEED_BUY_CHUNK=40` | animals unchanged (gate blocks) | −$8,316 |
| + `WHEAT_TILES_PER_ANIMAL_P2=0.8` | animals 8/8/10/12/13 → 9/10/13/14/16 | **−$20,572** |
| shed loop (3 knobs) | MOVE 4,434 → 4,287 | −$8,668 |
| shed + land + feed + herd | animals → 16 | −$15,386 |
| `SAME_TILE_CROP_CHAIN` / `COMPLETE_TILE` (+ mp0) | FERTILIZE chained 3.1→3.4 % | −$6.8k…−$8.2k |
| `USE_SLICES_P2=0` | moves/act **1.81 → 2.35** | −$7,064 |
| `HARVEST_AGE_WHEAT=3;MELON=10` | HARVEST 253→456 | −$2,361 |

**Why chaining cannot work:** FERTILIZE is *inventory*-gated, not priority-gated — a unit
can only fertilize while carrying fertilizer, and it usually is not carrying it when it
stands on an unfetrilized in-window tile.

## Findings

- **Clone target is an equilibrium, not a knob.** His `empty` is 0 every day, land arrives
  one quadrant at a time, and the herd runs on bought feed. Every piece moved alone loses.
- **The gate chain:** bare land → wheat base → `WHEAT_TILES_PER_ANIMAL` → herd → 284 missing
  FEED/CARE/COLLECT acts. `herd_gate`: `W` fails d13–d17 with cash and window green.
- **Capacity is the binding constraint.** Unit-turns are identical (3,077 vs 3,044); we do
  half the acts at 1.78 vs 0.77 moves/act. `turn_budget`: Boey's workload needs 16.2 hands
  at our rate, ~10.6 at ≤0.8.
- **`docs/v0-boey` volume figures were requested, not executed.** Shed-capped: wheat 2,542
  (was 6,786), egg 147, fertilizer 487, milk 17.

## Fast commands

```bash
# screen (8 games)
PYTHONPATH=. python -m tools.diagnose --scratch --pa 2,3 --batch 4 --seed 4362837462 --run-dir /tmp/arm
SCRATCH_PARAMS='KNOB=1' PYTHONPATH=. python -m tools.diagnose --scratch --pa 2,3 --batch 4 --seed 4362837462 --run-dir /tmp/arm-x
# causal map
PYTHONPATH=. python -m tools.phases.divergence --pa 2,3 --batch 4 --ref-from replays/Boey/v1 --ref-max 60
PYTHONPATH=. python -m tools.phases.boey_model --ref-from replays/Boey/v1 --ref-max 120 --out-json docs/boey_kg.json --out-md docs/boey_kg.md
PYTHONPATH=. python -m tools.phases.propagate --dir /tmp/arm --set wheat_tiles2=+8
PYTHONPATH=. python -m tools.phases.target_check --run-dir /tmp/arm --ref-from replays/Boey/v1 --ref-max 60
PYTHONPATH=. python -m tools.labour.hop_regret --days 6-17 --dir /tmp/arm --seat 1 --exclude-claimed
```
