# TOP_PLAYER_GAP.md — What the current agent does wrong, measured against the top player (DSM)

Data-anchored comparison between our production agent (`old` = `src/main.py` alone) and the
top tournament opponent **DSM**, using only what the replays actually contain. Every claim cites
a concrete `seed`, `day`, and `column`. **No generalities.** This file is the analysis that feeds
`ERRORS.md`; each "fix item" below names the exact observable it moves and the same-seed command
to prove it.

---

## 0. Sources, and which numbers may be trusted

| Source | Contents | What is trustworthy |
|---|---|---|
| `replays/DSM/*.json` + `replays/DSM/days_seed1120*.csv` (124 episodes) | DSM's leaderboard games; both seats analysed with `--lb`; rows where `agent == "DSM"` are the top player's own seat | **structural fields only** (see below). |
| `diag-replays/sweep_old_s4362837462_b15/games.csv` + `days_seed4362837462.csv`… (15 seeds × 13 public agents, 195 games) | our `old` agent's seat vs the 13 public opponents | full audit-backed fields (realized `avg_price_<p>`, `sell_revenue_total`, `floor_sales`, `below_base_*`). |

**Hard comparability rule.** Leaderboard replays (`--lb`) carry **no market audit**, so on the DSM
rows these columns are **missing/unusable**, and we must never compare them across the two datasets:

- `sell_revenue_total` (= 0 on every DSM row), realized `avg_price_<p>`, `revenue_<p>`,
  `premium_below_base_frac` (needs realized prices), `below_base_sales_*`.

These price-timing claims are therefore asserted **only from our own audited sweep runs**, never from
DSM. The columns that **are** audit-independent and fair to compare (structural + spend) are:
`idle_share_pct`, `idle_units_total`, `idle_units_ready_total`, `locked_steps`, `shed_overflow_days`,
`shed_pressure_days`, `discarded_units_total`, `discarded_items`, `animal_cost_total`,
`escaped_by_type`/`animal_escapes`, `plants_died`, `plants_fertilized`, `wheat_fed`, `feed_surplus`,
`land_cost_total`, `land_unlocks`, `hire_cost_total`/`hires`, `seed_cost_total`, `product_cost_total`,
`max_shed_total`, `weeds_peak`.

Second caveat: DSM's 124 games are against arbitrary leaderboard opponents of varying strength, while
ours are vs the fixed 13 public files. So this report compares **distributions** of each metric, never
paired head-to-head finals, and never a money mean.

---

## 1. The headline fact: our agent is mid-field, not dominant

Out of **195** sweep games (`diag-replays/sweep_old_s4362837462_b15/games.csv`), our `old` agent went
**~146 W / 49 L** (~25% losses), and almost every loss is razor-thin:

| opponent | seed | our final | opp final | result |
|---|---|---|---|---|
| kaggriculture-one-more-wheat | 4362837462 | 71715 | 71920 | **LOSS** (−205) |
| kaggriculture-one-more-wheat | 4362837471 | 92600 | 93071 | **LOSS** (−471) |
| kaggriculture-pipe16-idle-workers | 4362837462 | 72154 | 72330 | **LOSS** (−176) |
| kaggriculture-master-engine-v3 | 4362837474 | 111807 | 112079 | **LOSS** (−272) |
| kaggriculture-v53-opening-signature | 4362837475 | 122696 | 123202 | **LOSS** (−506) |

Even the "wins" are often single-digit-$-thousand margins (e.g. seed 4362837462 `74147 vs 61722`,
`95346 vs 83599`). The ladder pays **wins**, so flipping a handful of these ±$500 games is the whole
game. Against a top enemy the same thin margins decide rating. **DSM's typical final is 100k–184k**
and it beats most opponents by tens of thousands (e.g. `149697 / 44266`, `168479 / 52225`,
`183954 / 90553`); our high-water marks (~140k) are near DSM's *average*. So the gap is structural
throughput, not luck.

---

## 2. The single most reproducible differentiator: workforce idle

### 2a. DSM's day-by-day `idle_share_pct` (three episodes)

`idle_share_pct` = `n_pass / unit_turns`, computed the same way for both datasets. DSM's **game average
is 3.2–4.1%**, but that masks a two-phase shape: setup-idle early, then ~0% for the rest of the season.

