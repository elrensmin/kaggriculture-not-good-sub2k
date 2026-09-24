# todo.md — build plan to reach DSM-comparable performance

**Objective: beat all 13 public agents by $30–50k, consistently.**

Current state (`diag-replays/run-1`, 78 games = 13 agents × 6 seeds):

```
W/L/T      36/42/0        win rate 46%
median margin   -$1,415   mean $10,640      <- the mean is one broken opponent
median WIN      $6,328    median LOSS -$3,672
```

The mean is a mirage: `shop-router-0909` finishes with **$3,000** (it does
nothing) and we beat it 6/6 by $162,624, which alone drags the mean from −$1,415
to +$10,640. Against the **12 real agents** the picture is stark and consistent:

| | our median final | their median final |
|---|---|---|
| vs the 12 real agents | **~$104,000** | **~$122,000** |

We lose to six of them (`master-engine-v3`, `pipe16-idle-workers`,
`one-more-wheat`, `v53-opening-signature`, `cloning-agent`,
`market-smart-farming`) and scrape wins on the rest by $4–14k.

**Target math.** To win by $30–50k against a field sitting at $122k we need a
median final of **$152–172k**, i.e. **+$48–68k** on today's $104k. Costs total
only ~$32,762/game (seed 6,760 + animals 6,000 + product 8,741 + hire 5,261 +
land 6,000), so **even eliminating every cost cannot get us there — revenue has to
roughly double.** That rules out tuning; this is a throughput + market problem.

Companion documents: **[dsm_gap.md](dsm_gap.md)** (three-column gap),
**[dsm_v1.md](dsm_v1.md)** (full DSM anatomy and the price-curve data).

---

## 0. Where the money actually is

Taken from our **own** 78 games, split into our 15 best and 15 worst by final
money. Costs are identical; harvests are identical; **only price realization
differs.**

| | top 15 | bottom 15 |
|---|---|---|
| final money (median) | **$160,478** | **$69,446** |
| revenue | $187,211 | $95,538 |
| harvests | 464 | 506 |
| seed / animal / hire / land cost | 6,480 / 6,900 / 5,515 / 6,000 | 6,520 / 5,600 / 5,028 / 6,000 |
| `floor_sales` | **13** | **123** |

Per product, per game — **the same volumes, wildly different prices**:

| product | qty top | qty bot | **px top** | **px bot** | rev top | rev bot |
|---|---|---|---|---|---|---|
| STRAWBERRY | 237 | 234 | **204.2** | **67.5** | $48,427 | $15,790 |
| MILK | 190 | 130 | **232.5** | **38.7** | $44,262 | $5,014 |
| WOOL | 217 | 105 | **174.9** | **103.5** | $38,038 | $10,889 |
| EGG | 15 | 174 | 49.8 | 57.1 | $748 | $9,931 |
| CARROT | 83 | 139 | 34.4 | 61.1 | $2,836 | $8,511 |

**A ~$98k/game swing on STRAWBERRY + MILK + WOOL at near-identical volume.**

So the target is not "produce more" — it is **"get the good-game price in every
game."** We already achieve $204 strawberry / $232 milk / $175 wool in our best
games; DSM's own averages are $148 / $102 / $145. We are *capable* of beating him.
We just do it in ~20 % of games and dump at $1–$67 in the rest.

---

## 1. W1 — Market-price discipline (the $40–90k lever)

**Problem.** We sell each product whenever we hold it, regardless of the shared
market level. When the market is already above `I0` our sell walks the price into
the $1 floor and takes the rest of the season's supply down with it. DSM never
does this: across 123 leaderboard games he sells **literally zero** STRAWBERRY,
MILK or WOOL units above `I0+100` (`dsm_v1.md` §8.2).

**Evidence.**
- `dsm_gap.md` §5: floor units/game **v1 58.3 vs DSM 16.2**, and v1's floor is
  51 % STRAWBERRY (our largest revenue line at 22.4 %) while DSM's is 47 %
  FERTILIZER (no shop buyer — dumping it is rational).
- §0 above: `floor_sales` 123 in our worst games vs 13 in our best, at identical
  volume.
- Curve breakpoints: MILK/STRAWBERRY hit $1 by `I0+90`/`I0+75`, WOOL by `I0+50`.
  WHEAT/EGG/CARROT/TOMATO/MELON are log-shaped with no cliff and should be sold
  freely — a single global threshold is wrong for them.

**Change.** Arm the sell-side inventory ceiling (`_rate_apply`,
`KAGGICULTURE_STRAWRATE=1`) on **STRAWBERRY, MILK and WOOL**, with the ceiling
**derived from the price curve** (bisect for the inventory where the marginal unit
clears `_RATE_FRAC × base`), not hand-set. Leave the log-curve goods out of the
ceiling — they have no cliff to fall off.

