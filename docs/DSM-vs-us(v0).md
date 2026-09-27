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

Sources: `docs/v0/phase1.txt`, `docs/v0-boey/phase_all_vs_boey.txt`.

| metric | us | DSM | Boey | DAG |
|---|---|---|---|---|
| opening cash committed | **0.81** | 1.00 | 0.99 | **ROOT** |
| PLANT ops | **20** | 30 | 31 | **ROOT** |
| MELON tiles | **6** | 10 | 10 | BAD |
| STRAWBERRY tiles | 6 | 10 | **4** | — (archetype) |
| WATER ops | 45 | 74 | 76 | BAD |
| CARE ops | 20 | 34 | 40 | BAD |
| animals | 4 | 5 | 10 | WARN |
| idle share % | **27.2** | 26.2 | **6.9** | BAD |
| owned / quadrants / hands | 25 / 1 / 6 | 25 / 1 / 6 | 25 / 1 / 6 | ok |
| `open_dist` | **9** | 0 | n/a | BAD |

**DAG causation (the trace we fix against):**

```
animals on board     <- opening cash committed          [ROOT]   (explains 7 vs Boey)
MELON / STRAWBERRY   <- opening cash committed          [ROOT]
quadrants            <- opening cash committed          [ROOT]
WATER ops            <- MELON tiles, PLANT ops
WATER ops            <- PLANT ops                       [ROOT]
idle share %         <- PLANT ops                       [ROOT]
CARE ops             <- animals on board <- opening cash committed  [ROOT]
```

Boey's opening is **DSM's script plus a bigger herd**: cash 0.99, PLANT 31, WATER 76, MELON 10, and
**10 animals bought before the crop payment** — while we hold ~19 % of the bank and sow 6+6.
Against Boey, `opening cash committed` explains **7** deficient metrics, not 3.

**Verdict.** The opening is half-sown and under-committed against both references. The root has **no
deficient ancestor**, but it is **not dependency-free in practice**: closing it adds crop tiles, which
adds water demand — which is why Step 3 below depends on Step 1.

**Trap, measured.** `open_dist` is descriptive, not an objective. Closing it via `WHEAT_LANDS_DAY=2`
cost **−$15,452 (0/8, p=0.005)**; `P_BUILD` 45→95 and `BUILD_PER_TURN` 2→3 likewise cost margin. Ship
opening changes only with a paired `dterm`.

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
animals on board [p2]      <- animals [p1] <- opening cash committed [p1]   (has a BAD ancestor)
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
FERTILIZE [p3]      <- FERTILIZE [p2] <- animals [p2] <- animals [p1] <- opening cash committed [p1]
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
| `plant_ops [p1] → water_ops [p1]` | sowing under-committed; coverage 0.58 vs 0.77–0.83 |
| `water_ops [p2] → plants_died [p2]` (lag 2) | died 21 vs 0–2; weeds 17 vs 0–1 |
| `animals [p1] → animals [p2]` | 11 vs 20–22; FEED/COLLECT/FERTILIZE all ~0.4–0.5× |
| `wheat_tiles [p2] → feed_ops [p2]` | `feed_surplus` −126 vs +191 / +3,021 |
| `harvests [p2] → shed [p2/p3]` | shed peak 18 vs 28–31; stranded $1,100 vs $45 / $0 |
| sell ceiling → shed fill (C6) | our STRAWBERRY floor% p90 53.2, px p10 $9.6 |

---

## 7. Fix plan — dependency-ordered, one gate per step

**Gate after every step (same seeds, before committing):**

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

**Step 1 — Finish the tile on one visit. No dependencies.**
- **DAG node:** `WATER ops per planted tile` — ROOT, owner `src/scheduler.py::_pick`, **no deficient ancestor**.
- **Evidence (both references):** WATER chained 0.0 % vs 21.8 / 22.7 %; PLANT→WATER split 86 % vs 4 / 12 %; WATER 2.92 vs 1.17 / 1.25 mv/op; FEED 2.12 vs 0.09 / 0.54.
- **Target:** coverage **0.58 → ≥0.77**; `moves/act` **2.03 → ~0.8**.
- **Expected downstream (DAG):** `plants died` ↓, `weeds` ↓, `HARVEST ops` ↑, `shed peak` ↑.
- **Gate phase:** phase2. **Watch:** `plants died`, `weeds`, margin must not fall.

