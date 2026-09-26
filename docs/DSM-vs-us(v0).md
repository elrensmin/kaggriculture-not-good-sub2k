# DSM vs us (v0)

**Why the from-scratch agent loses to every public agent while DSM wins 95.9 %.**

This is a diagnosis, not a scorecard. It answers *what the farm is doing differently, phase by
phase, and how one difference propagates into the next*. Every number is reproduced by a command in
[Appendix B](#appendix-b--regenerating-every-table); the raw tool output behind each table is in
`docs/v0/`.

---

## 0. Provenance and comparability — read before any table

| column | what it is | sample | audit? |
|---|---|---|---|
| **DSM** | the #1 team's own leaderboard games, `replays/DSM/v1/` | **123 episodes / 246 seat-rows**, 66–67 distinct teams, W **117** – L **5** (95.9 %, excluding the self-play mirror; 118–5 counting it), median margin **+$14,144**, normalised (median-of-per-opponent-medians) **+$20,351**, worst game **−$3,570**, games lost by >$4k: **0.0 %** | **no market audit** |
| **us** | the from-scratch agent, `src/scratch/`, config `SCRATCH_PARAMS='PLANT_RAMP=0;MOVE_WEIGHT=0'` | `diag-replays/v0-us`, **96 games = 12 public agents × 8 seeds**, W **0** – L **96** | audit-backed |
| **us (PA 2 only)** | same config, one matchup, many seeds — the seed-variance ladder | `diag-replays/v0-pa2`, **24 games**, and `diag-replays/m-A0`, 12 games | audit-backed |

Three rules this document obeys:

1. **No cross-game means.** Every per-game figure is a median or a `p10 p25 p50 p75 p90` ladder; win
   counts are per *episode*, never per seat-row. Per-day tables are normalised
   **per-opponent median → median across opponents**, so one heavily-sampled opponent cannot outvote
   another.
2. **The audit asymmetry is stated.** Leaderboard replays carry no market audit, so for DSM
   `sell_revenue_total`, `revenue_*`, `avg_price_*`, `discarded_units_total` and `land_cost_total` are
   **0 or modelled** and are not usable. Where a revenue shape is compared it is compared as a
   *shape*; per-day revenue for DSM is the sign-split of the money delta (it undercounts any step that
   both buys and sells).
3. **The shop draw is a function of our own play.** `_spawn_weeds` draws the RNG once per empty tile
   of *both* farms and the day's shop unlock is drawn from that same stream immediately afterwards,
   so any change to our planting moves which shops appear (measured previously: 18/18 games differed
   between two arms on identical seeds). Every shop-conditioned row below carries its shop mix.

**The arm caveat that matters.** `v0-us` spans 12 public agents, so its ladders are field ladders —
but it is still *not* DSM's ladder (61–67 distinct teams, real humans), so the two ladders are
compared as distributions, never head-to-head. `v0-pa2` is a **single-opponent** arm: its p10/p90
describe seed variance inside one matchup, not a field, and it is used only where seed variance is
the question.

> **Two harness defects this document uncovered — neither is fixed in the core harness here, and both
> are listed so the numbers below can be read correctly.**
>
> **(a) Observation↔action pairing is off by one.** A kaggle_environments step records the action that
> *produced* its observation, so the action decided from `steps[t]["observation"]` lives at
> `steps[t+1]["action"]`. Verified on a real replay: `pos[t+1] == pos[t] + action[t+1]` holds for
> **97.1 %** of moves, versus **53.3 %** for the same-index pairing. `replay_to_record` pairs them at
> the same index, so every *tile-conditioned* metric in the harness (`idle_units_ready_total`,
> `locked_steps`, `missed_harvest_eod`, `near_shed_*`, and the order↔tile coupling behind
> `land_cost`) is measured against the wrong step. Op-count and revenue aggregates are **not**
> affected — they read the action stream, and only the ~1/24 of ops at a day boundary are attributed
> to the adjacent day. `tools/labour/op_patterns.py` and `tools/labour/ready_idle.py` were corrected
> during this work and the figures here use the shifted form; the core harness was deliberately left
> alone, because changing it moves every historical CSV number and belongs in its own change with its
> own re-baseline.
>
> **(b) `land_cost_total` is not trustworthy on either arm.** It reports **$10,000 at p10…p90** for us
> against a real ceiling of **$7,000** (`LAND_PRICES = [1000, 2000, 4000]`): the agent re-issues
> `BUY_LAND` every turn until it fills, and the derivation charges the `min(n, 3)`-clamped price again
> for each re-issue. The money ledger settles it — start 3,000 + `sell_revenue_total` 49,941 − seed
> 9,180 − hire 7,029 − **7,000** = 29,732 ≈ the observed final bank 29,782, whereas 10,000 misses by
> 3,000. (`docs/dsm_gap.md` already flags this field as unusable for DSM's LB rows at up to $88,000;
> it turns out to be unreliable for our arm too.) **Do not quote it.**

---

## 1. Headline

| metric | **us** (n=96, 12 opponents) | **DSM** (n=123) | gap |
|---|---|---|---|
| record | **0 W – 96 L (0 %)** | 118 W – 5 L (95.9 %) | — |
| median margin | **−$127,987** | **+$14,144** | — |
| **normalised margin** (median of per-opponent medians — the apples-to-apples one) | **−$127,655** | **+$20,351** | — |
| worst game | **−$173,160** | **−$3,570** | — |
| games lost by >$4k | **100 %** | **0.0 %** | — |
| closest game | **−$101,586** (a loss) | worst game −$3,570 | — |
| our final bank | p10 $13,011 · p50 **$29,782** · p90 $38,605 | p10 $88k · p50 **$110,708** · p90 $139k | −73 % |
| opponent final bank | p10 $140,985 · p50 **$150,406** · p90 $172,092 | — | — |
| worker-turns / season | 7,306 | 7,527 | **−2.9 %** |
| **productive acts / game** | 1,550 | **4,061** | **−62 %** |
| **moves / game** | **4,217** | 3,128 | **+35 %** |
| idle (PASS) units / season | **1,112** | **260** | **+328 %** |
| cows / sheep / geese at d16 | **0 / 0 / 0** | 7.2 / 8.0 / 7.4 | **absent** |
| animals fed / season | **0** | 369 | **absent** |
| plants fertilized / season | **0** | 238 | **absent** |
| units sold / season | — | 2,080 | — |

Act/move counts are from `op_patterns` (ours n=96, DSM n=12); season totals from `day_gap`
(ours n=96, DSM n=123).

**Every single one of the 96 games is a loss, and it is not a near-run thing.** Our *best* game
across the whole arm is **$39,233** — still below the opponent's *worst decile* ($140,985) — and the
single closest game we played was lost by **$101,586**. No opponent is close: our per-opponent
medians run $25,055 – $31,182 against theirs of $130k–$172k. This is not a tuning problem; it is a
**missing-farm** problem.

Note the seed-pool asymmetry while reading the two bank columns: the public agents' own median bank
on these seeds is **$150,406**, i.e. *higher* than DSM's median of $110,708. These are not DSM's
worlds, and the public field here is not weak. The comparison is therefore distributional (our farm
shape versus his farm shape), never head-to-head — which is exactly why §0 states the provenance
rules before any table.

> **The thesis in one sentence.** We hire the same crew as DSM and spend almost the same number of
> worker-turns (−2.9 %), but we perform **60 % fewer productive acts** with them and make **46 % more
> moves**, because two whole modalities are missing (there are **zero** animals, **zero** fertilizing)
> and the labour we do have is not arranged the way his is.

### 1.1 The defect ledger

`dsm_profile` GUARDS, median per game (ours n=96, DSM n=122; per-opponent normalised). This is the
per-defect form of the headline, and it is where the *shape* of the loss lives:

| defect | **ours** | **DSM** | ratio | read it as |
|---|---|---|---|---|
| `harvests` | **167** | **597** | **0.28×** | the throughput gap — we bring in a third of the crop |
| `plants_died` | **123** | 19 | **6.5×** | **we lose 6.5× as many plants as he does while planting a third as many** |
| `missed_harvest_eod` | **59** | 5 | **12×** | ready produce left standing at the bell |
| `weeds_peak` | **22** (p90 **58**) | 10 (p90 16) | 2.2× | our weeds are neglect; his are retirement (§4.1) |
| `locked_steps` | **252** | 106 | 2.4× | worker-turns spent on land we do not own |
| `idle_share_pct` | **15.2** | 3.5 | 4.3× | — |
| `idle_units_ready_total` | **26** | **0** | ∞ | PASSing while standing on ready produce; his p90 is **1** |
| `unwatered_eod` | 616 | 574 | 1.07× | ≈ level — we are not careless waterers |
| `stranded_at_bell` | **$510** | $45 | 11× | sellable stock that died in the shed |
| `shed_overflow_days` | 0 (p90 1) | 2 (p90 5) | — | **ours is better** — our shed never fills |
| `floor_sales` | 0 (p90 2) | 10 (p90 36) | — | **ours is better** — see §4.4, this is a consequence of scale, not skill |
| `animal_escapes` | 0 | 10 | — | his are the deliberate release; ours are trivially 0 (no herd) |
| `feed_surplus` | 150 | 191 | — | both positive — we are not over-feeding, because we do not feed |

The `harvests` row is the whole document in one line. Note also the pairing of rows 2 and 8: **we lose
6.5× the plants and leave 12× the harvest on the table while being no worse at watering** — so this
is not carelessness, it is the *scheduling* defects of §3.4–§3.5.

And note the two rows where we "win": `shed_overflow_days` and `floor_sales` are both **better than
DSM's**, and both are *artefacts of being small*. A shed that never reaches 80 units cannot overflow;
a farm that sells 632 units cannot floor the market. §4.4 and §5 (C1/C6) show why these two will
**invert the moment the farm is scaled** — which is exactly why they are watchlist items in the
roadmap rather than achievements.

The revenue consequence, by band (`day_gap`, normalised per-opponent then medianed):

| band | our revenue | DSM revenue | gap | share | our idle units | DSM idle units |
|---|---|---|---|---|---|---|
| **d0–5** | 801 | 1,717 | −916 | **−53.3 %** | 452 | 239 |
| **d6–11** | 7,531 | 18,511 | −10,980 | **−59.3 %** | 324 | **21** |
| **d12–17** | 3,613 | 36,728 | −33,115 | **−90.2 %** | 119 | **0** |
| **d18–23** | 12,353 | 31,728 | −19,375 | −61.1 % | 112 | **0** |
| **d24–29** | 19,741 | 36,405 | −16,664 | −45.8 % | 105 | **0** |
| **total** | **44,039** | **125,089** | **−81,050** | **−64.8 %** | **1,112** | **260** |

These are the **96-game, 12-opponent** figures. They are within a few percent of the same table run on
the 12-game single-opponent arm, which is the useful part: the phase shape is not an artefact of one
matchup. (`day_gap` normalises per-opponent median → median across opponents, so what changes between
the arms is the number of opponents, not the weight of any one.)

Two things stand out before any detail:

- **The midgame is the wound.** d12–17 is the worst band by a wide margin (−90.2 %, and it holds
  whole days at $0), and it is where DSM earns a quarter of his season.
- **Our idle is not endgame idle, it is opening idle.** 452 of our 1,112 idle units are in d0–5 and
  324 in d6–11. DSM's idle is *260 for the entire season*, and from d12 onward it is **literally
  zero**.

---

## 2. Opening (d0–d5) — we do not commit

### 2.1 The day-by-day shape

`day_gap` per-day medians, ours / DSM:

| day | unit-turns | idle | idle % | watered | fed | max shed | end shed | revenue |
|---|---|---|---|---|---|---|---|---|
| 0 | 116 / 112 | 27 / 9 | 23 / **8** | 25 / 15 | **0 / 4** | **0 / 8** | 0 / 0 | 0 / 28 |
| 2 | 162 / 162 | **78 / 38** | **48 / 24** | 25 / 19 | **0 / 3** | 0 / 5 | 0 / 0 | 0 / 399 |
| 4 | 162 / 162 | 7 / 65 | 4 / 41 | 38 / 11 | **0 / 5** | 0 / 12 | **0 / 4** | 0 / 470 |
| 6 | 162 / 208 | **84 / 2** | **52 / 1** | 23 / 23 | **0 / 6** | 24 / 10 | 15 / 0 | 224 / 1,968 |

Three separate things are happening at once.

**(a) We idle hardest exactly when the farm is emptiest.** Day 2 is 48 % idle against DSM's 24 %;
day 6 is **52 % idle against his 1 %**. `missed_work` localises it: idle-on-work spikes at
**d1 = 46, d5 = 51, d6 = 73, d9 = 31** turns while WATER and HARVEST work is pending. Day 4 is the
one day we beat him (4 % vs 41 %) and it is not a compliment — his 4 hands are waiting on animals
that are not yet producing; ours are waiting on nothing at all.

**(b) There are no animals, from day 0.** `herd_hold`, mean animals per game:

| day | DSM COW | DSM SHEEP | DSM GOOSE | DSM feed | **ours (all)** |
|---|---|---|---|---|---|
| 1 | 2.0 | 3.0 | 0.0 | 5.0 | **0** |
| 4 | 2.0 | 3.0 | 0.0 | 5.5 | **0** |
| 7 | 5.8 | 4.5 | 1.8 | 13.1 | **0** |
| 10 | 7.5 | 6.0 | 5.3 | 19.3 | **0** |
| 16 | 7.2 | 8.0 | 7.4 | 19.2 | **0** |

DSM's opening bank is spent on day 0 (2 COW + 3 SHEEP + 10 structures + 9 WHEAT + 6 MELON, ending
the day at **$6**). Geese first yield on day 4, sheep on day 6, cows on day 8 — which is why his
d6–11 band is $18,511 and ours is $7,519.