**The trap that killed the last attempt — do not repeat it.** When this ceiling
was armed before, MILK floor went *up* (56 → 265): we stopped selling, the glut
sat in the shed, the shed guard fired, and we dumped it anyway. A sell-side hold
**without** either a production cut or a shed-lean guarantee merely moves the
loss. So W1 must ship **together with** W2 and must not be evaluated alone.

**Accept.** Per game: STRAWBERRY/MILK/WOOL `floor_sales` → ~0;
`shed_overflow_days` not above baseline; `stranded_at_bell` = 0; no regression in
`sell_revenue_total`; `tools/margin.py` win count improves.

---

## 2. W2 — Production that matches the market (the supply half)

**Problem.** We keep producing goods the drawn shops cannot absorb, then face a
choice between flooring them and discarding them. DSM instead **cuts production**
and lets the ground go.

**Evidence (`dsm_v1.md` §6, §3).** DSM's weeds go 0 → 10 over days 20–29 while
watering drops 63 → 24 ops, feeding 21 → 1, fertilizing 17 → 1, caring 21 → 1.
That is deliberate retirement of unprofitable production, not neglect. Our
`weeds_peak` is 7 against his 10 — we keep working ground that can no longer pay.

**Change.**
1. **Crops — rotate, don't stack.** DSM runs MELON day 0–11, STRAWBERRY peaking
   d15–18, then CARROT ramping d17+ to 23 tiles. Retire a crop once
   `market_price(crop) < _RATE_FRAC × base` and its shed stock stops clearing.
2. **Herd — cap by shop demand.** DSM runs COW 9 with a milk shop and **5
   without**; SHEEP 10 with `YARN_STORE` and 3 without; and fills the no-YARN gap
   with **GEESE, not sheep** (EGG sold 171 → 267, WOOL 226 → 46) because the egg
   curve is log-shaped and absorbs volume. Current v1 in run-1: YARN worlds buy
   9 sheep / sell 228 wool / 0 egg; no-YARN worlds buy 2 sheep / sell 50 wool /
   155 egg. The no-YARN branch is *directionally* right — the gap is that in YARN
   worlds we still sell ~28 % less wool than the field.
3. **The freed labour must be re-routed.** This is the failure mode of every
   previous attempt at W1/W2: we cut the work and the hands `PASS`
   (`idle_units_total` 358 vs DSM's 264). Any production cut ships with a routing
   change that consumes the freed turns — see W3.

**Accept.** `idle_units_total` flat or down while production drops; `floor_sales`
down; `sell_revenue_total` flat or up; `feed_surplus ≥ 0` at all times.
a
---

## 3. W3 — Labour routing (`locked_steps` 197 → 106, `idle_units_ready` 13 → 0)

**Problem.** Two independent defects, both pure waste with no economic trade-off.

**Evidence (`dsm_gap.md` §3).**

| metric | DSM | current v1 |
|---|---|---|
| `locked_steps` | **106** (97–117) | **197** (121–226) |
| `idle_units_ready_total` | **0** (0–1) | **13** (9–31) |
| `idle_units_total` | 264 (230–297) | 358 (320–546) |

**Change.**
1. `idle_units_ready_total` — units PASS while standing on ready produce or a full
   animal tile. DSM's p90 is 1; our p10 is 9. Every unit is a missed collect.
   Locate the collect/harvest priority in the layer stack.
2. `locked_steps` — nearly 2× DSM's worker-turns spent on or routed across **land
   we do not own**. Pure pathing; fixing it costs nothing.

**Accept.** `idle_units_ready_total < 3`, `locked_steps` toward ~106, and the freed
turns show up as extra harvests/sells, not as idle somewhere else.

---

## 4. W4 — Scale (the throughput ceiling)

**Problem.** Our farm is smaller than DSM's, and smaller than the field's.

**Evidence (`dsm_gap.md` §2).**

| metric | DSM | current v1 |
|---|---|---|
| `seed_cost_total` | 10,780 | **6,760 (−37 %)** |
| `animal_cost_total` | 10,400 | **6,000 (−42 %)** |
| `hire_cost_total` | 6,691 | **5,261 (−21 %)** |
| COW bought | 11 | **6.3** |
| GOOSE bought | 7 | **3.7** |
| quadrants at the bell | **4** (NE d6, SW d9, SE d10) | **3** in 21/26 games |
| `harvests` | 597 | **503 (−16 %)** |
| units sold | 2,080 | **1,557 (−25 %)** |

DSM spends the **entire $3,000 opening bank on day 0** (bank ends day 0 at $6)
with 10 structures, 2 COW, 3 SHEEP, 9 WHEAT and 6 MELON already placed. There is
no slow ramp to copy — the ramp *is* the point.

**Change.** Raise input spend toward DSM's: more animals (COW and GOOSE in
particular), and **buy the fourth quadrant** (we skip SE in 21 of 26 games). Land
is cheap; worked land is not, so this ships with W3's routing so the new tiles are
actually staffed.

