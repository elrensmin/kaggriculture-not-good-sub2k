# TODO — Boey clone (goal round 1→2)

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

## Next (round 4)

- [ ] **Revenue variance first** (`--public` at d10: money spread 1,562 %). A state we reach on
      his replays is not one we reach against the field.
- [ ] **WHEAT vs STRAWBERRY trade** — `STRAWBERRY_PEAK=11` fixes straw (worse→−13.6 %) but
      costs wheat (−3.8 %→−19.2 %). Find the mix that holds both.
- [ ] **FILL / crew turns** — planted 46 vs 55, empty 10 vs 0: the kernel (`moves/act` 1.5 vs 0.8).
- [ ] **`--public` variance run + d15 checkpoint** once d10 is as close as the knobs allow.

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