**(c) Land arrives late, and everything downstream is capped by it.** `dsm_profile` quadrant unlock
day (median):

| quadrant | **ours** | **DSM** |
|---|---|---|
| NE | **d10** | d6 |
| SW | **d11** | d9 |
| SE | **d21** | d10 |

We do eventually buy all four (12/12 games), so this is not a decision failure — it is a 4–11 day
*timing* failure. For ten days we farm 40 tiles where DSM farms 100, and that cap is what makes the
wheat curve in §3.2 look the way it does.

### 2.2 The movement signature of the opening

`movement`, movement as a share of unit-turns by hour of day:

| | h0 | h1 | h2 | h3 | h4 | h5 | h6 | h7 |
|---|---|---|---|---|---|---|---|---|
| **ours** | 47 % | **70 %** | **92 %** | **93 %** | 85 % | 82 % | 71 % | 69 % |
| **DSM** | 53 % | **18 %** | 56 % | 46 % | 51 % | 37 % | 41 % | 34 % |

Our first four hours of **every single day** are 70–93 % pure travel. His h1 is 18 %. The reason is
structural and it is the same reason as (b). At every day boundary `_end_of_day` resets
`farm["farmer"] = _default_spawn()` — the first NW **shed-access** tile, `(4,4)` — wipes `hands`, and
clears every carried inventory; each re-hired hand enters on a free shed-access tile
(`_spawn_hand`). **So the shed is the daily origin of every unit in the game, for both players.**
DSM's animal ring is shed-adjacent, so his hands begin work on the first or second turn; ours walk
3–6 tiles to crops before the first act — visible in the raw trace in §3.5, where our farmer starts
at `h00@4,4` and does not perform her first act until `h07@3,0`, six moves later. `movement`
measures the whole-game consequence over the full 96-game arm versus 12 leaderboard replays:

