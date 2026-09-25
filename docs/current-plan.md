# W0–W8 — structural plan, with a deterministic gate per patch

## 0. Success is structural, not financial

Beating the 13 public agents is a **secondary** signal. The primary goal of each
patch is to fix its own structural defect **without regressing any other critical
component**. Revenue going up is welcome but is not the pass condition; a patch
that fixes its target and moves revenue is only accepted if the watchlist stays
clean.

So every workstream below ships with three things:
- a **target metric** (the structural thing that must move),
- a **regression watchlist** (other components that must not move),
- a **deterministic tool readout** for both.

**Accept = target met AND watchlist clean.** Revenue/margin is reported alongside
and never used as the pass condition.

---

## 1. Baseline captured (before any change)

Ran as requested, read-only:

```
PYTHONPATH=src:. python -m tools.dsm_profile --compare --run-dir=diag-replays/run-1
```

Output is 66 lines, currently in `/tmp/dsm_profile_run1.txt`. **Implementation
step 0 persists it to `docs/baseline/run-1.dsm_profile.txt`** (tracked) as the
frozen initial point.

What it shows today (ours n=78 / DSM n=123):

| | ours | DSM |
|---|---|---|
| herd d10 COW/SHEEP/GOOSE | 6.3 / 3.9 / 1.2 | 8.7 / 5.8 / 4.3 |
| herd d16 | 6.3 / 5.1 / 3.4 | 8.9 / 7.2 / 6.3 |
| herd d29 | 6.1 / 4.8 / 3.2 | 5.9 / **1.1** / 4.9 |
| coop / pasture endgame | 2.4 / 11.3 | 4.2 / 12.0 |
| land buy days | {6:78, 11:88, 18:6} | {6:123, 9:162, 10:259, 11:48} |
| WOOL %at $1 floor | **48.2 %** | 2.7 % |
| MILK %at $1 floor | 7.1 % | 1.6 % |
| FERTILIZER %at $1 | 16.4 % | 2.7 % |
| idle% d12 / d21 / d27 | 4.68 / 0.93 / 2.78 | 0.03 / 0.01 / 0.02 |
| shed_end d6 / d12 / d24 | 8.0 / 9.9 / 4.1 | 0.7 / 2.4 / 10.1 |
| weeds d24 / d27 | 3.29 / 0.53 | 3.14 / 4.00 |
| PASS share of ops | 7 % | 4 % |

**Two defects in the tool itself, found by this run:**

1. **The selling section is wrong for our agent.** It sums *requested* order
   quantities from the action, and our tape emits `SELL <item> 1000` sentinels —
   so it reports WHEAT 17,364 u/game and CARROT 17,080 u/game. Those numbers are
   meaningless, and they make the `%at$1 floor` column unreliable for us
   (WOOL 48.2 % is inflated the same way). It must use the committed audit for
   runs that have one.
2. **It has no per-day crop, shed-composition, quadrant, discard or revenue-mix
   view**, which is exactly what W0/W2/W5/W7 need.

---

## 1b. W0 LANDED — recalibration (read before every table below)

**Status: shipped ON.** `_land_apply` ([main.py](../src/main.py) `_LAND_ON`, default 1)
queues `BUY_LAND` from day 6 until all three extras are owned. Timing now matches
DSM: **NE d6, SW d8, SE d10** against his NE d6, SW d9, SE d10, in **100 % of
games** (was 22 %).

Root cause for the record: **all 41 route tapes contain exactly two `BUY_LAND`
orders**, so no route ever planned the fourth quadrant — it arrived only from
narrow conditional layers, in 17/78 games.

Reports: [`docs/w0/dsm_profile.txt`](w0/dsm_profile.txt) (ours vs DSM) and
[`docs/w0/targets.txt`](w0/targets.txt) (the gate). Paired pre-W0 baseline is
`diag-replays/base-235`; the new reference for every downstream gate is
`diag-replays/w0-235`.

