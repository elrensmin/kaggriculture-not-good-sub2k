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
| herd revenue / game | $43,985 | $44,517 | $176,209\* |
| **productive share** | **31 %** | **55 %** | **53 %** |
| **moves per act** | **2.03** | **0.76** | **0.82** |
| moves empty-handed | 62 % | 33 % | 30 % |

\* Boey's herd-revenue figure includes **bought-and-resold fertilizer** (buys 728/game, sells 4,622 at
$38.7); it is a trading line, not herd output.

**Both leaders are structurally the same and we are not.** They agree to within a few points on the one
axis that separates us: ~54 % productive share at ~0.8 moves/act, against our 31 % at 2.03. Everything
else is archetype: **DSM is a production farm** (597 harvests, 20 animals, no trade), **Boey adds
arbitrage** (6,786 wheat and 4,622 fertilizer sold per game on 3,497 + 728 bought). Boey has the best
normalised margin but the worse tail — it dumps 58 floor units a game and loses 6.4 % by >$4k.

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

| | Boey | us (before) | us (now) |
|---|---|---|---|
| gross sell revenue | $11,624 | $2,834 | $5,023 |
| **product trade net** | **$2,438** | **$1,753** | **$2,368** |
| animal spend | $4,000 | $3,200 | $3,200 |
| net cash (bank 3,000 →) | −$2,974 | −$2,876 | — |

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

Sources: `docs/v0/phase2.txt`, `docs/v0-boey/phase_all_vs_boey.txt`.

| metric | us | DSM | Boey | DAG |
|---|---|---|---|---|
| **WATER ops** | **318** | 585 | 466 | **ROOT** (explains 4) |
| **WATER ops / planted tile** | **0.58** | 0.83 | 0.77 | **ROOT** |
| animals on board | **11** | 22 | 20 | **ROOT** (explains 6) |
| FERTILIZE ops | 0 | 76 | 64 | BAD |
| HARVEST ops | **71** | 182 | 183 | BAD |
| COLLECT_FERTILIZER ops | 85 | 215 | 215 | BAD |
| FEED ops | 101 | 197 | 209 | BAD |
| **plants died** | **21** | 2 | **0** | **BAD** |
| **weeds** | **17** | 1 | **0** | **BAD** |
| shed peak | 18 | 28 | 31 | BAD |
| planted tiles | 73 | 72 | 56 | ok |
| owned tiles / quadrants | 100 / 4 | 100 / 4 | **75 / 3** | ok |
| STRAWBERRY tiles | 30 | 30 | 27 | ok |
| idle share % | 0.00 | 0.00 | 2.46 | ok |

**DAG causation:**

```
animals on board [p2]      <- animals [p1]  (p1 ROOT vs Boey; opening cash committed is now CLOSED)
COLLECT/FEED/FERTILIZE [p2]<- animals on board [p2]
WATER ops per planted tile <- scheduler._pick          [ROOT, NO bad ancestor]
plants died [p2]           <- WATER ops per planted tile [p2]   (lag 2)
weeds [p2]                 <- plants died [p2] <- WATER ops [p2]
HARVEST ops [p2]           <- weeds, plants died, animals
shed peak [p2]             <- HARVEST ops, animals
```

**Boey beats DSM on agronomy while working fewer tiles.** It owns 75 tiles to our 100 and plants 56 to
our 73, yet **loses 0 plants and 0 weeds** and still harvests **183 ops to our 71**. It runs 466 WATER
ops on 56 tiles = **0.77 coverage**, second only to DSM. With no plant loss, its fertilizer and water
are spent on output instead of repair — which is why it can afford the trading side of its game.

**The farm we have is the right size; it is the wrong throughput.** Two roots, and only one of them is
dependency-free:

1. `animals` (11 vs 20–22) — chain runs back to phase 1.
2. **`WATER ops per planted tile` (0.58 vs 0.77–0.83) — owned solely by `_pick`, no deficient ancestor.**

### 3.1 The mechanism is the same-tile revisit — both references agree

| measure | us | DSM | Boey | source |
|---|---|---|---|---|
| moves / act | **2.03** | 0.76 | 0.82 | `movement.txt` |
| movement share | 63.3 % | 41.5 % | 43.8 % | `movement.txt` |
| WATER chained (act→act on the spot) | **0.0 %** | 21.8 % | **22.7 %** | `op_patterns.txt` |
| FEED chained | **5.0 %** | 89.4 % | 64.5 % | `op_patterns.txt` |
| PLANT → WATER split across two visits | **86 %** | 4 % | **12 %** | `visit_trace.txt` |
| FEED → CARE split across two visits | **100 %** | 5 % | ~8 % | `visit_trace.txt` |
| ops per tile stop | **1.36** | 1.90 | 1.78 | `visit_trace.txt` |
| extra trips / tile-day | 0.350 | 0.202 | 0.328 | `visit_trace.txt` |
| WATER moves per op | **2.92** | 1.17 | 1.25 | `move_trace.txt` |
| FEED moves per op | **2.12** | 0.09 | 0.54 | `move_trace.txt` |
| PASS-on-READY turns / game | **119.5** | 30.3 | 72.4 | `ready_idle.txt` |
| value left on tiles / game | **$36,024** | $7,168 | $8,435 | `ready_idle.txt` |