| metric | **ours** | **DSM** |
|---|---|---|
| movement share | **60.5 %** | 41.9 % |
| PASS share | 17.3 % | 3.8 % |
| productive share | **22.2 %** | **54.3 %** |
| moves per act | **2.72** | **0.77** |
| moves that are empty-handed | **87 %** | 33 % |

### 2.3 The op mix: 5 productive ops against 12

`dsm_profile` unit op mix, share of all unit-turns:

| ours | | DSM (per `dsm_v1.md` §11) | |
|---|---|---|---|
| WEST | 23 % | movement (all) | 41.6 % |
| EAST | 18 % | WATER | 16.9 % |
| **PASS** | **17 %** | HARVEST | 7.8 % |
| WATER | 14 % | COLLECT_FERTILIZER | 6.5 % |
| SOUTH | 10 % | CARE | 5.5 % |
| NORTH | 9 % | FEED | 5.5 % |
| PLANT | 4 % | PLANT | 3.8 % |
| **HARVEST** | **2 %** | FERTILIZE | 3.0 % |
| DIG | 2 % | PICKUP | 2.6 % |
| DROP | 1 % | PLACE | 1.3 % |
| — | | DROP | 0.88 % |
| — | | DIG | 0.58 % |
| — | | BUILD | 0.33 % |

Five op types against twelve. FEED / CARE / COLLECT_FERTILIZER / FERTILIZE / PLACE / BUILD / PICKUP
are **exactly 0** for us all season. Note also `PICKUP = 0`: our fertilizer loop is dead at the
source, because with no animals there is no fertilizer to pick up (`crop_plan.jobs` only emits a
fertilizer `PICKUP` when the shed actually holds some).

---

## fin: Where the opening actually stands now — our agent vs the #1's entry, measured

Both arms through the **same extractor and aggregation**. Ours live, `--pa 1-12 --batch 4`
(12 opponents x 4 seeds = **48 games**); his entry by auditing his own replays
(`--replay-dir replays/DSM/v1 --ref-max 20 --seat auto`, **20 games**). Targets are his
*measured* reduction, never the transcribed table.

| d0-d5 metric | ours | #1 | ratio | |
|---|---|---|---|---|
| **CARE ops** | **23.0** | **34.0** | **0.68** | BAD (his 34 includes no-ops; effective 30) |
| opening cash committed | 0.82 | 1.00 | 0.82 | by design |
| `open_dist` | 2.0 | 0.0 | - | accepted, see the cost table |
| animals on board | 4.0 | 5.0 | 0.80 | WARN - the melon trade, see below |
| FEED ops | 22.0 | 27.0 | 0.81 | WARN (same cause) |
| empty owned tiles | 3.5 | 0.0 | - | accepted |
| idle share % | 30.9 | 26.4 | 1.17 | ok |
| animal structures | 4.0 | 5.0 | 0.80 | ok |
| MELON tiles | 9.0 | 10.0 | **0.90** | ok |
| PLANT ops | 29.0 | 30.0 | **0.97** | ok |
| WATER ops | 73.0 | 74.0 | **0.99** | ok |
| STRAWBERRY tiles | 10.0 | 10.0 | **1.00** | ok |
| owned tiles / quadrants / hands | 25 / 1 / 6 | 25 / 1 / 6 | **1.00** | ok |
| shops unlocked | 1 | 1 | 1.00 | ok (latent) |

**The crop block is intact**, and the herd/cash/labour half is now at
parity: `animals 5/5`, `structures 5/5`, `STRAWBERRY 10/10`, `FEED 26/27`, cash committed
**0.97**, idle **20.0 vs 26.5** (we idle *less*). The open items are all on the crop side
(`MELON 6/10`, `PLANT 25/30`, `WATER 64/74`), and they are the *price* of the herd fix below., and the eleven structural
things the #1 fixes at d0 — herd, housing, land, crew, the 20-tile crop block — are **exact**.

**The opening is near-deterministic.** With the new `--spread` column, every metric has
`min == max` except `idle share %` (26.7-28.9). Our d5 state is identical in 48/48 games; his
is identical in 40/40 (his own spread: CARE 33-37, empty tiles 0-0.5). So `--batch 1` was
never under-sampling the opening — there is nothing to sample. Use `--spread` at `--batch 4`
for d6+, where the midgame does diverge.

**The cost, stated plainly.** Three independent measurements now show the #1's opening
structure is **anti-correlated with our season margin**:

| lever | structure | season (`dterm`) |
|---|---|---|
| `WHEAT_LANDS_DAY=2` (helps close `open_dist`) | better | **-$15,452** (0/8, p=0.005) |
| `P_BUILD` 45 -> 95 (unblocks the herd) | better | **-$3,328** (0/24, p=0.000) |
| `BUILD_PER_TURN` 2 -> 3 (animals 5/5) | better | **-$6,591** (0/12, p=0.001) |
| season-optimal settings | `open_dist` 8, STRAWBERRY 6 | baseline |

The structure-optimal defaults are shipped (`P_BUILD=95`, `BUILD_PER_TURN=3`) because the
phase-1 gaps were the explicit target; one `SCRATCH_PARAMS` line reverses the cost.
**`open_dist` 1 is recorded as met-but-not-free, not as a win.** `empty owned tiles`
(3.5 vs 0) is the same trade in miniature.

---

## 3. Midgame (d6–d17) — the calendar hole and the empty modality

### 3.1 The d12–17 cliff

| day | our revenue | DSM revenue |
|---|---|---|
| 10 | 2,919 | 7,283 |
| 12 | 1,950 | 3,971 |
| **14** | **0** | **7,388** |
| **16** | **529** | **7,752** |
| **18** | **178** | **6,767** |
| 20 | 238 | 5,933 |
| 22 | 2,804 | 5,307 |

From d12 to d21 we are **revenue-dead** — six consecutive days averaging $305 against DSM's $6,700 —
and then we catch up violently at d22–27. This is not a market problem; it is a *supply* problem. The
`day_gap` cumulative curve breaks away at exactly d12 and never recovers.

### 3.2 Cause 1 — the wheat hole (and the fully decoupled herd)

`crop_demand`, WHEAT tiles per day:

| day | 4 | 6 | 8 | 10 | 12 | 14 | 16 | 18 | 20 | 22 | 24 | 26 | 28 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **ours** | 15 | **5** | **5** | **4** | 23 | 26 | 20 | 19 | 14 | 24 | 31 | 29 | **5** |
| **DSM** | 0 | 0 | 10 | 20 | 31 | 25 | 22 | 22 | 25 | 25 | 31 | 27 | 25 |

We plant 15 wheat on day 0 (good), harvest it around d4–5, and then **do not replant** — five tiles
through d6–10, which is precisely the band where DSM is growing his herd and we have $0 of animal
revenue. Then we over-correct to 23–31 for the rest of the season.

The flow table makes the modality decoupling explicit (`dsm_profile`, per game):

| | bought | fed | sold | buy/feed |
|---|---|---|---|---|
| **ours** | **0** | **0** | 259 | 0.00 |
| **DSM** | 186 | **380** | 591 | 0.49 |

We grow wheat purely to sell it. DSM grows 1.5× more and feeds 380 units of it to animals. Our crop
modality and our herd modality do not interact at all — which is why turning the herd on later
(§7) immediately created a **negative feed balance**: see coupling **C2**.

### 3.3 Cause 2 — strawberry arrives in waves, not a ramp

`dsm_profile` CROPS, mean tiles by day:

| day | WHEAT | CARROT | TOMATO | STRAWBERRY | MELON | max single-crop share |
|---|---|---|---|---|---|---|
| 6 | 5.0 | 0.0 | 0.0 | 10.0 | 10.0 | 40.0 % |
| 9 | 5.0 | 0.0 | 0.0 | 10.0 | 10.0 | 40.0 % |
| 12 | 24.1 | 0.0 | 13.2 | **27.5** | 0.0 | 42.4 % |
| 15 | 28.0 | 0.0 | 15.9 | 29.9 | 0.0 | 40.5 % |