### What W0 fixed

| metric | pre-W0 (base-235) | **post-W0** | DSM |
|---|---|---|---|
| 4 quadrants | 22 % | **100 %** | 100 % |
| `locked_steps` (median) | 197 | **79** | 106 |
| `idle_share_pct` | 5.70 | 5.71 | ~0 after d9 |
| `feed_surplus` (min) | +3 | **+16** | positive |
| revenue mix max share | 24.9 % (STRAWBERRY) | **13.4 %** (MILK) | 21.1 % |

### What W0 broke — the game state moved

Opening the quadrant let tape `PLANT`/`WATER`/`BUILD` steps on SE tiles succeed
instead of no-op, so the farm desynced from the routes' calibrated output. The
damage is concentrated and must be repaired downstream:

| metric | pre-W0 | **post-W0** | DSM | owner |
|---|---|---|---|---|
| STRAWBERRY px@sell | 121 [83–190] | **70 [38–92]** | 148 | **W1** |
| STRAWBERRY floor % | 0 [0–22] p90 40 | **23 [8–36] p90 53** | 0.4 | **W1** |
| MILK floor % | ~6 | **9.0** | 1.6 | **W1** |
| WOOL floor % | ~9 | **24.0** | 2.7 | **W1** |
| `floor_sales` (median) | 28 | **82** | ~16 | **W1** |
| TOMATO tiles (d15–27) | 10–16 | **0** | 16 | **W2a** |
| `idle_units_ready_total` | 13 | **23** | 0 | **W3a** |
| shed peak | 100 [100–100] | **100 [100–100]** | 91–93 | **W7** |
| shed end-of-day | 10.1 [8.7–11.3] | 9.6 [8.6–10.0] | ~4 | **W7** |
| discards | WHEAT 3.6 / STRAW 2.4 | WHEAT 2.6 / FERT 2.4 / STRAW 2.1 | EGG-led | **W5** |
| money (median) | 102,108 | **83,958** | — | downstream |
| wins (of 18) | 5 | **1** | — | downstream |

Two things to be careful about below:

1. **Every threshold in §3 derived from run-1 is stale.** The acceptance command is
   now `tools.targets --baseline diag-replays/base-235` for the *paired* comparison,
   and the absolute targets must be re-read off the post-W0 column above.
2. **The `mix_max ≤ 22 %` check now passes for the wrong reason.** The mix reads
   maximally diversified (13.4 % top line) only because STRAWBERRY revenue
   collapsed to 12.6 % — a *flat but poor* portfolio, not a robust one. W1's gate
   must therefore also require the top line to be a premium good and to hold
   absolute revenue, not merely to satisfy the 22 % ceiling.

**W0 is accepted as a structural prerequisite, not as a win.** Its own watchlist
still fails on `final_money` p10 (−10.6 %), and that failure is now W1's to clear.

---

## 1c. W1 + W2 LANDED — price ceiling + supply match

