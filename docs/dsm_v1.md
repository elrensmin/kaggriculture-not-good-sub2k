# DSM — the complete picture

A data-backed anatomy of the team sitting at the top of the ladder, rebuilt from
their own 123 leaderboard replays. Every figure is tagged by provenance at the top
of this file, and nothing here is inferred from a vibe. Where a number is modelled
rather than measured it says so — and where it turned out to be **unmeasurable** it
has been retracted rather than kept (see §7).

- **Source:** `replays/DSM/v1/` — 123 episode replays (`episode-*.json`), 4.2 GB.
- **Extraction:** `tools/dsm_extract.py` → `tools/dsm_report.py`
  (`python tools/dsm_extract.py --dump /tmp/dsm_cache.json` then
  `python tools/dsm_report.py --cache /tmp/dsm_cache.json`).
- **Wheat/milk specifics:** `tools/dsm_flows.py`.
- **Caveat that shapes everything below:** leaderboard replays carry **no market
  audit**, so every `revenue_*` / `avg_price_*` column in `days_seed*.csv` is
  zero. All flows here are reconstructed from the replay's own per-step
  `action` + `observation` stream, which is exact for counts and positions.

---

> ## Measurement provenance — read before using any number in this file
>
> Every figure here is tagged by *how* it was obtained, and the tag decides how much
> weight it can carry:
>
> | tag | meaning | safe for |
> |---|---|---|
> | **audited** | the env's market audit (`_diagnose_meta.audit`) | everything |
> | **observed** | read straight off a replay observation — tiles, shed, worker inventories, market inventory/prices, `town.unlocked_shops` | exact counts and states |
> | **derived** | arithmetic over audited/observed values (e.g. `harvested = dW - bought + fed + sold`) | totals, under the stated assumption |
> | **modelled** | reconstructed where the data does not exist (e.g. the day-end discard of an unaudited replay) | orders of magnitude only |
>
> **Leaderboard replays carry no market audit.** So for DSM the audit-backed fields
> are missing entirely — `discarded_units_total`, `sell_revenue_total`, `revenue_*`,
> realised `avg_price_*` — and anything built on them is *modelled*. Two rules:
>
> 1. **Never promote a modelled number to a target.** If it cannot be audited or
>    directly observed it cannot be a KPI. §7's discard table was withdrawn for
>    exactly this reason; it had been used as a target.
> 2. **Calibrate any model against the audited arm first.** A model that gets the
>    total right can still get the composition wrong — measured: −10 % on the
>    discard total, but ~7× wrong on WHEAT (0.44 modelled vs 3.28 actual per game).
>
> Where a claim below is modelled it now says so inline, and the tools print the
> model and its calibration side by side (`tools/discards.py`).

---

## 1. The record

| | |
|---|---|
| games | 123 |
| W–L–T | **118–5–0** |
| win rate | **95.9 %** |
| mean margin | **+$17,585** |
| median margin | +$13,959 |
| median end bank | $110,708 |
| distinct opponents faced | 66 |

The five losses are **−139, −1,682, −1,830, −2,683, −3,570**. That distribution
is the whole story of how they play: they do not blow the field away, they
almost never lose. The mean margin is inflated by a handful of huge wins; the
*median* win is what the ladder actually rewards, and the loss tail is capped at
a few thousand dollars. This is a µ/σ maximiser, not a bank-balance maximiser.

---

## 2. The thesis in one paragraph

**DSM is a market-inventory manager who happens to run a farm.** The price
curves in this game are knife-edge: for MILK, WOOL and STRAWBERRY the price
collapses to the $1 floor within roughly 50–100 units above `I0 = 10 000`, while
WHEAT, EGG, CARROT, TOMATO, MELON and FERTILIZER have gentle curves that sag
only 10–25 % even hundreds of units above `I0`. DSM's entire market behaviour is
organised around that fact: he sells each product **only while the shared market
inventory is below the point where its curve breaks**, and he holds and re-times
otherwise. Over 3 690 game-days he sells **255 830 units** and puts **2 002 of them
(0.78 %) into the $1 floor** — and **944 of those 2 002 are FERTILIZER**, a
product with essentially no shop buyer. Excluding fertilizer, the floor rate
across the eight tradeable goods is **0.48 %**.

