# dsm_gap.md — DSM vs the previous agent vs current iteration v1

Where we stand against the top player, in three columns.

| column | what it is | sample |
|---|---|---|
| **DSM** | the top team's own leaderboard games | 124 episodes, `replays/DSM/v1/` + `/tmp/dsm_lb/games.csv` |
| **previous agent** | our `old` sweep, recorded by the first revision of this document | 195 games, 15 seeds × 13 public agents, base seed `4362837462` — *that run no longer exists on disk; those figures are quoted from the previous revision of this file* |
| **current iteration v1** | our `old` agent today (`src/main.py`, this working tree) | 78 games, 6 seeds × 13 public agents, base seed `5243532`, `diag-replays/run-1/` |

Full behavioural anatomy of DSM: **[dsm_v1.md](dsm_v1.md)**. Data tools:
`tools/dsm_extract.py` → `tools/dsm_report.py` (DSM), `tools/margin.py` (W/L + margin),
`tools/sell_price.py` (price-at-sell, both seats).

---

## 0. Comparability — read this before any table

The three samples are **not** the same games, so every table below compares
*distributions*, never paired head-to-head results, and never a cross-game mean
of money. Two traps, both of which bit the previous revision:

**1. Leaderboard replays carry no market audit.** In `/tmp/dsm_lb/games.csv`:

| column | DSM rows | usable? |
|---|---|---|
| `discarded_units_total` | **0 in all 124 rows** | ✗ — not measured, *not* "DSM never discards" |
| `sell_revenue_total` | **0 in all 124 rows** | ✗ |
| `land_cost_total` | up to 88,000 (real ceiling is 7,000) | ✗ — the LB derivation is wrong |
| `floor_sales` | non-zero in 110/124 | ✓ (from price-at-order) |
| `idle_*`, `shed_*`, `animal_escapes`, `plants_died`, `weeds_peak`, `harvests`, `unfed_signals`, `unwatered_eod`, `missed_harvest_eod`, `seed/animal/hire/product cost`, `wheat_fed`, `feed_surplus`, `locked_steps`, `stranded_at_bell` | non-zero | ✓ |

The previous revision concluded **"DSM never discards; we do"** from
`discarded_units_total = 0`. That was the missing audit, not a fact. Measured
properly (hour-23 force-drop overflow, `tools/dsm_extract.py`), DSM discards
**≈16 units/game** — see §4. The defect was never "we discard and they don't";
it is *what* we discard.

**2. The previous sample is gone and used different seeds.** Any column marked
`—` in the previous-agent column was simply not recorded there.

Two independent measurements agree on DSM's floor volume, which is why §5 is
trustworthy: the diagnosed `floor_sales` sums to **2,010** over 124 games, and the
price-at-order reconstruction from the raw replay stream gives **2,002** over 123.

---

## 1. Headline scorecard

| metric | **DSM** | **previous agent** | **current v1** | v1 verdict |
|---|---|---|---|---|
| record | **118–5 (95.9 %)** | ~146–49 (~75 %) | **36–42 (46 %)** | ✗ much worse |
| median final bank | $110,708 | high-water ≈$140k | $104,311 | ~ |
| p10–p90 bank | $88k–$139k | — | $70k–$148k | wider spread |
| **units sold / game** | **2,080** | — | **1,557** | ✗ **−25 %** |
| **harvests / game** | **597** | — | **503** | ✗ **−16 %** |
| `idle_share_pct` | **3.5** (3–4) | 4.2 (d10–29 mean) | **5.0** (5–8) | ✗ |
| `idle_units_total` | 264 (230–297) | 340–590 | 358 (320–546) | ✗ |
| `idle_units_ready_total` | **0** (0–1) | 10–61 | **13** (9–31) | ✗ |
| `locked_steps` | **106** (97–117) | 125–233 | **197** (121–226) | ✗ **1.9×** |
| `floor_sales` / game | **16.2** | > 0, unquantified | **58.3** | ✗ **3.6×** |
| `shed_pressure_days` | 5 (2–9) | 1–6 | 4 (1–6) | ~ |
| `shed_overflow_days` | 2 (1–5) | 0–4 | 2 (0–4) | = |
| `discarded_units_total` | ~16 (estimated) | > 0 | 3 (0–22) | ✓ |
| `animal_escapes` | **10** (5–18) | 0–1 | **0** (0–1) | ✓ (deliberate) |
| `plants_died` | 19 (14–28) | — | 20 (19–20) | = |
| `weeds_peak` | **10** (6–16) | — | **7** (7–9) | ✗ |
| `stranded_at_bell` | 47 (0–358) | — | **0** | ✓ |
| `seed_cost` | **10,780** | — | **6,760** | ✗ **−37 %** |
| `animal_cost` | **10,400** | 6,500–7,900 | **6,000** | ✗ **−42 %** |
| `hire_cost` | **6,691** | — | **5,261** | ✗ **−21 %** |
| `feed_surplus` | 189 (82–347) | sometimes **negative** | 90 (9–173) | ✓ (no longer negative) |
| `wheat_fed` | 372 | 290–470 | 350 | = |
| `premium_below_base_frac` | 0.62 | 0.45–0.86 | 0.54 | ~ |