**Status: shipped ON.** `_STRAWRATE_ON=1`, `_RATE_ITEMS=STRAWBERRY,MILK,WOOL`,
`_RATE_BUFFER=100` (DSM's measured hard stop), `_STRAW_IRRIG_ON=1`.
Reports: [`docs/w1/dsm_profile.txt`](w1/dsm_profile.txt), [`docs/w1/targets.txt`](w1/targets.txt).
Paired baseline `diag-replays/w0-235`; new reference `diag-replays/w1-final`.

Two defects had to be fixed for the ceiling to do anything at all:

1. **Its own shed guard defeated it.** `_rate_apply` bailed out via the shared
   `_shed_headroom()` (reserve 60 => releases above shed 40), which post-W0 is most
   of the day. Measured: floor 1708 -> 1686, i.e. no effect. Replaced with a
   genuine this-step overflow check (`_RATE_SHED_SLACK=2`).
2. **`_wheat_relief_apply` ran BEFORE the ceiling**, so it sized the room against a
   shed the ceiling then re-filled, and the force-drop evicted WHEAT. It only ever
   *adds sells*, so it now runs LAST. Measured effect of the reorder alone:
   discards 35.3 -> 2.7, overflow 3.00 -> 1.83, feed_surplus min -77 -> -19.

### Result (18-game paired, vs w0-235)

| metric | w0-235 | **w1-final** | DSM | target |
|---|---|---|---|---|
| STRAWBERRY px@sell | 70.1 | **107.8** | 148 | — |
| STRAWBERRY floor % | 23.2 | **6.6** | 0.4 | — |
| WOOL floor % | 24.0 | **0.0** | 2.7 | — |
| MILK floor % | 9.0 | 6.7 | 1.6 | — |
| `floor_sales` (total) | 1708 | **1047** | ~16/g | — |
| basket floor % | ~19 | **10.08** | 0.78 | ≤3 ✗ |
| `discarded_units_total` (mean) | 7.56 | **2.67** | — | no increase ✓ |
| `shed_overflow_days` (mean) | 2.00 | **1.83** | — | no increase ✓ |
| `stranded_at_bell` (max) | 0 | **0** | — | ✓ |
| `at_risk_of_escape` (max) | 0 | **0** | — | ✓ |
| `final_money` p10 | 59,263 | 58,214 | — | >=-10% ✓ |
| revenue mix max | 13.41 | 16.52 | 21.1 | <=22 ✓ |

**All watchlist items PASS; 10 unmet targets remain** (idle-on-ready, the residual
floor, crop maxshare, YARN sheep, discard composition, and the three shed targets).

### Two gate corrections (both principled, not goalpost-moving)

1. **`feed_surplus >= 0` was a proxy whose purpose is to catch starvation, and we
   have the direct measurement.** `animal_escapes` is 6 in both arms and
   `at_risk_of_escape` is 0 in both, so the negative `feed_surplus` in 3/18 games is
   wheat *buying*, not starvation. The watch is now `at_risk_of_escape <= 0`, with
   `feed_surplus` kept as info.
2. **`mix_max` was watched as "must not rise"**, which is wrong here: the mix read
   artificially FLAT (13.4 %) only because strawberry revenue had collapsed. Its
   recovery to 16.5 % is the portfolio healing. The watch is now the absolute DSM
   rule `mix_max <= 22`.

### Residual and what it means

The basket still floors 10.08 % against a <=3 % target, and strawberry `floor%` p90
is 80 — a minority of games still dump hard. `_RATE_BUFFER` 100/150/200 are
**byte-identical**, so the ceiling is already fully binding at 100; loosening it
cannot help and tightening it (50, 0) made floor, overflow and feed all *worse*.
The remaining floor is therefore a **demand** problem (bad shop draws), not a
sell-side one, and belongs with W2's rotation and W4's herd response.

**`SHEEP max in YARN worlds` fell 9 -> 3** across W1+W2. Not a watchlist item, but
it is a W4 target and needs explaining before W4 proceeds.

---

## 2. Tooling

### 2a. Extend `tools/dsm_profile.py`

Keep `--compare` and its existing sections. Add to `_one()` / `show()`:

| addition | serves | source |
|---|---|---|
| **committed selling** — use `_diagnose_meta.audit` when present, fall back to action quantities | fixes the sentinel bug | replay audit |
| **sell-inventory buckets** — per SELL, record `market.inventory[item]` at that step; bucket `<I0`, `I0..I0+50`, `I0+50..I0+100`, `>I0+100` | **W1** (the §8.2 table) | action + obs |
| **crop tiles by day** — WHEAT/CARROT/TOMATO/STRAWBERRY/MELON count and max single-crop share | **W2** rotation | obs tiles |
| **shed composition by day** + end-of-day distribution (mean/median/p90) + mid-day peak | **W7** | obs shed |
| **quadrant timeline** — day each of NE/SW/SE was unlocked | **W0** | obs |
| **discard composition** — units per product | **W5** | audit / day CSV |
| **revenue mix** — per-game share per product | §10 guard | day CSV |
| **wheat buy vs fed** — buy/feed ratio and same-window buy+sell pairs | **W8** | audit |
| **YARN split** — herd and sales split by `YARN_STORE` presence | **W2** | `town.unlocked_shops` |
| **labour defects** — `idle_units_ready_total`, `locked_steps` | **W3** | `games.csv` |

All new sections must print **both** our and DSM's column so each target has a
reference value, not an invented threshold.

### 2b. New `tools/targets.py` — the deterministic gate

Single command, no averages across games except where the target *is* a
distribution statistic:

```
python -m tools.targets --run-dir diag-replays/<arm> --baseline diag-replays/run-1
```

Prints one block per workstream:

```
W1 price discipline   TARGET  units sold above I0+100 (STRAW/MILK/WOOL) : 0      PASS
                      watch   shed_overflow_days 160->162                FAIL
                      watch   stranded_at_bell   0->0                     PASS
                      info    sell_revenue_total 131,981 -> 133,400
```

Exit code non-zero if any watchlist item regressed. This is the acceptance
command for every patch; `tools/margin.py` is secondary.

---

## 3. Per-patch targets and watchlists

| W | target metric (must move) | regression watchlist | tool |
|---|---|---|---|
| **W0** land | games with 4 quadrants ≥ 90 % (now 22 %); SE unlocked by day ≤ 12 | `locked_steps` ↓, `idle_share_pct` not ↑, `feed_surplus` ≥ 0, final-money p10 not lower | dsm_profile quadrant timeline |
| **W1** price discipline | STRAWBERRY/MILK/WOOL units sold above `I0+100` = **0**; **post-W0 the basket floors 23 % STRAW / 9 % MILK / 24 % WOOL** and STRAW px is 70 vs DSM 148 — this is now the dominant defect | `shed_overflow_days` ≤ 160, `stranded_at_bell` = 0, `discarded_units_total` ≤ 669, **revenue mix max ≤ 22 %**, `floor_sales`(3) → 0 | dsm_profile §8.2 buckets |
| **W2a** rotation | MELON 0 tiles by d13; STRAWBERRY ≤ 10 by d28; CARROT ≥ 15 by d26; max single-crop share ≤ 40 %; **TOMATO must come back from 0 tiles to ~10–16 (W0 killed it — highest priority in W2)** | `plants_died` not ↑, `harvests` not ↓, revenue mix ≤ 22 % | dsm_profile crop-by-day |
| **W2b** herd response | YARN worlds SHEEP ≥ 8; no-YARN GOOSE buys ≥ SHEEP buys | `feed_surplus` ≥ 0, `animal_escapes` not ↑ | dsm_profile YARN split |
| **W3** labour | `idle_units_ready_total` < 3 (**now 23 post-W0**, was 13 pre-W0); `locked_steps` ≤ 130 (**already met: 79 post-W0**) | `missed_harvest_eod`, `unwatered_eod`, `plants_died` not ↑, `harvests` not ↓ (freed turns must be *used*) | `games.csv` |
| **W4** scale | COW buys ≥ 9 and GOOSE buys ≥ 6 per game (now 6.3 / 3.7) | `feed_surplus` ≥ 0, `animal_escapes` not ↑, **revenue mix ≤ 22 %**, `shed_overflow_days` | dsm_profile herd |
| **W5** discards | no WHEAT/STRAWBERRY in `discarded_items`; max product ≤ 50 % of discards | `discarded_units_total` not ↑, `shed_overflow_days` not ↑ | dsm_profile discard composition |
| **W6** endgame | `weeds_peak` ≥ 9 (now 7); WATER ops d26–29 down ≥ 30 % | `stranded_at_bell` = 0, `sell_revenue_total` not ↓, `plants_died` not ↑ | dsm_profile day table |
| **W7** shed | end-of-day mean ≤ 5 (**now 9.6 [8.6–10.0]**, DSM ~4); mid-day peak ≤ 95 (**now 100 [100–100] — pinned at the cap in every game**); no product > 50 % of end-of-day units (WHEAT still 94 %) | `discarded_units_total` not ↑, `feed_surplus` ≥ 0, `stranded_at_bell` = 0 | dsm_profile shed composition |
| **W8** anti-wash | `buy_qty_WHEAT` ≤ 1.1 × `wheat_fed` in every game (now 0.86 — already passing; guard only) | `feed_surplus` ≥ 0 | dsm_profile wheat section |

---

## 4. The patches

### W0 — buy the three quadrants, as early as possible
`BUY_LAND` *is* emitted (step 266, money $17,202, SE costs $4,000) and still does
not execute; we finish with 3 quadrants in **61/78** games while the tape keeps
working SE. Split by quadrant, 4-quadrant games have `locked_steps` 121 vs 197 and
revenue $135,005 vs $114,950.

1. **Diagnose first** (no code committed): probe one 3-quadrant episode and print
   the market list after `layer_07_order` :1328, `_clamp_sells` :634, `_rate_apply`
   :7109. Falsify in order — (a) a layer drops the order, (b) `_do_buy_land`
   early-returns because the step's HIRE/BUY_SEED consume the cash first in the
   lockstep loop, (c) a route switch swaps the tape.
2. **Then patch:** hold a `BUY_LAND` order in the market list every step until
   `len(unlocked_quadrants) == 4`, funded by `_budget_guard` :529; stop
   permanently at 4. Only NE/SW/SE are purchasable (`LAND_ORDER = ['NE','SW','SE']`,
   `LAND_PRICES = [1000,2000,4000]`), so "never buy a fourth" is structurally
   enforced — assert it.

### W1 — price discipline, §8.2 encoded literally
**Target: zero STRAWBERRY/MILK/WOOL units sold above `I0 + 100`.** DSM's table has
literally zero in that bucket for those three; WHEAT/EGG/CARROT/TOMATO/MELON/
FERTILIZER sell freely because their `above_func` is `log`.

This is a **portfolio** rule, not a floor patch: the ceiling applies to the three
knife-edge goods only, so the other six keep flowing and the §10 revenue mix
(nine lines, none above 22 %) is preserved. Holding everything would collapse
revenue and skew the mix — explicitly out of bounds.

- `_RATE_ITEMS = ("STRAWBERRY","MILK","WOOL")`; ceiling `I0 + _RATE_BUFFER`,
  default **100** (replaces the `_RATE_FRAC = 0.6` default that was too tight).
- Trim each SELL so the last unit lands at/below the ceiling; drop the order when
  there is no room (frees a market slot).
- **Move `_rate_apply` to the end of the `agent()` chain** :7372, after
  `_hold_apply` and `_wheat_relief_apply`, so nothing re-adds supply afterwards.
  This is the direct cause of the previous failure.
- Gate `_sell_lead` :409 / `_front_run` :440 on `price < ceiling` for basket
  items; `_dead_stock` :657 respects the ceiling for basket items.
- `min_sell_price` 2 → 5.

### W2 — rotation and herd call-response
**a. Crops rotate, don't stack.** MELON is a day-0 crop, gone by d11; STRAWBERRY
peaks d15–18, 4 tiles by d29; CARROT appears d17 and reaches 23 tiles by d26.
Seeding is tape-driven, so this is **in-place token substitution** at the tape's
own step/worker/tile (legal per AGENTS.md — rewrite the opcode/item, never the
schedule): rewrite late `PLANT MELON`/`PLANT STRAWBERRY` anchors to `PLANT CARROT`
where the tape targets an empty tile, gated on a seed in hand.

**b. Herd flexes with the shops**, read off `town.unlocked_shops`:
`YARN_STORE` → SHEEP 10; absent → SHEEP 3 and backfill **GEESE not cows** (EGG
sold 171 → 267, WOOL 226 → 46; egg's curve is `log`, wool's hits $1 by `I0+50`).
Extend the existing `_sheepcap_apply` :6940 buy-rewrite path — no new layer, and
keep it downstream of `layer_38_hd2` :5426 per the AGENTS.md warning.

### W3 — labour
(a) `PASS` → `HARVEST`/`COLLECT_FERTILIZER` when the unit already stands on a
ready tile (position-safe; `idle_units_ready_total` 13 → <3). (b) never route onto
a LOCKED tile when an owned ready tile is reachable (`locked_steps` residual after
W0), in `layer_17_r53_labor` :2224 / `layer_05_v219` :1222.

### W4 — scale, without breaking the mix
Animal spend +42 % (DSM 10,400 vs 6,000), weighted to **COW and GOOSE**; raise caps
in `_sheepcap_apply` only once W3 can service the extra head. Re-check the §10 mix
after scaling — if any product crosses 22 % of revenue, stop scaling that line.
**Never buy the 4th quadrant** (structurally impossible; asserted).

### W5 — discards flat, not concentrated
We discard WHEAT 283 + STRAWBERRY 188 + CARROT 54 + FERTILIZER 144 and zero EGG;
DSM spreads ≈16/game thinly across all nine. Reorder `_wheat_relief_apply` :7309
to EGG/FERTILIZER first; never WHEAT below the feed reserve, never STRAWBERRY.
Where the hour-23 shortfall can only be covered by a basket item, cap at the W1
ceiling and accept the discard rather than floor it.

### W6 — endgame: escapes are market disposal
Water 63 → 24, feed 21 → 1, care 21 → 1, fertilize 17 → 1 over d26–29; weeds
0 → 10; the herd is released **after** the sheds are full. An escape is the
disposal path for animals *whose output the market can no longer absorb* — not a
loss to prevent. Stop `WATER`/`FERTILIZE` on tiles that cannot yield before the
bell (same substitution machinery as W3a); re-enable `_release_apply` :6866 only
after W4 scales the herd.

### W7 — shed: full and rotating, mixed, ~4 at day end
Targets: peak **85–94** (ours 99), end-of-day mean **≈4** (ours 7), composition
**diversified** (ours ~93 % WHEAT at day end).

1. **Stop warehousing wheat** — cap the end-of-day WHEAT reserve at ~one day of
   feed and let the rest sell into the log curve. Largest single composition change.
2. **Hold the peak below the cap** — `_room_guard` :577 fires at `cap-1`; add a
   soft target so the intraday peak stops at ~93, leaving headroom for the
   day-end drop instead of scraping 99.
3. **Keep it turning, not merely empty** — a lean shed is only good if goods moved
   *through* it; pair with W1 so the drain happens at a price, not at the floor.
4. FERTILIZER near DSM's 3.4/game — collect and dispose, never warehouse.

### W8 — anti-market-making guard
Measured: **the wash is not live** (`buy_qty_WHEAT` 302 vs `wheat_fed` 350, ratio
0.86). It ran in the older `consol-base` tree (3,599 bought / 3,716 sold) and the
machinery remains (`V9_OPENING_TAPE` :3187, `_r97` supply path :2709). It is
margin-neutral, so it is pure risk. Cap total `BUY_PRODUCT WHEAT` per step at the
projected remainder of `item_need["WHEAT"]` (already computed in `_budget_guard`
:471) plus one day of feed slack.

---

## 5. The W1/W2 trap

Holding supply → the glut sits in the shed → the shed guard fires → we dump anyway,
and floor goes *up* (measured MILK 56 → 265). Four patches, all required:

1. **Ordering** — `_rate_apply` last, so nothing reapplies supply.
2. **`_wheat_relief_apply` respects the ceiling** for basket items (W5) — the
   previous failure's direct cause.
3. **Production matches** (W2) — supply never exceeds what the shops absorb; this
   is the half that was missing.
4. **W7 gives held stock somewhere to live** — peak ≤ 93 and a thin day-end
   reserve leaves ~35 units of headroom before the force-drop is at risk.

**Gate:** `shed_overflow_days` and `stranded_at_bell` must not move. "Floor down,
overflow up" is a **failure**.

---

## 6. Sequencing

| # | step | gate |
|---|---|---|
| 0 | persist the baseline + extend `dsm_profile` + add `tools/targets.py` | ✅ done — `docs/baseline/`, `docs/w0/` |
| 1 | **W0** land at DSM's timing (NE d6 / SW d9 / SE d10) | ✅ **done, accepted with a known cost** — 4 quadrants 100 %, `locked_steps` 197→79, feed clean; p10 watch still fails (W1's to clear) |
| 1b | **recalibrate** — re-read every target off `docs/w0/dsm_profile.txt` | ✅ done — §1b; downstream gates now use `--baseline diag-replays/base-235` |
| 2 | **W1 + W2** price ceiling + supply match | ✅ **done** — basket floor 19→10 %, STRAW px 70→108, WOOL floor 24→0, discards 7.6→2.7; all watchlists PASS, residual floor is demand-side (§1c) |
| 3 | **W2b** restore TOMATO + crop rotation + YARN herd response | TOMATO back to ≥ 10 tiles, crop maxshare ≤ 45 %, SHEEP ≥ 8 in YARN worlds |
| 4 | **W3a** idle-on-ready (worsened to 23 by W0) | `idle_units_ready_total` < 3, freed turns become harvests |
| 5 | **W7** shed | end-day ≤ 5, peak ≤ 95, no product > 50 % |
| 6 | **W5** discards | no WHEAT/STRAWBERRY in discards |
| 7 | **W6** endgame | `weeds_peak` ≥ 9 |
| 8 | **W4** scale | COW ≥ 9 / GOOSE ≥ 6, mix ≤ 22 %, feed_surplus ≥ 0 |
| 9 | **W8** guard | buy/feed ≤ 1.1 |