---

## 3. Farm timeline

Median per game. `structs` = COOP + PASTURE tiles. `escapes` are inferred from
an animal vanishing from an animal structure (the engine cannot `DIG` a
structure that still holds an animal, so a disappearance is an escape).

| day | money | hands | quad | shed max | COW | SHEEP | GOOSE | structs | wheat | straw | carrot | tomato | melon | weeds | feed | care | water | fert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 6 | 4 | 1 | 8 | 2 | 3 | 0 | 10 | 9 | 0 | 0 | 0 | 6 | 0 | 4 | 4 | 15 | 0 |
| 1 | 2 | 4 | 1 | 4 | 2 | 3 | 0 | 10 | 10 | 0 | 0 | 0 | 10 | 0 | 5 | 6 | 5 | 0 |
| 2 | 8 | 6 | 1 | 5 | 2 | 3 | 0 | 10 | 4 | 4 | 0 | 0 | 10 | 0 | 3 | 7 | 18 | 0 |
| 3 | 18 | 6 | 1 | 12 | 2 | 3 | 0 | 10 | 0 | 10 | 0 | 0 | 10 | 0 | 5 | 7 | 14 | 0 |
| 4 | 438 | 5 | 1 | 13 | 2 | 3 | 0 | 10 | 0 | 10 | 0 | 0 | 10 | 0 | 5 | 5 | 11 | 0 |
| 5 | 822 | 6 | 1 | 8 | 2 | 3 | 0 | 10 | 0 | 10 | 0 | 0 | 10 | 0 | 5 | 6 | 11 | 0 |
| 6 | 43 | 8 | **2** | 10 | 6 | 3 | 2 | 24 | 7 | 15 | 0 | 0 | 10 | 0 | 6 | 7 | 23 | 0 |
| 7 | 77 | 9 | 2 | 6 | 8 | 3 | 2 | 26 | 11 | 16 | 0 | 0 | 10 | 0 | 13 | 13 | 23 | 0 |
| 8 | 2,312 | 9 | 2 | 16 | 8 | 3 | 2 | 26 | 10 | 16 | 0 | 0 | 10 | 0 | 10 | 11 | 37 | 0 |
| 9 | 379 | 10 | **3** | 25 | 9 | 3 | 4 | 32 | 21 | 19 | 0 | 2 | 10 | 0 | 13 | 13 | 42 | 1 |
| 10 | 2,477 | 12 | **4** | 47 | 9 | 3 | 6 | 34 | 29 | 22 | 0 | 2 | 4 | 0 | 19 | 19 | 46 | 3 |
| 11 | 6,506 | 11 | 4 | 74 | 9 | 3 | 7 | 35 | 32 | 25 | 0 | 4 | 0 | 0 | 18 | 18 | 52 | 11 |
| 12 | 9,769 | 11 | 4 | 64 | 9 | 3 | 7 | 37 | 29 | 26 | 0 | 5 | 0 | 0 | 19 | 19 | 59 | 9 |
| 13 | 13,989 | 11 | 4 | 81 | 9 | 3 | 7 | 37 | 27 | 28 | 0 | 7 | 0 | 0 | 21 | 21 | 62 | 8 |
| 14 | 23,041 | 12 | 4 | 88 | 9 | 3 | 7 | 37 | 26 | 28 | 0 | 8 | 0 | 0 | 21 | 21 | 55 | 10 |
| 15 | 28,886 | 12 | 4 | 93 | 9 | 3 | 7 | 39 | 23 | **30** | 0 | 10 | 0 | 0 | 19 | 19 | 60 | 13 |
| 16 | 37,748 | 12 | 4 | 93 | 9 | 3 | 7 | 37 | 21 | 30 | 0 | 11 | 0 | 0 | 20 | 19 | 56 | 10 |
| 17 | 43,520 | 12 | 4 | 89 | 9 | 3 | 7 | 37 | 20 | 30 | 2 | 12 | 0 | 0 | 20 | 20 | 62 | 10 |
| 18 | 49,291 | 12 | 4 | 89 | 9 | **4** | 7 | 37 | 21 | 27 | 3 | 15 | 0 | 0 | 15 | 14 | 54 | 12 |
| 19 | 55,108 | 12 | 4 | 86 | 9 | 4 | 7 | 37 | 24 | 21 | 4 | 16 | 0 | 0 | 19 | 18 | 58 | 13 |
| 20 | 61,007 | 12 | 4 | 88 | 8 | 4 | 7 | 37 | 26 | 20 | 6 | 15 | 0 | **1** | 15 | 15 | 58 | 14 |
| 21 | 65,365 | 12 | 4 | 92 | 8 | 4 | 7 | 37 | 27 | 20 | 7 | 14 | 0 | 1 | 16 | 15 | 62 | 17 |
| 22 | 71,604 | 12 | 4 | 90 | 7 | 4 | 7 | 35 | 30 | 17 | 8 | 13 | 0 | 1 | 13 | 13 | 58 | 14 |
| 23 | 75,651 | 12 | 4 | 92 | 7 | 4 | 6 | 34 | 32 | 15 | 10 | 11 | 0 | 2 | 17 | 16 | 60 | 15 |
| 24 | 80,266 | 12 | 4 | 93 | 7 | 4 | 6 | 32 | 33 | 15 | 14 | 8 | 0 | 2 | 12 | 11 | 63 | 17 |
| 25 | 85,283 | 12 | 4 | 93 | 7 | 4 | 6 | 30 | 32 | 13 | 18 | 7 | 0 | 2 | 14 | 14 | 61 | 15 |
| 26 | 90,217 | 11 | 4 | 94 | 7 | 3 | 6 | 28 | 29 | 12 | 23 | 6 | 0 | 2 | 11 | 11 | 63 | 15 |
| 27 | 96,237 | 11 | 4 | 93 | 7 | 3 | 6 | 28 | 28 | 9 | 21 | 5 | 0 | 3 | 11 | 11 | 58 | 15 |
| 28 | 102,162 | 11 | 4 | 93 | 6 | 3 | 6 | 28 | 15 | 8 | 10 | 5 | 0 | **6** | **3** | **2** | 48 | 14 |
| 29 | 110,708 | 10 | 4 | 85 | 6 | **0** | 5 | 28 | 2 | 4 | 0 | 4 | 0 | **10** | **1** | **1** | 24 | **1** |

