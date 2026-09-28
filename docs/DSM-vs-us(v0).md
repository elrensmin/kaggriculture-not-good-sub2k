# DSM & Boey vs us — data-backed, DAG-grounded

Every claim has two anchors: a **measured number** (`docs/v0/`, `docs/v0-boey/`) and a **DAG node/edge**
(`tools/phases/dag.py`, evaluated by `phase_map`). Fix order follows the DAG: **the first fix has no
deficient ancestor**, and both top agents independently confirm it.

## 0. Read first

| arm | sample | record | audit |
|---|---|---|---|
| **us** — `src/`, tree defaults, `rev 694e48aa` | `diag-replays/v1-us`, 12 opponents × 8 seeds = **96 games** | **0 W – 96 L** | audit-backed |
| **DSM** — `replays/DSM/v1` | **123 episodes / 122 scored**, 66 opponents | **117 W – 5 L (95.9 %)** | **no audit** |
| **Boey** — `replays/Boey/v1` | **359 episodes**, 148 opponents (`diag-replays/boey-lb`) | **305 W – 56 L (84.5 %)** | **no audit** |

- Per-day figures are **per-opponent median → median across opponents**. Win counts are per episode.
- For leaderboard arms `sell_revenue_*`, `avg_price_*`, `discarded_*`, `land_cost_*` are **0/modelled**. `land_cost_total` is unusable everywhere.
- Shop draw is RNG we move: YARN_STORE appears in **95/96** of ours, **78/123** of DSM's, **238/359** of Boey's → no shop-conditioned comparison is controlled.
- Tile-conditioned CSV columns are off-by-one; `op_patterns`/`ready_idle`/`visit_trace`/`move_trace` use the corrected form.
- Tools now resolve the reference arm via `tools/team.py` (`--team` > `$KAGG_OPPONENT` > DSM) — see `docs/v0-boey/MANIFEST.md`.

## 1. Scoreboard

| | **us** | **DSM** | **Boey** |
|---|---|---|---|
| record | **0 – 96 (0 %)** | 117 – 5 (95.9 %) | 305 – 56 (84.5 %) |
| median margin | **−$104,670** | +$14,144 | +$9,812 |
| **normalised margin** | **−$98,759** | +$20,351 | **+$23,101** |
| worst game | −$126,334 | **−$3,570** | −$21,468 |
| games lost >$4k | 100 % | **0.0 %** | 6.4 % |
| harvests | **279** | **597** | 529 |
| plants died | **65** | 19 | **9** |
| weeds_peak | **41** | 10 | **4** |
| idle share % | 4.9 | 3.5 | **2.5** |
| stranded_at_bell | **$1,100** | $45 | **$0** |
| floor_sales (med / norm) | 0 / 7 | 10 / 11 | **58 / 80** |
| feed_surplus | **−126** | +191 | **+3,021** |
| buy-side spend / game | $4,432 | $7,036 | **$153,863** |
| animal-days | 241 | 428 | 437 |
| herd revenue / game | $43,985 | $44,517 | **~$28,000\*** |
| **productive share** | **31 %** | **55 %** | **53 %** |
| **moves per act** | **2.03** | **0.76** | **0.82** |
| moves empty-handed | 62 % | 33 % | 30 % |

**Both leaders are structurally the same and we are not.** They agree to within a few points on the one
axis that separates us: ~54 % productive share at ~0.8 moves/act, against our 31 % at 2.03. Everything
else is archetype: **DSM is a production farm** (597 harvests, 20 animals, no trade), **Boey adds
arbitrage** (shed-capped ~2,542 wheat and ~487 fertilizer sold per game on ~3,497 + 728 bought). Boey has the best normalised margin but the worse tail — it dumps 58 floor units a game and loses 6.4 % by >$4k.

---

## 2. Phase 1 — opening (d0–d5)

Sources: `docs/v0/phase1.txt`, `docs/v0-boey/phase_all_vs_boey.txt`. Current **us** values are fresh
d0–d5 audits of the shipped tree with the opening tape on and the water cluster fixed:
`docs/v0/sc-p1-water.txt` (60 Boey replays, 16 games) and `docs/v0/sc-p1-water-dsm.txt`
(123 DSM replays, 24 games).

| metric | us | DSM | Boey | DAG |
|---|---|---|---|---|
| opening cash committed | **1.00** | 1.00 | 0.99 | met |
| PLANT ops | 29 | 30 | 30 | ok |
| MELON tiles | 9 | 10 | 10 | ok |
| STRAWBERRY tiles | 4 | 10 | 4 | **ROOT vs DSM** — Boey-match by choice |
| WATER ops | 68 | 74 | **76** | WARN (was BAD at 53) |
| CARE ops | 34 | 34 | **40** | WARN |
| FEED ops | 32 | 27 | **38** | WARN |
| animals | 8 | 5 | **10** | **BAD — the last node (§2.4)** |
| — COW / SHEEP / GOOSE | 4 / 2 / 2 | 2 / 3 / 0 | **4 / 3 / 2** | COW + GOOSE **met**, SHEEP 1 short |
| **d0–5 trade net $** | **2,368** | 1,836 | **2,438** | **ok — 0.97× Boey, 1.33× DSM** |
| d0–5 sell revenue | 5,023 | 2,743 | 11,624 | *descriptive* — turnover, not profit |
| idle share % | 8.66 | 26.2 | 6.62 | ok |
| owned / quadrants / hands | 25 / 1 / 5 | 25 / 1 / 6 | 25 / 1 / 5 | met |
| empty owned tiles | 3.0 | 0 | 0 | ok (was 4) |
| animal structures | 8 | 5 | 10 | ok (was 5) |

### The market/trade layer

| | Boey | us (now) |
|---|---|---|
| gross sell revenue | $11,624 | $5,023 |
| **product trade net** | **$2,438** | **$2,368** |
| animal spend | $4,000 | $3,200 |
| net cash (bank 3,000 →) | −$2,974 | — |

### The gross-revenue question, settled with numbers

The table shows `sell revenue` 0.43× Boey's, which invites the reading that the opening's market engine
is underbuilt. Four measurements say otherwise:

1. **It is inventory-limited, not tuned.** `TRADE_CASH_FLOOR` 150/50/0 and `TRADE_CHUNK` 25/10/50 all
   produce **byte-identical** d0–d5 metrics — the binding constraint is the wheat we hold, not the
   order size or the float rule.
2. **Raising turnover costs the herd and the net.** Selling deeper into the feed reserve
   (`TRADE_FEED_RESERVE=2`) takes gross **$5,023 → $6,401 (0.55×)** but drops trade net to **0.76×**
   and the herd to 7 animals with GOOSE 2 → 1 and MELON 9 → 7. Rejected.
3. **The net rate is already Boey's.** $2,368 over d0–d5 against his $2,438 (0.97×), i.e. ~$395/day
   against his ~$406/day. We are not slower at the trade; we run it on a smaller float.
4. **Over a season the "revenue gap" is PRODUCTION, not trading.** `--days 0-29` against 60 Boey
   replays: trade net **$64,970 vs $131,508 (0.49×)** — but the same screen shows `HARVEST ops`
   **245 vs 540**, `HARVEST per planted tile` **0.36 vs 0.70**, `plants died` **61 vs 11** and
   `weeds` **56.5 vs 3**. Most of a season's wheat sales are *own harvest*, so a 2× harvest gap
   produces a 2× revenue gap with no market-making involved.

So the opening's revenue node is **resolved on the measure that is profit** (`trade net`, exact from
the ledger), and the season revenue gap is Phase-2 agronomy — the same root already listed as
`WATER per planted tile` → `plants died` → `weeds` → `HARVEST`. Building more turnover in d0–d5 would
buy gross and sell the herd.

### Front-loading the herd's cash (the carry now funds the buying window)

The carry's profit used to land d3–d5, after the herd buys d0–d4. The fix exploits a property of the
engine that the DAG does not show: **the market list is funded positionally**, so a SELL emitted before
the animal order makes its cash spendable by the herd *in the same turn*. `src/trade.py` therefore grew
a liquidation mode, and the opening now calls it on the last two days:

- `OPENING_HERD_LIQUIDATE_DAY=4` — from d4, if the day's animal target is unmet and unaffordable, the
  carry's entire wheat position is sold (down to **zero**, at any price above base), instead of only
  the surplus above a multi-day feed reserve.
- `OPENING_HERD_COVER_BUFFER=0` — the feed cover in `_buy_herd` becomes `herd x feed_days` units rather
  than `(herd+2) x feed_days`, releasing ~$60 of the ~$240–300 that stood between liquid cash and a
  ninth animal.

| | before | after |
|---|---|---|
| d0–5 sell revenue | $5,023 (0.43×) | **$7,086 (0.61×)** |
| d0–5 trade net | $2,368 (0.97×) | **$2,443 (1.00×)** |
| animals / SHEEP | 8 / 2 | 8 / 2 |

Day matters: liquidating from **d3** costs net (0.97× → 0.78×) with no animal gained; **d4** is the win,
and it is also where an escape risk is cheapest. Season A/B (16 games, `arm_diff`): median margin
**+$5,730** (11/16), `animal_escapes` **0 (0/16 worse)**, `idle_units_total` **−1,471 (0/16 worse)**.

**`animals` is still 8 and the gap is now quantified to ~$50–100.** At d4 the opening holds ~$450 of
liquid cash after liquidation; the 3rd SHEEP costs $500 *and* the cover holds ~$240 back, so the buy
needs ~$740. That residue is not reachable by any further lever inside the opening — every one measured
either costs the net (`TRADE_FEED_RESERVE=2`: net 0.76×, herd 7) or the crop (`OPENING_WHEAT_KEEP_DAYS=1`:
FEED turns BAD). It needs either a cheaper 9th animal (a 3rd GOOSE at $300 would fit, but that breaks the
4/3/2 combination) or income that lands before d4.

---

## 3. Phase 2 — midgame (d6–d17)

Sources: `docs/v0/sc-p2-shipped16.txt` — fresh d0–d17 audit of the shipped tree
(`tools.phases.phase_map --phase phase2 --pa 1-4 --batch 4 --ref-from replays/Boey/v1
--ref-max 40 --team Boey`, 16 games). `us (before)` is `docs/v0/sc-p2-current.txt`
from the same 16-game protocol before the 2026-09-27 crew/visit round. **Anchored to
Boey only.** The DSM column was removed: the two leaders are different
archetypes (DSM is a pure production farm, Boey adds arbitrage), so a two-reference table
invites averaging choices that are not comparable.