**Accept.** `harvests` and units sold up; money up; `feed_surplus ≥ 0`;
`plants_died` and `weeds_peak` not worse.

---

## 5. W5 — Discard composition

**Problem.** We discard the expensive things and keep the cheap one.

**Evidence (`dsm_gap.md` §4).** v1 discards WHEAT 283 + STRAWBERRY 188 + CARROT 54
+ FERTILIZER 144 = 669 units over 78 games, **zero EGG**. DSM discards ≈16
units/game spread thinly over all nine products, dominated by **EGG (497 units
over 123 games)**. Wheat is the feed reserve; strawberry is our top revenue line.

**Change.** Make the day-end overflow relief sell the *cheapest, least useful*
stock first (FERTILIZER, EGG) and never evict WHEAT below the feed reserve or
STRAWBERRY. The mechanism exists (`_wheat_relief_apply`, hour-23 force-drop aware);
the sell order needs to match DSM's revealed preference.

**Accept.** `discarded_items` contains no WHEAT/STRAWBERRY; total discards flat or
down; `feed_surplus ≥ 0`.

---

## 6. W6 — Endgame extraction

**Problem.** We work retired ground to the bell instead of liquidating.

**Evidence (`dsm_v1.md` §6).** DSM's last four days: water 63 → 24, feed 21 → 1,
care 21 → 1, fertilize 17 → 1, weeds 0 → 10, herd released (~10 escapes/game,
deliberately, **after** the sheds are already full at 93). v1 has `weeds_peak` 7,
`animal_escapes` 0, `stranded_at_bell` 0.

**Change.** From ~day 26, stop watering/fertilizing crops that cannot yield before
the bell and re-route those hands to harvest/collect/sell. Do **not** copy DSM's
escape count until W4 has scaled the herd — on a 6-COW farm escapes are pure loss;
on a 9-COW farm with a full shed they are disposal.

**Accept.** `weeds_peak` toward ~10, `stranded_at_bell` stays 0, revenue up.

---

## 7. Order of work and why

1. **W3 first** (routing). Free, measurable, and the prerequisite that makes
   W1/W2 safe — every previous attempt at the sell ceiling failed because the
   freed labour idled.
2. **W1 + W2 together** (market discipline + production match). One change in two
   halves; shipping either alone moves the loss rather than removing it. This is
   the $40–90k lever.
3. **W5** (discard composition). Small, safe, verifiable.
4. **W4** (scale). Only once W3's routing can absorb the extra work — otherwise the
   new tiles just become more `locked_steps`.
5. **W6** (endgame). Last; depends on a scaled herd.

---

## 8. How to measure (non-negotiable)

- **Never a cross-game mean.** Use `python tools/margin.py <run-dir>...` — W/L,
  median margin, median WIN and median LOSS, plus paired same-seed deltas.
- **Per-product, both seats.** `python tools/sell_price.py --dir <run-dir> --summary`.
- **Per-game floors, not averages.** `python tools/floor_sell.py`.
- **Structural guards stay green:** `discarded_units_total`, `shed_overflow_days`,
  `animal_escapes`, `stranded_at_bell`, `feed_surplus`.
- **Baseline hygiene.** The frozen `consol-base` arm quoted in earlier notes came
  from a different working tree and is **not** a valid baseline. Re-derive the
  all-levers-off arm from the current tree on the same seeds before claiming a
  delta.
- **Ignore `shop-router-0909`** when reading margins — it ends at $3,000 and
  inflates every mean. Report it separately or drop it.

Target readout: **≥10/13 opponents with a median margin ≥ $30,000** on a
6-seed × 13-agent run.

---

## 9. What not to do (learned the hard way)

- **Do not ship the sell ceiling alone.** Measured: it cost ~$7.7k of our own money
  for 90 floor units and *created* a MILK glut (56 → 265 floor units), because the
  held stock hit the shed guard and was released anyway.
- **Do not chase WHEAT volume.** The opponents' 33k wheat units are largely a
  market-making wash, and a wash is margin-neutral (measured: $86,763 with it,
  $86,568 without, same seed). Our wheat deficit is real but second-order.
- **Do not add a production cut without a routing plan.** `idle_units` rises and
  the cut is paid for twice.
- **Do not copy DSM's escapes before scaling the herd.**
- **Do not edit `src/route_tape.py`** — read-only data.
- **Do not trust `consol-base`.** Re-baseline from the current tree.