### 3.1 What it shows

**Day 0 is a full-time commitment.** DSM spends essentially the entire $3 000
opening bank on day 0: the bank is at **$6** at the end of day 0. He has already
placed 2 COW and 3 SHEEP, built 10 structures, and planted 9 WHEAT and 6 MELON.
There is no slow ramp — he converts cash into productive assets immediately and
lets the land/animal schedule carry him.

**Land is bought as fast as the tape can fund it.** 1 quadrant on day 0 → NE on
day 6 → SW on day 9 → SE on day 10. Median 3 `BUY_LAND` orders per game
(1000 + 2000 + 4000 = $7 000). The 592 recorded `BUY_LAND` orders across 123
games (~4.8/game) versus 3 successful unlocks shows he **re-issues the order
every turn until it fills** — the purchase is gated on cash, not on a decision.

**Labour is re-hired from scratch every single day.** A median of **311 hire
orders per game** (~10.4/day). This is not a hiring spree: the engine wipes
`hands` and `hires_today` at every day boundary (`_end_of_day`), so a farm that
wants 12 hands must buy 12 hands every day. Cost is `fib(n)` for the n-th hand of
the day, so a 12-hand day costs 1+1+2+3+5+8+13+21+34+55+89+144 = **$376**, and
the day is structured to spend it: hands climb 4 → 8 by day 6 → 12 by day 10 and
stay there until they taper to 10 on day 29.

**The build peaks around day 15–19** — 37–39 structures, herd 9 COW / 3–4 SHEEP
/ 7 GOOSE, crops ~30 STRAWBERRY / ~25 WHEAT / ~12 TOMATO — and then is
deliberately dismantled over the last third of the season.