| metric | us (before) | us (now) | Boey | DAG |
|---|---|---|---|---|
| animals on board | 13 | **16** | **21** | **ROOT** — explains 4 |
| — animal structures | 13 | 17 | 21 | symptom of `animals` |
| COLLECT_FERTILIZER ops | 84 | **130** | 222 | symptom of `animals` |
| FEED ops | 120 | **132** | 218 | symptom of `animals` |
| HARVEST ops | 79.5 | **95.5** | **194** | symptom of BOTH roots |
| WATER ops | 248 | **332** | **465** | **ROOT** — explains 3 |
| WATER ops / planted tile | 0.61 | 0.64 | 0.78 | WARN (same node as coverage) |
| plants died | **22.5** | **12.0** | **0** | symptom of `WATER` (lag 2) |
| weeds | **27** | **7.5** | **0** | symptom of `WATER` |
| **move share %** | 60.0 | 59.5 | **41.6** | **ROOT (new)** — see §3.1g |
| shed peak | 20.5 | 20.0 | 24.5 | WARN |
| WHEAT tiles | 23 | 28 | 30.5 | ok (the feed ceiling on `animals`) |
| planted tiles | 51 | 57 | 55 | ok |
| owned tiles / quadrants | 75 / 3 | 75 / 3 | 75 / 3 | **met** (W2) |
| STRAWBERRY tiles | 23 | 26.5 | 24 | ok |
| hands | 12 | 12 | 11 | ok |
| idle share % | 0.00 | 1.79 | 2.52 | ok |
| FERTILIZE ops | 0 | 0 | 64 | **ROOT (re-opened §3.4)** — a yield multiplier, not a portfolio choice |

**DAG causation — traced, not asserted** (`sc-p2-shipped16.txt` walks this and names the
deepest line as the furthest upstream):

```
animals on board [p2]  16 vs 21   [ROOT, no deficient ancestor]
  -> COLLECT_FERTILIZER 130 vs 222  one fertilizer per animal per day
  -> FEED 132 vs 218               one wheat per animal per day
  -> animal structures 17 vs 21    housing is built only for animals already owned
  -> HARVEST 95.5 vs 194, shed peak the herd's output and its daily work
  WHY it is short: feed-limited, not window-limited (3.1b). The window is open
  (BUY_UNTIL=20) and money is available; the standing WHEAT base (28 tiles vs Boey's
  30.5) cannot ration 21 animals at 1.7 tiles/animal.

move share % [p2]      59.5 vs 41.6 [ROOT, no deficient ancestor]
  -> WATER ops 332 vs 465          walking is a turn not spent watering
  -> HARVEST 95.5 vs 194           walking is a turn not spent harvesting
  -> FEED 132 vs 218               walking is a turn not spent feeding
  WHY it is high: the crew still leaves a tile it is standing on. §3.1g.

WATER ops [p2]         332 vs 465 [symptom of `move share`, not a root any more]
  -> plants died 12 vs 0           an unwatered plant weeds after two nights (C5)
     -> weeds 7.5 vs 0             a dead plant IS a weed
        -> HARVEST 95.5 vs 194     a weeded tile cannot be harvested
  WHY it is short: crew REACH. Planted tiles are within 4 % of Boey's and we run MORE
  hands (12 vs 11), yet cover 0.64 vs 0.78 ops per planted tile. W2 shipped
  `LAND_QUADRANT_MAX=3` (weeds 35 -> 27); the crew-rate + visit-chaining round (§3.1g)
  took it to 7.5. The residue is `_pick` movement.

FERTILIZE ops 0 vs 64 -- RE-OPENED as a ROOT in §3.4. The old reading ("descriptive,
measured out, the fertilizer is sold instead") came from arms that measured our DELIVERY
cost, not the op: `crop_cycle` shows our FERTILIZE at 4.35 moves/op against the reference's
0.09, while the reference fertilizes 1,390 wheat tiles in d6-17 and its fertilized wheat
yields 5.35 against 3.17 unfertilized. The yield gap is real; whether it PAYS at our
movement cost is the open question (the 2026-09-29 screen says not yet -- see §3.4).
```

**The root moved.** After the 2026-09-27 round the old pair ("animals" + "WATER" = one
capacity-per-tile bottleneck) is no longer the whole story: `WATER` is now *downstream of
`move share`*, because the crew is not short of turns any more (§3.1g measured +14 %
hands-hours of acts for free). What is left is what those turns are spent on: 59.5 % of
them are WALKING, against Boey's 41.6 %.

Progress since the first Phase-2 audit: `animals` 11 → **16**, `owned/quadrants` 100/4 →
**75/3** (matching Boey exactly), `WATER ops` 248 → **332**, `HARVEST` 79.5 → **95.5**,
`COLLECT` 84 → **130**, `plants died` 22.5 → **12.0**, `weeds` 27 → **7.5**,
`FERTILIZE` re-opened as a root (§3.4) after `crop_cycle` showed the yield mechanism.

### 3.1 The mechanism: the same-tile revisit

**"us" in this table is the PRE-FIX arm** — it is the evidence that identified the root, not
the current state. `SAME_TILE_FIRST` at the default `SAME_TILE_MIN_PRIORITY=70` has since
shipped (§2.1) and took phase-1 `WATER ops` 53 → 66 and `PLANT` 27 → 30.

| measure | us (pre-fix) | Boey | source |
|---|---|---|---|
| moves / act | **2.03** | 0.82 | `movement.txt` |
| movement share | 63.3 % | 43.8 % | `movement.txt` |
| WATER chained (act→act on the spot) | **0.0 %** | **22.7 %** | `op_patterns.txt` |
| FEED chained | **5.0 %** | 64.5 % | `op_patterns.txt` |
| PLANT → WATER split across two visits | **86 %** | **12 %** | `visit_trace.txt` |
| FEED → CARE split across two visits | **100 %** | ~8 % | `visit_trace.txt` |
| ops per tile stop | **1.36** | 1.78 | `visit_trace.txt` |
| extra trips / tile-day | 0.350 | 0.328 | `visit_trace.txt` |
| WATER moves per op | **2.92** | 1.25 | `move_trace.txt` |
| FEED moves per op | **2.12** | 0.54 | `move_trace.txt` |
| PASS-on-READY turns / game | **119.5** | 72.4 | `ready_idle.txt` |
| value left on tiles / game | **$36,024** | $8,435 | `ready_idle.txt` |

The crew is not idle (`idle-on-work` ~72 turns/game); it never reaches the work. Pending per day is
**WATER 1,341 / FERT 561 / HARVEST 472 / DIG 337** (`missed_work.txt`). `_pick` splits one tile's acts
into separate trips; that is the root Boey has solved and we have not.

**This is still the live root in the midgame** — see §3.1c: `WATER ops` 248 vs 464 and `WATER
ops / planted tile` 0.61 vs 0.78 with *more* hands and zero idle. What changed is which half
of the mechanism we attack: chaining (shipped) and geometry (`LAND_QUADRANT_MAX=3`,
shipped) are in; the remaining distance is that Boey does the same work in fewer steps.

**MEASURED — the chaining fix is a revenue lever that breaks the health watchlist.** Three 96-game
arms on the same seeds/opponents (`docs/v0/step1-*.txt`, `arm_diff` vs the baseline reconstructed from
`docs/v0/sweep-run.txt`):

| arm | median margin vs base | sign | watchlist |
|---|---|---|---|
| **CHAIN** `SAME_TILE_FIRST=1;SAME_TILE_MIN_PRIORITY=0` | **+$10,626** | **96/96, p=0.0000** | `shed_overflow_days` **+1 (96/96 worse)**, `discarded` +7.5, `stranded_at_bell` **+$1,218**, `plants_died` **+9 (83/96)**, `missed_harvest_eod` +7.5, idle share +2.0 pp |
| **ROOT** + `URGENCY_SLOPE=0.6` (`src/roots.py`) | +$8,057 | 84/96, p=0.0000 | worse than CHAIN on every guard: overflow +2.5, discards +20, `plants_died` +13, idle +3.3 pp |
| **GUARD** CHAIN + `SAME_TILE_PROTECT_CRITICAL` | −$1,593 (47/96, p=0.92 — **inert**) | — | fixes all of it: `plants_died` **−14 (0/96 worse)**, overflow **−1 day (0/96)**, discards −7.5, idle −0.6 pp |

So the gain came from chaining *even while a tile was about to die* (the guard is too blunt: any
pending critical disables chaining for the whole turn, which on a 100-tile farm is almost always), and
the shed overflow/discard/strand rise is the **C1/C6 sell-side coupling** chaining exposes. Neither
arm passes the watchlist gate as-is; the two correctives are (a) narrow the guard to the unit nearest
the critical tile / only when the local job is low-value, and (b) ship it with the sell-ceiling
workstream (§7 Step 2/3), never before it. This is the non-composability rule in one measurement.

### 3.2 Volume, not price

Season selling, ours (audit) vs Boey's shed-capped line medians (`dsm_profile.txt`):

| product | our units | our px | Boey units | Boey px |
|---|---|---|---|---|
| WHEAT | 128 | $42.2 | **2,542** | $36.1 |
| STRAWBERRY | 94 | $171.5 | 111 | $136.3 |
| MELON | 28 | $198.0 | 28 | $169.6 |
| EGG | 52 | $54.4 | **147** | $44.2 |
| MILK | **107** | $202.3 | 17 | $87.4 |
| WOOL | **88** | $228.9 | 53 | $53.3 |
| FERTILIZER | 192 | $52.3 | **487** | $41.1 |
| CARROT | 20 | $49.2 | **97** | $43.5 |

We get a **better unit price than Boey on every line** and move less of the deep liquid
goods, so the gap is supply, not pricing. For Boey it is also **trading** — he buys wheat
and fertilizer to resell into the `log`-curve goods. But the corrected numbers kill the
"13.6x volume" framing: the honest midgame revenue ratio is ~0.65x, and the two lines that
actually carry his lead are **wheat** (which is also the feed base — see §3.4) and the
herd's **fertilizer/egg** cycle.

`crop_demand` peaks: WHEAT 33 / 57 / —, STRAWBERRY 31 / 56 / —, CARROT 17 / 55 / —, MELON 6 / 10 / 10
against Boey's per-day curve in `docs/v0-boey/crop_demand.txt`.

### 3.3 Demand-side permutations — the shop draw is latent now and decisive later

The engine's demand rule is exact (`_town_consume`): every **4 steps**, each unlocked shop
instance subtracts `multiplier` from `market["inventory"][item]` for each product on its menu —
`2` for single-product shops (`YARN_STORE`, `PET_CAFE`), `1` otherwise; the town center drains 1
every 24. Shops unlock every **3 days**, drawn **with replacement**, so instances stack.
**Drain/day = instances × multiplier × 6.**