`crop_demand` shows why, on the same 96-game arm — tiles per day for STRAWBERRY and WHEAT:

| day | 4 | 6 | 8 | 10 | 12 | 14 | 16 | 18 | 20 | 22 | 24 | 26 | 28 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **ours** STRAWB | **0** | 10 | 10 | 10 | **27** | 29 | 30 | 30 | 30 | 21 | 20 | 20 | 11 |
| **DSM** STRAWB | 10 | 10 | 19 | 21 | 25 | 30 | **35** | 34 | 24 | 24 | 15 | 12 | 9 |
| **ours** WHEAT | 15 | **5** | **5** | **4** | **23** | 26 | 20 | 19 | 14 | 24 | 31 | 29 | **5** |
| **DSM** WHEAT | 0 | 0 | 10 | 20 | 31 | 25 | 22 | 22 | 25 | 25 | 31 | 27 | 25 |

Ours moves in **steps** — strawberry 0 → 10 → 10 → 10 → **27** (a **+17 tile jump in two days**),
wheat 15 → 5 → 5 → 4 → **23** (a −10 collapse then a +19 spike). DSM's largest two-day move on either
crop is **+9**. Strawberry's `first_yield_day` is **10**, so the tiles that appear on d12 cannot fruit
before d22 — long after our melon (planted d0–2) has finished at d11, and squarely inside the hole.

This is the mechanical link the whole midgame hangs on:

> **a planting wave is a future revenue gap, and the gap is exactly `first_yield_day` wide.**

DSM's curve is smooth for the same reason his seed purchases are spread: 191 WHEAT / 49 STRAWBERRY /
48 CARROT / 23 MELON / 18 TOMATO seeds sown steadily across each crop's whole viable window
(`dsm_v1.md` §5). We instead fill each crop's tile target as fast as we have hands.

`crop_demand`'s rotation summary also sizes the *scale* gap crop by crop (peak standing tiles,
same tool, same arm):

| crop | our peak tiles | DSM peak tiles | ratio |
|---|---|---|---|
| WHEAT | 36 | 45 | 0.80× |
| STRAWBERRY | 33 | 56 | 0.59× |
| CARROT | 27 | 41 | 0.66× |
| TOMATO | 19 | 33 | 0.58× |
| MELON | 10 | 10 | **1.00×** |

So it is not only *when* we plant; it is *how much* — **58–80 % of DSM's peak on every crop except
melon**, the one crop he deliberately abandons by day 11. (`dsm_v1.md` §5 quotes a strawberry peak of
~30 against this tool's 56; the two use different tile definitions, so read the **ratio** here, which
is tool-internal, and not the absolute DSM level.)

### 3.4 Cause 3 — the labour is there, the acts are not

This is the sharpest single measurement in the document, because the inputs are identical:

| | **ours** | **DSM** |
|---|---|---|
| worker-turns / season | 7,306 | 7,527 (**−2.9 %**) |
| productive acts / game | 1,550 | **4,061** (−62 %) |
| moves / game | **4,217** | 3,128 (+35 %) |
| idle units / season | **1,112** | **260** (+328 %) |

\* `op_patterns` (ours n=96, DSM n=12) and `day_gap`.

We are not under-hiring. We are **wasting an identical crew**. `missed_work` (work that was pending
for a full day and never addressed) is remarkably stable across the whole arm — per game it runs
**WATER 1,453–1,598 · FERT 526–579 · HARVEST 355–499 · DIG 187–264** — i.e. the farm leaves a
season's worth of watering undone *every single game*. `idle_pool` classifies where the idle turns
go: **780/game movement-needed, 215/game sitting on a tile that needed WATER, 25/game sitting on a
tile that needed HARVEST, 80/game truly idle.**

`leverage` closes the obvious escape hatch — "maybe the idling hand was about to do something
valuable, so rerouting it would forfeit more than it gains":

> over the full arm, **107,338 idle-hand events (1,118/game); 100 % of them are LOW-leverage
> (forfeit value 0)**. Nothing valuable is being protected. Rerouting an idle hand onto pending work
> is free.

`ready_idle` prices what is being left on the ground: **632 PASS-on-READY events per game, leaving
1,510 units worth $166,199 standing on the tile**, against DSM's **34.8 events / 42.6 units /
$8,427** — an **18× frequency and 20× value** gap, all of it on crops (`...crop` 632 vs 30; the animal
and fertilizer columns are 0 for us because we have neither). The harness's own tile-conditioned
counter independently agrees (`idle_units_ready_total`): ours **26** (p10–p90 21–29) vs DSM **0**.
It also counts **243 LOCKED turns per game against DSM's 106** — the same 2.4× `locked_steps` gap
that §1.1 reports, measured a second way.

### 3.5 The mechanism: our turns are not arranged like his

Aggregates say "we walk more". They do not say *how*. `op_patterns` measures the arrangement, and
the answer is that DSM's hand does the **whole stack of ops a tile offers before stepping next
door**, and ours does not:

| metric | **ours** (n=96) | **DSM** (n=12) |
|---|---|---|
| mean act-run length (consecutive acts, no MOVE between) | **1.32** | **1.92** |
| acts that are a run of exactly 1 (isolated) | **59.4 %** | 23.6 % |
| acts inside a run of ≥2 | 40.6 % | **76.4 %** |
| acts inside a run of ≥4 | 10.6 % | **27.9 %** |
| what follows a productive act → another **ACT** | **24.2 %** | **48.4 %** |
| what follows a productive act → a **MOVE** | **70.6 %** | 47.2 % |
| productive acts / game | **1,550** | **4,061** |
| moves / game | **4,217** | 3,128 |

Per-act-type chaining (share of occurrences immediately followed by another act):

| op | ours (n) | DSM (n) | |
|---|---|---|---|
| PLANT | 75.3 % (23,945) | **99.3 %** (3,491) | |
| HARVEST | 41.9 % (14,520) | 53.1 % (7,103) | |
| DIG | 30.7 % (12,601) | **81.7 %** (531) | |
| **WATER** | **8.2 %** (93,445) | 20.8 % (15,445) | our single biggest op is our least chained |
| DROP | 7.6 % (4,253) | 49.8 % (818) | |
| FEED | — (0) | **89.6 %** (4,637) | |
| FERTILIZE | — (0) | 86.1 % (2,683) | |
| CARE | — (0) | 63.2 % (4,671) | |
| COLLECT_FERTILIZER | — (0) | 20.4 % (5,662) | |

And here is the same fact as a raw trace — the artifact behind every claim above. **Day 12, the
farmer (unit 0) in each arm, same seed and opponent** (`op_patterns --day 12 --unit 0`):

```
---- ours, day 12, farmer (24 turns, 7 acts, 17 moves) ----
h00@4,4:WATER:STRAWBERRY  h01@4,4:WEST  h02@3,4:NORTH  h03@3,3:NORTH
h04@3,2:NORTH  h05@3,1:NORTH  h06@3,0:WATER:STRAWBERRY  h07@3,0:WEST
h08@2,0:WATER:STRAWBERRY  h09@2,0:WEST  h10@1,0:WATER:STRAWBERRY  h11@1,0:WEST
h12@0,0:WATER:STRAWBERRY  h13@0,0:EAST  h14@1,0:EAST  h15@2,0:EAST
h16@3,0:EAST  h17@4,0:EAST  h18@5,0:WATER:WHEAT  h19@5,0:WEST
h20@4,0:WEST  h21@3,0:WEST  h22@2,0:SOUTH  h23@2,1:HARVEST:WHEAT

---- dsm, day 12, farmer (24 turns, 16 acts, 8 moves) ----
h00@4,4:NORTH   h01@4,3:HARVEST  h02@4,3:SOUTH  h03@4,4:DROP
h04@4,4:PICKUP:WHEAT  h05@4,4:WEST  h06@3,4:FEED  h07@3,4:CARE
h08@3,4:COLLECT_FERTILIZER  h09@3,4:WEST  h10@2,4:FEED  h11@2,4:CARE
h12@2,4:WEST    h13@1,4:SOUTH  h14@1,5:WATER  h15@1,5:HARVEST
h16@1,5:PLANT:WHEAT  h17@1,5:WATER  h18@1,5:WEST  h19@0,5:FERTILIZE
h20@0,5:WATER  h21@0,5:NORTH  h22@0,4:HARVEST  h23@0,4:WATER
```