| day | 112077395 big win (149697) | 112298128 thin loss (120732) | 112076061 mirror (104928) |
|---|---|---|---|
| 0 | 8.0 | 8.0 | 8.0 |
| 1 | 18.1 | 21.1 | 20.2 |
| 2 | 23.5 | 24.1 | 24.1 |
| 3 | 27.2 | 28.4 | 32.1 |
| 4 | 40.1 | **42.6** | 40.3 |
| 5 | 35.2 | **46.3** | 44.4 |
| 6 | **2.4** | **3.4** | **1.0** |
| 7 | 8.7 | 8.7 | 9.6 |
| 8 | 8.7 | 8.7 | 6.5 |
| 9 | 2.0 | 0.0 | 0.4 |
| 10 | **0.0** | 3.5 | **0.0** |
| 11 | 0.4 | 0.0 | 0.0 |
| 12 | 0.0 | 0.0 | 0.0 |
| … | … | … | … |
| 29 | 0.0 | 0.4 | 0.0 |

**Call-response read:** DSM spends days 0–5 *setting up* (buying the opening herd, structure, seeds;
money is spent, nothing to collect yet, so 8–46% idle is normal and free). Then, from the day it begins
scaling (d6, when it buys the SW quadrant and a bigger herd), idle collapses and **stays ≈0% through the
bell**. DSM's idle after day 9 is ~0 in a **win**, a **loss**, and a **mirror match** — it is a constant of
the engine, not a property of the result. Its idle is bounded by setup, not by laziness.

### 2b. Our agent's day-by-day `idle_share_pct` (seed 4362837462, vs public-state-router)

Same column, same harness:

| day | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| idle% | 22.4 | 37.6 | 20.7 | 10.8 | 16.4 | 13.0 | 7.0 | 6.0 | 11.1 | 2.9 | 5.8 | 3.2 | 8.7 | 1.3 | 5.2 | 1.6 |

| day | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| idle% | 4.0 | 2.9 | 4.7 | 4.7 | 5.5 | 1.1 | 4.7 | 1.1 | 4.4 | 4.1 | 5.2 | 2.5 | 5.5 | 9.1 |

The contrast is exact: **DSM reaches ~0% from day ~10 and holds it; we never reach 0% and in the very
days (10–29) when there is the most to collect/sell we sit at ~1–9% (mean ≈4.2%), spiking to 9.1% at the
bell.** With ~274 unit-turns/day that ≈ 10–11 idle worker-turns/day on days 10–29 ≈ **~210 idle
worker-turns wasted in the productive half of the season, vs DSM's ~0.**

### 2c. What kind of idle it is (the highest-value kind)

`games.csv` comparison (audit-independent):

| metric | our `old` (sweep, 195 games) | DSM (124 lb games) |
|---|---|---|
| `idle_units_total` / game | 340–590 | 200–310 |
| `idle_units_ready_total` (PASS standing on READY produce/animal) | **10–61** | **0–1** |
| `locked_steps` (worker-turns parked on unbought LOCKED land) | ~125–233 | ~86–125 |

