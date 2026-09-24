# F3+ Plan — Adopt DSM's measured herd / shed / sell-timing / late-game behavior

## Goal
Close the throughput+price gap to DSM by implementing the four **replay-validated** DSM behaviors in `src/main.py` (never `route_tape.py`), stepwise, each judged on same-seed **WIN** vs PA 2,3,5 plus audited defect columns. Target: flip the razor-thin losses (~−$200…−$500) to wins; do not regress wins.

## Validated evidence (grounding)
- **Price-at-sell (qty-weighted market price at each SELL step):** DSM vs us — MILK 94.8/81.0, STRAWBERRY 167.6/105.1, MELON 205.0/120.7, WOOL 172.8/72.8.
- **Herd/care:** SHEEP 0.8/6.1, GOOSE 5.8/2.2, COW 6.9/8.2; plants_fertilized 236.8/125.1.
- **Shed:** DSM `max_shed_total` ~88–94 from day 13; ours lags to ~d19.
- **Late:** DSM `weeds_max` d28/29 = 5.94/10.44 vs ours 4.53/0.53.

## Current state (assumptions / preconditions)
- `src/main.py` currently carries an **uncommitted** sheep→cow cap (`_v231_controller`) that cut WOOL floor 73% but raised MILK floor +36%, `floor_sales` +17%, money −2.4% ⇒ **net regression; not promotable**.
- `src/agent.py` = identity. `diagnose/report.py`, `docs/TOP_PLAYER_GAP.md` modified; `tools/{missed_work,leverage,idle_pool}.py` untracked.
- **Assumption:** validation baseline for main.py changes is `diag-replays/run-5` (unmodified main, PA 2,3,5, seeds 700–711, 36 games).

## Validation methodology (applies to every step)
Because changes are in `main.py`, `--compare`/`--xray` are **invalid** (old==new). For each step:
1. `PYTHONPATH=. .venv/bin/python -u -m diagnose --old --pa 2,3,5 --batch 12 --seed 700 --run-dir diag-replays/<step>` (modified main as `old`).
2. Diff that `games.csv` vs the frozen baseline on the step's target column(s) and the guards (`sell_revenue_total` ≥ −10%, `shed_overflow_days`, `discarded_units_total`, `animal_escapes`, `premium_below_base_frac`, `stranded_at_bell`) + per-seed WIN/LOSS.
3. **Accept** a step only if its target defect improves AND no win flips to a loss. On accept, copy the run as the new frozen baseline; else revert the step.

## Step 0 — Freeze baseline + build a read-only measuring tool (no behavior change)
- Revert the uncommitted sheep→cow cap in `main.py` (`git checkout -- src/main.py`) so we start from the true baseline.
- Add `tools/footprint.py` (read-only) that, for a run dir or `replays/DSM`, reports per-game: shed `max/end` per day, `weeds_max` per day, `plants_fertilized`, per-species endgame counts, and qty-weighted **price-at-sell** per product (from replay `market.prices` + SELL orders). This is the decision readout for every later step and the tool that proved the four claims.
- Accept: tool reproduces the validated DSM-vs-us table above.