---

## 4. The herd

| species | median max | median buys | buy cost | end of season |
|---|---|---|---|---|
| COW | **9** | 11 | $400 each | 6 |
| SHEEP | **3–4** (10 in YARN worlds) | 4 | $500 each | **0** |
| GOOSE | **7** | 7 | $300 each | 5 |

Median animal spend ≈ **$10 400/game**. Feeding peaks at ~21 animals/day around
day 13–22 and collapses to 1/day by day 29.

### 4.1 The YARN / no-YARN split is a herd decision

| | YARN (n=78) | no-YARN (n=45) |
|---|---|---|
| SHEEP max | **10** | **3** |
| GOOSE max | 6 | 8 |
| COW max | 9 | 9 |
| WOOL sold | 226 | 46 |
| EGG sold | 171 | 267 |
| end bank | $114,871 | $108,656 |

`YARN_STORE` unlocks at a median of **day 6** and appears in **78/123 games**.
When it does, DSM commits ~10 sheep; when it does not, he runs 3 sheep and
backfills with geese. He does **not** discover this from the market — he reads
it off `town.unlocked_shops` and switches species. That is the single clearest
example of "call and response to demand" in the whole corpus.

The no-YARN counter-move is geese, not cows: EGG sold rises 171 → 267 while WOOL
falls 226 → 46. Egg's curve is gentle (base $50, log above `I0`, ~$38 even at
`I0+800`), so a goose flock can be sold almost without limit — exactly the
opposite of wool, whose curve hits $1 by `I0+50`.

### 4.2 The release: he lets the herd go at the end

This is deliberate, not a defect. Escapes by day across the corpus:

| day | 24 | 25 | 26 | 27 | 28 | 29 |
|---|---|---|---|---|---|---|
| escapes | 69 | 71 | **164** | 51 | **143** | **553** |
| feed | 12 | 14 | 11 | 11 | **3** | **1** |
| care | 11 | 14 | 11 | 11 | **2** | **1** |

Feeding and care stop on day 28 and the animals escape on days 28–29 (median
total **10 escapes/game**, 1 325 across the corpus). The logic is that an animal
carried to the bell costs feed and produces goods that must then be sold into a
market that is already saturating; letting it walk away converts the remaining
season into pure selling time and frees the hands. SHEEP reach **0** on day 29.
Note the sequencing: **the release happens after the sheds are already full**
(shed max 93 on day 28), so the escaping animals are the ones whose output the
market can no longer absorb.

---

## 5. Crops

Median purchases per game: WHEAT 191 seeds, CARROT 48, STRAWBERRY 49, MELON 23,
TOMATO 18. Median seed spend ≈ **$10 740**.

| crop | peak tiles | when | note |
|---|---|---|---|
| WHEAT | ~32 (day 11, 23–25) | all season | feed + the biggest single sale line |
| STRAWBERRY | **30** (day 15–18) | days 2–28 | ongoing; sold at $135.6 avg — **above** its $120 base |
| TOMATO | 16 (day 19) | days 9–27 | ongoing, $66.6 avg vs $60 base |
| CARROT | 23 (day 26) | days 17–27 | a *late* crop: ramps exactly as strawberry is retired |
| MELON | 10 (day 1–9) | days 0–11 | **abandoned after day 11** |

**CROPS ARE ROTATED, NOT STACKED.** MELON is a day-0 crop and is gone by day 11.
STRAWBERRY peaks day 15–18 and is at 4 tiles by day 29. CARROT does not appear
until day 17 and is at 23 tiles by day 26. Seed purchases mirror this (MELON 23
seeds early, CARROT 48 spread late). DSM is continuously retiring one crop and
standing up the next, so the harvest arriving at the shed is a *diversified*
basket rather than one glut.

**STRAWBERRY IS SOLD ABOVE ITS BASE PRICE.** 223 units at $135.6 average against
a base of $120 — the market for strawberry is *below* `I0` when he sells. He
never sells strawberry above `I0+100` (that bucket is literally empty in the
curve table below).