**The shape of the gap has changed.** The previous revision's headline was
*"we are mid-field; our loss is idle + discards + a tiny herd."* The v1 data says
something different and more concrete:

> **v1 is a smaller farm than DSM, and it wastes more of the labour it has.**
> It spends 37 % less on seed, 42 % less on animals and 21 % less on labour,
> harvests 16 % less and sells 25 % less — while burning **1.9× the worker-turns
> on land it does not own** and putting **3.6× the units into the $1 floor**.

Two of the previous revision's three named defects are now closed: **feed surplus
is never negative** (was −22…−60) and **discards are no longer the problem**
(3/game vs DSM's ~16). What is left is scale and floor discipline.

---

## 2. Scale — the dominant term

| metric | **DSM** | **previous agent** | **current v1** |
|---|---|---|---|
| `seed_cost_total` | **10,780** (9,270–12,370) | — | **6,760** (6,480–7,200) |
| `animal_cost_total` | **10,400** (8,100–14,900) | 6,500–7,900 | **6,000** (5,600–6,900) |
| `hire_cost_total` | **6,691** (5,882–7,466) | — | **5,261** (5,028–6,036) |
| COW bought / game | **11** | 1–2 animals in total | **6.3** |
| SHEEP bought / game | 4 | — | 5.1 |
| GOOSE bought / game | **7** | — | **3.7** |
| herd at the bell (proxy) | COW 6 / SHEEP 0 / GOOSE 5 | — | COW 6.7 / SHEEP 5.7 / GOOSE 3.9 |
| `harvests` | **597** (547–630) | — | **503** (464–522) |
| units sold | **2,080** | — | **1,557** |

DSM converts roughly **1.6× the cash into inputs** and gets **19 % more harvests**
out. Nothing here is a *timing* problem — the farm is simply smaller. The previous
revision's fix item F3 ("scale the herd toward DSM's throughput") was correct and
is **still open**: v1 buys 6.3 COW against DSM's 11 and 3.7 GOOSE against 7.

The species mix is also wrong for the worlds we are in. DSM's no-YARN counter-move
is **geese, not sheep** (`dsm_v1.md` §4.1): with no `YARN_STORE` he runs 3 sheep
and 8 geese, because the egg curve is log-shaped and can absorb almost unlimited
volume while wool's hits $1 by `I0+50`. v1 buys 5.1 sheep against 3.7 geese.

**Land is a third scale gap, not a guard.** `land_cost_total` is unusable for DSM
(the LB derivation reports up to 88,000 against a real ceiling of 7,000), so this
is read from `unlocked_quadrants` in the raw replays. DSM buys all three extra
quadrants — NE on day 6, SW on day 9, SE on day 10 — and ends with 4. v1 ends with
**3 quadrants in 21 of 26 games, all four in only 5**: it usually never buys the
SE quadrant at all.

DSM's build ordering, for reference (`dsm_v1.md` §3): the entire $3,000 opening
bank is spent **on day 0** (bank ends day 0 at $6), with 10 structures, 2 COW,
3 SHEEP, 9 WHEAT and 6 MELON already placed. There is no slow ramp to copy.

---

## 3. Labour — v1's sharpest remaining defect

| metric | **DSM** | **previous agent** | **current v1** |
|---|---|---|---|
| `idle_share_pct` (game) | **3.5** (3–4) | 4.2 (d10–29 mean) | **5.0** (5–8) |
| `idle_share_pct`, days ≥10 | **≈0** (0.0–0.4) | 1–9, mean 4.2, spike 9.1 at bell | **2.60 median / 3.33 mean** |
| `idle_units_total` | **264** | 340–590 | **358** |
| `idle_units_ready_total` | **0** (0–1) | **10–61** | **13** (9–31) |
| `locked_steps` | **106** (97–117) | 125–233 | **197** (121–226) |
| `missed_harvest_eod` | 5 (2–9) | — | **2** (2–6) |

Two separate defects, pointing at different layers:

1. **`idle_units_ready_total` = 13.** Our units still PASS while standing on
   ready produce or a full animal tile — DSM does this **0 times**. This is the
   previous revision's F1 and it has not been fixed. It is the cleanest binary
   signal in the table: DSM's p90 is 1, our p10 is 9.
2. **`locked_steps` = 197, 1.9× DSM's 106.** Nearly twice as many worker-turns
   spent standing on or routed across **land we do not own**. This is new
   information — the previous revision recorded 125–233 and treated it as a
   footnote; against the corrected DSM figure (106) it is a top-three gap.

Note the exchange rate: v1 has *better* `missed_harvest_eod` (2 vs DSM's 5) and
equal `plants_died`, so this is not careless harvesting — it is **routing**.

---

## 4. Shed

| metric | **DSM** | **previous agent** | **current v1** |
|---|---|---|---|
| `shed_pressure_days` (≥95) | 5 (2–9) | 1–6 | 4 (1–6) |
| `shed_overflow_days` (==100) | 2 (1–5) | 0–4 | 2 (0–4) |
| `discarded_units_total` | ~16 *(estimated)* | >0, items unrecorded | **3** (0–22) |
| games with any discard | 115/123 | "most games" | **67/78** |
| what gets discarded | EGG, MILK, STRAWBERRY, WHEAT, TOMATO, CARROT, WOOL, FERTILIZER — **spread over all nine** | FERTILIZER, WHEAT, WOOL, STRAWBERRY | **WHEAT 283, STRAWBERRY 188, FERTILIZER 144, CARROT 54** |

**The previous revision's F2 is done.** v1 discards *less* than DSM in absolute
terms (3 vs ~16 units/game) with the same pressure/overflow profile.

But the *composition* is inverted, and that matters more than the count:

- DSM's discarded volume is dominated by **EGG (497 units over 123 games)** and
  spread thinly across all nine products — no product ever becomes the dumping
  ground, so no line is ever lost outright.
- v1 discards **WHEAT (283) and STRAWBERRY (188)** and **zero EGG**. Wheat is the
  feed reserve; strawberry is our **largest revenue line (22.4 % of v1's own
  revenue mix**, ahead of MILK 18.4 % and WOOL 15.6 %). We throw away the
  expensive things and keep the cheap one.

---

## 5. Market and floor — the clearest, most quantifiable gap

Per game. DSM's units and prices come from the price-at-order reconstruction
(123 games); v1's from the market audit (78 games).

| product | units DSM | units v1 | px DSM | px v1 | **floor % DSM** | **floor % v1** |
|---|---|---|---|---|---|---|
| WHEAT | 591 | 397 | 34.8 | 37.8 | 0.00 % | 0.00 % |
| CARROT | 219 | 131 | 41.5 | 58.1 | 0.00 % | 0.00 % |
| TOMATO | 123 | 5 | 70.2 | 207.5 | 0.00 % | 0.00 % |
| **STRAWBERRY** | 227 | 234 | **148.3** | **128.8** | **0.44 %** | **12.68 %** |
| MELON | 60 | 72 | 204.6 | 203.7 | 0.00 % | 0.00 % |
| EGG | 219 | 106 | 48.2 | 51.5 | 0.00 % | 0.00 % |
| **MILK** | 196 | 183 | **102.3** | **135.9** | **1.60 %** | **5.88 %** |
| **WOOL** | 165 | 128 | **145.3** | **164.8** | **2.70 %** | **8.91 %** |
| FERTILIZER | 279 | 301 | 51.0 | 49.8 | 2.75 % | **2.14 %** |
| **total** | **2,080** | **1,557** | | | **0.78 %** | **3.7 %** |

Floor units per game: **DSM 16.2, v1 58.3 (3.6×)**. Where they come from:

| | STRAWBERRY | MILK | WOOL | FERTILIZER |
|---|---|---|---|---|
| DSM floor units/game | **1.0** | 3.1 | 4.5 | **7.7** (47 % of DSM's total) |
| v1 floor units/game | **29.7** (51 % of v1's total) | 10.8 | 11.4 | 6.4 |

**This is the clearest statement of the gap in the document.** DSM's floor volume
is *mostly fertilizer* — no shop buyer, only productive use is `FERTILIZE`, so
dumping it is rational. v1's floor volume is *mostly strawberry*, our single
highest-revenue product.

The mechanism, from `dsm_v1.md` §8.2 — the shared market inventory at the moment
of every SELL order:

| product | `<9900` | `9900–10000` | `10000–10050` | `10050–10100` | `>10100` |
|---|---|---|---|---|---|
| WHEAT | **45,800** | 14,508 | 4,144 | 2,774 | 5,425 |
| STRAWBERRY | 4,784 | **14,113** | 8,297 | 685 | **0** |
| MILK | 86 | 5,852 | **10,366** | 7,855 | **0** |
| WOOL | 454 | 5,915 | **10,149** | 3,810 | **0** |

MILK, WOOL and STRAWBERRY sell **literally zero units above `I0+100`**. The floor
is avoided by a **hard inventory stop at the point the curve breaks**, not by
reacting to price. WHEAT is the mirror play: 63 % of it sold *below* `I0`, into
scarcity at $37–41 against a $25 base.

Also visible: v1 **undercuts DSM on strawberry** (128.8 vs 148.3) and **beats him
on milk and wool** (135.9 vs 102.3, 164.8 vs 145.3). We get better unit prices on
milk and wool precisely *because* we sell fewer of them — the volume goes to the
floor instead.

One number worth carrying forward: v1's `premium_below_base_frac` is 0.54 against
DSM's 0.62. We are not worse at premium timing on average — we are worse in the
**tail**.

---

## 6. Late game and weeds

| metric | **DSM** | **previous agent** | **current v1** |
|---|---|---|---|
| `weeds_peak` | **10** (6–16) | — | **7** (7–9) |
| weeds, day 19 → 29 | 0 → **10** | — | — |
| `unwatered_eod` | 574 (522–607) | — | 532 (457–533) |
| `unfed_signals` | **96** (73–120) | — | 46 (20–84) |
| `animal_escapes` | **10** (5–18) | 0–1 | 0 (0–1) |
| `stranded_at_bell` | 47 (0–358) | — | **0** |
| `feed_surplus` | 189 | sometimes **negative** | 90 |

DSM's weeds are **not neglect** — they are the endgame plan. Watering drops
63 → 24 ops and feeding 21 → 1 across days 26–29, deliberately retiring production
so the last four days are pure liquidation (`dsm_v1.md` §6).

v1 has **lower** weeds (7 vs 10) because it *keeps working retired ground*. That is
the same "busy but not productive" signature as `locked_steps`: worker-turns spent
on tiles that can no longer pay.

The counterweights are real: v1 ends with **`stranded_at_bell` = 0 vs DSM's 47**,
has **equal `plants_died`**, and has **eliminated the negative `feed_surplus`** the
previous revision flagged.

On escapes: DSM's 10/game is deliberate — release the herd once the sheds are
already full (`dsm_v1.md` §4.2). v1's 0 is not automatically better, but it should
not be copied blindly either; the previous revision's F3 warning stands, since
scaling the herd without feed headroom converts escapes into starvation.

---

## 7. Where v1 has already closed the gap

| previous fix item | status in v1 | evidence |
|---|---|---|
| **F2** shed-overflow discards | ✅ **done, and better than DSM** | 3 units/game vs DSM's ~16; `shed_overflow_days` 2 = DSM's 2 |
| **F3** feed never negative | ✅ **done** | `feed_surplus` 90 (9–173), never negative; previous sample had −22…−60 |
| **F4** fertilizer timing | ✅ **improved** | v1 floors 2.14 % of fertilizer vs DSM's 2.75 % |
| **F5** land lock-step guard | ⚠️ **inverted** | the guard was never needed — v1 *under*-buys land: 3 quadrants in 21/26 games vs DSM's 4 |
| **F1** idle collapse | ⚠️ **half done** | game idle 5.0 vs previous 4.2 is *worse*; `idle_units_ready` 13 vs previous 10–61 is better |
| **F3** scale the herd | ❌ **not done** | 6.3 COW bought vs DSM's 11; 3.7 GOOSE vs 7 |

---

## 8. Priority order

1. **Floor discipline on STRAWBERRY** (biggest single number). v1 puts 29.7
   strawberry units/game into the $1 floor; DSM puts 1.0. DSM's rule is a hard
   stop at `I0` on the sell side *and* production cuts late. Surfaces: the
   sell-side rate/threshold layers. Judge with `tools/sell_price.py` and
   `tools/margin.py`, per game, never on a mean.
2. **Scale the farm to DSM's input spend.** Seed +37 %, animals +42 %, labour
   +21 %, **the fourth quadrant** (v1 skips SE in 21/26 games), and the species mix
   toward geese in no-YARN worlds. This is the previous revision's F3 and the only
   change that moves `harvests` (503 → 597) and units sold (1,557 → 2,080). Guard:
   `feed_surplus ≥ 0` at all times.
3. **`locked_steps` 197 → ~106.** Nearly 2× DSM's wasted turns on unowned land.
   Pure routing, no economic trade-off.
4. **`idle_units_ready_total` 13 → 0.** The previous F1, still open. Every unit is
   a missed collect. Binary and measurable.
5. **Discard composition.** Stop discarding WHEAT and STRAWBERRY (471 of our 669
   discarded units); discarding fertilizer instead is strictly better, since it
   has no buyer.
6. **Late-game retirement.** Let weeds rise toward DSM's ~10 and re-route the freed
   hands into harvesting and selling instead of watering retired ground.

**Do not** copy DSM's escape count (10/game) until the herd is actually scaled —
on a 6-COW farm escapes are pure loss; on a 9-COW farm with a full shed they are
disposal.