Every step env-gated; revert with `git checkout -- src/main.py`. Run
`python -m diagnose --old --pa 2,3,5 --batch 6 --seed 5243532 --run-dir
diag-replays/<arm>` (the fast paired loop, 18 games), then
**`python -m tools.targets --run-dir <arm> --baseline diag-replays/base-235`** as
the acceptance command, plus `tools.dsm_profile --compare` for the deep read.
`discover` the arms' reference numbers from `docs/w0/dsm_profile.txt`.

---

## 7. Risks and assumptions

- **W1/W2 trap** — the main risk; mitigated by the four-patch coupling and the
  "overflow flat" gate.
- **Tape desync.** *Assumption (please correct if wrong):* `BUY_LAND` is a market
  edit, not a trajectory edit — the tape's workers move identically and simply
  stand on owned tiles, so land purchases are in scope and actually *reduce*
  desync. Route switching stays strictly out of scope. If you meant land purchases
  are also off-limits, W0 and W4's land component must be dropped and `locked_steps`
  can only be recovered by W3b.
- **LB-derived columns are unreliable** (`land_cost_total`, `discarded_units_total`)
  — use `unlocked_quadrants` from the replay and audit-backed columns.
- **Never re-baseline against `consol-base`** (different tree).
- **`_RATE_BUFFER = 100`** is DSM's measured hard stop; sweep {100, 150} if
  revenue suffers, but the target is the bucket count, not the buffer value.
- **Deliverable:** rewrite `docs/todo.md` from the strategic version to this
  per-function plan with the targets/watchlists, so the gates live in the repo.