`idle_units_ready_total` is the smoking gun: our units repeatedly PASS **while standing on ready
produce / a full animal tile** (a missed collection — exactly the "labour is movement; waste shows up as
idle-in-place" defect from `AGENTS.md`). DSM literally never does this (0–1). `locked_steps` shows we
also route/park hands across board we don't own ~2× more than DSM.

**Fix item F1 — collapse sustained idle, convert idle-on-ready to collect/sell.**
Proven by: our d10–29 `idle_share_pct` mean ≈4.2% (never 0) vs DSM ≈0% (days 10–29 of
112077395/112298128/112076061); our `idle_units_ready_total` 10–61 vs DSM 0–1.
Likely root (see `GAME_DYNAMICS.md` §watering): watering everything **every day** wastes worker-turns —
ongoing crops (tomato/strawberry) need water only every other day *unless fertilized*, and first-day/
age-1 water on one-shot crops buys survival only (0 yield bonus). Convert those wasted water-turns into
harvest/collect/sell. Locate the exact layer with `make xray PA=9 SEED=700` (`hand_align`, the watering
scheduler, the collect priority in `main.py`).
**Accept rule (same-seed `make compare PA=<idx> BATCH=12 SEED=700`, judged per-opponent on WIN):**
after day 10 `idle_share_pct` <3%, `idle_units_ready_total` <3, and the WIN tally does not drop.

---

## 3. Shed overflow: we discard; DSM never discards

From `games.csv`, audit-independent:

| metric | our `old` | DSM |
|---|---|---|
| `shed_pressure_days` (≥95) | 1–6 | 2–12 |
| `shed_overflow_days` (==100) | 0–4 | 1–8 |
| `discarded_units_total` | **>0** (e.g. `{FERTILIZER}`, `{WHEAT}`, `{WOOL}`, `{STRAWBERRY}`) | **0 in every seat** |

DSM regularly **pressures** the 100-cap shed (days at 100) but **always sells to drain before it
throws anything away**. Concrete: episode 112077395 (DSM seat 0) **day 24** has
`shed_items_start total = 100` (at cap), yet `discarded_units = 0` and `market_orders = 50`
(`sell_qty_WHEAT 63`) — it liquidates on the very day it hits cap, ending the day at `end_shed_total 0`.

Our agent instead lets the shed fill and **destroys stock** — and because we also sell fertilizer below
base (see §5), we are often discarding the very input we under-use.

**Fix item F2 — stop shed-overflow discards.**
Proven by: our `discarded_units_total` >0 in most sweep games (shed_overflow_days up to 4) while DSM's is
0 at every shed-pressure day (e.g. 112077395 d24 start=100 end=0 discard=0).
Surfaces in `src/main.py`: the `room_guard`, `clamp_sells`, `sell_lead`, `dead_stock`,
`terminal_liquidation` layers already exist to keep the shed ≤99/100 — verify with `make xray` which one
is failing to fire before the end-of-day overflow drop.
**Accept rule (same-seed compare):** `discarded_units_total → 0` on the same seed, `sell_revenue_total`
no worse than −10%, WIN no regression.

---

## 4. Animal escapes are the wrong lever; scale and feed are the right one

The existing `ERRORS.md` treats an animal escape as an unqualified `[MEDIUM]` loss (E5). Against DSM the
data says the opposite:

| metric | our `old` | DSM |
|---|---|---|
| `animal_cost_total` / game | 6.5–7.9k (~1–2 COW, few GEO/GOOSE per game; `escaped_by_type` almost always a single `GOOSE:1` or none) | **8–25k**; herds like `COW:10`, `SHEEP:19`, `GOOSE:6`, and commonly **3–19 animals of 2–3 species simultaneously** (read off `escaped_by_type`) |
| `animal_escapes` / game | 0–1 | **3–24** |
| `feed_surplus` (produced−fed) | sometimes **negative** (−22 … −60) | mostly positive (162, 295, 91, 82…) |
| `wheat_fed` | ~290–470 | ~320–470 |

DSM deliberately runs a large, diverse herd, **accepts a dozen-plus escapes per game, and still out-earns
everyone** (its turnover dwarfs the loss). Our agent's failure mode is the mirror: a *tiny* herd that
still occasionally under-supplies feed (`feed_surplus < 0` in several games). Preventing escapes on a
small herd is optimising the wrong variable.

**Fix item F3 — scale the herd toward DSM's throughput, but only with feed in the bank.**
Proven by: DSM `animal_cost_total` 8–25k vs our 6.5–7.9k; DSM `escaped_by_type` shows 3–19 cows/sheep
concurrently vs our 1–2; yet our `feed_surplus` is sometimes negative while DSM's is positive.
Guard: scaling the herd while `feed_surplus` is negative just forces escapes (2 consecutive unfed → escape,
`GAME_DYNAMICS.md`). Because this changes planting coverage, it can decouple the shared shop/weed RNG
stream (`AGENTS.md` caveat) — so **evaluate the combined scale+feed patch on the same seed, judged on
WIN**, never each piece alone.
**Accept rule:** herd grows, `feed_surplus ≥ 0` all season, `animal_escapes` not exploding relative to
herd size, WIN improves per opponent.

---

## 5. Price timing (refined E1/E2) — from our audited runs

DSM has no realized prices, so this section is our own `old` data only (`days_seed4362837462.csv`).

**We already catch the scarcity spike on the premium crops it matters for — but we butcher the tail.**
Same game, day 10 (audited `avg_price_<p>`):

| product | base | day-10 sell | avg realized | vs base |
|---|---|---|---|---|
| STRAWBERRY | 120 | 60 | **216.67** | **+80%** ✓ |
| EGG | 50 | 12 | **187.75** | **+275%** ✓ |
| WOOL | 200 | 9 | **77.22** | **−61%** ✗ |

That is the correct pattern early: sell the strawberry/egg spike (we do). But then we **over-produce
strawberry into a glut and dump it to the floor** in the last third of the season (same game):

| day | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 |
|---|---|---|---|---|---|---|---|---|---|
| STRAWBERRY `avg_price` (base 120) | 60.57 | **8.82** | **4.53** | 7.14 | 27.2 | 35.5 | 38.4 | 38.4 | 35.5 |

So E1 is not "we sell premium goods below base" broadly — our **TOMATO (avg ~45–48 vs base 60 in the
gluts, 180–200 on spike days), early STRAWBERRY (216), and EGG (187) capture the spike**. The real leak
is (a) **WOOL realised ~77–114 vs base 200 for most of the season** and (b) **late-season STRAWBERRY
dumped to the $1 floor** (avg 4.5–8.8) because we timed it out of the demand window. `premium_below_base_frac`
for our `old` is 0.45–0.86/game.

**Fertilizer (`E2`).** In our days CSVs, `plants_fertilized = 0` on **days 2–12** (the wheat/carrot and
melon bonus window) in the sample game, even though the herd is bought by ~day 6 — while DSM (mirror
112076061) shows `plants_fertilized = 5–16/day` from mid-season. We sell fertilizer that we could be
farming with.

**Fix item F4 — hold the WOOL/MILK price floor AND fertilise the window (extends the existing floor gate).**
The `agent.py` `E1_PARAMS` floor gate already hedges WOOL/MILK (`--exp floor` grid: `price_frac`,
`hold_cap`, `shed_cap_frac`) — but it is too weak to stop the late straw dump and does nothing about
applying fertilizer. Sweep it wider and add a fertilise-during-window rule.
**Accept rule:** `make grid --exp floor PA=... GRIDPARAMS='price_frac=[0.0,0.4,0.7,1.0];hold_cap=[0,5,10,20]'`;
accept a combo that drops `avg_price_WOOL/MILK/STRAWBERRY`-below-base on the same seed AND raises
`plants_fertilized` days 2–12 AND keeps the guard columns green (`premium_below_base_frac` falls, WIN no
regression).

---

## 6. Land: the top player can over-expand, and it loses them

DSM's typical land spend is 6–12k (SW + SE). But its **thin loss** (112298128, 120732 vs 122414) is
exactly the over-expansion case: on **day 10 it spent `land_cost 32000` / `land_unlocks 8`** — buying far
more board than it can work — and finished with `weeds_peak 14`, `plants_died 39`, still losing by $1,682.
So even the top player pays for buying land it can't keep busy.

Our `old` already runs 6–10k land (SW / +SE), which is in DSM's healthy range. The point is a **guard**,
not a patch: land must be added only in lock-step with worked tiles and hands (`GAME_DYNAMICS.md`: "land
is cheap; *worked* land is not"). Fold this guard into F3/F4 so a scale-up doesn't turn into
over-expansion.

**Fix item F5 (guard) — never buy land you cannot staff.** Do not add land unless the new tiles are
matched by worked ground + the hand count to cover it. No independent test needed beyond the F3/F4
combined WIN run.

---

## 7. Day-by-day call-response rules DSM follows (the "how")

Distilled from the per-day episodes above — these are the behaviours to reproduce, each with its evidence:

1. **Setup idle is free; productive idle is not.** Days 0–5 idle 8–46% (nothing to collect, spending only);
   after the d6 scale-up, idle must be ~0% (all three episodes). *We keep 1–9% idle in that productive
   window (F1).*
2. **Scale on the season.** d6: buy SW (`land_cost 2000`) + a large herd (`animal_cost 3400`) + seeds
   (`seed_cost 1810`) + ramp hands 8→; d9–10: buy SE (`4000`) and peak hands at 14 (112077395 d10 `hires`
   cost spike, idle still 0.0). Reinvest cash the same day it lands.
3. **Sell into scarcity, drain before the cap.** Sell WHEAT/EGG/STRAWBERRY on the shop-unlock spike days
   (d8 revenue 2761, d10 7444, d18 BAKERY 12159); when the shed hits 100 (d24) sell same-day —
   `discarded_units` stays 0 (F2).
4. **Liquidate at the bell.** d28–29 sell the standing shed wholesale (`sell_qty_WHEAT 97→105`,
   `CARROT 26→39`), drop hands 11→8–10, leave only a small `stranded_at_bell`. Our d29 idle spiked to 9.1%
   while DSM's was 0.0.
5. **Accept animal loss as a cost of scale, but never run negative feed** (DSM feed_surplus positive;
   ours occasionally negative).

---

## 8. Priority order of fix items (work top-down)

1. **F1 idle collapse** (biggest, seed-independent, directly reproduces the top player's #1 trait). Surface:
   `main.py` watering/harvest/collect scheduling; locate with `make xray`. Judge on WIN, same-seed.
2. **F2 shed-overflow discards** (clean, verifiable: `discarded_units_total → 0`). Surface:
   `room_guard`/`clamp_sells`/`sell_lead`/`dead_stock`.
3. **F4 premium/fertilizer timing** (extend `E1_PARAMS` floor gate; fertilise the water window).
4. **F3 herd/feed scale-up** (only after F1/F4 land; feed_surplus guard; evaluate combined on WIN).
5. **F5 land lock-step guard** (built into F3/F4; plus never buy land you can't staff).

Test everything with **same-seed `make compare PA=<idx> BATCH=12 SEED=700`** (or `./sweep.sh new` for a
broad read) and with the 13-public-agent field; judge on the **per-opponent WIN tally**, never a money mean.
