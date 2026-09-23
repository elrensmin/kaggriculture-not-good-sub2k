# ERRORS.md — concrete gameplay errors in the current agent

Found by mining our saved replays (`diag-replays/**/new_vs_*.json`, `old_vs_*.json` —
the `main.py`/`agent.py` production seats) and reading the engine's rules back against the
measured numbers in `ntbk/kaggriculture-visualized-what-every-crop-pays.ipynb`.

Every error below is a **system-level defect** you can point at in a specific game / day /
step — not a mean, not a luck issue. Each entry gives the concrete evidence, why the mechanic
makes it a loss, and where to look to fix it. Severity is how much money it leaks.

---

## E1. Livestock by-products + melon sold into the glut / at/under base  [HIGH]

**Evidence (audited per-product totals across all 16 `run-1/grid/baseline` games
vs master-engine-v3; `% below base` = share of units sold under base, `% floor`
= share sold at the $1 floor):**

| product | units | % below base | % floor | avg realized / base |
|---|---|---|---|---|
| FERTILIZER | 5358 | **99%** | 1% | $45 / $100 |
| MELON | 1152 | **86%** | 0% | $198 / $250 |
| WOOL | 2396 | **81%** | 20% | $114 / $200 |
| MILK | 3431 | **65%** | 6% | $115 / $160 |
| STRAWBERRY | 3937 | 46% | 13% | $117 / $120 |

Note what is **not** leaking: TOMATO realises $167/base $60 (0% below base — the
scarcity spike is captured), and WHEAT/CARROT/EGG sell at/above base
($40/$47/$52 vs $25/$35/$50). So the defect is concentrated in the livestock
by-products (milk/wool/fertilizer) and melon, not "premium goods" broadly.

**Why it's wrong.** The market is shared and price is a function of how much of
the product exists. `below_base_*` high + `floor_sales` high = we sell after
over-supplying, into the price we (and possibly the rival) crashed — the
opposite of "sell into scarcity." Milk/wool/strawberry/melon use
`above_target > 1`: a small glut craters them. And selling **FERTILIZER below
base is a double waste**: its $100 base is the ceiling *and* it is the input
that doubles watering yield — we burn the input we need to hit max crop output,
then realise it at a discount.

**Fix direction.** Trade output to match the drawn `unlocked_shops`, bundle and
time sales of the crash-prone by-products into a short shelf, and apply
fertilizer to the watering window instead of selling it at a discount. Watch
`avg_price_<p>` / `below_base_sales_<p>` in `days_seed<S>.csv` vs `base`.

---

## E2. Fertilizer liquidated instead of used  [CRITICAL, largest single leak]

**Evidence.** Across all 16 `run-1/grid/baseline` games, FERTILIZER: 5358 units
sold, **99% below base** (`% floor` ~1%), realized ~$45/base $100 (≈ $15.6k of
revenue/seed on a base-$100 good). Yet only ~120–136 units/seed are actually
**applied to crops**: `plants_fertilized` is **0 on days 2–12** (the wheat/carrot
and melon window) even though the herd is bought by day ~6 and `plants_watered`
is 40–48/day — the agent sells 9–17 fertilizer/day during that window instead
of using it. So we are not merely selling surplus; we are liquidating an input
we could be farming through the bonus window.

**Why it's wrong.** Fertilizer is worth $100 but is a *means of production*: applied in the
watering window it doubles yield (the only way wheat reaches its 6-unit cap; +2/day on any
one-shot crop in the window; doubles scheduled fruit on fertilised ongoing days). Dumping ~330
units/seed below base is throwing away the crop boost we should be harvesting with. The engine
even prices it linear both sides (target 0.40), so its *scarce* value is real when the field
under-produces it — instead we add to the glut.

**Fix direction.** Build a fertilizer application schedule (fertilise the window; never sell
below base / at the floor while a watering window is open). If we really can't consume it, at
least sell it into scarcity or hold, never floor it.