**Watering peaks at 63 ops/day (day 24–26) and halves to 24 on day 29** while
fertilizing runs 10–17/day all season and stops dead on day 29. The work is
front-loaded into the productive window and switched off for the endgame.

---

## 6. Late game: the weeds are the plan

| day | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| weeds (median, end of day) | 0 | 1 | 1 | 1 | 2 | 2 | 2 | 2 | 3 | **6** | **10** |

Weeds are **zero for the first 19 days** and then climb monotonically to 10 by
day 29. Weed spawn is a flat 0.5 %/tile/day and is unavoidable on any unwatered
tile — so the weed count is a direct readout of **how much land DSM stops
watering**. Watering drops 63 → 24 ops, feed 21 → 1, care 21 → 1, fertilizing
17 → 1, across days 26–29.

He is not "losing" those tiles. He is **retiring production in the last four
days and converting the labour into harvesting and selling**, exactly when the
market cannot absorb more supply. The shed stays loaded (85–94) right through
day 28, the herd is released, and the last days are spent liquidating.

---

## 7. The shed

| | median |
|---|---|
| max shed reached | **100** (he does hit the cap) |
| shed max, day 12 | 64 |
| shed max, day 14 | 88 |
| shed max, day 15–28 | **93** |
| shed max, day 29 | 85 |

The shed is not kept "lean" in the sense of empty — it is kept **full and
rotating**. He holds 85–94 units through the middle of the season. What matters
is *what* is in it and whether it turns over.

Units sitting in the shed at end of day, totalled over the corpus:

| product | units | per game |
|---|---|---|
| WHEAT | 6 549 | 53.2 |
| STRAWBERRY | 4 295 | 34.9 |
| MILK | 3 641 | 29.6 |
| WOOL | 3 030 | 24.6 |
| EGG | 2 605 | 21.2 |
| CARROT | 1 343 | 10.9 |
| TOMATO | 1 153 | 9.4 |
| FERTILIZER | 419 | 3.4 |
| MELON | 84 | 0.7 |

WHEAT is the ballast — it is the feed reserve and the most liquid commodity.
FERTILIZER is almost absent (3.4/game), which is the tell: he collects it and
gets rid of it, he does not warehouse it.

**Discards: RETRACTED — not measurable from this corpus.** An earlier revision of
this file claimed DSM discards "≈19 units/game, ~0.65 per game-day, spread thinly
across all nine products, EGG-dominated (497 units)". That came from a *model* of the
hour-23 force-drop, and the model does not survive calibration. Run against our own
arm, where the audit gives the exact answer, it lands the **total** within −10 %
(5.61 modelled vs 6.22 actual per game) but gets the **composition** badly wrong —
WHEAT 0.44 modelled vs 3.28 actual, STRAWBERRY 0.22 vs 1.33 — because it computes
the free room from the start-of-step shed instead of the post-market, post-unit one.

There is no market audit in these replays, so DSM's true discard composition is
**unrecoverable**, and the claim above was being used as a target. Do not rebuild it.

What *is* observed and safe to build on: the **end-of-day shed total** — median **4**,
min 0, max 11, with 1112 of 3690 game-days ending at exactly 0 — and the fact that
the shed is a transit buffer, not storage (§7 above).

---

## 8. Market management — the core of the team

### 8.1 Per-product season totals (median per game)