**Step 2 — STRAWBERRY sell ceiling. No dependencies.**
- **DAG node:** sell-policy leaf; C6 edge into shed fill.
- **Evidence:** our floor% p90 **53.2**, px p10 **$9.6**; leaders floor more but their *tail* is priced.
- **Target:** our STRAWBERRY `px` p10 → ≥ base, `floor%` p90 < 1 % **at growing volume**.
- **Gate phase:** phase2/3. **Watch:** `shed_pressure_days`, `stranded_at_bell`, `floor_sales`.

**Step 3 — Finish the opening crop script. Depends on Step 1.**
- **Dependency (DAG):** `plant_ops → water_ops → plants_died`; sowing more tiles before coverage is fixed raises deaths.
- **DAG nodes:** `opening cash committed` (ROOT) → MELON/animals; `PLANT ops` (ROOT) → WATER/idle.
- **Evidence:** cash 0.81 vs 1.00 / 0.99; MELON 6 vs 10 / 10; PLANT 20 vs 30 / 31; idle 27 % vs 26 % / 7 %.
- **Target:** MELON 10, PLANT ~30, `open_dist` 0, opening idle near Boey's.
- **Gate phase:** phase1 **plus paired `dterm`** (the `open_dist` trap costs −$15,452).

**Step 4 — Wheat / feed self-sufficiency. Depends on Step 3.**
- **DAG edge:** `wheat_tiles [p2] → feed_ops [p2]`; feed gates `animals`.
- **Evidence:** `feed_surplus` **−126 vs +191 / +3,021**; 130 wheat bought/game; 20 wheat tiles died unharvested vs 5.
- **Target:** `feed_surplus` ≥ 0; wheat peak 33 → ~57.
- **Gate phase:** phase2. **Watch:** `shed_pressure_days`.

**Step 5 — Herd scale. Depends on Step 4.**
- **DAG chain:** `animals [p1] → animals [p2]`; `animals [p2] → FEED/COLLECT/FERTILIZE`; C2 gates it.
- **Evidence:** 11 vs 20–22; our $/animal-day is already 1.75× DSM's, so this is **count**, not husbandry.
- **Target:** `animals` 11 → ~20 **with** `feed_surplus` ≥ 0.
- **Gate phase:** phase2. **Watch:** feed_surplus, plants_died.

**Step 6 — Crop scale to the leaders' peaks. Depends on Steps 1 + 2.**
- **DAG edges:** `planted → water_ops`; `harvests → shed`. C5 and C6 both bite.
- **Evidence:** peaks 0.3–0.6× theirs; endgame harvest/planted 0.45 vs 0.78 / **1.42**.
- **Target:** per-crop peaks → 1.0× with floor% < 1 %.
- **Gate phase:** phase2/3. **Watch:** floor%, plants_died, shed.

**Step 7 — Endgame rotation. Depends on Steps 5 + 6.**
- **DAG edge:** `harvests [p3] → shed [p3] → idle`.
- **Evidence:** `stranded_at_bell` **$1,100 vs $45 / $0**; shed at bell 25.5 vs 1.0 / 0.0.
- **Target:** stranded ≤ $100. Keep `RETIRE_DAY=99` (blanket water-off was catastrophic).

**Closed — do not re-try:** `FERTILIZE_FROM_DAY=6` (−$14,230, 2/96), `FERTILIZE_ONGOING_ONLY`,
`P_WATER_SURVIVAL`, `PLANT_WATER_CAP_DIVISOR=2`, `HANDS_MIDGAME=20`, `WHEAT_LANDS_DAY=2`,
`CASH_RESERVE=0`, `MOVE_WEIGHT` 15/60, `HERD_BUY_UNTIL=5` (−$2,080 vs the shipped 12).

Raw output: `docs/v0/MANIFEST.md` (us vs DSM) and `docs/v0-boey/MANIFEST.md` (us vs Boey).