Read those side by side and the gap is not "movement efficiency". It is **a different unit of work**:

- Our farmer makes **7 acts in 24 turns (17 moves)** — six isolated WATERS and one HARVEST, each at
  a different tile, each reached by 3–5 moves. She never performs two ops at the same tile. Every act
  is a round trip, and she ends the day parked at `(2,1)` with a stray harvest.
- DSM's farmer makes **16 acts in 24 turns (8 moves)**. Watch what he does with a single animal tile:
  `NORTH → HARVEST (4,3) → SOUTH → DROP → PICKUP:WHEAT` at the shed-adjacent `(4,4)` — harvest,
  walk back, empty the hands **and** reload feed in the same visit — then `WEST` and
  `FEED → CARE → COLLECT_FERTILIZER` at `(3,4)`, `WEST` and `FEED → CARE` at `(2,4)`. Only then does he
  turn to crops, and there he stacks those too: `WATER → HARVEST → PLANT:WHEAT → WATER` at `(1,5)`
  (water, harvest, immediately replant, water the new seed — four acts, no move), then
  `FERTILIZE → WATER` at `(0,5)`, then `NORTH` and `HARVEST → WATER` at `(0,4)`.

That is the entire labour gap in one day of two workers doing the same job: **same 24 turns, 7 acts
versus 16**, and the difference is not speed — it is that his turnaround unit is *a tile* and ours is
*an act*.

The mechanism in our code is `scheduler._pick`, which ranks candidate jobs by
`(-priority, distance)`: **priority dominates completely and distance is only a tie-break.** So a
unit standing on a tile with three unfinished ops under its feet will walk across the farm for a
higher-priority job elsewhere, and it will never "finish the tile". Secondarily, `layout.slice_partition`
gives each worker a contiguous band and `_pick`'s first pass refuses `_FIELD_OPS` outside that band,
so a worker whose band has any field work will never leave it for a ripening HARVEST in another
band — which is where the 487 missed harvests come from.

---

## 4. Endgame (d18–d29) — weeds we did not plan, and a shed that does not rotate

### 4.1 Weeds: ours are neglect, his are a plan

| metric (season sum of per-day medians) | **ours** | **DSM** |
|---|---|---|
| `weeds_max` | **190** | **39** |
| `plants_died` /game | 118–159 | 19 (14–28) |
| `missed_work` DIG pending /game | **190** | — |
| DIG share of ops | 2 % | 0.58 % |

DSM's watering:feeding:care:fertilizing collapses 63 → 24, 21 → 1, 21 → 1, 17 → 1 across d26–29 and
his weeds climb 0 → 10. That is a **retirement**: he stops investing in ground that cannot pay back
before the bell and converts the freed turns into harvesting and selling. Ours is the opposite
signature — `dsm_v1.md` puts it well about an earlier agent: *"lower weeds because it keeps working
retired ground… the same 'busy but not productive' signature as `locked_steps`."*

### 4.2 The shed: full-and-rotating versus spike-and-hold

`dsm_profile` SHED + CARRIED:

| | **ours** p10 → p90 | **DSM** p10 → p90 |
|---|---|---|
| peak SHED | 67 → **100** (p50 86) | **100 → 100** |
| end-of-day SHED | **12.9 → 18.8** | 4.4 → 8.3 |
| end-of-day CARRIED | 9.1 → 15.2 | 50.2 → 56.3 |
| peak SYSTEM (shed + carried) | 69 → 129 | **129 → 150** |

DSM's shed **hits the 100 cap in every game at every percentile** and drains back to ~6 by day end:
that is what "full but rotating" means, and it is why his hands are always carrying (50–56 units) —
the shed is a transit buffer, not storage. Ours spikes to 67–100 (p50 86) and then *holds 13–19 units
overnight*. And what we hold is not a rotating basket:

> `dsm_profile` "top items at day end" — **ours: `WHEAT=100 %` on every sampled day.**
> DSM's end-of-day content (per `dsm_v1.md` §7, unit-days/game): WHEAT 53.2, STRAWBERRY 34.9,
> MILK 29.6, WOOL 24.6, EGG 21.2, CARROT 10.9, TOMATO 9.4, FERTILIZER 3.4, MELON 0.7.

One product overnight versus nine. This is the single clearest readout that a modality is missing:
our shed's composition *is* our revenue mix *is* our crop list.

**What the hour-23 force-drop actually throws away** (`discards`, modelled identically for both arms
from the force-drop, and calibrated in-line against our audit — the model reproduces our audit to
**−1 %**, 4.39 modelled vs 4.43 actual per game):

| | units/game | composition |
|---|---|---|
| **ours** | **4.4** | WHEAT **56 %** · STRAWBERRY **38 %** · TOMATO 5.5 % |
| **DSM** | **15.8** | WHEAT 29.5 · STRAWBERRY 14.7 · CARROT 12.1 · TOMATO 11.6 · EGG 11.6 · FERTILIZER 11.1 · WOOL 8.4 · MILK 1.1 |

DSM discards **3.6× more than we do, and spreads it over eight products**; we discard little, but
**94 % of it is the two lines we can least afford to lose** — wheat is the feed reserve and strawberry
is our largest revenue line. And our discards are concentrated, not routine: `dsm_profile`'s audit
ladder is `0` at p50 and p75 with `29` at p90, i.e. they happen in roughly a tenth of games, which is
the signature of a spike (a harvest landing on a near-full shed) rather than a steady leak. This is
coupling **C1**: the moment the herd fills the shed, the composition of those discards becomes a
first-order decision rather than a rounding error.

### 4.3 Revenue concentration, and the volume behind it

`dsm_profile` REVENUE MIX (median per-game share), ours n=96 vs DSM's season mix:

| product | **ours** | **DSM** | base / above-curve |
|---|---|---|---|
| STRAWBERRY | **40.4 %** | 21.1 % | $120, `linear` t=1.6 → **\$1 at I0+62** |
| MELON | **24.7 %** | 8.1 % | $250, `sq` t=3.6 → \$1 at I0+158 |
| WHEAT | 19.1 % | 13.0 % | $25, `log` → never floors |
| CARROT | 10.9 % | 5.2 % | $35, `sqrt` t=0.7 → \$1 at I0+842 |
| TOMATO | 9.3 % | 4.6 % | $60, `sqrt` t=0.6 → \$1 at I0+529 |
| MILK / WOOL / EGG / FERTILIZER | **0 % / 0 % / 0 % / 0 %** | 11.9 / 9.1 / 6.3 / 9.2 % | — |

DSM's rule is *"diversify revenue, nine lines, none above 22 %"*. We are a **five-line farm with 65 %
of it in the two most fragile curves in the game**, and four lines at exactly zero. Adding the herd
does not merely add revenue; it is what makes the *mix* legal.

But the more useful table is the volume behind those shares — `dsm_profile` "selling per game"
(ours audit-backed, DSM reconstructed from the action stream):