| product | sold | harvested | bought | fed | revenue | inv min | inv mean | inv max | px sold avg | px min | px max | base |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WHEAT | 562 | 764 | 183 | 372 | $19,553 | 9,736 | 9,859 | 10,092 | 34.6 | 21 | 41 | 25 |
| CARROT | 190 | 190 | — | — | $7,687 | 9,863 | 9,968 | 10,024 | 39.8 | 30 | 45 | 35 |
| TOMATO | 117 | 119 | — | — | $7,459 | 9,895 | 9,970 | 10,000 | 66.6 | 63 | 72 | 60 |
| STRAWBERRY | 223 | 223 | — | — | $32,452 | 9,899 | 9,986 | 10,041 | 135.6 | 49 | 202 | 120 |
| MELON | 60 | 60 | — | — | $12,546 | 9,989 | 10,100 | 10,119 | 208.7 | 136 | 250 | 250 |
| EGG | 207 | 207 | — | — | $9,938 | 9,946 | 9,996 | 10,046 | 46.3 | 43 | 53 | 50 |
| MILK | 191 | 192 | — | — | $16,901 | 9,963 | 10,023 | 10,071 | 90.6 | 13 | 207 | 160 |
| WOOL | 104 | 104 | — | — | $13,130 | 9,993 | 10,039 | 10,059 | 128.0 | 1 | 206 | 200 |
| FERTILIZER | 266 | 262 | 0 | — | $13,623 | 10,000 | 10,258 | 10,459 | 52.1 | 8 | 100 | 100 |

**The `inv max` column is the signature.** For the six shop-bought goods the
market never goes far above `I0`:

- MILK max **10,071** — its curve hits $1 at ~`I0+90`
- WOOL max **10,059** — hits $1 at ~`I0+50`
- STRAWBERRY max **10,041** — hits $1 at ~`I0+75`
- EGG max 10,046, TOMATO max 10,000, CARROT max 10,024

Only FERTILIZER (max 10,459) and MELON (10,119) are allowed to run — FERTILIZER
because it has essentially no buyer and a gentle linear curve, MELON because its
supply is small and finite.

### 8.2 Where on the curve he sells

For every SELL order in all 123 games, the **shared market inventory at the
moment of the order**, bucketed. This is the single most important table in this
document.

| product | sell orders | median inv at order | `<9900` | `9900–10000` | `10000–10050` | `10050–10100` | `>10100` |
|---|---|---|---|---|---|---|---|
| WHEAT | 13,355 | 9,867 | **45,800** | 14,508 | 4,144 | 2,774 | 5,425 |
| CARROT | 2,836 | 9,903 | 12,580 | 8,913 | 3,019 | 1,849 | 618 |
| TOMATO | 2,460 | 9,930 | 6,323 | 6,427 | 2,018 | 276 | 109 |
| STRAWBERRY | 10,077 | 9,985 | 4,784 | **14,113** | 8,297 | 685 | **0** |
| MELON | 1,111 | 10,061 | 0 | 0 | 3,354 | 2,724 | 1,338 |
| EGG | 4,112 | 9,999 | 2,708 | 9,973 | 5,141 | 3,296 | 5,794 |
| MILK | 7,051 | 10,046 | 86 | 5,852 | **10,366** | 7,855 | **0** |
| WOOL | 7,106 | 10,041 | 454 | 5,915 | **10,149** | 3,810 | **0** |
| FERTILIZER | 12,844 | 10,214 | 0 | 0 | 3,047 | 3,135 | **28,171** |

Read the last column against the product's curve:

- **MILK / WOOL / STRAWBERRY: exactly zero units sold above `I0+100`.** Not "few"
  — zero. The $1 floor is not avoided by reacting to the price, it is avoided by
  a *hard inventory stop* at the point where the curve breaks. This is why his
  floor rate on those three is 1.6 %, 2.7 % and 0.4 % respectively, while ours
  runs far higher.
- **WHEAT is the opposite play.** 45 800 of 72 651 units (63 %) are sold *below*
  `I0` — when the curve pays $37–41 against a $25 base. Only 5 425 units go out
  above `I0+100`. He treats wheat as a scarcity asset: hold it, sell it when the
  market is short.
- **EGG is sold freely** (5 794 units above `I0+100`) because the egg curve is
  log-shaped and $38 is still a good price against a $50 base. There is no reason
  to hold it, so he doesn't.
- **FERTILIZER is dumped** (28 171 units above `I0+100`, 82 % of its volume). No
  shop buys it, the curve is linear and gentle, and the only productive use is
  `FERTILIZE` — so surplus goes out the door for whatever it fetches.

### 8.3 The sell-price outcomes

Floor units across the whole corpus — 3 690 game-days, 255 771 units sold:

| product | units sold | at the $1 floor | floor share |
|---|---|---|---|
| WHEAT | 72,651 | 0 | **0.000 %** |
| CARROT | 26,979 | 0 | **0.000 %** |
| TOMATO | 15,153 | 0 | **0.000 %** |
| MELON | 7,416 | 0 | **0.000 %** |
| EGG | 26,912 | 0 | **0.000 %** |
| STRAWBERRY | 27,879 | 123 | 0.441 % |
| MILK | 24,159 | 386 | 1.598 % |
| WOOL | 20,328 | 549 | 2.701 % |
| FERTILIZER | 34,353 | 944 | 2.748 % |
| **total** | **255,830** | **2,002** | **0.78 %** |

Strip out FERTILIZER (which has no buyer at all) and the floor rate across the
eight tradeable goods is **0.48 %** — 1 058 floor units out of 221 477 sold.

### 8.4 The buy side

DSM buys exactly two products, and only two:

- **WHEAT**: median **183 units/game** (~$6 700 of spend), against 764 harvested
  and 372 fed. He grows most of his own feed and tops up the shortfall at market.
  Buying feed rather than growing it frees the crop plan for higher-value goods
  and lets the herd size be independent of the wheat acreage.
- **FERTILIZER**: median **0**.

No other `BUY_PRODUCT` appears in 123 games. He never buys a good to resell it.

### 8.5 Market-making is not his game

A comparison worth stating explicitly, because our own replays show the
confusion: on some seeds our agent runs a **wheat wash** — thousands of units
bought and immediately resold per game. That wash is **margin-neutral** (same
seed, same game: $86 763 with it, $86 568 without) because the engine quotes
`BUY_PRODUCT` at post-buy inventory, so a same-inventory round trip nets zero.
DSM's 183-unit buy book is three orders of magnitude too small to be a wash. His
wheat volume is *harvested* wheat (764/game) plus a small feed top-up — every
unit is either fed or sold once.

---

## 9. Shop unlocks and the demand response

| shop | median first-unlock day | games with it | buys |
|---|---|---|---|
| YARN_STORE | **6** | 78/123 | WOOL |
| ICE_CREAM_SHOP | 9 | 87/123 | STRAWBERRY, MILK, WHEAT |
| BRUNCH_SPOT | 12 | 94/123 | EGG, WHEAT, STRAWBERRY |
| SMOOTHIE_SHOP | 12 | 80/123 | STRAWBERRY, MILK |
| PET_CAFE | 12 | 78/123 | CARROT |
| BAKERY | 12 | 76/123 | EGG, WHEAT |
| PIZZA_SHOP | 12 | 76/123 | MILK, TOMATO, WHEAT |
| FARMERS_MARKET | 15 | 84/123 | WHEAT, CARROT, TOMATO, STRAWBERRY… |

Shops unlock every 3 days, drawn **with replacement** from the full pool, capped
at 8 instances. So the shop set is **memoryless** — there is no deterministic
future signal to plan against. DSM's response is therefore always *reactive and
immediate*:

1. **YARN_STORE at day 6 → 10 sheep instead of 3.** The strongest response in the
   corpus, and it happens within the same day the shop appears.
2. **No YARN → geese.** EGG sold rises 171 → 267, WOOL falls 226 → 46.
3. **CARROT is a late crop** (tiles appear day 17+, 48 seeds bought) which lines
   up with PET_CAFE's median day-12 unlock and FARMERS_MARKET's day 15.
4. **MILK is sold the same way in both worlds** (187 vs 206 units, $88.6 vs
   $93.6) — because 118 of 123 games have at least one milk shop, and the cow
   herd is 9 either way. The measured exception: in the **5 games with no milk
   shop at all**, cows drop to **5** and milk sales to 54.

The pattern is: **the herd and crop mix flex with the shops; the sell rule does
not.** The sell rule is the same invariant inventory-targeting rule in every
world.

---

## 10. Revenue mix