---

## E3. Crops decay to weeds concentrated in the final week  [HIGH]

**Evidence.** `plants_died_to_weeds` 20–31 per game; per-day breakdown of one game
(`new_vs_kaggriculture-cloning-agent_seed42`) shows 15 of 20 deaths land on **days 22–28**
(1+7+3+4+5). `missed_harvest_eod` >0 and `stranded_at_bell` 0 mean we are *not* keeping
endgame plants harvested.

**Why it's wrong.** Once a plant passes max lifespan it loses a unit every other turn and
collapses to a weed (harvest before decay). Dying in the last week = either over-planting
crops that cannot mature by the bell, or failing to harvest/convert standing yield. Either way
those tile-days earned nothing and the crops decayed into weeds that now block digging.

**Fix direction.** Endgame scheduler: stop planting crops that won't mature, and convert the
final week's standing stock to cash before the bell. Look at `plants_died`/`missed_harvest_eod`
spikes in the day report and correlate with `shop_unlocks` and `shed_items_*`.

---

## E4. Shed overflow discards inventory (incl. fertilizer)  [MEDIUM-HIGH]

**Evidence.** `shed_overflow_days`>0 in 21/25 games (up to 7 days at/over cap); discarded
units present in 19/25, e.g. `discarded {FERTILIZER: 3}` (`v56seeds-42` game).

**Why it's wrong.** Shed cap is 100 and end-of-day overflow is destroyed. We're harvesting
into a shed already at the cap and throwing away product — including fertilizer we then also
sell below base (E1/E2). Overflow is a timing/aggregation defect: produce accumulates faster
than the shed drains.

**Fix direction.** Match harvest cadence to shed drain (sell before it fills), and treat shed
at ~95 as an urgent sell trigger rather than harvesting more into it. `shed_pressure_days`
(≥95) is the leading indicator.

---

## E5. Animals go unfed / occasionally escape  [MEDIUM → LOW in current baseline]

**Evidence.** `animal_escapes` max 1/6 of the 16 `run-1/grid/baseline` games;
`unfed` signals and `at_risk_of_escape` (≥2 consecutive unfed) present but rare.
This is a real but uncommon scheduling defect, **not** the "2–4 escapes per
game" it used to be — the current agent keeps the herd fed to near-100%.

**Why it's wrong.** Two consecutive unfed end-of-day refreshes → animal escapes, unrecoverable.
Each escape is lost structural + feed cost, and it's a pure scheduling defect (feed is not
being matched to the herd). Even at-risk (unfed-once) animals are one missed day from escape.

**Fix direction.** Guarantee every animal is fed each day before any non-urgent work; check
`animals_fed` vs herd size in `days_seed<S>.csv`, and `at_risk_of_escape` in `games.csv`.

---

## E6. Standing ready produce left unharvested (idle-on-ready)  [MEDIUM]

**Evidence.** `idle_units_ready_total` ~55 and `missed_harvest_eod`>0 in the sample game;
`idle_share_pct` 5–8% overall.

**Why it's wrong.** A unit that PASSes while standing on ready produce/animals is a missed
harvest (and on an animal, a missed collection that also means the cap stops further
production). Idle is the clearest labour-efficiency defect signal and it's present in every
game.

**Fix direction.** Priority pass: harvest/collect before idle. `idle_units_ready_total` and
`idle_share_pct` in `games.csv` are the lead signals.

---

## How to recheck any of these

Baseline = the current production agent's run against master-engine-v3 (16 seeds):

```bash
make render DIR=diag-replays/run-1/grid/baseline   # per-game table + games.csv/days_seed CSV
```

Per-product: open `days_seed<S>.csv` and read `sell_qty_<p>`/`avg_price_<p>`/`revenue_<p>`
and `below_base_sales_<p>` against `base`. E1/E2 are the ones to fix first — they are
concrete, audit-backed below-base leaks that need no average to see.