**It does not act in the opening** — d0–d5 has exactly one shop, and YARN appears in 0/36 opening
games — but it shapes the whole season's revenue mix. The two branches are asymmetric and must be
handled dynamically:

| branch | demand consequence | policy |
|---|---|---|
| **YARN_STORE** (2× drain, WOOL only) | wool becomes the premium line | buy **SHEEP** after the reveal; keep the goose line as the no-YARN fallback |
| **no YARN** | no wool buyer; single-product drain is 2× but scarce | lean on **GOOSE→EGG** (BAKERY/BRUNCH) and MILK shops |

Running metric: `tools/market/demand_map.py` — season shop drain vs our sales per product, plus a
YARN/no-YARN split. Measured on the fresh arm (`docs/v0/demand_map.txt`):

| product | season shop drain | our sold | coverage | our px | below-base |
|---|---|---|---|---|---|
| WHEAT | 378 | 128 | 34 % | $42.1 | 0 % |
| WOOL | 288 | 88 | 31 % | $209.8 | 5 % |
| STRAWBERRY | 270 | 94 | 35 % | $133.7 | 6 % |
| MILK | 234 | 107 | 46 % | $178.3 | 0 % |
| CARROT | 162 | 20 | **12 %** | $49.9 | 0 % |
| TOMATO | 162 | 50 | 31 % | $84.3 | 0 % |
| EGG | 117 | 52 | 44 % | $54.2 | 0 % |

**We satisfy 12–46 % of the modelled shop drain on every line** — the unmet-demand side of the
volume gap, and the reason the demand map is the instrument for the season plan rather than a
phase-1 one. Boey fills far more of it and adds **trading** on the deep `log`-curve goods
(shed-capped ~2,542 wheat + ~487 fertilizer sold/game on ~3,497 + 728 bought; the
requested-order figure was 6,786 / 4,622 — see §3.2).

**Caveat, and it is the whole point of the running metric:** the draw is a function of our own
play (`_spawn_weeds` shares the RNG stream), so the two arms are *different worlds*. YARN appears
in **238/359** of Boey's episodes and in **95/96** of our reference arm, but that is not a
controlled comparison — our own empty-tile count moves the draw. `demand_map` prints the mix
first for exactly this reason, and every judgement in this section is made on unconditional
metrics.

### 3.4 The midgame root: fertilize the wheat — real yield, and why it does not pay yet