Median revenue per game **$149,958** from **2 018 units**, against a median end
bank of **$110,708** and a $3 000 start — i.e. roughly **$42 000 of spend**, of
which seed ≈ $10 740, animals ≈ $10 400, land $7 000, and the rest (~$14 000)
labour. Median spend per game is dominated by the fixed daily hire bill, not by
inputs.

Median **per-game** share of revenue (each game's own split, then the median —
not a ratio of medians):

| product | share of revenue |
|---|---|
| STRAWBERRY | **21.1 %** |
| WHEAT | 13.0 % |
| MILK | 11.9 % |
| FERTILIZER | 9.2 % |
| WOOL | 9.1 % |
| MELON | 8.1 % |
| EGG | 6.3 % |
| CARROT | 5.2 % |
| TOMATO | 4.6 % |

**No product is more than 22 % of revenue.** Nine revenue lines, all between 4.6 %
and 21.1 %. That is the structural reason the team is robust to a bad shop draw
and to a hostile opponent: there is no single line that can be shut off.

---

## 11. The transferable rules

Distilled, in priority order. Each one is directly supported by a table above.

1. **Never sell a knife-edge good into the break.** For MILK, WOOL and
   STRAWBERRY the rule is a hard stop at roughly `I0`, not a price reaction —
   DSM sells literally zero units above `I0+100` in those three, and 0.4–2.7 %
   of volume ever reaches $1. Any sell-side change we make must preserve that.
2. **Let the curve decide per product, not a global threshold.** WHEAT is held
   for scarcity (63 % of volume sold below `I0`); EGG and FERTILIZER are sold
   continuously. The same rule applied to all three produces the wrong answer for
   two of them. The dividing line is the shape of `above_func`:
   `linear`/`sq` = hard ceiling, `log` = sell freely.
3. **Flex the herd and the crop mix to the shop draw; keep the sell rule
   invariant.** YARN → 10 sheep, no YARN → 3 sheep + more geese. No milk shop →
   5 cows. Crops rotate (melon → strawberry → carrot) rather than stacking.
4. **Cut production at the end instead of selling at the end.** Weeds go 0 → 10
   over days 20–29 because watering, feeding, care and fertilizing are switched
   off (63 → 24 water ops, 21 → 1 feed). The last four days are liquidation, not
   production.
5. **Release the herd once the sheds are already full.** Feed stops day 28, ~10
   animals/game escape. The escape is the disposal mechanism for animals whose
   output the market can no longer take.
6. **Diversify revenue.** Nine lines, none above 22 %. Do not optimise a single
   product's throughput.
7. **Keep the shed full but rotating.** The end-of-day shed total (median 4) is
   the observed signal; the earlier "~19 discard units/game, spread evenly" figure
   is withdrawn as unmeasurable — see §7.
8. **The objective is the loss tail, not the win size.** 118–5, and all five
   losses are under $3 600. Nothing DSM does is worth a $20 000 blow-up.

---

## 12. Known gaps in this analysis

- **Discards are NOT measurable here.** The day-end figure has to be modelled from
  the hour-23 force-drop, and that model calibrates badly against our own audited
  arm: −10 % on the total but ~7x wrong per item. See the retraction in §7 — no
  per-item discard claim for DSM should be used at all.
- **`land_cost_total` is unusable for LB replays** — it reports up to 88,000 against
  a real ceiling of 7,000 (1,000 + 2,000 + 4,000). Read quadrants from the replay's
  `unlocked_quadrants` instead.
- **Revenue per product** is computed from the quoted price at order time
  (`market.prices[item]` when the SELL was issued), not from a committed-trade
  audit. Because the engine quotes per unit in lockstep, this is close but not
  exact for large orders that walk the curve.
- **Animal escapes are inferred** from an animal disappearing from a structure
  tile. A `DIG`ped empty structure is indistinguishable from an escape in the
  same step, so days with heavy structure removal may over-count slightly.
- **`hires_today` and money** are read at the last step of each day, so day `d`'s
  money is the bank *after* day `d`'s spending.
- 123 replays is what was downloadable; AGENTS.md quotes 124 games / 118–6. The
  discrepancy is one episode, and the direction of the record is unchanged.