The crew is not idle (`idle-on-work` ~72 turns/game); it never reaches the work. Pending per day is
**WATER 1,341 / FERT 561 / HARVEST 472 / DIG 337** (`missed_work.txt`). `_pick` splits one tile's acts
into separate trips; that is the root both leaders have solved and we have not.

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

`dsm_profile` selling, ours (audit) vs DSM (reconstructed) — Boey's line totals are in
`dsm_profile.txt`/`dsm_flows.txt`:

| product | our units | our px | DSM units | DSM px | Boey units | Boey px |
|---|---|---|---|---|---|---|
| WHEAT | 128 | $42.2 | 562 | $34.6 | **6,786** | $35.3 |
| STRAWBERRY | 94 | $171.5 | 223 | $135.6 | 358 | $157.7 |
| MELON | 28 | $198.0 | 60 | $208.7 | **337** | $194.6 |
| EGG | 52 | $54.4 | 207 | $46.3 | **2,025** | $44.1 |
| MILK | 107 | $202.3 | 191 | $90.6 | 720 | $87.3 |
| WOOL | 88 | $228.9 | 104 | $128.0 | 161 | $106.8 |
| FERTILIZER | 192 | $52.3 | 266 | $52.1 | **4,622** | $38.7 |
| CARROT | 20 | $49.2 | 190 | $39.8 | **968** | $42.0 |

We get a **better unit price than either leader on most lines** and move a small fraction of their
volume. The gap is supply, and for Boey it is also **trading** (it buys 3,497 wheat and 728
fertilizer to resell into the deep `log`-curve goods).

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
(6,786 wheat + 4,622 fertilizer sold/game on 3,497 + 728 bought).

**Caveat, and it is the whole point of the running metric:** the draw is a function of our own
play (`_spawn_weeds` shares the RNG stream), so the two arms are *different worlds*. YARN appears
in **95/96** of our games against **78/123** DSM and **238/359** Boey — no shop-conditioned
comparison across arms is controlled. `demand_map` prints the mix first for exactly this reason.

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

**FERTILIZE stays off — re-measured with the herd present.** `FERTILIZE_FROM_DAY=6`:
**−$14,230 median, 2/96, p=0.0000** (`probe-fert.txt`). We sell 100 % of 191.5 collected units for
$10,153; Boey buys and resells fertilizer rather than fertilizing its own field more than DSM.

---

## 5. Two leaders, two shapes — and why both point at the same first fix

| | DSM | Boey |
|---|---|---|
| shape | production farm | production + **arbitrage** |
| harvests / animals (d16) | 597 / 22 | 529 / 20 |
| agronomy (weeds / plants died) | 10 / 19 | **4 / 9** |
| buys (wheat / fertilizer per game) | 183 / 0 | **3,497 / 728** |
| sells (wheat / fertilizer) | 562 / 266 | **6,786 / 4,622** |
| buy-side spend | $7,036 | **$153,863** |
| tail (worst / % lost >$4k) | **−$3,570 / 0.0 %** | −$21,468 / 6.4 % |
| moves/act / productive share | 0.76 / 55 % | 0.82 / 53 % |
| WATER chained / PLANT→WATER split | 21.8 % / 4 % | 22.7 % / 12 % |

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

**Closed — do not re-try:** `FERTILIZE_FROM_DAY=6` (−$14,230, 2/96), `FERTILIZE_ONGOING_ONLY`,
`P_WATER_SURVIVAL`, `PLANT_WATER_CAP_DIVISOR=2`, `HANDS_MIDGAME=20`, `WHEAT_LANDS_DAY=2`,
`CASH_RESERVE=0`, `MOVE_WEIGHT` 15/60, `HERD_BUY_UNTIL=5` (−$2,080 vs the shipped 12),
`SAME_TILE_MIN_PRIORITY=0` (steals the planters), `SAME_TILE_ORDER=1` and `EXACT_ASSIGN=1`
(CARE 70 → 8 / 0), `ON_TILE_BONUS=20` (WATER → 49), `P_WATER_BONUS` 140/160 (identical to 120),
`OPENING_WHEAT_KEEP_DAYS=1` (WATER 68 but FEED turns BAD), `OPENING_OWNS_SELLS=1` (slightly worse).

Raw output: `docs/v0/MANIFEST.md` (us vs DSM) and `docs/v0-boey/MANIFEST.md` (us vs Boey).