MEASURED 2026-09-29 with the new `tools/labour/crop_cycle.py` (d6-17, ours 8 games vs
Boey's 40 replays). This is the instrument the round was missing: `phase_map` had already
printed `FERTILIZE ops 0 vs 64`, but nothing joined *fertilization* to the *yield and
harvest age* it buys, so the params' "never fertilizing is +$2,294" note was allowed to
stand.

| crop_cycle, d6-17 | ours | Boey |
|---|---|---|
| WHEAT harvest yield (units) | **2.93** (only 2s and 3s) | **4.41** (852 5s, 519 6s) |
| WHEAT fertilized share / ops | **0 % / 0** | **57 % / 1,390** |
| WHEAT fertilized yield vs not | — | 5.35 vs 3.17 |
| WHEAT harvest age | **4.0 d** | **3.0 d** |
| WHEAT units/tile-day (`yield/(age+gap)`) | **0.59** | **1.10** |
| STRAWBERRY fertilized share / ops | 0 % / 0 | 77 % / 470 |
| FERTILIZE moves/op | — (0 ops) | **0.09** |

**Mechanism.** The engine pays `+2` instead of `+1` on a window water when
`fertilized_until_day >= day`, and one `FERTILIZE` covers three days (`day+2`). A
fertilized wheat tile therefore peaks at **5 on age 3** and 6 on age 4, against 3 and 4
unfertilized.

**What was measured, and what shipped (8 paired games each; `arm_diff`):**

| arm | result |
|---|---|
| **one-shot fertilize** `FERTILIZE_FROM_DAY_P2=6` (`FERTILIZE_ONESHOT_ONLY`) — **SHIPPED** | **+$4,786 mean / +$8,020 median, 5/8**; wheat yield 2.93 → 3.49, fertilized share 0 → 79 %, `plants_died` **−8**, `missed_harvest_eod` −8.5, `shed_overflow_days` **−1 (0/8 worse)** |
| delivery fix: `FERTILIZE_SHED_PICKUP_P2=0` + `P_FERTILIZE_P2=88` + `FERTILIZE_PRE_WINDOW` | **−$8,077 mean** — and FERTILIZE moves/op did not move (3.3 vs 3.2) |
| **early harvest** `HARVEST_AGE_WHEAT=3;MELON=10` — shipped OFF | **−$2,361 mean / −$9,526 median, 3/8**; revenue −$10,984 |
| one-shot fertilize + early harvest | −$6,761 mean, 3/8 |

**The two levers failed for opposite reasons, and the second is the finding.**

1. **Fertilize pays modestly, but not because its delivery got fixed.** Our `FERTILIZE` is
   still **3.3 moves/op** against the reference's 0.09. The shed-pickup-off experiment did
   not move that number, which means the cost is not the pickup: **the crop tiles are far
   from the animal tiles the fertilizer comes from.** That is a layout problem, and it is
   what has to be fixed before the ongoing-crop lever (the reference fertilizes strawberry
   470 times in d6-17) can be tried.

2. **Raising wheat turnover LOSES even though the agronomy works.** At
   `HARVEST_AGE_WHEAT=3;MELON=10` the wheat machine does exactly what the reference's does:
   `HARVEST ops` **253 → 456**, harvest age 4.0 → 3.0, missed window **1.07 → 0.14**, melon
   12 → 10, `missed_harvest_eod` −17 (0/8 worse). And it costs **−$10,984 revenue, −$2,361
   mean**. The explanation is one sentence: **doubling a $25 crop's throughput spends crew
   turns that were earning $120–200 strawberry, milk and wool.** The crew-turn allocation,
   not wheat yield, is the binding constraint — which is also why making fertilize free
   matters more than making it abundant.
   (`state.plant_ready` is guarded on `watered_today`; without that guard the harvest fires
   before the day's window water and the tile turns over on ONE water — measured yield
   4.03 → 2.53, water/cycle 1.93 → 1.00.)

---

### 3.5 Crew-turn conversion — the phase-2 gap, and why the kernel knobs cannot close it

MEASURED 2026-09-29 with four new instruments (`tools/phases/turn_budget.py`,
`tools/labour/stack_trace.py`, `tools/labour/hop_regret.py`,
`tools/phases/target_check.py`) on the shipped tree, d6-17, 8 games vs `replays/Boey/v1`.

**Same crew-hours, half the acts.** `op_patterns` / `turn_budget`:

| d6-17, per game | ours | Boey |
|---|---|---|
| unit-turns | 3,077 | 3,044 |
| acts | **1,068** | **1,670** |
| moves | **1,900** | 1,294 |
| moves / act | **1.78** | **0.77** |
| mean walk / walk-len-1 | 2.65 / 44.7 % | 1.79 / 64.4 % |
| acts in runs ≥3 / ≥4 | 24.3 % / 6.3 % | 47.1 % / **29.4 %** |
| tile-days touched (`stack_trace`) | 3,480 | **5,238** |
| ops / visit | 1.55 | **1.93** |

Hiring, idle and crew size are **not** the cause — the unit-turn totals are identical
(PASS 92 vs 109), which also retires the old "we lose ~40 unit-turns a day to the morning
hire ramp" concern as a *phase-2* explanation.

**The closure arithmetic is the roadmap.** `turn_budget`: Boey's 1,641 acts/game at our
1.78 moves/act needs **4,653 unit-turns (16.2 hands)** against the 3,077 we have; at
`moves/act ≤ 0.8` it fits in ~10.6 hands. So exact d17 parity is a conversion problem, and
the target vector (`target_check`, currently **1/16 PASS**) is unreachable until walks fall.

**Where the walking is.** `hop_regret` computes, per act, `hop − nearest-same-op-tile`:

| op | hop | nearest | regret | mean/op |
|---|---|---|---|---|
| WATER | 2.85 | 1.20 | **2,773** | 1.65 |
| HARVEST | 2.60 | 1.03 | **862** | 1.57 |
| FERTILIZE | 2.56 | 0.85 | 387 | 1.70 |
| FEED / CARE / COLLECT | 1.5–2.2 | 1.2–2.0 | 276 / 128 / 104 | 0.36 / 0.23 / 0.55 |

**30.2 % of our walking is avoidable-by-nearest (Boey 21.1 %)**, and 78 % of it is
WATER + HARVEST. The animal ops are geometric; the crop ops are not. (`nearest` does not
account for tiles another unit has already claimed, so 30 % is an upper bound — but the
per-op split is honest.)

**The kernel knobs are exhausted — measured, not assumed.** Seven arms, 8 paired games each,
all vs the shipped tree (`arm_diff`):

| arm | mechanism | result |
|---|---|---|
| `SAME_TILE_CROP_CHAIN_P2=1` | FERTILIZE chained 3.1 % → 3.4 % | **−$6,836** mean |
| `COMPLETE_TILE_P2=1` | acts in runs ≥3 24.3 → 24.7 % | **−$8,028** |
| both | moves/act 1.81 → 1.70 | **−$7,388** |
| both + `SAME_TILE_MIN_PRIORITY_P2=0` | moves/act → 1.62 | **−$8,213** |
| `USE_SLICES_P2=0` (nearest global) | moves/act → **2.35** (much worse) | **−$7,064** |
| `USE_SLICES_P2=0` + COMPLETE_TILE | moves/act 2.32 | **−$4,429** |
| `WHEAT_TILES_PER_ANIMAL_P2=1.2` | animals 13 → 15, move share 62.9 → 61.7 % | **−$10,571** |

Two things this settles. First, **the same-tile floor was not the gate**: FERTILIZE cannot
chain just because it is allowed to — a unit can only fertilize while *carrying* fertilizer,
and it usually is not carrying it when it stands on an unfetrilized in-window tile. The
`stack_trace` "eligible and left" table, which does check inventory, is ~100 % on **both**
arms, so it is context, not signal; the `WATER → FERTILIZE` split pair (175 occurrences) is
the real structural read. Second, **band locality is load-bearing**: removing it makes
`moves/act` worse, so the 30 % regret is not "the band hid a nearer tile" — it is the
per-turn greedy re-decision plus claimed tiles, which a priority knob cannot fix.

**Where this points.** Since no per-turn knob helps, the remaining candidates are structural
or a different formulation:
1. **The act gap is ~half work we do not have.** Of Boey's 602 extra acts, **283 are
   FEED/CARE/COLLECT** — work that exists because he runs ~20 animals to our 13, and our
   herd is capped by `WHEAT_TILES_PER_ANIMAL=1.7` against 22 wheat tiles. Growing the herd
   requires wheat **area**, which the crop ramp does not deliver (22 vs 30 tiles).
2. **A global per-day assignment** (match/route the day's op demand to units once, instead
   of re-deciding greedily per turn), which is the only shape that can capture
   nearest-avoidable walking without removing band locality.
3. **Geometry**: the shed round-trip (PICKUP 110 vs 88, DROP 48 vs 41) and `W1`'s
   `PICKUP→PICKUP` split pair (312) are a fetch/delivery loop, not a crop problem.

---

### 3.6 The Boey knowledge graph — what he actually runs, and the clone worklist

MEASURED 2026-09-29 by inducing a graph from his replays (`tools/phases/boey_model.py`,
120 replays; ours 8 games) and composing it with `propagate.py`. Artifacts:
`docs/boey_kg.md` / `docs/boey_kg.json`.

| d6-17 median | d6 | d8 | d10 | d12 | d14 | d16 | d17 |
|---|---|---|---|---|---|---|---|
| animals — Boey / ours | 8.5 / 8.5 | 13 / 8.5 | **17 / 8.5** | 18 / 11 | 19 / 13 | 19 / 13 | 19 / 13 |
| WHEAT tiles — Boey / ours | 1 / 2 | 7 / 3 | **17 / 10.5** | 24 / 20.5 | 24 / 20 | 22 / 17.5 | 21.5 / 15.5 |
| STRAWBERRY tiles — Boey / ours | 4 / 4 | **16 / 4.5** | 20 / 13 | 24 / 19.5 | 28 / 23 | 29.5 / 25.5 | 29.5 / 24 |
| planted — Boey / ours | 16 / 14.5 | **35 / 16** | **53 / 33.5** | 55 / 51.5 | 56 / 47.5 | 55 / 46.5 | 56 / 43.5 |
| **empty owned — Boey / ours** | 0 / 2 | **0 / 0** | **0 / 25.5** | 0 / 11 | 0 / 6.5 | 1 / 5.5 | 0 / 4.5 |
| quadrants — Boey / ours | 1 / 1 | **2 / 1** | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| `BUY_PRODUCT WHEAT`/day — Boey / ours | 27 / 6 | 34 / 11 | **68 / 10** | 30 / 12 | 18 / 10 | 13 / 18 | 22 / 12 |
| money at d6 | **$99** | | | | | | $37,729 (d17) vs ours $292 → $15,384 |

**Three structural deltas, in causal order.**

1. **Land arrives late and then sits bare.** We hold `CASH_RESERVE=1500` against the $1,000
   NE purchase (`budget.market_intents`), so NE needs $2,500 and lands around d9 together
   with SW; **25.5 tiles are bare at d10** and take until d16 to fill. Boey's `empty` is
   **0 every day** and he is always spent ($99 at d6 against our $292).
2. **The wheat base never reaches our own herd gate.** 10.5 vs 17 tiles at d10, 15.5 vs 21.5
   at d17. `herd_gate` shows `W` failing d13–d17 while cash and window are green.
3. **The gate itself is ours, not his.** The induced buy-rate by wheat-ratio bucket:

   | wheat/(animals+1) | Boey buy rate | ours |
   |---|---|---|
   | 0.0–0.5 | **95 %** (384 days) | 97 % |
   | 0.5–1.0 | **91 %** (390) | 100 % |
   | 1.0–1.5 | 75 % (508) | 94 % |
   | 1.5–2.0 | 65 % (117) | 100 % |
   | 2.0–2.5 | **44 %** (16) | 100 % |

   His buy rate **falls** as the standing wheat base rises: he is not gated by it — he
   stocks feed (`BUY_PRODUCT WHEAT` up to 68/day against our 10) and grows the herd on it.
   Our `WHEAT_TILES_PER_ANIMAL = 1.7` is the single policy that holds the herd at 8.5.

**Non-composability, measured.** The land fix alone is not a win:
`LAND_CASH_RESERVE_P2=700` → **−$7,026** median; `=0` → **−$7,586** — *while* moving the
mechanism the right way (planted d8 **16 → 32**, d10 45 → 51.5 against Boey 35/53). Filling
land without the herd/feed equilibrium feeds extra low-value tiles with crew turns that were
funding the herd. The clone has to move the three together; a single knob cannot buy a
different equilibrium.

---

### 3.7 Round log — the clone attempt (2026-09-29) and the next lever

Seven arms, 8 paired games each, all against the shipped tree. **Every one is negative**;
each moved the mechanism it targeted. This is the non-composability rule in numbers.

| arm | mechanism moved | margin (median) |
|---|---|---|
| `LAND_CASH_RESERVE_P2=700` | planted d8 16 → 32 | **−$7,026** |
| `LAND_CASH_RESERVE_P2=0` | planted d8 16 → 32, d10 45 → 51.5 | **−$7,586** |
| `FEED_STOCK_DAYS_P2=2;FEED_BUY_CHUNK=40` | animals unchanged (gate still blocks) | **−$8,316** |
| land + feed + `WHEAT_TILES_PER_ANIMAL_P2=0.8` | animals 8/8/10/12/13 → **9/10/13/14/16**; `plants_died` +4 | **−$20,572** |
| shed loop (`FEED_PICKUP_INFLIGHT`+`PICKUP_WITH_PRODUCE`+`CARRY_PASS_IN_FIELD`) | MOVE 4,434 → 4,287 | **−$8,668** |
| shed + land + feed + herd | animals → 16 | **−$15,386** |

**The causal map names the blocker: crew-turn capacity.** The herd *can* grow (the bundle
reaches 16 animals against Boey's 19) but `plants_died` rises with it — the extra
FEED/CARE/COLLECT turns are taken out of watering. `propagate` predicted exactly this: the
wheat+8 change fits the spare turns on 10 of 12 days and goes **OVER on d11-d12**.

**And it names the specific defect.** `hop_regret --exclude-claimed` (tiles another unit
serves are removed, so the number is kernel error, not legitimate claiming) barely moves:
**29.5 %** of all walking is still avoidable-by-nearest (was 30.2 %), with per-op means
**WATER 1.64, FERTILIZE 1.68, HARVEST 1.52**. So the kernel really does pass a nearer
unclaimed eligible tile. The mechanism is `scheduler._pick`: pass 1 returns the best
**band-local** job as soon as it finds one, so a farther in-band water beats a nearer
out-of-band water — while `USE_SLICES_P2=0` (nearest globally) is far worse (`moves/act`
1.81 → **2.35**), so the band is load-bearing and cannot simply be dropped.

**Next lever (round 2): a distance-aware band choice.** Keep the band preference but do not
let it hide a strictly nearer same-op tile: in `_pick` pass 1, compare the best band-local
candidate against the best out-of-band candidate *of the same op* and take the out-of-band
one when it is nearer by more than `BAND_LOSS_TOL` tiles. Judge on `hop_regret` regret and
`moves/act`, then re-run `propagate` before re-bundling with the land/feed/herd clone.

#### Round 2 — that lever is inert, and it falsifies the metric

`BAND_LOSS_TOL_P2=1` → **−$2,396** median; `=3` → **−$2,190**, with the mechanism almost
unmoved: `moves/act` 1.81 → 1.79 / 1.80, avoidable-walking regret **29.5 % → 28.2 %**,
WATER regret 1.64 → 1.56 / 1.54 tiles per op. The change is byte-identical at its default
(`arm_diff` delta 0), so nothing regressed — but it buys nothing either.

That falsifies the *reading*, not just the knob. `hop_regret`'s `nearest` uses the ENGINE's
eligibility (any plant needing water, any ripe crop), not the agent's policy. If the nearest
eligible WATER were genuinely available, letting it win across the band boundary would have
moved the number; it moved 1.3 pp. So most of the 28 % is **policy-gated work** — tiles the
agent deliberately does not serve (out-of-window water, unripe-in-our-rule harvest, tiles
already claimed) — not kernel error. The same caveat that applies to `stack_trace`'s
"eligible and left" table applies here.

**Consequence for the roadmap:** the global per-day assignment (W-G) is chasing a number
that is not real, so it does **not** get built. The binding constraint stays what round 1
measured — **crew-turn capacity** — and the only levers left that add acts without adding
net turns are structural (fewer shed round-trips, less re-walking within a band that the
policy actually wants served), or a genuine reduction in walk *distance* via layout. The
seven clone arms and this one all lose, so round 3 starts from the map again rather than
from another knob.

---

### 3.8 The state/policy separator — the gap is POLICY, measured on his own farm

`tools/phases/transplant.py` builds a Boey replay in a fresh engine, replays both seats'
recorded actions to a cut day, **overwrites our seat's live state with his observation**
(farm tiles, shed, seeds, inventories, market, town — the engine keeps all of it inside the
observation objects), then plays **our** agent in *his* seat for the rest of the game while
the opponent's recorded actions continue. Same opponent, same world at the cut, different
policy.

**Validity gate first.** The `control` mode replays both seats' actions to the bell with no
transplant; it must reproduce the replay's final money exactly.

| mode | result (24 random non-mirror episodes, cut d10) |
|---|---|
| control | **24/24 reproduce EXACTLY** (`delta_vs_ref = 0`) |
| treatment | our final **−$59,966 median** vs his own final; we out-earn him in **0/24** |

So the nine losing arms were not the problem, and neither is state accumulation: **handed his
exact d10 farm, his herd, his shed and his market, our policy still loses $60k.** This is the
same direction `state_value --cross` found at d5 (d_state +$7,410, d_policy −$16,775).

**What our policy does wrong on his state** (d11–17 totals, median over 24 episodes,
control = his own play):

| metric | his | ours | delta |
|---|---|---|---|
| unit-turns | 5,148 | 5,431 | +282 |
| **moves / act** | **0.80** | **1.50** | **+0.70** |
| MOVE | 2,139 | 3,145 | **+1,006** |
| **WATER** | **784** | **307** | **−477** |
| **plants died** | **9** | **52** | **+43** |
| HARVEST | 470 | 283 | −187 |
| **FERTILIZE** | **204** | **40** | **−164** |
| PICKUP / DROP | 118 / 73 | 272 / 194 | +155 / +121 |
| PLANT | 178 | 73 | −105 |
| COLLECT_FERTILIZER | 357 | 300 | −57 |
| FEED / CARE | 309 / 298 | 340 / 336 | +31 / +38 |
| WHEAT tiles | 37.5 | 28.0 | −9.5 |
| planted | 56.0 | 54.5 | −1.5 |
| animals | 21.0 | 20.0 | −1.0 |

The chain is one line: **2× the walking ⇒ 40 % of the watering ⇒ 5.8× the plant deaths ⇒
60 % of the harvest.** The herd is serviced (FEED/CARE actually *above* his), so this is not
a herd problem at all — it is the crew spending its turns walking and letting crops die.

**Why this settles the roadmap.** Every clone arm tried to fix the *state* (land, fill, herd,
feed) and lost, because the state was never the binding constraint. `transplant` gives a
**fixed-state, low-noise evaluation loop** — one game is one measurement of our policy on his
position, with a control that proves the world is his — so the next work is aimed at exactly
three policy numbers instead of the whole table: `moves/act 1.50 → 0.80`, `WATER 307 → 784`,
`FERTILIZE 40 → 204`, and `died 52 → 9`.

**The divergence is steady-state, not a re-plan transient.** Cutting at three different days
(16 random episodes each, control exact 16/16 every time):

| cut day | final delta | moves/act (his→ours) | died (his→ours) | WATER | FERTILIZE |
|---|---|---|---|---|---|
| d6 | **−$67,526** | 0.8 → **1.8** | 9 → **59.5** | 910 → 456 | 204 → 53 |
| d10 | −$59,966 | 0.8 → 1.5 | 9 → 52 | 784 → 307 | 204 → 40 |
| d14 | −$52,888 | 0.8 → 1.5 | 8.5 → 46.5 | 616 → 206 | 174 → 20 |

The damage scales with how long our policy runs (the later the cut, the smaller the loss) and
the *rate* signature — `moves/act` ≈1.5–1.8, `died` 5–6×, `WATER` ~40 %, `FERTILIZE` ~20 %,
`PICKUP/DROP` ~2.3× — is **identical at every cut**. That rules out "it just re-plans after
taking over": it is the steady-state kernel.

One secondary signature is worth recording: at a **d6** cut our policy actively *degrades* his
position — his herd reaches 21, ours only 14, and wheat tiles 36 → 18.5 — because the
`WHEAT_TILES_PER_ANIMAL` gate blocks the herd until a wheat base exists that he never had to
build. At d10+ that mostly disappears (animals 20 vs 21). So the state-policy deltas (land,
gate, feed) are real but **second-order**; the kernel is first-order.

---

### 3.9 Phase-1 verification — the opening is fine; it is worth ~0.3 % of the gap

Asked directly: *is the agent working in phase 1, or do we have to change the opening again?*
`transplant --prefix ours --cut-day 5` runs **our** agent for d0–d5 (against the opponent's
recorded actions) in the reference's own episodes, then reports our state against his at the
cut. 24 random non-mirror episodes:

| at end of d5 | ours | his | delta |
|---|---|---|---|
| planted | 15.0 | 15.0 | **0** |
| STRAWBERRY tiles | 4.0 | 4.0 | **0** |
| quadrants | 1.0 | 1.0 | **0** |
| MELON tiles | 9.0 | 10.0 | −1.0 |
| WHEAT tiles | 2.0 | 0.0 | +2.0 |
| **animals** | **8.0** | **10.0** | **−2.0** |
| animal structures | 8.0 | 10.0 | −2.0 |
| empty owned | 2.0 | 0.0 | +2.0 |
| money | 448.5 | 26.0 | **+422.5** |
| shed total | 3.0 | 20.0 | **−17.0** |

So the opening is **close but not exact**: the known §2 residue (−2 animals, housing follows)
plus the same signature as everywhere else — **we hold $422 he has spent, and we hold 3 shed
items where he holds 20** (his feed buffer).

**And it does not matter.** The two d5 experiments, same 24 episodes:

| continuation | final vs his own | we beat the opponent |
|---|---|---|
| our agent end-to-end (our d5 state) | **−$51,656** | 7/24 |
| our policy from **his exact d5 state** | **−$51,504** | 1/24 |

**The d5 state is worth $152 — 0.3 % of the gap.** Every dollar of the $51.5k is post-d5
policy. Changing phase 1 again cannot move this, and the §2 open item ("animals 8 vs 10,
needs ~$50–100") is confirmed as a rounding error at the season scale. The budget goes to the
kernel.

---

### 3.10 The 5-day checkpoint method, and the d10 baseline

From 2026-09-29 the method is: **clone the reference's state 5 days at a time**, using
`transplant --prefix ours --cut-day N` — our agent plays d0..N, and the report is our state
against his in the *same episode*. The target is <1 % per metric before moving to the next
checkpoint. This is deliberately a state-parity objective first, not a margin objective: the
policy work comes after the states match.

**d10 baseline** (24 random non-mirror episodes; `%` = ours vs his):

| at end of d10 | ours | his | gap |
|---|---|---|---|
| quadrants | 3.0 | 3.0 | **0 %** |
| carrot | 0.0 | 0.0 | **0 %** |
| tomato | 1.0 | 0.0 | n/a |
| STRAWBERRY | 16.0 | 20.5 | −22 % |
| **planted** | **43.0** | **54.5** | **−21 %** |
| WHEAT | 17.0 | 28.0 | **−39 %** |
| MELON | 9.0 | 5.0 | **+80 %** |
| **animals / structs** | **9.0** | **20.0** | **−55 %** |
| **empty owned** | **20.0** | **1.0** | **+1,900 %** |
| shed total | 51.0 | 72.0 | −29 % |
| money | 632 | 9,555 | −93 % |
| **WITHIN 1 %** | **2/13** | | |

**Arms tried at this checkpoint (12 episodes each):**

| arm | planted | empty | wheat | within 1 % | note |
|---|---|---|---|---|---|
| baseline | 43 | 19.5 | 17 | 2/13 | |
| `PLANT_CAP_BY_SEEDS_P2=1` | 43 | 19.5 | 17 | 2/13 | **inert** — the flat seed BUFFER, not the request count, is what limits planting |
| `+ SEED_FILL_BUFFER_P2=1` | **30.5** | 10.5 | **7** | 2/13 | **harmful** — sizing the ask to the full deficit spent the land money (money 592 → **5.5**, quadrant 3 → 2) |
| **`LAND_CASH_RESERVE_P2=0`** | **48** | **8** | **22** | **3/13** | the NE buy lands ~2 days earlier; **the biggest checkpoint mover** |
| `+` herd gate 1.3 `+` feed stock | 49 | 8 | 22 | 2/13 | animals still 10: **cash is $22, so the herd cannot be bought** |

**The wall this exposes.** After the land fix we are at d10 with **$22 against his $9,371**,
20 tiles worked instead of 1 bare, and 22 wheat tiles against 28 — but no cash to buy the
herd, the feed or the next quadrant. The state gap at d10 is therefore **bounded by revenue**,
and revenue is the kernel policy gap §3.8 measured. Land timing closes ~60 % of the `empty`
gap and ~45 % of the `wheat` gap; the rest needs the economy, not another scheduler knob.

**The d10 cash event is the melon harvest.** The reference's money series (his replays, start
of day) runs `100 / 36 / 111 / 530 / 504` through d6–d10 and then **+$9,570 on day 10**. His
melon harvest age is **10**; ours was **12**, so we held 9 melon tiles through the exact day he
banked the cash. Shipping `HARVEST_AGE_MELON=10`:

| at d10 | before | after | his |
|---|---|---|---|
| MELON tiles | 9.0 | **5.0** | 5.0 (**0 %**) |
| shed total | 44.0 | 68.0 | 73.0 (−6.8 %) |
| WHEAT | 22.0 | 23.5 | 26.0 (−9.6 %) |
| STRAWBERRY | 16.0 | 17.0 | 19.0 (−10.5 %) |
| within 1 % | 3/13 | **3/13** (quadrants, carrot, melon) | |

Cost: **−$5,299 median on the season** (`floor_sales +25`: the block harvest sells into a
glut; `plants_died +6`: the early harvest competes with watering).

**The remaining d10 gap is cash → herd, and it cannot be bought at d6–d10.** Adding
`WHEAT_TILES_PER_ANIMAL_P2=1.2` + `FEED_STOCK_DAYS_P2=2` + `FEED_BUY_CHUNK=40` leaves animals
at **10 against his 20** with **$15.50** at d10 — the melon cash lands *on d10*, after the
window in which the herd had to be bought. What is left, in order:

1. **Revenue d6–d10** — we sell WOOL 144 / MILK 165 / FERTILIZER 143 / EGG 66 against **0
   melon and 0 strawberry** (our d6–10 sell sheet). His d6–d10 income is ~2× ours and it funds
   12 animals; ours funds one quadrant.
2. **Herd** (10 vs 20, structs 12 vs 20) — blocked on (1).
3. **Fill** — planted 47.5 vs 55, empty 8 vs 1; bounded by crew turns (the kernel).
4. **TOMATO 2 vs 0** — our own `TOMATO_TARGET=16`; he runs no tomato in the midgame.
   Setting it to 0 for p2 closes this metric outright.
5. **`yarn` 0 vs 1** — shop-draw RNG we move with our own empty-tile count; not directly
   fixable, and not a policy defect.

#### d10 iteration log — 13 arms, plateau at 4–5/13

| arm | planted | empty | wheat | straw | animals | within 1 % |
|---|---|---|---|---|---|---|
| baseline (land+melon shipped) | 47.5 | 8 | 23.5 | 17 | 10 | 3/13 |
| `TOMATO_TARGET=0` | 46.5 | 10 | 24.5 | 17.5 | 10 | **4/13** |
| `+ STRAWBERRY_PEAK=9` | 46.5 | 9.5 | 21 | **22** (+15.8 %) | 10 | 4/13 |
| `+ herd gate 1.2 + feed stock` (C) | 46.5 | 12.5 | 23 | 18.5 | 10 | **5/13** |
| C + `PLANT_GLOBAL=1` | 43.5 | 14 | 22 | 16.5 | 10 | 4/13 |
| C + `STRAWBERRY_PEAK=11` (E) | 46.5 | 12.5 | 23 | 18.5 | 10 | **5/13** |
| E + `P_PLANT_P2=105` | 45 | 12.5 | 21 | 19.5 | 10 | 4/13 |
| E + `P_PLANT_P2=120` (G) | **49** | **7.5** | 23 | 20.5 | 10 | 4/13 |
| E + `TRADE_MIDGAME=1` | 44 | 13.5 | 20.5 | 18.5 | 10 | 4/13 |
| G + `TRADE_MIDGAME=1` | 46.5 | 10 | 21.5 | 18.5 | 10 | 4/13 |
| E + `WHEAT_TARGET=36` | 47 | 12.5 | 23 | 18.5 | 10 | 5/13 |
| E + `WHEAT_TARGET=36;STRAWBERRY_TARGET=32` | 47 | 12.5 | 23 | 18.5 | 10 | 5/13 |

Best config (E/C) re-validated at **n = 24**: **4/13** (5/13 was n = 12 noise). Shipped so far
at this checkpoint: `LAND_CASH_RESERVE_P2=0`, `HARVEST_AGE_MELON=10`, `TOMATO_TARGET=0`.

**The bundle is not shippable:** E adds `WHEAT_TILES_PER_ANIMAL_P2=1.2` +
`FEED_STOCK_DAYS_P2=2` + `FEED_BUY_CHUNK=40`, which raises **sell revenue +$31,829 (0/8
worse)** but costs **−$10,593 median** — the bought feed costs more than the herd earns. That
is the known "herd is unprofitable at the margin" result reappearing, and it is the lead for
the *revenue-consistency* goal: the revenue IS reachable, the feed bill is what eats it.

**Why it plateaus, precisely.** The eight remaining metrics are not knob-closable:
- **money (−99.9 %), animals (−50 %), structs (−40 %)** are **cash-gated**, and cash is
  revenue; at d10 we hold **$13 against his $9,555**. The three move together, and only the
  kernel/revenue can fund them.
- **planted (−14.7 %), empty (+1,100 %)** are **crew-turn-gated** (`moves/act 1.5 vs 0.8`);
  `P_PLANT_P2=120` buys planted 46.5 → 49 at the cost of straw, and `PLANT_GLOBAL` makes it
  worse.
- **wheat (−19.6 %), straw (−9.8 %)** are 2–6 tiles, same crew limit.
- **`yarn`** is the shop draw, which our own empty-tile count moves.

#### The public-agent checkpoint (`transplant --public`)

Our agent vs the 12 public opponents (2 seeds each = 24 games), snapshotted at d10:

| metric | median | p10 | p90 | spread | Boey | gap |
|---|---|---|---|---|---|---|
| money | 8 | 0 | 125 | **1,562 %** | 9,653 | −99.9 % |
| planted | 44 | 39 | 47 | 18 % | 55 | −20 % |
| WHEAT | 17 | 16 | 22 | 35 % | 26 | −34.6 % |
| animals | 10 | 9 | 11 | 20 % | 19 | −47.4 % |
| straw | 21 | 15 | 25 | **48 %** | 22 | −4.5 % |
| shed | 68 | 62 | 84 | 32 % | 71 | −4.2 % |
| melon / tomato / carrot / quadrants / yarn | | | | **0 %** | | **0 %** |

**Our d10 revenue is not just low, it is wildly inconsistent — a 1,562 % p10–p90 spread**,
with strawberry at 48 % and wheat at 35 %. That variance, not the median, is the thing to fix
next: a state we reach on the Boey replays is not a state we reach reliably against the field.

#### The feed-churn bug — the herd was never the problem

The herd bundle (`WHEAT_TILES_PER_ANIMAL_P2=1.2` + `FEED_STOCK_DAYS_P2=2` +
`FEED_BUY_CHUNK=40`) measured **−$10,593**. The cost breakdown (`games.csv` medians, 8 games)
said why:

| | land+melon | herd bundle | delta |
|---|---|---|---|
| final money | 43,709 | 34,119 | **−9,590** |
| sell revenue | 82,666 | 115,168 | +32,502 |
| **`product_cost_total`** | **19,327** | **64,356** | **+45,029** |
| `wheat_fed` | 324 | 349 | **+24** |

We bought **$45,029 of wheat and fed 24 more units**. Two bugs, both ours:

1. **`herd_plan.market_intents` sized the stock from the SHED alone.** Units carrying wheat
   leave the shed looking empty, so the layer rebought the same units every turn.
2. **`sell_policy` liquidated the stock.** Its wheat reserve was `unfed + WHEAT_SELL_RESERVE(5)`
   and did not know about the feed stock, so the herd rebought what the sell policy had just
   sold — a round trip that loses the spread every turn.

Both fixed (count carried wheat; fold the feed stock into the sell reserve). Same arm:

| | before | after |
|---|---|---|
| `product_cost_total` | 64,356 | **21,596** (base 19,327) |
| final money | 34,119 | **57,692** |
| vs the previous tree | −$10,593 | **+$10,218 median** |

**The "herd is unprofitable at the margin" conclusion was this churn**, and the parts are not
separable: the herd gate + stock **alone** is −$5,448 without `STRAWBERRY_PEAK=11` — the herd
eats feed that only the earlier strawberry ramp pays for. Shipped as one 4-part bundle.

#### Revenue variance and the wheat/strawberry mix — both reduce to the fill

**Revenue variance is not a sell-policy problem.** Across 48 public games at d10 our cash is
`median 31, p10 3, p90 369` (CoV **149 %**, p10–p90 spread **1,181 %**) against his 9,653.
The drivers, measured on the same 48 games:

| correlation with d10 cash | |
|---|---|
| planted tiles | **−0.85** |
| STRAWBERRY / WHEAT tiles | −0.60 / −0.54 |
| animals | **+0.49** |
| structs | +0.30 |

Cash at d10 is a **residual — income minus investment** — and we convert it into crops that
have not yielded yet. The per-opponent medians split 70 vs 6, i.e. the residual swings with
early allocation, not with the opponent's market play. Two arms confirm it is not the sell
side: `TRICKLE_P2=20` makes it **worse** (median 6, spread 1,583 %), and
`SELL_TRICKLE_FRACTION_P2=0.25` is **inert** (byte-identical). Two more confirm it is not the
melon event: `HARVEST_AGE_MELON` 9 and 8 leave d10 cash at 5 and 8.5.

**The mix is nearly right.** Ours at d10 vs his (357 replays):

| | ours | his |
|---|---|---|
| WHEAT tiles | 21 | 26 |
| STRAWBERRY tiles | **22** | **22** (0 %) |
| WHEAT/STRAWBERRY ratio | 0.95 | 1.18 |
| wheat+straw total | 43 | 48 |

Strawberry is exactly at parity and the ratio is only mildly strawberry-heavy: the deficit is
**5 wheat tiles out of 48 crops**, i.e. a uniform shortfall, not a mix error. `WHEAT_TARGET=36`
does not bind — the queue already asks for an 11-tile wheat deficit; we plant ~4/day because
the crew is walking.

**Both questions are the same question.** Revenue variance is the residual of an
under-producing farm; the mix is 5 tiles short. Both are the **fill**, and the fill is the
kernel: `moves/act 1.5 vs 0.8`, `WATER` 40 %, `died` 5.8× (§3.8). That is round 5.

---

### 3.11 The kernel, decomposed — it is the DELIVERY decisions, not geometry or layout

`transplant --save-dir` now saves the post-cut env as replays (stamping our seat into
`info.TeamNames`, because `env.toJSON()` drops it and the analysis tools would otherwise read
the *opponent*). Running `move_trace` on the d11–17 window of the control (his own play) and
the treatment (ours, from his d10 state) gives the kernel line by line, per game:

| d11–17 | his ops | his mv/op | our ops | our mv/op |
|---|---|---|---|---|
| total moves | **815** | | **1,142** | |
| **COLLECT_FERTILIZER** | 156 | **0.78** | 154 | **2.35** (32 % of all our moves) |
| **FERTILIZE** | 67 | **0.03** | 47 | **2.40** |
| PICKUP | 55 | 0.98 | 84 | 1.27 |
| DROP | 22 | 0.86 | 26 | 2.08 |
| WATER | **298** | 1.21 | **147** | 1.74 |
| CARE | 155 | 0.43 | 154 | 0.69 |
| FEED | 154 | 0.60 | 154 | 0.38 |
| HARVEST | 140 | 0.49 | 97 | 0.73 |
| PLANT | 60 | 0.10 | 36 | 0.19 |
| moves empty / carrying | | 17 % / 83 % | | 12 % / **88 %** |

**We do the same number of collects (154 vs 156) and walk 240 more tiles doing them.** The
same layout, the same ops, 3× the travel — so this is the **assignment**, not the geometry.
The pattern is uniform: our *on-tile* ops are fine or better (FEED 0.38 vs 0.60, PLANT 0.19,
HARVEST 0.73), while every **carry/delivery** op costs us 2–3× (COLLECT 3×, FERTILIZE 80×,
DROP 2.4×). And we water **half as often** (147 vs 298) — that is the `died` gap.

Three arms against it, all measured on the transplant (12 episodes, control exact):

| arm | COLLECT mv/op | FERTILIZE mv/op | total moves | final |
|---|---|---|---|---|
| baseline | 2.35 | 2.40 | 1,142 | −$53,402 |
| shed loop (3 knobs) | — | — | 1,142→(PICKUP 280→219) | −$52,878 (but MOVE **rose** to 3,221) |
| fertilize both crop types | 2.35 | 2.40→(ops 42→72) | 1,136 | −$54,190 |
| `CARRY_BAND_LOCAL_P2=1` | 2.18 | 2.27 | 1,121 | −$60,791 |

**None closes it, and that is the finding: the delivery policy needs a redesign, not another
knob.** The mechanism is that after a `COLLECT_FERTILIZER` the unit re-picks delivery
**globally** (`only_delivery` `_pick` has no `prefer`) and walks ~2.4 tiles; the reference
delivers to the tile it is standing on or next to (FERTILIZE **0.03 mv/op**). The target is
explicit: `COLLECT 2.35 → 0.8`, `FERTILIZE 2.40 → 0.1`, total moves `1,142 → 815`, and then
the freed turns pay for the `WATER 147 → 298` that stops the `died 52 → 9`.

---

## 4. Phase 3 — endgame (d18–d29)
Sources: `docs/v0/phase3.txt`, `docs/v0-boey/phase_all_vs_boey.txt`.

| metric | us | DSM | Boey | DAG |
|---|---|---|---|---|
| **WATER ops** | **288** | 662 | 486 | **ROOT** (explains 4 vs Boey) |
| **FERTILIZE ops** | **0** | 162 | 142 | **ROOT** |
| HARVEST ops | **185** | 394 | 334 | BAD |
| HARVEST / planted tile | 0.45 | 0.78 | **1.42** | BAD |
| weeds | **35** | 10 | **3** | BAD |
| **shed at the bell** | **25.5** | 1.0 | **0.0** | **BAD** |
| animals at the bell | 11 | 12 | 15 | WARN |
| idle share % | 0.00 | 0.00 | 1.32 | ok |

**DAG causation:**

```
WATER ops [p3]      <- WATER ops [p2] <- plants planted [p2]
weeds [p3]          <- WATER ops [p3]   (retiring a tile weeds it)
HARVEST per planted <- HARVEST ops <- weeds, plants died
FERTILIZE [p3]      <- FERTILIZE [p2] <- animals [p2] <- animals [p1] (p1 ROOT; cash closed by the tape)
shed at the bell    <- HARVEST ops [p3]
```

We finish with **$1,100 stranded** and a shed holding **25.5**; DSM $45 / 1.0; **Boey $0 / 0.0**. Boey's
endgame harvest-per-planted-tile is **1.42 against our 0.45** — it converts standing crop, we leave it.

**Sell ceiling (C6):** our STRAWBERRY `floor%` p90 **53.2**, `px` p10 **$9.6**. But both leaders floor
more than we do (DSM 10/game, Boey 58/game) and win anyway — so the target is **our own p10 price and
tail**, not a zero-floor count.

**FERTILIZE — SUPERSEDED 2026-09-29, see §3.4.** The recorded arm (`FERTILIZE_FROM_DAY=6`:
−$14,230 median, 2/96) was real, but it measured the wrong thing: our delivery path, not the
op. The reference fertilizes (1,390 wheat ops in d6-17, 57 % of wheat harvests) and its
fertilized wheat yields 5.35 against 3.17. Our FERTILIZE ran at 4.35 moves/op against its
0.09. The node is now judged, and the open question is economic: at our current turn cost
the 8-game screens are still net-negative, which makes the **movement cost of the
application** the thing to fix before the op can pay.

---

## 5. Two leaders, two shapes — and why both point at the same first fix

| | DSM | Boey |
|---|---|---|
| shape | production farm | production + **arbitrage** |
| harvests / animals (d16) | 597 / 22 | 529 / 20 |
| agronomy (weeds / plants died) | 10 / 19 | **4 / 9** |
| buys (wheat / fertilizer per game) | 183 / 0 | **3,497 / 728** |
| sells (wheat / fertilizer per game) | 562 / 266 | **2,542 / 487**\* |
| buy-side spend | $7,036 | **$153,863** |
| tail (worst / % lost >$4k) | **−$3,570 / 0.0 %** | −$21,468 / 6.4 % |
| moves/act / productive share | 0.76 / 55 % | 0.82 / 53 % |
| WATER chained / PLANT→WATER split | 21.8 % / 4 % | 22.7 % / 12 % |

\* Boey's sell figures are shed-capped (`dsm_profile`); the requested-order totals were 6,786 / 4,622.
DSM's column is still the older method — regenerate before quoting it.

The two archetypes disagree on *what to produce and trade* and agree on *how to move*. We match
neither shape, and the movement gap is common to both: **that is why the first fix is the kernel, not
a strategy change.**

---

## 6. Cross-phase edges that set the fix order

| edge (DAG) | measured |
|---|---|
| `plant_ops [p1] → water_ops [p1]` | PLANT closed by the tape (26 vs 30/32); the WATER gap (53 vs 74/78) is now crew-limited, not seed-limited |
| `water_ops [p2] → plants_died [p2]` (lag 2) | died 21 vs 0–2; weeds 17 vs 0–1 |
| `animals [p1] → animals [p2]` | 11 vs 20–22; FEED/COLLECT/FERTILIZE all ~0.4–0.5× |
| `wheat_tiles [p2] → feed_ops [p2]` | `feed_surplus` −126 vs +191 / +3,021 |
| `harvests [p2] → shed [p2/p3]` | shed peak 18 vs 28–31; stranded $1,100 vs $45 / $0 |
| sell ceiling → shed fill (C6) | our STRAWBERRY floor% p90 53.2, px p10 $9.6 |

---

## 7. Fix plan — dependency-ordered, one gate per step

**Two-stage protocol: SCREEN on 16 games, CONFIRM on the field.** A full arm is ~13 minutes and
~6.6 GB; screening must not cost that just to see a direction.

```bash
# SCREEN (16 games, ~2-3 min): --pa 1-4 --batch 4
#   judge only direction + sign; a screen that regresses a guard is dead and never reaches confirm
.venv/bin/python -m tools.diagnose --scratch --pa 1-4 --batch 4 --seed 4362837462 --run-dir diag-replays/sc-X
.venv/bin/python -m tools.report.arm_diff --a diag-replays/<prev> --b diag-replays/sc-X
# CONFIRM (96 games) — only if the screen moved the target and no watchlist column regressed
.venv/bin/python -m tools.diagnose --scratch --pa 1-12 --batch 8 --seed 4362837462 --run-dir diag-replays/stepN
```

**Gate after every confirmed step (same seeds, before committing):**

```bash
# 1. run the candidate
.venv/bin/python -m tools.diagnose --scratch --pa 1-12 --batch 8 --seed 4362837462 --run-dir diag-replays/stepN
# 2. the root for the phase it attacks, against BOTH references
PYTHONPATH=. .venv/bin/python -m tools.phases.phase_map --phase <p> --pa 1-12 --batch 2 \
    --ref-from replays/DSM/v1 --ref-max 123 --spread
PYTHONPATH=. .venv/bin/python -m tools.phases.phase_map --phase <p> --pa 1-12 --batch 2 \
    --ref-from diag-replays/boey-lb --ref-max 359 --team Boey --spread
# 3. reference integrity (DAG fallback table is DSM-specific; use --ref-from for Boey)
PYTHONPATH=. .venv/bin/python -m tools.phases.phase_map --phase all --replay-dir replays/DSM/v1 --max-games 123 --seat auto
# 4. did we regress?
PYTHONPATH=. .venv/bin/python -m tools.gates.margin diag-replays/stepN
PYTHONPATH=. .venv/bin/python -m tools.report.arm_diff --a diag-replays/v1-us --b diag-replays/stepN
```

**Commit only if:** the target root moved against both references; the phase trace shows downstream
symptoms moved with it; `arm_diff` median margin is not negative; the DSM self-check is unchanged.

---

**Step 0 — DONE: `open_dist` deleted.** `tools/phases/dag.py`, `tools/phases/phase_map.py`, the
`params.py` comment and this document. No code path or output prints it.

**Step 1 — Finish the tile on one visit. DONE (shipped at the right threshold).**
- **DAG node:** `WATER ops per planted tile` — ROOT, owner `src/scheduler.py::_pick`, **no deficient ancestor**.
- **Evidence (both references):** WATER chained 0.0 % vs 21.8 / 22.7 %; PLANT→WATER split 86 % vs 4 / 12 %; WATER 2.92 vs 1.17 / 1.25 mv/op; FEED 2.12 vs 0.09 / 0.54.
- **Shipped:** `SAME_TILE_FIRST=True` at the default **`SAME_TILE_MIN_PRIORITY=70`** (the threshold is
  the whole result: at 0 it steals the planters and regresses MELON/empty/idle, §2.1);
  `SAME_TILE_PROTECT_CRITICAL=True`, `CRITICAL_RESCUE_K=1`; `src/roots.py` stays inert
  (`URGENCY_SLOPE=0`). `SAME_TILE_ORDER` and `EXACT_ASSIGN` measured **harmful** — not shipped.
- **Measured:** Phase-1 `WATER ops` 53 → **66**, PLANT 27 → **30**, animals 7 → **8**, idle 0.78 → 5.08
  (still below Boey's 6.62); season A/B vs no-chain: margin **+$5,061** (11/16), revenue **+$8,747**,
  `plants_died` **−5.5 (0/16 worse)**. **Watch:** `stranded_at_bell` (+$40 median), `floor_sales`.

**New instruments shipped with this step:**
- `src/roots.py` — the binding-root controller (state-derived priority multipliers; `URGENCY_SLOPE=0` is inert by default).
- `tools/market/demand_map.py` — the demand-side running metric (season shop drain vs our sales, YARN/no-YARN split; §3.3, `docs/v0/demand_map.txt`, `docs/v0-boey/demand_map.txt`).
- `tools/phases/compose.py` — the portfolio/interaction evaluator: runs base + candidates + every 2^k combination on matched seeds and reports each combination's interaction term and sign test, so combinations are evaluated instead of hill-climbed.



**Step 2 — STRAWBERRY sell ceiling. ALREADY MET — the recorded measurement is stale.**
- **DAG node:** sell-policy leaf; C6 edge into shed fill.
- **Evidence (current tree, 16 games, day CSVs of `diag-replays/sc-tape-v2`):** 152 units sold,
  **below-base 3.9 %**, **floor 0 units**, avg px **$183.54**, per-game px p10 **$173.60** — against a
  STRAWBERRY base of **$120**. The §7 figure (`floor% p90 53.2`, `px p10 $9.6`) predates the current
  tree. `SELL_CEILING_BOOST` stays 0.
- **Target met:** `px` p10 ≥ base, `floor%` p90 < 1 %.

**Step 3 — Opening script: DONE. The Boey script is the tape's d0–d5 plan.**
- **DAG:** closed `opening cash committed` (0.81 → **1.00** vs 0.99) and the PLANT/MELON root.
  Phase-1 now reads PLANT **30/30**, MELON 9, STRAWBERRY 4, hands 5, empty 3.0, idle 5.08 (Boey 6.62).
- **Shipped:** the measured per-day tables in `src/opening.py` (`CROP_BY_DAY`, `HERD_BY_DAY_SPECIES`),
  a ring reservation that grows with the herd, `_early_harvest` (wheat taken at first yield, so the
  d0 sow converts on schedule), `_seed_need`/`_animal_budget` (the d0 basket is $690 seed + $2,200 herd
  against the $3,000 bank), and three previously dead mechanisms wired: `OPENING_SELL_CHUNK`,
  `opening.jobs()`, `MAX_HIRE_PER_TURN=1`.
- **A/B (16 games, old script → new):** median margin **+$3,230** (9/16), revenue **+$9,293**,
  idle **−1.7 pp**. Watchlist: `stranded_at_bell` +$102 (16/16), `floor_sales` +11 — the Step 2 edge.
- `WHEAT_LANDS_DAY=2` stays rejected: **−$15,452 (0/8, p=0.005)**.

**Step 4 — WATER coverage: DONE. `P_WATER_BONUS` was a phantom knob.**
- **DAG:** `WATER ops` (was 53 vs 76) — the root with no deficient ancestor, owner `_pick`.
- **Root cause:** window watering is emitted at `P_WATER_BONUS`, a bare constant `50` in `src/job.py`
  with **no `params.py` entry**, so every A/B of it measured nothing; 50 sits below `P_CARE`/`P_PLANT`/
  `P_PICKUP`, so yield-watering was the first job dropped and wheat yielded 1 unit instead of 3.
- **Shipped:** `P_WATER_BONUS=120` (real param now; 140/160 identical) **with** `SAME_TILE_FIRST=True`.
- **Measured:** WATER 53 → **66**, animals 7 → **8**, CARE 33 → **35**, FEED 27 → **33**, PLANT 27 → 30;
  `OPENING_WHEAT_KEEP_DAYS=1` would give WATER 68 / idle 1.16 but turns FEED **BAD** (31) — rejected.
- **Watch:** `plants_died`, `unwatered_eod` (both improved on the season arm).

**Step 4b — the scheduler market branch day-gate (DONE, a correctness fix).**
`src/scheduler.py` gated the tape's *jobs* branch on `day <= OPENING_HERD_UNTIL_DAY` but not its
*market* branch, so with `OPENING_TAPE` on, d6–bell ran the tape's market list and
`herd_plan.market_intents` / `crop_plan.market_intents` never ran (no midgame seed rebuy, no midgame
herd buying). Now day-gated. Measured: full-season idle **25.8 % → 1.3 %**, paired margin **+$14k to
+$18k** over 16 games. Phase-1 unaffected.

**Step 5 — Market/trade layer: DONE (`src/trade.py`). The herd is now a TIMING problem.**
- **Built:** `src/trade.py` — a price-threshold wheat carry (`sell_intents` / `buy_intents(state, reserve)`),
  wired into the opening tape. Params: `TRADE_BUY_MARGIN`/`TRADE_SELL_MARGIN` (4/4), `TRADE_CHUNK`,
  `TRADE_FEED_RESERVE`, `TRADE_CASH_FLOOR`, `TRADE_FROM_DAY=1`.
- **Measured:** `d0–5 trade net` **$1,753 → $2,368** (0.72× → **0.97× Boey**, **1.33× DSM**), WATER 66 → 68,
  herd composition intact (COW 4/4, GOOSE 2/2). Cost: `idle` 5.08 → 8.66, PLANT/CARE/FEED −1 op each.
- **Infrastructure shipped with it:** `flow:TRADE_NET` in `phase_map.extract` — the exact ledger identity
  `d_money + fixed spend = sells − product buys`; a **descriptive** DAG flag (`M(..., descriptive=True)`)
  so gross revenue is reported beside the net but never judged; `revenue_per_item` populated on the
  non-audit path in `tools/diagnose/analysis.py`, so leaderboard replays have revenue at all.
- **Left:** the carry's +$615 lands d3–d5, after the herd buys. `animals` 8 vs 10 needs the herd's cash
  **earlier** (front-load the carry, or extend it to d0 behind a protected animal budget).
- **Gate:** phase1 `animals` ≥ 9.

**Step 6 — Wheat / feed self-sufficiency. Depends on Step 5.**
- **DAG edge:** `wheat_tiles [p2] → feed_ops [p2]`; feed gates `animals`.
- **Evidence:** `feed_surplus` **−126 vs +191 / +3,021**; 53 wheat units bought in the opening alone;
  20 wheat tiles died unharvested vs 5.
- **Target:** `feed_surplus` ≥ 0; wheat peak 33 → ~57.
- **Gate phase:** phase2. **Watch:** `shed_pressure_days`.

**Step 7 — Herd scale (midgame). Depends on Step 5.**
- **DAG chain:** `animals [p1] → animals [p2]`; `animals [p2] → FEED/COLLECT/FERTILIZE`; C2 gates it.
- **Evidence:** 11 vs 20–22; our $/animal-day is already 1.75× DSM's, so this is **count**, not husbandry.
- **Target:** `animals` 11 → ~20 **with** `feed_surplus` ≥ 0.
- **Gate phase:** phase2. **Watch:** feed_surplus, plants_died.

**Step 8 — Crop scale to the leaders' peaks. Depends on Steps 1 + 2.**
- **DAG edges:** `planted → water_ops`; `harvests → shed`. C5 and C6 both bite.
- **Evidence:** peaks 0.3–0.6× theirs; endgame harvest/planted 0.45 vs 0.78 / **1.42**.
- **Target:** per-crop peaks → 1.0× with floor% < 1 %.
- **Gate phase:** phase2/3. **Watch:** floor%, plants_died, shed.

**Step 9 — Endgame rotation. Depends on Steps 7 + 8.**
- **DAG edge:** `harvests [p3] → shed [p3] → idle`.
- **Evidence:** `stranded_at_bell` **$1,100 vs $45 / $0**; shed at bell 25.5 vs 1.0 / 0.0.
- **Target:** stranded ≤ $100. Keep `RETIRE_DAY=99` (blanket water-off was catastrophic).
- **New (from the §3.1g 96-game confirm):** phase 3 is where this round's surplus lands as a
  *regression* — `WATER ops` 165 → **126** against Boey's 472 and `weeds` 31 → **40** against his
  3, while `HARVEST ops` 147 → 158. Phase 3 is the dominant root of the season's `plants_died +4`.
  A bigger phase-2 farm has to be **spent** at d18; that is this step, and it now has a measured
  starting point (`step10-{pre,ship}-phase3.txt`, replayed from the saved 96 games).

**Step 10 — `move share` is now its own ROOT (OPEN). Depends on nothing; blocks everything.**
- **DAG node:** `move share %` — 59.5 vs Boey's 41.6, **no deficient ancestor** since §3.1g.
- **Evidence:** `moves/act` 1.52 vs 1.09; 3,073 walks totalling 7,341 tiles at a mean of 2.39 vs
  2,895 / 5,650 / 1.95 (`tools/labour/walk_runs.py`, d6-17, 4 games each); WATER starts **40.4 %** of
  our walks. Act-by-act chain rate after §3.1g: WATER 0.0 %, COLLECT 20.9 %, PICKUP 46.8 %,
  DROP 44.8 % (Boey: WATER 15.9 %, COLLECT 33.9 %, PICKUP 26.8 %, DROP 44.7 %).
- **What is already known NOT to work** (§3.1g table): `DIST_CAP_P2` 2/3 and `ON_TILE_BONUS_P2=60`
  buy 1.5–2.2 pp of `move share` and pay 7–10 extra plant deaths; `PLANT_BLOCK` (sow a band in one
  day) empties WHEAT.
- **The shape of the fix:** the demand, not the choice rule. `layout.slice_partition` gives each
  worker a ~6-tile band, but `_plant_jobs` fills it one tile per turn, so the band carries six
  different water windows and the day's thirsty tiles are never neighbours. A correct version of
  block-sowing has to consume the per-crop deficit (`crop_plan.plant_queue`) instead of filling a
  band blindly — that is the difference between the measured regression and the intended win.
- **Target:** `move share` ≤ 45 % **with** `plants died` ≤ 8 and `WHEAT tiles` ≥ 28. **Watch:**
  `plants_died`, `weeds`, `shed peak`, `HARVEST`.

**Closed — do not re-try (the FERTILIZE entries are SUPERSEDED — re-open only via §3.4,
where the yield mechanism and the delivery-cost cause are measured):** `FERTILIZE_FROM_DAY=6`
(−$14,230, 2/96), `FERTILIZE_ONGOING_ONLY`,
`P_WATER_SURVIVAL`, `PLANT_WATER_CAP_DIVISOR=2`, `HANDS_MIDGAME=20`, `WHEAT_LANDS_DAY=2`,
`CASH_RESERVE=0`, `MOVE_WEIGHT` 15/60, `HERD_BUY_UNTIL=5` (−$2,080 vs the shipped 12),
`FERTILIZE_FROM_DAY=6` (**−$4,474 median, 4/16, p=0.077, revenue −$6,549** on the earlier
tree — SUPERSEDED: that arm measured the shed-pickup delivery, which `crop_cycle` dated at
4.35 moves/op; the yield the op buys is real, see §3.4), `P_COLLECT_FERT=70` (phase-1 regression: animals 8 → 7,
GOOSE 2 → 1, trade net 0.98× → 0.90×),
`SAME_TILE_MIN_PRIORITY=0` (steals the planters), `SAME_TILE_ORDER=1` and `EXACT_ASSIGN=1`
(CARE 70 → 8 / 0), `ON_TILE_BONUS=20` (WATER → 49), `P_WATER_BONUS` 140/160 (identical to 120),
`OPENING_WHEAT_KEEP_DAYS=1` (WATER 68 but FEED turns BAD), `OPENING_OWNS_SELLS=1` (slightly worse),
`DIST_CAP_P2=2` (plants died 10 → 17) and `=3` (shed peak 40.5, animals 16 → 15),
`ON_TILE_BONUS_P2=60` (move share 57.4 but plants died 10 → 20.5), `PLANT_BLOCK_P2=3/5`
(WHEAT 28 → 17.5/9, animals 16 → 10/9, idle 7–10 %), `HANDS_MIDGAME=14` (idle rises —
the extra hands have nothing to do, so the midgame is not throughput-limited), `TRADE_MIDGAME=1` (re-measured on the post-W6/W7 tree: revenue +6.6 % but trade net −$1,605 and plants died 10 → 15.5 — the carry is churn, §3.1h), `STRAWBERRY_PEAK=8/6` (animals 16 → 11.5, WHEAT 28 → 20), `BAND_ANIMALS_P2=1` (animals 16 → 13, move share 59.6 → 61.1), `WATER_ONGOING_PRODUCE_P2=1` (inert — the survival rule already covered ~half the production days), and the whole of §3.1i: `DIST_CAP_P2` 2/3/5 with `CRITICAL_FREE_WALK_FRAC=0`, `LAYOUT_RADIAL_P2=1`, `LAYOUT_EVEN_BANDS_P2=1`, `HANDS_MIDGAME` 14/16, `MAX_HIRE_PER_TURN_P2` 2/3, `FERTILIZE_FROM_DAY_P2=6` with our own fertilizer (**−$9,338 net**, herd 16 → 12) and both of its ONEHOT/ONGOING restrictions. `EXACT_ASSIGN` is now correct and still slower than `_pick`.

Raw output: `docs/v0/MANIFEST.md` (us vs DSM) and `docs/v0-boey/MANIFEST.md` (us vs Boey).