| product | our units | our px@sell | DSM units | DSM px@sell | volume ratio | price verdict |
|---|---|---|---|---|---|---|
| STRAWBERRY | 116 | **$190.7** | 223 | $135.6 | 0.52× | **we beat him by +$55/unit** |
| WHEAT | 294 | $33.6 | 562 | $34.6 | 0.52× | level |
| CARROT | 98 | $47.8 | 190 | $39.8 | 0.52× | we beat him by +$8 |
| TOMATO | 64 | $74.1 | 117 | $66.6 | 0.55× | we beat him by +$7.5 |
| MELON | 60 | $175.8 | 60 | $208.7 | **1.00×** | he beats us by −$33 |
| EGG / MILK / WOOL / FERTILIZER | **0 / 0 / 0 / 0** | — | 207 / 191 / 104 / 266 | $46.3 / $90.6 / $128.0 / $52.1 | **0.00×** | **absent** |
| **total** | **632** | | **1,920** | | **0.33×** | |

**This reframes the market gap entirely.** We move **one third** of DSM's volume and, on four of the
five lines we actually have, we get a **better or equal unit price than he does**. Our marketing is
not the problem; our *supply* is. (MELON is the exception and is worth a look later — we sell the same
60 units at $176 against his $208.7, which is a timing difference, not a volume one.)

### 4.4 The market ceiling is set past the cliff — a latent bug, not yet a realised one

`sell_policy._sellable` uses `CEILING = 100`, i.e. it sells STRAWBERRY/MILK/WOOL while the shared
inventory is below `I0 + 100`. Evaluating the engine's own `market_price` on `MARKET_PARAMS`:

| product | above-curve | price at `I0` | at `I0+50` | **at `I0+100` (our stop)** | first `$1` at | our stop vs the cliff |
|---|---|---|---|---|---|---|
| STRAWBERRY | `linear`, t=1.6, T=100 | 120 | **24** | **1** | **I0+62** | **38 past the floor** ✗ |
| MILK | `linear`, t=1.6, T=122 | 160 | **55** | **1** | **I0+76** | **24 past the floor** ✗ |
| WOOL | `sq`, t=3.2, T=105 | 200 | **55** | **1** | **I0+59** | **41 past the floor** ✗ |
| MELON | `sq`, t=3.6, T=300 | 250 | 225 | 150 | I0+158 | 8 short of it ✓ |
| CARROT | `sqrt`, t=0.7, T=450 | 35 | 27 | 23 | I0+842 | far too tight |
| TOMATO | `sqrt`, t=0.6, T=200 | 60 | 42 | 35 | I0+529 | far too tight |
| WHEAT / EGG | `log` | 25 / 50 | 22 / 43 | 21 / 42 | never | fine (sell freely) |

**At the exact inventory our agent still sells at, all three knife-edge goods are already sitting on
the \$1 floor.** That is a one-constant bug — **but on the current farm it is a latent one, and saying
so matters.** Our *realised* audit floor rates (ours n=96, DSM n=122, `dsm_profile`):

| metric | our p50 | our p90 | DSM p50 | DSM p90 |
|---|---|---|---|---|
| STRAWBERRY `floor%` | **0.0** | 2.1 | 0.0 | 3.8 |
| MILK / WOOL `floor%` | — (0 units sold) | — | 0.0 / 2.4 | 8.4 / 12.7 |
| harness `floor_sales`, all products | **0** | 2 | **10** | 36 |

**We floor *less* than DSM does.** The reason is §4.3: we sell 632 units to his 1,920, and a glut we
cannot create we cannot floor. The ceiling bug is therefore not today's leak — it is the **trapdoor
under the fix**: roadmap items 1–3 exist to scale supply, and every unit of strawberry they add is a
unit sold at `I0+100` where the price is already $1. That is exactly coupling **C6**, and it is why
the ceiling belongs in the *same* change window as the scale-up, not before it and not after.

The one live demand signal we ignore is the shop. `shop_response` on the 96-game arm, with the shop
mix printed first (as the confound rule requires) — YARN_STORE 68, PIZZA_SHOP 72, ICE_CREAM_SHOP 45,
SMOOTHIE_SHOP 62, BAKERY 61, BRUNCH_SPOT 82, PET_CAFE 73, FARMERS_MARKET 73 of 96 games:

| condition | games with the buyer shop | bought | placed | herd | sold | `nosale` games |
|---|---|---|---|---|---|---|
| **WOOL ← SHEEP** (buyer `YARN_STORE`) | **68** | **0** | **0** | **0** | **0** | **68 / 68** |

DSM's clearest "call and response to demand" is `YARN_STORE → 10 sheep` (`dsm_v1.md` §4.1: 78 of his
123 games have YARN, and sheep max 10 in those versus 3 without). We see the same shop in **71 %** of
our games, buy nothing, place nothing, and sell nothing — 68 out of 68 games end with `nosale` on the
pair. This is coupling **C7** read in reverse as well: buying a herd changes our empty-tile count,
which moves the weed RNG, which changes which shops unlock — so a YARN-conditioned herd decision has
to be measured *after* it lands, never assumed from the current shop mix.

---

## 5. The coupling map — how one change propagates

This is the part that matters for sequencing. Each entry is a real dependency observed in this
repo, with the measurement that demonstrates it.

### C1 — herd count → shed capacity → hour-23 force-drop → wastage
Adding an animal adds MILK/WOOL/EGG **and** a daily FERTILIZER to a 100-unit shed, and the engine
force-drops overflow at hour 23. Throughput is capped on the other side by `MAX_ORDERS = 10` sell
orders per turn and `TRICKLE = 6` units per order.
*Measured:* our herd-on arms this session reached `discarded_units_total` **34–39/game** against 0 on
the crops-only baseline, with `shed_pressure_days` going 0 → 6. DSM absorbs the same load by pinning
peak shed at 100 and holding a 9-product basket. **Animal count, sell-order budget and shed
composition are one knob in three places.**

### C2 — wheat tiles → herd size → cash → wheat bought at retail
A wheat tile turns over ~4 units per 5 days (0.8/day); an animal eats 1/day. So the farm needs
~1.7 standing wheat tiles per animal before the next animal is affordable (DSM: 32 tiles / 19
animals).
*Measured:* when the herd was enabled earlier in this session, `feed_surplus` went to **−125 … −360**
per game (we *bought* feed), and the arm lost **$20–30 k/game while every labour defect improved**
(idle 12.9 → 7.8 %, `unwatered_eod` 626 → 183, `plants_died` 118 → 27). **The crop modality gates
the herd modality; enabling the herd first is a guaranteed loss.**

### C3 — planting date → `first_yield_day` → the d12–17 revenue hole
Strawberry's `first_yield_day` is 10. Our wave — 10 tiles flat through d6–d10, then **+17 tiles in
two days** — puts its
first fruit at d14–d21, after melon (planted d0–2) has finished at d11.
*Measured:* d12–17 revenue **−90.2 %** (−$33,115), with whole days at $0/$529/$178.
**Moving the strawberry ramp earlier also moves C1**: its first fruit then collides with the melon
harvest at d10–11, and both land in the shed on the same days.

### C4 — land-unlock day → tile supply → every crop ramp ceiling
We farm 40 tiles, not 100, for the whole of d0–d9.
*Measured:* NE d10 vs d6, SW d11 vs d9, SE d21 vs d10, and WHEAT sitting at **5 tiles through
d6–d10** against DSM's 10 → 20 → 31. **A late quadrant is not a $1,000 decision, it is the ceiling
on the wheat curve that C2 depends on.**

### C5 — plants dying → WEED tiles → DIG labour → less watering → more deaths
An unwatered plant becomes a WEED after two nights; a WEED tile then needs a DIG before it can be
replanted, and DIG is a low-priority op competing with the watering that prevents the next death.
*Measured:* `plants_died` is **123/game, 6.5× DSM's 19**, while `missed_work` reports DIG 187–264 and
WATER 1,453–1,598 pending per game; the positive feedback is visible on seed 702, where an uncapped
distance-priced kernel let a local DIG outrank a survival water 8 tiles away — the farm collapsed,
**weeds hit 58, and the day-21 $6.7 k liquidation was lost.** This is the one coupling that runs away.