## Step 1 — Herd composition: sheep → **GOOSE** (not COW)
**Problem:** we run 6.1 sheep (wool ~54% of base) vs DSM 0.8; my cow-cap simply moved the glut to MILK.
**Location:** `_v231_controller` ([main.py:1350–1417](src/main.py#L1350-L1417)) — convert surplus `BUY_ANIMAL SHEEP` to **`GOOSE`** (EGG never floors: 106% of base; DSM GOOSE 5.8). Goose needs `BUILD_COOP`; if no empty coop, fall back to **reducing** the sheep buy (not converting) rather than `COW`.
**Mechanism:** keep `_V231_SHEEP_KEEP≈2`; convert/trim the surplus sheep buys at the day-8/9 tape ramp (read-only tape) only while a coop slot can host a goose and `feed_surplus` headroom exists (goose = 1 wheat/day; cheap).
**Guards:** no double cow herd; `animal_escapes`/feed_surplus/MAX_ORDERS preserved; opening days 0–7 untouched.
**Accept:** SHEEP→~1–2, GOOSE up, WOOL floor_sales down, **MILK floor_sales not up**, money ≥ baseline, no win lost.

## Step 2 — Crop fertilizing expansion (toward DSM's 236)
**Problem:** `plants_fertilized` 125 vs 236.
**Location:** `_v9_fert` ([main.py:3092](src/main.py#L3092)) currently fertilizes only WHEAT/CARROT at age 1 from day 14; extend to the full profitable window for all non-ongoing crops (and the strawberry/melon yield window) using `_r37_market_price('FERTILIZER')` vs the crop's marginal units — i.e. spend fertilizer on crops while a fertilized unit out-earns selling the fertilizer.
**Guards:** only spend fertilizer an idle carrier already holds; never pre-empt a tape `FERTILIZE`; keep shed/feed untouched.
**Accept:** `plants_fertilized` rises materially, crop revenue up, money ≥ baseline, no win lost.

## Step 3 — Sell timing: capture non-floor prices (the biggest $ lever)
**Problem:** we sell MILK/STRAWBERRY/MELON/WOOL far below DSM's prices (shed is full of glut at $1).
**Location:** `layer_10_r36_sale` ([main.py:1532](src/main.py#L1532)) + `layer_11_r37` (`_r37_quote_priority`/`_r37_reorder_sales`, [main.py:1584–1629](src/main.py#L1584-L1629)); the marginal-price model already exists.
**Change:** a **capacity-aware hold**: defer a SELL when `_r37_market_price(item, inv+qty) ≤ base·hold_frac` **and** projected shed has room; force-sell when shed pressure or terminal. Spend the freed early-game turns (exposed as idle by `tools/leverage.py`) on harvest/collect instead. Must be sequenced **after Step 1** so reduced gluts don't overflow (the E1 gate failed because production wasn't reduced first — state this as the explicit lesson).
**Guards:** `shed_overflow_days`/`discarded` must not regress (this killed the prior hold gate); `stranded_at_bell` ≤ baseline.
**Accept:** price-at-sell up for ≥2 of {MILK, STRAWBERRY, MELON}, `floor_sales` down, `sell_revenue_total` ≥ −10% and ideally up, no win lost.

### Step 3 — MEASURED (done; landed as the `_hold_apply` layer at the top of `main.py`)
**What the defect actually is.** Audit of 8 PA2 seeds (forced-goose arm): floor units
($1) = STRAWBERRY 337, WOOL 162, MILK 53; below-base units = FERTILIZER 2352,
MILK 992, STRAWBERRY 832, WOOL 532. At the floor sales the shed held only **~30–40
of 100** (plenty of room) and the live price was **$3–41** — so the floor units are
the **tail of an oversized SELL batch walking the price down**, not an overflow dump.
**What worked.** A general price-impact **trim** (not a full hold): keep the prefix of
each order whose marginal unit clears a threshold (`max(base·frac, $2)`), hold only the
tail, capped at 3 units/product, shed ≤0.88·cap, release at/after step 672. Paired vs
the no-hold arm on 8 seeds: `floor_sales` **−1.6/game**, `discarded`/`shed_overflow_days`
**flat**, `sell_revenue_total` −0.01%, margin ±0 → **passes the guards but is a micro
fix**. Wins unchanged (0/8 both arms).
**What failed.** A full capacity-aware hold (the original Step-3 wording) at cap 20/30
**regressed**: shed_overflow_days +0.6–1.0, discarded +0.4–9, margin −$250…−$4.6k, floor
barely moved — held units accumulate and overflow at the day-end drop. This is the
sequencing lesson again: do **not** raise `KAGGICULTURE_HOLD_CAP` without re-checking the
overflow guard.
**Still open (the real levers).** (a) WOOL: we still run 4–7 sheep under forced-goose —
the conversion fires only at HD2's single anchor, so later sheep buys survive; convert
every sheep buy (or cut the herd) to remove the 162 floor + 532 below-base units.
(b) FERTILIZER: 2352 units at 49% of base while `plants_fertilized` is ~125 vs DSM 236 —
Step 2 (fertilize instead of dump) is worth far more than any sell-timing change.

## Herd hold / release — MEASURED (`tools/herd_hold.py`)

New read-only tool: per-day COW/SHEEP/GOOSE + feed + escapes + animal-product
selling/floor, DSM vs ours side by side (`python -m tools.herd_hold --compare`).

**What DSM actually does (n≈8–12 LB replays).** He does *not* run a small herd —
he peaks at **~23.8 head** (COW 7.5 / SHEEP 8.0 / GOOSE 7.4), *more* sheep than us,
then lets them go from ~day 16–20: fed drops 10.8→0.2 over d27–29, **~10.7 animals
escape**, end herd ~11.1 (C4/S2/G5). Our no-release arm holds **15.0 flat to the
bell** and releases 0.1.

**But the carry is already level:** DSM wheat_fed 380 ($9,493) vs ours 343 ($8,566);
animal revenue DSM ~$45.3k vs ours ~$44.6k; **carry DSM $35.8k vs ours $36.0k**. So the
release is not where his edge is.

**His floor advantage is STRAWBERRY, not animals.** Floor units/game: DSM **9** vs ours
**67** — and ours is STRAWBERRY 41 + WOOL 20 + MILK 7. DSM's WOOL/MILK floor is 4+3.
Price-at-sell: DSM STRAWBERRY **154.9** vs ours **118.0** (his WOOL 108 / MILK 83.5 are
actually *lower* than ours). STRAWBERRY is an ongoing crop, so the lever is the crop
side (Step 5: stop watering late / let fields weed — DSM `weeds_max` d28/29 ≈5.9/10.4
vs ours ≈0.5), not the herd.

**The release, implemented and rejected.** `_release_apply` drops FEED/CARE from day 27
(position-safe: both are stationary). Paired on 8 PA2 seeds vs the same code with it off:
escapes +14.9, `sell_revenue_total` **−$2,324/game**, margin **−$2,708/game**,
`floor_sales` only −2.1, discarded +2.4, `shed_overflow_days` +0.5, wins 0→0 ⇒ **default
OFF** (`KAGGICULTURE_RELEASE=1` re-enables; try releasing only WOOL species and/or a later
start). Our 15-head herd still earns above its feed cost, so dropping it just burns
production.

## Crop abandonment (Step 5) — MEASURED, default OFF (`_abandon_apply`)

Stops `WATER` on ongoing crops (STRAWBERRY, TOMATO) from a cutoff day, position-safe
(WATER→PASS). It **does** hit the target: paired on 8 PA2 seeds vs the same code off,
`floor_sales` **−12.2** at day24/frac1.0 and **−5.8** at day26/frac0.6, with
`shed_pressure_days`/`shed_overflow_days`/discards all improving. But it always costs
margin, because our STRAWBERRY already sells at **~118 (98% of base)** — only ~41 of 232
units floor, so killing the crop to save those throws away the good units, and the rival
captures the premium we stop dumping:

| config | floor | revenue | margin | plants_died |
|---|---|---|---|---|
| day24, frac1.0 | −12.2 | −$1,026 | **−$1,814** | +6.8 |
| day26, frac0.6 | −5.8 | −$302 | **−$569** | +5.6 |

Wins unchanged (0/8 both) ⇒ **default OFF** (`KAGGICULTURE_ABANDON=1`, `_FROM`, `_FRAC`,
`_CROPS` to tune). Conclusion: the floor tail is real but too small to pay for removing
the crop; the same ~41 units are better attacked on the sell side (the `_hold_apply`
trim, margin-neutral) or by fixing why we overproduce STRAWBERRY at all.

## Step 4 — Shed utilization / early production ramp
**Problem:** DSM packs the shed from d13; ours lags (less early volume extracted).
**Location:** herd/crop build schedule in `layer_08_v31_core`/`layer_24_v9_herd` and the room/sell guards ([main.py:577–684](src/main.py#L577-L684)); use `tools/idle_pool.py` to find unused early hand-turns.
**Change:** only after Steps 1–3: shift some production earlier (goose/crop placement) so `max_shed_total` reaches the DSM band (~85+) by d13, without changing total season spend.
**Accept:** `max_shed_total` d13–d29 closer to DSM; `discarded`/overflow flat; money/WIN not worse.

## Step 5 — Late-game extraction (abandon crops to weeds, focus selling)
**Problem:** we keep watering late (weeds d28–29 ≈ 0.5–4.5) while DSM lets fields weed (5.9–10.4) and extracts.
**Location:** the field-watering schedule (general path around `layer_04_v28_core`/`layer_15_r51_input`; **not** the v219 tomato path at [main.py:1172](src/main.py#L1172), which is already day<29) + labor routing `layer_17_r53_labor` ([main.py:2215](src/main.py#L2215)).
**Change:** after a validated cutoff (~day 23–24), stop watering non-ongoing field crops and re-route those hands to harvest/collect/deliver/sell; keep watering only crops that still yield before the bell.
**Guards:** never strand stock (`stranded_at_bell` ≤ baseline), never reduce `animal_escapes` margin; keep shop-window sales.
**Accept:** late `weeds_max` rises toward DSM, idle_share down, revenue up, no win lost.

## Risks / edge cases / failure modes
- **Shared market:** holding/selling changes both players' prices; judge on WIN, and re-check the committed sell volume.
- **Overflow** is the historical failure mode of holding → Steps 1→3 ordering and shed-room guards are mandatory.
- **Tape is read-only:** all changes are layers/guards over the tape; never edit `route_tape.py`.
- **Latent first-mover risk:** delaying sales could let the rival grab the top price → validate per-opponent, keep a bounded hold cap + endgame cutoff.
- Each step is independently revertable (`git checkout -- src/main.py`).

## Deliverables
- `tools/footprint.py` (new, read-only).
- Stepwise `src/main.py` edits, each only promoted after a passing same-seed WIN + defect comparison.
- An updated `docs/TOP_PLAYER_GAP.md` section recording, per accepted step, the before/after DSM-vs-us table.