### C6 — tighter sell ceiling → shed fill → C1
Tightening the knife-edge ceiling (§4.4) makes us hold stock, which fills the shed and moves us along
C1 toward the hour-23 force-drop. **Today the ceiling is set past the cliff but we are too small for it
to bite** — our `floor_sales` p50 is **0** against DSM's **10** precisely because we sell a third of
his volume (§4.3). So this is not a live leak; it is the **trapdoor under the scale-up**: every
strawberry unit roadmap items 1–3 add is a unit sold at `I0+100`, where the price is already $1. The
market fix and the scale-up belong in the *same* change window, which is why §6 sequences them
adjacently rather than putting the ceiling first.

### C7 — the shop draw is a function of our own play
`_spawn_weeds` draws the RNG once per empty tile of both farms, and the day's shop unlock is drawn
from that same stream immediately after. There is therefore **no such thing as a controlled
shop-conditioned comparison across arms** (measured previously: 18/18 games differed, and the YARN
split went 9/18 vs 15/18 between two arms on the same seeds).
*Consequence for this document:* every shop-conditioned row carries its shop mix, and no
shop-conditioned metric is used as a target.

---

## 6. Structural fix roadmap

Ordered by the size of the band it attacks and by the prerequisite edges in §5. Each item names its
target metric, its gate tool, and its watchlist. `v0-us` is the frozen reference for all of them.

> **Status after §2.11.** The old items **1 (land), 2 (wheat) and 3 (herd) are done in their
> opening form**: the d0–d5 commitment is the #1's script (5 animals, 5 structures, 10 strawberry,
> wheat base) and it is worth **+$16,596 median over 36 paired games (35/36, p=0.0000)**. That moved
> the frontier: the opening is no longer the constraint, so the old item 5 (**turn arrangement**) is
> now item 1. The evidence is structural — `idle` is 18.0 against the #1's 26.5 (we are
> labour-*saturated*), the residual `open_dist` of 5 is 4 melon + 1 strawberry tile the crew cannot
> reach at 2.65 moves per act against his 0.76, and the one column that regressed is `floor_sales`
> (+50, 36/36). **The herd's season-ramp form is measured *negative* and must stay off**
> (`HERD_BUY_UNTIL=5`; post-opening expansion costs $16,775 from an identical state).

| # | fix | attacks | target metric | gate tool | watchlist (must not regress) |
|---|---|---|---|---|---|
| **1** | **Rearrange the turns** — chain acts, finish the tile, cut the seed shuttle; price walking and let an irreversible-loss job outrank local busywork | whole season, and now the opening's own residual | **moves per act 2.65 → 0.76**; `open_dist` 5 → 0; acts/game up | `op_patterns`, `phase_map --days 0-5`, `ready_idle` | C5 (no weed spiral); `plants_died`; margin must not fall |
| 2 | **Floor-sale discipline** — the only column that regressed with §2.11 | whole season | `floor_sales` +50 → ≤0; `premium_below_base_frac` | `sell_price`, `floor_sell` | `sell_revenue_total`; C6/C1 shed pressure |
| 3 | **Wheat base → feed self-sufficiency** | d6–11 | WHEAT tiles track DSM's d6–d12 curve; `feed_surplus ≥ 0` | `crop_demand` | `shed_pressure_days` |
| 4 | **Rotate the plantings** — sow across each crop's window, no waves | **d12–17** | d12–17 revenue gap; STRAWBERRY tile curve monotone | `day_gap`, `crop_demand` | `max single-crop share ≤ ~22 %`; C3 collision with melon |
| 5 | **Market ceiling** — stop knife-edge goods at the real break (I0+~30), loosen CARROT/TOMATO | scales with 2–4 | `floor%` on MILK/WOOL/STRAWBERRY **stays <1 % while volume triples** | `sell_price`, `floor_sell` | C6/C1: `shed_pressure_days`, `stranded_at_bell` |
| 6 | ~~Land / cash timing~~ | **done in §2.11** | `open_dist` 13 → 5; NE at d6 | `phase_map --days 0-5` | — |
| 7 | ~~Enable the herd~~ / ~~Wheat base~~ as opening commitment | **done in §2.11** | 5 animals, 5 structures, idle 54.6 → 18.0 | `phase_map --days 0-5` | season ramp stays off |
| 8 | **Weed discipline** — gate `plants_died`; retire ground at the bell instead of working it | d18–29 | `plants_died` 123 → ~19; `weeds_max` 22 → ~10 | `dsm_profile`, `missed_work` | harvest timing; `stranded_at_bell` |

Sequencing note — **REVISED TWICE by measurement.** The original order assumed **wheat → herd**
with land as a cheap prerequisite. Then §2.5 said the herd was tile-blocked (at 25 tiles it lost
$15,020) and re-ordered to **land → wheat → herd**. **§2.11 overturns both**: the herd is *not*
tile-blocked, it is *ramp*-blocked. Committed on day 0 as the #1 does it — 2 COW + 3 SHEEP, fed and
cared from the opening, funded by daily fertilizer sales — and **not expanded afterwards**, the same
herd is worth **+$16,596 median (35/36, p=0.0000)**. The earlier −$15,020 and −$15,230 results were
the *season ramp* and the *crippled fixed continuation*, not the herd.

- The opening is a **coupled package**: the crop script alone is −$7,350, the herd script alone is
  unknown, the two together with `HERD_BUY_UNTIL=5` are +$16,596. Do not re-test the halves in
  isolation and conclude from them — that mistake was made three times here.
- **Post-opening herd expansion is measured negative ($16,775 from an identical state).** Revisit
  only with a specific mechanism, never by re-enabling `HERD_BUY_UNTIL=18`.
- **The new frontier is execution**, not commitment: items 1 and 2 above. `idle` is 18.0 against the
  #1's 26.5, so the farm is labour-saturated; `open_dist`'s residual 5 is tiles the crew cannot
  reach at 2.65 moves per act against his 0.76.
- The opening is **not** a 6.5 % lever in the sense §2.5 assumed. Its revenue *band* is small, but
  its *commitment shape* was worth +$16,596 — the failure mode was never the size of the band, it
  was committing the right resources in the wrong shape. Judge any further opening change with
  `phase_map --days 0-5` **and** a paired `dterm`; `open_dist` = 0 is the target, and a change that
  lowers it while `dterm` falls is still a trap.

---

## 7. The instruments — how to measure an opening that is 6.5 % of the game

The opening is a small lever with a large consequence, so it needs instruments with
enough resolution to see it. Three were added this session; all are documented in
`AGENTS.md` and `tools/readme.md`.

| tool | answers | key output |
|---|---|---|
| `tools/phases/phase_map.py --days 0-5` | **what** is structurally wrong in the opening, and which defect is the root | the DAG's BAD metrics, roots and blast radius, plus `open_dist` |
| `tools/phases/phase_map.py --dag phase1` | the opening subgraph **and its downstream reach** (the edges leaving the window) | the causal chains from d0–d5 into d6–d29 |
| `tools/phases/state_value.py` | **what is a d5 state worth**, and which d5 feature predicts the finish | `liquid` / `nav` at d5, frozen continuations (`live`/`nobuy`/`liquidate`), and an OLS of the terminal bank on the d5 state |
| `tools/phases/shadow_prices.py` | **what is one more unit** of cash / a hand / a tile / the herd worth | paired `dNAV_d5` **and** `dterm`, with sign disagreements flagged |

Plus the `--days 0-5` window itself, now on every analysis tool: `movement`,
`op_patterns`, `ready_idle`, `missed_work`, `idle_pool`, `leverage`, `sell_price`,
`discards`, `floor_sell`, `crop_demand`, `shop_response`, `day_gap`. A whole-season
aggregate buries a d0–d5 defect under 24 days of noise; with the window the opening
defects are immediate and legible.

Two bugs surfaced while wiring the window, both worth knowing about:

- `missed_work` recorded the game's final banks **inside** the day loop, so under
  `--days` they stayed `None` and the report crashed. The banks belong to the game, not
  the window — they are now captured before the guard.
- `floor_sell` printed the herd timeline at d10/d16/d29 even when those days were
  outside the window, implying "0 animals" where the truth was "not measured". Probe
  days outside the window are now omitted rather than reported as zero.

**How to use them on the opening, in order.** (1) `phase_map --days 0-5 --ref-from
replays/DSM/v1` to see the roots and `open_dist`; (2) `shadow_prices` on the candidate
perturbations, reading `dterm` and treating any `dNAV_d5 > 0, dterm < 0` row as a trap;
(3) `state_value` to confirm the new d5 state price moved and, on `--cont
live,nobuy,liquidate`, that the frozen continuations bracket it. Only then spend a
full-game A/B — the opening's own experiments have p-values that flip on sample size,
which is precisely why the d5 price exists.

---

## Appendix A — in-flight changes and their measured status

Honest record of what is already in the tree from this session's work, so nothing is re-derived or
re-tried blindly. Defaults are noted; `SCRATCH_PARAMS` can select any configuration for an A/B.

| change | default | evidence so far | status |
|---|---|---|---|
| **`SEED_BUFFER_BY_FREE`** — cap the seed buffer by the free tile count | **on** | 48 matched games: median **+$2,136**, 29/48 sign test, p=0.19. While tile-bound (`empty` = 0 through d6–d10) a held seed is cash that cannot buy land | **mildly positive, unconfirmed** |
| **structures follow owned animals** | on | a real bug: the layer built toward the *season* targets and erected **16 structures for 3 animals** on day 0, eating the held-back tiles and the crop tiles (8 planted tiles instead of 25) | **fixed** (only bites when `HERD_ENABLED`) |
| **`HERD_BUY_FROM_DAY`=0 + `ANIMAL_FEED_RESERVE_DAYS`** | on (herd off) | a day-0 animal starves on day 3 under the old `day >= 4` feed gate; feed cover is now a hard gate on the purchase | **correct by inspection** |
| **enabling the herd as the opening commitment** | **OFF** (`HERD_ENABLED=False`) | 48 matched games: median **−$15,020**, 10/48, **p=0.0001** — while idle fell 14.7 % → 2.2 % and `plants_died` 122 → 58. The herd spends $15,691 (animals + bought feed) and returns $1,369 of net revenue: **crop revenue falls $49.3k → $33k**. Tile-blocked at 25 tiles | **do not enable before land** (see §2.5, §6) |
| **`CASH_RESERVE=0`** (land as soon as affordable) | off (1,500) | 48 matched games: median **−$6,537**, 19/48, p=0.19 — buying land early spends the seed money and the crop ramp loses more than the extra tiles gain | **measured negative** |
| `MOVE_WEIGHT` / `DIST_CAP` — price walking, cap it at 2 tiles | on (30 / 2) | reduces movement 61.3 → ~55 % but *raises* PASS; uncapped (no `DIST_CAP`) caused the seed-702 weed spiral (58 weeds) | **unverified** at n≥12 |
| `Job.critical` — irreversible-loss jobs pay no walk cost | on | a large `CRITICAL_BONUS` variant was **catastrophic** (revenue $61.5 k → $28.1 k): every freshly planted tile is "at risk" for one turn, so the plant wave became globally top-priority and starved HARVEST. The "no walk cost" form is the corrected version | **unverified** |
| `PLANT_RAMP` / ramp-based `CROP_PLAN` — sow across the window | on | spreads day 0's planting wave into d1–d3 work and targets the §3.3 wave defect by construction; the `PLANT_RAMP=0` arm is the `v0-us` reference | **unverified in isolation** |
| daily feed + `FEED_EVERY_DAY` | on (herd off) | the engine pays the banked CARE bonus **only on a fed production day** and resets it otherwise, so an every-other-day feed silently halves herd output | **correct by inspection**, unverified in play |
| `WHEAT_TILES_PER_ANIMAL` (1.7) — crop gates herd size | on | implements C2 directly; at 3.0 the opening herd stayed at ~3 animals | **unverified** |
| **blanket endgame water-off at d26** | **reverted** (`RETIRE_DAY = 99`) | 16 paired games, **every seed down**; d26–29 go 0 → **56 / 67 / 96 / 96 % idle** and watering 37 → 0. DSM's water falls 63 → **24**, not → 0 | **do not re-try** as a labour switch |

## Appendix B — regenerating every table

```bash
export PYTHONPATH=.
DIR=diag-replays/v0-us          # 96-game arm; v0-pa2 is the single-opponent ladder

# the multi-opponent arm (12 opponents x 8 seeds)
SCRATCH_PARAMS='PLANT_RAMP=0;MOVE_WEIGHT=0' python -m diagnose --scratch \
    --pa 1-12 --batch 8 --seed 4362837462 --run-dir "$DIR"

# CSV-based behavioural map, per-day gap, margin
python -m tools.report.dsm_profile --compare --run-dir "$DIR" --agent scratch --workers 4
python -m tools.report.day_gap     --ours "$DIR" --ours-agent scratch
python -m tools.gates.margin       "$DIR"

# the three phases' movement and labour evidence
python -m tools.labour.op_patterns --dir "$DIR" --glob 'scratch_vs_*.json' --dsm-max 12 --day 12 --unit 0
python -m tools.labour.movement    --dir "$DIR" --glob 'scratch_vs_*.json' --dsm-max 12
python -m tools.labour.missed_work --dir "$DIR" --glob 'scratch_vs_*.json' --summary-only
python -m tools.labour.idle_pool   --dir "$DIR" --glob 'scratch_vs_*.json' --summary-only
python -m tools.labour.leverage    --dir "$DIR" --glob 'scratch_vs_*.json' --horizon 8
python -m tools.labour.ready_idle  --dir "$DIR" --dsm-max 12

# supply / demand / market / shed / herd
python -m tools.market.crop_demand  --dir "$DIR" --dsm-max 12
python -m tools.market.sell_price   --dir "$DIR" --glob 'scratch_vs_*.json' --seat 1 --summary
python -m tools.market.floor_sell   --dir "$DIR" --glob 'scratch_vs_*.json' --seat 1 --summary
python -m tools.market.discards     --dir "$DIR" --dsm-max 12
python -m tools.market.shop_response --dir "$DIR"
python -m tools.report.footprint    --compare --run-dir "$DIR" --max-games 12
python -m tools.report.herd_hold    --compare --run-dir "$DIR" --max-games 12
python -m tools.report.dsm_flows    --dir replays/DSM/v1 --summary --max-games 40
```

### The opening-commitment experiment (§2.5)

```bash
# four arms, 48 matched games each (12 opponents x 4 seeds)
S="--pa 1-12 --batch 4 --seed 4362837462"
SCRATCH_PARAMS='SEED_BUFFER_BY_FREE=0' python -m tools.diagnose --scratch $S --run-dir diag-replays/of-A
                                      python -m tools.diagnose --scratch $S --run-dir diag-replays/of-B
SCRATCH_PARAMS='HERD_ENABLED=1;STRUCTURE_HOLDBACK=6' python -m tools.diagnose --scratch $S --run-dir diag-replays/of-C
SCRATCH_PARAMS='CASH_RESERVE=0' python -m tools.diagnose --scratch $S --run-dir diag-replays/of-D
# matched-pair verdicts (median delta + sign test) and the per-arm ladders
python -m tools.report.arm_diff --a diag-replays/of-A --b diag-replays/of-C
python -m tools.gates.margin diag-replays/of-C
```
Raw output: `docs/v0/opening-fix.txt`.

Raw tool output otherwise lands in `docs/v0/*.txt`. DSM's reference anatomy is `docs/dsm_v1.md`; the
previous agent's scorecard is `docs/dsm_gap.md`.
