# Revenue report — what broke, what's fixed, and what to push

Written after a diagnostic session on the current tree. Every number below is from a
matched-pair run (`arm_diff`, same opponent+seed) or a field run, not a cross-game average.

---

## 1. TL;DR

- The agent had a **catastrophic regression**: it bought $690 of opening seed on d0 and
  **planted nothing for six days**. Fixed; verified +$39k on the probe seed and MELON 0→7 /
  idle 46.9%→12.4% on the 48-game field.
- **The diagnosis tool itself was wrong** on three nodes (a backwards edge, a missing
  market op, and a `empty` reader that counted the reserved animal ring). Fixed — this is
  why several earlier hypotheses failed.
- **Five phase-1 knobs were tested and all fail** (they trade one leak for another). The
  root cause is structural: on a 25-tile opening you cannot hold 20 crops + 12–20 animals +
  a busy crew at once.
- The current tree's binding constraint is **crew turns**, not any single priority: the
  midgame runs at ~0–4% idle and still under-produces, so every "do more" knob starves
  something else.
- **One measured win, now SHIPPED and field-verified: `HIRE_FROM_WORKLOAD_P2=1`** — midgame
  workload hiring, **19/24 matched pairs better, p=0.0066, median +$2,974, mean +$6,042**,
  11 of 12 opponents positive. Its only regressed guard is `plants_died +7` (23/24), which is
  the next thing to chase. Scoping it to phase 2 *is* the finding: the whole-season version
  over-hires on the opening and washes out (idle +2.55, 8/8 worse).

---

## 2. Fixed and verified this session

| change | file | evidence |
|---|---|---|
| Opening PLANT restored (`_plant_jobs` re-added to the d0–d5 branch) | `src/scheduler.py:406` | probe $12,522 → **$51,933**; field MELON **0 → 7**, idle **46.9% → 12.4%** (BAD→OK), owned 50 → 75 |
| `structures → animals` edge direction corrected | `src/state_graph.py` | `cause_trace` now reports `animals` as a ROOT, not a symptom of `structures` |
| `BUY_ANIMAL` added to the `animals` node's ops | `src/state_graph.py` | the market layer can now be steered by the herd node |
| `empty` reader excludes the reserved animal ring | `src/state_graph.py` + `src/layout.py::holdback_tiles` | `empty` break moved d1 → d4 (the reserved ring is not "wasted land") |
| `labour → empty`, `quadrants → empty` edges added | `src/state_graph.py` | `empty` now traces to the crew, not standalone |
| `PLANT_CAP_BY_SEEDS=True` | `src/params.py` | stops the engine voiding over-requested WHEAT batches (9% waste → ~2%) |
| `LAND_FROM_PRIORS=True` | `src/params.py` | land schedule from `priors.LAND_BY_QUADRANT` (NE d6, SW d8, SE d9), removing the duplicate `LAND_TARGET_DAY` owner |
| `SELL_FLOOR_BASE` / `SELL_LOOKAHEAD` knobs | `src/sell_policy.py` | sell-timing machinery wired (off by default — see §3) |

New tools/docs: `tools/graph/cause_trace.py` (KNOBS + `--effects` ripple), `docs/engine_audit.md`.

---

## 3. Measured dead ends — do NOT spend time here again

| knob | result | why |
|---|---|---|
| `STRUCTURE_HOLDBACK=6` | **−$4,741** median, 4/4 worse | the ring is the herd's feed zone; shrinking it → escapes +1 (4/4) |
| `FEED_STOCK_DAYS=2` | +$1,461 median, 2/4, p=1.0 (wash) | it's the *shed buffer*, not the standing-wheat gate → `stranded_at_bell` +1,110 (4/4) |
| `WHEAT_TARGET_FROM_HERD=1` | **−$6,784** median, 4/4 worse | wheat displaces strawberry revenue |
| `FILL_LAND=1` | **−$2,905** median, 1/4 | idle +92 (4/4) — the crew cannot cover more tiles |
| `SELL_FLOOR_BASE=1` | **−$9,980** median, 3/4 worse | holding below base overflows the shed: `discarded` +309, shed pressure 10–14 days |
| `P_DIG=80` | +$2,246 median, 5/8, p=0.73 | escapes → 0 (8/8) and revenue +$3.9k, but `plants_died` **+22 (8/8)** |
| `P_DIG=55` | +$216 median, 4/8, p=1.0 (flat) | guards worse (discarded +7.5, stranded +405) |

**The pattern:** every single-node push ripples into another node. That is the 25-tile
tradeoff, and it is why `AGENTS.md` now says: chase philosophy, not per-day parity.

---

## 4. Current tree — the diagnostic picture (8 games, `diag-replays/d4-cur`)

**Result:** 8/8 LOSS, $18,086–$65,899 vs opponents $130k–$188k.

**Break points** (`graph_diag --section break`):

| node | first break | days deficient | reading |
|---|---|---|---|
| `planted` | d1 | **26/27** | the opening under-sow (reserved ring) — measured-optimal, don't chase |
| `empty` | d3 | 14/27 | improved from d1; the residual is real but the knob is exhausted |
| `animals` | d3 | **21/25** | the herd stalls at 5 — feed gate (`wheat tiles 3 < need 10.2`) |
| `structures` | d3 | 14/21 | symptom of `animals` (housing follows owned animals) |
| **`unfed`** | d1 | **9/25** | **REGRESSION** (was 4/25) — flaps, so a priority race |
| `weeds` | d10 | **19/29** | `P_DIG=20`, idle 0 → DIG never fires |
| `labour` | d6 | 2/29 | crew ramp |
| `quadrants` | d8 | 1/13 | land timing |
| `shed` | d7 | 1/29 | buffer pressure |
| `money`, `revenue_per_day` | d0/d1 | — | stock-vs-flow false positives (documented) |

**Demand** (`graph_diag --section demand`) — demanded but NOT delivered:

- `PLANT` on d2/d4/d8 (the reserved-ring demand is unactionable)
- `DIG` on d10 → **weeds accumulate**
- `BUILD_COOP` / `PLACE` on d8/d10 → the herd cannot grow
- `BUY_SEED` / `BUY_ANIMAL` "market NOT ORDERED" on d4/d8
- `HIRE` "market ordered with NO graph pressure" → **the graph never pressures HIRE**

**Money columns:** `feed_surplus` **−265 to −338** (we net-buy feed at retail), `plants_died`
38–67, `animal_escapes` 0–2, `premium_below_base_frac` 0.1–0.79.

---

## 5. Actionables to push revenue (ranked by evidence)

### A1 — ✅ SHIPPED: `HIRE_FROM_WORKLOAD_P2=True` (midgame-only workload hiring)
The strongest measured signal of the session, and **the phase scoping is the finding**.

| arm | median | mean | sign test | idle |
|---|---|---|---|---|
| `HIRE_FROM_WORKLOAD=1` (whole season) | +$1,017 | +$591 | 5/8, p=0.73 | **+2.55 (8/8 worse)** |
| **`HIRE_FROM_WORKLOAD_P2=1`** (phase 2+ only) | **+$1,478** | **+$4,126** | **7/8, p=0.070** | +0.10 (neutral) |
| **field: same knob, 12 opponents × 2 seeds** | **+$2,974** | **+$6,042** | **19/24, p=0.0066** | +0.40 |

The whole-season arm over-hires on a 25-tile opening with nothing to do (idle +2.55, 8/8
worse) and washes out. Scoped to phase 2+ it is a **significant field win, 11 of 12
opponents positive**. Shipped in `src/params.py` (`HIRE_FROM_WORKLOAD_P2 = True`).

Also improved: `sell_revenue +$1,508` (18/24 better), `premium_below_base_frac −0.026`
(1/24 worse), `animal_escapes −1` (3/24 worse), `shed_overflow` 0.

**One guard regressed: `plants_died +7` (23/24 worse, ~15%).** More hands should mean more
watering — the mechanism is unexplained (candidate: the hire cost competes with the seed/
feed budget, so fewer plants go in, or the band assignment cannot use the extra hands).
This is the next thing to chase; it is the only thing standing between A1 and a cleaner win.

```bash
# re-confirm any time (A = knob off, B = shipped default)
SCRATCH_PARAMS='HIRE_FROM_WORKLOAD_P2=0' python -m tools.diagnose --scratch \
    --pa 1-12 --batch 2 --seed 4362837462 --run-dir diag-replays/a1-field-base
python -m tools.diagnose --scratch \
    --pa 1-12 --batch 2 --seed 4362837462 --run-dir diag-replays/a1-field-cur
PYTHONPATH=. python -m tools.report.arm_diff --a diag-replays/a1-field-base --b diag-replays/a1-field-cur
```

### A2 — Feed self-sufficiency (`feed_surplus` −265 to −338/game)
We **buy feed at retail** every game; Boey's `feed_surplus` is positive from d3. Every bought
unit is cost against net revenue. The gate is `wheat_tiles >= 1.7 × (herd+1)`, and our wheat
base collapses after d3 (the opening script drops WHEAT to 0 by d3).
- Do **not** use `WHEAT_TARGET_FROM_HERD` (measured −$6,784).
- Instead: raise the *phase-1* wheat floor (a d6–d10 wheat re-sow) or credit shed wheat
  toward the gate — both untested, take them one at a time.

### A3 — Water coverage and plant deaths (`plants_died` 38–67 vs Boey 0–3)
`WATER ops per planted tile` is ~0.56 vs the reference's 0.91. Raising `P_WATER_SURVIVAL` is
measured inert (90/105/120 byte-identical) — the constraint is **crew turns**, not priority.
The lever is therefore either fewer tiles to cover or fewer turns spent walking (A4).

### A4 — Crew turns are the binding constraint
Midgame idle is ~0–4% and we still under-produce: the turns go to **walking**
(`moves per act` 1.41–1.78 vs Boey's 0.65). Per-turn priority tuning is exhausted (21 arms).
The two structural options left:
1. **Hire more** (A1) — adds turns.
2. **Spend fewer turns walking** — the shed round-trip (`DROP` 3.4× Boey) and the
   cross-band chase. `DROP`-reduction knobs were measured worse *in isolation* because the
   carried goods overflow (`discarded` +309), so any DROP fix must land **with** a sell
   change (A5), not alone.

### A5 — Sell timing, done as *timing* not as a floor
`SELL_FLOOR_BASE=1` failed because holding past the price **peak** is as wrong as selling
into the trough. The correct half is `SELL_LOOKAHEAD=1` (`demand.best_sell_now`, which prices
the town drain and the opponent's sell rate). Untested; test it **paired with** a DROP change
so held goods can still leave the shed.
```bash
SCRATCH_PARAMS='SELL_LOOKAHEAD=1' python -m tools.diagnose --scratch \
    --pa 2,9 --batch 4 --seed 4362837462 --run-dir diag-replays/a5-look
```

### A6 — Shop-responsive production (the "produce what shops buy" lever)
`priors.HERD_BY_SHOP` (YARN→SHEEP 9 vs 2, PIZZA/ICE_CREAM/SMOOTHIE→COW, BAKERY/BRUNCH→GOOSE)
is **already in state** but unused. d6+ only (the opening draw is one shop in 36/36 games).
This is the largest *unimplemented* strategic lever.

### A7 — Plug HIRE into the graph
`graph_diag --section demand` shows `HIRE` ordered on 40–96 turns with **NO graph pressure** —
the `labour` node licenses HIRE but the pressure never reaches the market. Either give HIRE a
pressure or accept the hand ramp as the owner (a `--section plug` audit would confirm).

### A8 — Verify the two un-tested defaults shipped this session
`PLANT_CAP_BY_SEEDS=True` and `LAND_FROM_PRIORS=True` are live but were never A/B'd alone, and
the `unfed` regression (4/25 → 9/25) appeared in the same window. One matched run isolates them:
```bash
SCRATCH_PARAMS='PLANT_CAP_BY_SEEDS=0;LAND_FROM_PRIORS=0' python -m tools.diagnose --scratch \
    --pa 2,9 --batch 4 --seed 4362837462 --run-dir diag-replays/a8-off
PYTHONPATH=. python -m tools.report.arm_diff --a diag-replays/a8-off --b diag-replays/d4-cur
```

---

## 6. How to read the next change (the rule this session produced)

1. Run `graph_diag --section break` + `--section demand` on a fresh arm.
2. Run `cause_trace --node <root>` → it prints the node's **KNOBS** and the remedy's
   **preconditions, measured** (e.g. `weeds standing 2, idle 0, DIG done 0`).
3. If a precondition is the binding one, that is the cause. Change exactly one thing.
4. Judge on `result` via `arm_diff`, and read the ripple with
   `cause_trace --effects <base> <arm>` **before** believing a median.

**If a hypothesis fails, suspect the tool first** — this session's three biggest wastes came
from a wrong edge, a missing op, and a reader that counted reserved land as wasted.

---

## 7. Iteration log (hypothesis loop)

### Iteration 1 — A1 hire ✅ SHIPPED
`HIRE_FROM_WORKLOAD_P2=True`. Field: **19/24 pairs, p=0.0066, median +$2,974, mean +$6,042**,
11/12 opponents positive. The phase scoping was the finding (whole-season over-hires the opening).

### Iteration 2 — A2 feed ❌ FIX FAILED; three TOOL/agent bugs found and fixed

Per the loop rule ("if the hypothesis is wrong, the tool was wrong — fix the tool"), the A2
iteration produced more tool fixes than agent fixes:

1. **`cause_trace` was blind to flapping nodes.** It required 3 *consecutive* deficient days and
   printed "not deficient" otherwise, so `unfed` — deficient on 9/25 days — was skipped entirely,
   which is exactly why A2 was under-investigated. **Fixed:** it now reports
   `FLAPPING: deficient N/M days (a priority race)`, matching `graph_diag --section break`.
2. **`cause_trace` reimplemented the node readers and drifted.** It read nodes off the extracted
   rec, but `unfed`/`dry_plants` are not in that rec, so they silently read **0** on every day.
   **Fixed:** it now builds a real `State` and calls the SAME `state_graph._LIVE` readers the live
   agent calls — one implementation, no drift.
3. **AGENT BUG: `output_per_day` was a DEAD node.** `_output_per_day` called
   `value.animal_output_per_day` with `value` un-imported, so the reader raised on every state and
   `read()`'s `except Exception: continue` swallowed it. The documented dead-node check
   (`set(NODES)-set(_LIVE)`) PASSES for such a node — it is listed, it just never evaluates.
   **Pre-existing at HEAD.** Fixed, and `graph_diag --section health` added as the guard.
   *The fix is byte-identical*, which is itself informative: `output_per_day`'s upstream
   (`planted`, `animals`) is deficient, so the node is a symptom, and `deficit_jobs` (roots-only)
   never fired on it.
4. **Tool gap: no per-crop resolution.** The failed A2 test used a *global* seed knob and lost
   **−$16,524 median (8/8 worse)**; the effects view explains it (`labour` idle +96 6/8,
   `sell_revenue` −$3,572) — but the aggregate "seed held 8" had hidden that the fix needed to
   name a crop. **Fixed:** the trace now prints per-crop seed held and per-crop tiles for
   `empty`/`planted`.

**Plug audit result (why graph work can be inert):** 6/27 modules import `state_graph`;
`crop_plan` (jobs), `herd_plan`, `sell_policy`, `opening`, `endgame` do **not**. The job-steering
actuators are OFF *by measurement* (`GRAPH_KERNEL`, `VALUE_KERNEL`); `GRAPH_MARKET` and
`GRAPH_DEFICIT_JOBS` are on but act only on ROOTS. **The graph is the diagnostic frame; the
balance moves only when a decision-layer owner (like `budget.py` in A1) changes.**

**Refined A2 state:** at d3 we hold WHEAT=6 seed and sow only 2, with 2 plantable empty tiles —
so the midgame wheat gap is not "no seed" at that point. The measured difference stands:
`WHEAT tiles` 3 vs Boey's 6.5–10 through d6–d8, `WHEAT_buy` 1/0/0 vs 6.5/2/2, and
`feed_surplus` −265…−338 (we buy feed at retail). The fix must be **wheat-specific and paired with
the feed budget**, not a global seed knob.

### Iteration 2 (A2) — two fixes tested, NEITHER shipped

| fix | median | mean | sign | verdict |
|---|---|---|---|---|
| `SEED_FILL_BUFFER=1;SEED_FROM_EMPTY=1` | −$16,524 | — | 8/8 worse | **reject** (idle +96, sell −$3,572) |
| `HERD_OPENING_DAYS=10` | +$4,204 | **−$3,147** | 5/8, p=0.73 | **reject** (bimodal −$30.8k…+$15.5k) |

The second is the important one: extending the cash-gated (bought-feed) herd window from d2 to
d10 lifts the *median* but its **mean is negative** and the spread is bimodal — a gamble, not a
win. Since the objective is `Pr[win] ≈ Φ(μ/σ)`, a mean-negative high-variance change is a
regression even when the median improves.

**A2's diagnosis stands, with the mechanism now named:** `PLANT_ORDER = (MELON, STRAWBERRY,
TOMATO, CARROT, WHEAT)` puts **WHEAT last**, so melon/strawberry preempt it in `plant_queue`;
the wheat base sticks at **3 tiles vs Boey's 6.5–10** (d6–d8), which holds the feed gate
(`wheat_tiles >= 1.7×(herd+1)`, and after `HERD_OPENING_DAYS=2` the gate is wheat-only) shut,
so the herd cannot grow and we buy feed at retail (`feed_surplus` −265…−338).

**Next round's A2 fix (not yet tested):** a wheat-specific queue priority — `PLANT_ORDER` is a
tuple and is NOT `SCRATCH_PARAMS`-settable, so this needs a code edit (move WHEAT ahead of
STRAWBERRY in `plant_queue`'s interleave, or give wheat a midgame floor), tested **with** the
feed budget rather than as a global seed knob.

### Iteration 2 (A2) — ✅ SHIPPED: `WHEAT_LEADS_FEED_BASE=True`

Third and final A2 fix, and the one that worked. Root: `PLANT_ORDER` puts WHEAT **last**, so
melon/strawberry preempt it in `plant_queue`'s interleave; the wheat base stuck at **3 tiles vs
the reference's 6.5-10** through d6-d8, holding the herd's feed gate
(`wheat_tiles >= 1.7*(herd+1)`, wheat-only after `HERD_OPENING_DAYS=2`) shut, so the herd could
not grow and the farm bought feed at retail.

Fix: while the standing wheat base is **below** the feed gate, wheat leads the interleave;
once it clears the gate the value order resumes (`src/crop_plan.py::plant_queue`).

| arm | median | mean | sign | sell_revenue |
|---|---|---|---|---|
| 8 games (pa 2,9 ×4) | +$11,013 | +$4,154 | 6/8, p=0.289 | +$12,158 |
| **field, 12 opponents × 2 seeds** | **+$8,363** | **+$7,621** | **21/24, p=0.0003** | **+$8,838** |

11 of 12 opponents positive (+$6.2k…+$12.4k). Guards mostly **improved**:
`idle_share −0.4`, `idle_units −26`, `floor_sales −3`, `discarded −3`,
`premium_below_base_frac −0.159`, `shed_overflow −0.5`, `animal_escapes` neutral.
Two mild regressions to watch: `stranded_at_bell +$96` (20/24) and `plants_died +5` (15/24).

Combined shipped state: A1 (`HIRE_FROM_WORKLOAD_P2`) + A2 (`WHEAT_LEADS_FEED_BASE`), both
field-verified at p<0.01. Together they move the 8-game baseline from ~$20-63k to ~$31-66k.

---

## 8. Iteration log — round 3 (diagnostics on the shipped tree)

`graph_diag --section health`: **all 14 readers evaluate cleanly** (the `output_per_day` fix holds).

`graph_diag --section break` on the shipped 24-game arm, vs the pre-A2 tree:

| node | before A2 | after A2 | reading |
|---|---|---|---|
| `unfed` | 9/25 | **7/25** | improved — the wheat fix feeds the herd |
| `structures` | 14/21 | **11/21** | improved |
| `output_per_day` | DEAD (crashed) | **d5, 21/26** | now visible — the revenue-chain middle link |
| `animals` | 22/25 | 22/25 | **the biggest remaining root** |
| `weeds` | 19/29 | 19/29 | `P_DIG=20`, idle 0 |
| `planted` / `empty` | 26/27 / 15/27 | unchanged | the reserved-ring tradeoff (measured-optimal) |

### The herd gap is now mostly closed — and the rest is measured-unprofitable

Day-wise herd (ours/Boey): d5 **8**/5, d6 8/**12**, d8 8/**14**, d10 8/**20**, d11 17/20,
**d12 20/20**. So the wheat fix opened the feed gate and the herd now reaches **parity — two
days late (d12 vs d10)**; it is flat at 8 through the d6–d10 window while Boey grows.

Tested the remaining lever — `HERD_OPENING_DAYS=10` (cash-gated/bought-feed herd through d10, on
top of the shipped wheat fix), 24-game field:
**median −$2,108, mean +$960, 11/24, p=0.84 → REJECTED.** Buying feed to grow the herd four days
early does not pay even with the wheat base fixed. This is a real finding, not a tool error: the
tool named the right location (the feed gate) and the A2 fix closed most of it.

**Next candidates:** A5 `SELL_LOOKAHEAD` (the timed sell rule, untested) and A6 shop-responsive
production (`priors.HERD_BY_SHOP` is in state but unused) — both are *decision-layer* changes,
which is where every shipped win this session has come from.

---

## 9. Iteration log — round 4 (A5 sell look-ahead: REJECTED, tool fixed)

A5 was "use `demand.best_sell_now` — the timed sell rule — instead of the inventory gate".
Tested on the 24-game field, twice:

| arm | median | mean | sign | floor_sales |
|---|---|---|---|---|
| `SELL_LOOKAHEAD=1` (as shipped) | −$10,753 | −$16,790 | **1/24, p=0.0000** | **+55.5 (24/24 worse)** |
| `SELL_LOOKAHEAD=1` + tool fix | −$6,152 | −$12,605 | 10/24, p=0.54 | **+33.0 (24/24 worse)** |

**Both rejected.** The knob stays OFF.

### The tool bug this exposed (fixed)

`demand.best_sell_now` answered `HOLD` on essentially every turn: it compares today's price to
the **maximum over the remaining day**, and the town drain keeps lowering the projected
inventory, so `future > now` almost always. The goods then piled up and were dumped at the $1
floor — which is exactly what `floor_sales +55.5 (24/24)` shows.

Fixed in `src/demand.py`: a `headroom` argument (free shed space — with no room to hold, the
sale is FORCED) and a `band` (a hold must clear a margin; selling within 5 % of the horizon peak
keeps the pipe clear). `sell_policy` now passes the headroom. The fix **halves the loss**
(−$10.7k → −$6.2k) but does not make the rule profitable.

### The standing finding: holding for the drain does not pay

The premise is still wrong after the fix. Even with headroom and a band, `floor_sales` is +33
(24/24 worse): the projection over a whole day of drain is effectively unbounded, so the rule
over-values waiting, and the stock still ends up at the floor. **The sell decision is better
served by the shipped inventory gate than by this look-ahead** — and the measured truth is that
the crew's turns, not the price, are what the farm is short of. A5 is closed pending a real
own+opponent supply model, which is out of scope for this sprint.

Rounds 1-4 cumulative: A1 shipped (p=0.0066), A2 shipped (p=0.0003), A3/A4 unstarted,
A5 rejected (x2), A6 (shop-responsive production) is the largest remaining un-tried lever.

---

## 10. Iteration log — round 5 (A6 shop-responsive production: ✅ SHIPPED, unproven)

A6 was "produce what the shops actually buy". The gap: `herd_plan._targets` fixes **COW at 9**
whatever the draw, and only reacts to YARN for SHEEP/GOOSE — while `priors.HERD_BY_SHOP` (the
reference's own medians) says a cow shop lifts COW 4→7-8, a goose shop GOOSE 3→7, YARN SHEEP 2→9.

Fix: `HERD_SHOP_RESPONSIVE=True` sets each species' target from the shops actually unlocked
(max of the with-shop medians; the without-shop median when none of that species' shops is up),
d6+ only (the opening draw is one shop in 36/36 games, so opening reactivity is vacuous).

| arm | median | mean | sign | sell_revenue |
|---|---|---|---|---|
| 4 matched pairs (pa 2,9) | +$1,990 | +$2,750 | 2/4 | — |
| **field, 12 opponents × 2 seeds** | **+$4,837** | **+$4,026** | 15/24, p=0.31 | **+$3,275 (19/24 better)** |

**Two independent samples both positive, but p=0.31 is NOT significant** — unlike A1 (p=0.0066)
and A2 (p=0.0003). Guards: `animal_escapes −1` (1/24 worse), `idle_share −0.1`, `idle_units −12`,
`shed_overflow 0 (0/24)`, `discarded 0 (1/24)`, `missed_harvest 0 (4/24)` — all neutral or better;
small regressions in `floor_sales +6 (21/24)` and `stranded_at_bell +26.5 (14/24)`.

Shipped as a one-knob revert (`HERD_SHOP_RESPONSIVE=False`) on the strength of the direction and
the clean revenue gain, flagged **unproven** — it needs a larger sample to confirm.

**Rounds 1-5 cumulative:** A1 shipped (p=0.0066), A2 shipped (p=0.0003), A5 rejected ×2 (tool
fixed), A6 shipped (p=0.31, unproven). A3/A4 remain; the plug audit still says the graph is the
diagnostic frame and every shipped win has come from a decision-layer owner.

---

## 11. Round 6 — A6 CONFIRMED (the p=0.31 was underpowered)

Re-tested `HERD_SHOP_RESPONSIVE` on a **fresh, independent seed** (`--seed 1234567`,
12 opponents × 2 seeds), both arms run head-to-head:

| sample | pairs | median | mean | sign |
|---|---|---|---|---|
| seed 4362837462 | 24 | +$4,837 | +$4,026 | 15/24, p=0.31 |
| **seed 1234567** | 24 | **+$2,688** | **+$7,938** | **22/23, p=0.0000** |

**Combined: 37/47 pairs positive (79%).** A6 is confirmed and stays shipped. The earlier
"unproven" flag is withdrawn — one 24-game sample at p=0.31 was simply too small to resolve an
effect this size, which is exactly the small-sample trap `AGENTS.md` warns about (the same trap
that made the *whole-season* hire arm read +$10k on 4 games).

**Shipped, field-verified state after 6 rounds — three decision-layer wins:**

| # | knob | field evidence |
|---|---|---|
| A1 | `HIRE_FROM_WORKLOAD_P2=True` | 19/24, **p=0.0066** |
| A2 | `WHEAT_LEADS_FEED_BASE=True` | 21/24, **p=0.0003** |
| A6 | `HERD_SHOP_RESPONSIVE=True` | **22/23, p=0.0000** (fresh seed) |

Rejected after measurement: A5 `SELL_LOOKAHEAD` (×2, tool fixed first),
`HERD_OPENING_DAYS=10`, `SEED_FILL_BUFFER`+`SEED_FROM_EMPTY`, `STRUCTURE_HOLDBACK=6`,
`FEED_STOCK_DAYS=2`, `WHEAT_TARGET_FROM_HERD`, `FILL_LAND`, `SELL_FLOOR_BASE`, `P_DIG` 55/80.

Remaining: A3 (water coverage / plant deaths) and A4 (crew turns) — both already partially
served by A1's extra hands.

---

## 12. Round 7 — where the shipped tree actually stands (the honest gap)

Absolute level on the fresh-seed 24-game field (`--seed 1234567`, 12 opponents × 2 seeds):

| arm | median bank | mean bank | median margin | wins |
|---|---|---|---|---|
| A6 off (pre-round-6 shipped) | $49,742 | $50,126 | −$107,436 | 0/24 |
| **SHIPPED (A1+A2+A6)** | **$53,162** | **$58,064** | **−$103,742** | 0/24 |

So six rounds of verified wins moved the median bank by **~+$3.4k** and the margin by **~+$3.7k**
— real, reproducible, and nowhere near enough. **We are still losing every game by ~$100k, and the
target is $120k.**

### Why more knobs will not close this

Every remaining root in the break table is a *structural* quantity whose local knobs are already
measured-unprofitable:

| root | days deficient | every knob tried | result |
|---|---|---|---|
| `planted` | 26/27 | `STRUCTURE_HOLDBACK=6`, `FILL_LAND=1` | −$4.7k, −$2.9k |
| `animals` | 22/25 | `HERD_OPENING_DAYS=10`, `FEED_STOCK_DAYS=2`, `WHEAT_TARGET_FROM_HERD=1` | wash, wash, −$6.8k |
| `weeds` | 19/29 | `P_DIG` 55/80 | +$0.2k, +$2.2k (deaths +22) |
| `empty` | 15/27 | the same holdback knobs | measured-optimal |

The pattern is uniform: **on a 25-tile-then-75-tile farm with the crew as the binding constraint,
every single-node push trades one leak for another.** That is what the graph has been saying since
round 1, and six rounds of measurement now confirm it rather than assume it.

### What actually closes it (the deferred structural work)

The wins that DID land were all *decision-layer* changes that added capacity or matched production
to demand (hire to workload, wheat base first, breed to the unlocked shops). Closing a $100k
margin needs the same kind of change at larger scale:

1. **Land + herd on it.** Boey's 100-tile, 20-animal farm is the shape that earns ~$111k median.
   Ours reaches herd parity only at d12 and stays at 75 tiles. Buying the 4th quadrant and
   growing the herd onto it is the single largest measured difference, and it is the "land is for
   later" item phase 1 deferred.
2. **Crew turns.** `moves_per_act` is 1.4-1.8 against the reference's 0.65; per-turn priority
   tuning is exhausted (21 arms), so this needs tile geography / the shed round-trip, not a knob.
3. **A6-style demand matching, extended to crops.** The herd now matches the shops; the crop mix
   still does not (`priors.CROPS` / shop-product demand is unused for the crop calendar).

---

## 13. Round 8 — the "buy the 4th quadrant" idea is REFUTED (and §12 was wrong about it)

§12 listed "land + herd on it — Boey's 100-tile farm" as the largest remaining lever. **That was
my error**, and the measurement says so twice over:

| arm | median | mean | sign | verdict |
|---|---|---|---|---|
| `LAND_QUADRANT_MAX=4` (buy SE) | **−$16,185** | −$14,398 | **1/24, p=0.0000** | **reject, hard** |

Boey owns **3 quadrants (75 tiles)** — the priors' *final quadrant order* is `NW,NE,SW` in
**352/359 games**, and the phase-1 `owned 75 vs 100` reading was a `--ref-max 8` sampling artefact
that §12 then repeated. Our shipped `LAND_QUADRANT_MAX=3` already **matches** him. The 4th quadrant
costs $16k because a bigger, sparser farm spreads the same crew — the same "bigger farm = more
walking" result the W2 geometry note recorded.

**Corrected remaining-lever list** (land is NOT on it):

1. **Crop mix by shop demand** — A6 matched the *herd* to the unlocked shops; the crop calendar
   still ignores `priors.CROPS` / shop-product demand. Same class of change as the three wins.
2. **Crew turns** — `moves_per_act` 1.4-1.8 vs 0.65; needs tile geography / the shed round-trip,
   not a knob (21 arms exhausted).
3. **The d6-d10 herd window** — we reach parity only at d12; every feed-gate knob is
   measured-unprofitable (`HERD_OPENING_DAYS=10` wash, `FEED_STOCK_DAYS=2` wash,
   `WHEAT_TARGET_FROM_HERD=1` −$6.8k).

### Session close-out

**Shipped and field-verified (3):** A1 `HIRE_FROM_WORKLOAD_P2` (19/24, p=0.0066),
A2 `WHEAT_LEADS_FEED_BASE` (21/24, p=0.0003), A6 `HERD_SHOP_RESPONSIVE` (22/23, p=0.0000).

**Rejected on measurement (11):** `SELL_LOOKAHEAD` ×2, `HERD_OPENING_DAYS=10`,
`SEED_FILL_BUFFER`+`SEED_FROM_EMPTY`, `STRUCTURE_HOLDBACK=6`, `FEED_STOCK_DAYS=2`,
`WHEAT_TARGET_FROM_HERD=1`, `FILL_LAND=1`, `SELL_FLOOR_BASE=1`, `P_DIG` 55/80,
`LAND_QUADRANT_MAX=4`, `WHEAT_LEADS_FEED_BASE` (now shipped), whole-season hire.

**Tool/agent bugs fixed (5):** `cause_trace` blind to flapping nodes; `cause_trace` reader drift
(`unfed`/`dry_plants` read 0); the dead `output_per_day` node + new `graph_diag --section health`
guard; `demand.best_sell_now` always-HOLD (+`headroom`/`band`); missing `labour→empty` /
`quadrants→empty` / `animals→structures` edges + `BUY_ANIMAL` op.

**Level:** median bank ~$53k (from ~$50k), margin ~−$104k. The $120k target is not reachable by
knob iteration — the next real gain needs lever (1) or (2) above, both decision-layer changes of
the same class as the three that worked.

---

## 14. Round 9 — A8 crop-demand matching: INERT, and the reason is the session's whole theme

Added `CROP_SHOP_RESPONSIVE` (the crop half of A6: a slot bonus in `plant_queue` for a crop whose
product has a volume buyer among the unlocked shops). Verified the knob is LIVE
(`at(d5)=True`, `at(d15)=True`) and the predicate is right (`WHEAT`/`TOMATO` return True under
`BAKERY`/`PIZZA_SHOP`).

**Result on the 24-game field: byte-identical, +$0 on all 24 pairs, 0/0 decided.**

The reason is mechanism, not a bug: the bonus changes the queue's **counts**, but the crew plants
the queue's **prefix** — it is turn-limited, not slot-limited (the demand view has shown `PLANT`
"NOT DELIVERED" all session). Adding slots behind the prefix changes nothing. **To move the crop
mix you must change the ORDER or the priority, not the length.**

That is the same wall every rejected knob has hit, now measured three ways:
* land: `LAND_QUADRANT_MAX=4` → −$16,185 (1/24) — a bigger farm spreads the same crew;
* herd window: `HERD_OPENING_DAYS=10` → wash — more animals need more turns to service;
* crop mix: `CROP_SHOP_RESPONSIVE` → inert — more queue slots behind a prefix the crew never reaches.

**The binding constraint of this agent is CREW TURNS, full stop.** Every win that landed (A1 more
hands; A2 the feed base so the hands do not have to fetch wheat; A6 breeding to the shops so the
same hands service demand) added effective turns or removed wasted ones. Knob stays OFF (inert).

---

## 15. Round 10 — the structural plan's step 1 is REJECTED, and it refutes "scale the herd"

Plan step 1 implemented the root cause found by inspection: at d12 the market list sits at exactly
`MAX_ORDERS=10` every turn and `BUY_ANIMAL` appears only **2/24 turns** while cash, the feed gate
(24 wheat vs 17 needed at herd 9) and housing are all green — the animal buy is truncated off the
tail, leaving no trace in any metric. `MARKET_RESERVED_SLOTS` reserves tail slots for the atomic
claims (`BUY_ANIMAL`, `BUY_LAND`) in `scheduler`'s market assembly.

**It worked mechanically and still lost money** (24-game field, seed 1234567):

| | d10 | d14 | d18 | d22 | d26 |
|---|---|---|---|---|---|
| herd, base | 8 | 9 | 12 | 15 | 16 |
| herd, `MARKET_RESERVED_SLOTS=2` | 8 | **11** | **13** | 15 | 16 |

| arm | median | mean | sign |
|---|---|---|---|
| `MARKET_RESERVED_SLOTS=2` | **−$840** | **−$5,866** | 9/24, p=0.31 |

So the herd **did** grow (+2 at d14, +1 at d18) and the money still fell. **Closing the herd scale
gap is not profitable in this configuration** — the truncated `BUY_ANIMAL` was, in effect,
protecting the farm. This is now the *fourth* independent measurement of the same wall:

| round | lever | result |
|---|---|---|
| 8 | buy the 4th quadrant (`LAND_QUADRANT_MAX=4`) | −$16,185 (1/24) |
| 8 | force the herd window (`HERD_OPENING_DAYS=10`) | wash |
| 9 | crop mix by shop demand (`CROP_SHOP_RESPONSIVE`) | inert (crew plants a prefix) |
| 10 | reserve market slots to grow the herd (`MARKET_RESERVED_SLOTS=2`) | −$840 median, **mean −$5,866** |

**The user's "scale up the operation to map to Boey" premise is measured-false in this
configuration.** Scale is not blocked by a missing mechanism — we can now *make* the herd grow on
demand — it is blocked by the **economics**: on 75 tiles with this crew, an extra animal costs more
(animal + housing + feed + the crew turns it consumes) than the milk/wool/egg it returns. Boey runs
20 animals profitably because his whole system differs (crew conversion 0.65 moves/act vs our
1.4-1.8), not because he buys more animals.

`MARKET_RESERVED_SLOTS` ships as **0** (inert; the knob and the wiring remain for a future
configuration in which the crew can service a larger herd).

---

## 16. Round 11 — the `deploy` node: correct mechanism, no operating point

Per the plan (evolve the graph, not the knobs), I added the missing graph node:

* **`deploy`** — `Node("priors", "cash_hold", "lower", ("BUY_ANIMAL","BUY_LAND","BUY_SEED"))`,
  reader `money`, target `priors.CASH[day]`. The deficiency is **excess cash against the
  reference's own trail** — the inverse of `money` (`"higher"`, licenses only `SELL`), which is why
  hoarding read as health and nothing ever pressed acquisition.
* Verified: dead-node check clean, `target_of('deploy', 8) = 27.0` (the priors' d8 cash), and the
  node is gated on `DEPLOY_NODE` so it A/Bs without editing code.

**Result (quick panel, `--pa 2,9 --batch 2`):**

| variant | median | sign | reading |
|---|---|---|---|
| `DEPLOY_NODE=1`, ungraded (ratio vs a ~$27 target) | **−$15,500** | 0/4 | pressure saturates → acquisition jumps the whole market queue |
| `DEPLOY_NODE=1`, graded (`_WIDTH["deploy"] = 25 → ~$2.5k ≈ 1 day of income`) | **+$0** | 0/0 | byte-identical — the pressure no longer moves any decision |

**So the node has no useful operating point: too strong destroys ~$15k, graded does nothing.**

That is the real finding, and it is more precise than "the knob was wrong": **the graph can now
compute the deployment deficiency correctly, but the acquisition chain cannot convert a moderate
pressure into spending.** The pressure reaches `apply_to_market` (which only *orders* the market
list), while the actual vetoes live downstream in the layers' own gates — `herd_plan`'s feed gate
(`wheat_tiles >= 1.7*(herd+1)`), `plan`/`budget`'s cash gates, and `emit`'s silent
`MAX_ORDERS=10` truncation. A pressure that is not paired with opening those gates changes either
everything (§1, −$15.5k) or nothing (§2, +$0).

**Next step is therefore not another node.** Deploying capital needs the veto gates themselves
made pressure-aware in one place — the feed gate, the acquisition cash gates, and the truncation
rule — so that "the graph says deploy" becomes "the layers allow the buy". The `deploy` node stays
in the tree, gated OFF, as the signal that work depends on.

---

## 17. Round 12 — the pressure-aware gates: TWO bugs found, mechanism now live

Implementing "make the vetoes pressure-aware in one place" (feed gate + truncation reading the
graph's deployment pressure) exposed that **the deployment pressure had never actually been
computed**, so the earlier "graded = byte-identical" result was measuring a dead helper:

1. **Tuple-unpack bug.** `deploy_pressure` unpacked **6** fields from `deviation`'s **5**-tuples
   (`(node, ours, tgt, pressure, urgency)`; `roots` is the 6-field one). The `ValueError` was
   swallowed by a bare `except`, so the helper returned `1.0` on **every** call — both
   pressure-aware gates were dead, and the graded node read +$0 for exactly that reason.
2. **Unclamped negative pressure.** With the unpack fixed, a "lower is better" node whose `ours`
   is *below* the target produced a negative ratio (d12: priors $14.5k vs ours $5.5k → **−3.44**).
   Clamped to `max(1.0, p)`: holding less than the reference is not a deficiency.

**Verified live after both fixes:** `deploy_pressure` = 0.996 at d6 (money $12 vs priors $21 — not
deficient), **1.645 at d8** ($1,640 vs $27), **1.674 at d10** ($1,726 vs $41).

**Quick panel (`--pa 2,9 --batch 2`), `DEPLOY_NODE=1` vs base:**

| variant | median | mean | sign |
|---|---|---|---|
| ungraded (saturing) | −$15,500 | — | 0/4 |
| graded, **buggy helper** | +$0 | +$0 | 0/0 |
| **graded, helper fixed + clamped** | **+$2,112** | **+$2,362** | 2/4 |

So the chain now works end to end: the graph computes the deployment deficiency from the priors'
own cash trail, and **the feed gate and the market truncation both yield to it** — which is what
"the graph says deploy ⇒ the layers permit the buy" required.

**Not yet confirmed** — 4 games at 2/4 is a quick check, not evidence. Next step per the run
protocol (`2 PAs × 2 batch` to look, then **12 PAs** to confirm):

```bash
SCRATCH_PARAMS='DEPLOY_NODE=0' python -m tools.diagnose --scratch \
    --pa 1-12 --batch 2 --seed 4362837462 --run-dir diag-replays/c-base
SCRATCH_PARAMS='DEPLOY_NODE=1' python -m tools.diagnose --scratch \
    --pa 1-12 --batch 2 --seed 4362837462 --run-dir diag-replays/c-deploy
PYTHONPATH=. python -m tools.report.arm_diff --a diag-replays/c-base --b diag-replays/c-deploy
```

Ship `DEPLOY_NODE=True` only on >=15/24 pairs and a non-negative mean; then confirm on a second
seed. `DEPLOY_NODE` currently defaults **False** (inert).

---

## 18. Round 13 — the learned weights FIT, and then hit the real blocker

### The fit works (new tool: `tools/phases/fit_graph.py`)

Fitted `ops_today ~ sum_node w[node,op] * deviation(node) + bias` on his own board, per game-day,
**split BY GAME** (no trajectory leakage), non-negative least squares. 60 replays → 1,800 game-days:

| op | mean/day | held-out R² | weights |
|---|---|---|---|
| COLLECT_FERTILIZER | 13.8 | **+0.419** | 2 |
| CARE | 13.6 | **+0.332** | 3 |
| **WATER** | 35.2 | **+0.321** | 2 |
| HARVEST | 16.6 | +0.270 | 1 |
| FEED | 12.5 | +0.264 | 3 |
| **FERTILIZE** | 5.2 | **+0.224** | 3 |
| PLACE / PLANT / DIG / BUILD_* | — | +0.02…+0.10 | 2-4 |

**So his op mix IS a learnable function of his own deviation** — the premise of the nervous system
holds. The learned edges are also interpretable and economically sensible:
`WATER ← output_per_day 1.00 + revenue_per_day 0.24`, `FERTILIZE ← output_per_day 1.00 +
revenue_per_day 0.12 + unfed 0.01` — i.e. *capacity deficiency drives watering intensity*.

Shipped as `src/graph_weights.py` (codegen'd literals, per the single-file bundle rule), with
`docs/graph_weights.json` as the evidence, behind `GRAPH_WEIGHTS` (defaults OFF).

### And then: the pressures have NO LIVE ACTUATOR for crew ops

Three wiring attempts, all measured on the quick panel:

| attempt | result |
|---|---|
| raw NNLS coefficients (unnormalised: `WATER ← output_per_day 24.8`) | **−$21,722** (0/4) — saturates the pressure cap |
| normalised per op, pressing from `roots()` only | **byte-identical (+$0)** |
| normalised, pressing from `deviation()` (all nodes) | **byte-identical (+$0)** |

The second and third are the finding. `pressures()` feeds only:
* `emit.apply_to_market` — **market ops only**; WATER/FERTILIZE/FEED are not market ops;
* `crew.score` via `state_graph.pressures` — but `crew.score`'s output is consumed **only when
  `VALUE_KERNEL` is on, and `VALUE_KERNEL=False`** (measured harmful: $42,446 vs $58,899);
* `plan.allocation`.

So the graph's pressures have **no live path to a crew decision**. The one live graph actuator is
`deficit_jobs` (`GRAPH_DEFICIT_JOBS=True`), and it reads **`deviations`, not the learned weights**.
That is why every pressure-side change this session — the `deploy` node, the learned weights — is
either inert or, when forced, destructive.

### The remaining step, precisely stated

**Feed the learned weights into `deficit_jobs`** (the live actuator), not into `pressures` (which
nothing consumes for crew ops). Concretely: `deficit_jobs` should issue an op's jobs when the
learned edge gain clears a threshold, with the **quantity** from the learned model
(`w[node,op] · deviation(node)` → how many ops today), which is the "how much should this be for
optimal revenue in that step" the design calls for. Re-enabling `apply_to_jobs`/`VALUE_KERNEL` is
NOT the answer — both are measured-rejected in `AGENTS.md`, and the fit gives a quantity, not a
priority multiplier.

`GRAPH_WEIGHTS` ships **OFF** (inert). Everything is recorded here; the handover is: make
`deficit_jobs` the consumer of `graph_weights.W`.

---

## 19. Round 14 — `work_orders` is inert, and that completes the diagnosis

Implemented steps A+B of the plan: `state_graph.work_orders(state, jobs)` — the graph's general
crew actuator — issuing jobs for the ops whose **learned gain** clears zero
(`quantity = WO_SCALE * sum_node W[op][node]*(p-1)*u`, shortfall vs what the layers already issued),
on **real precondition objects only** (the `deficit_jobs` rule), inside a **crew-turn budget**
(`WORK_ORDER_TURN_FRAC`). Dispatched from `scheduler.plan` behind `WORK_ORDERS`, with
`deficit_jobs` kept as the DIG-only fallback so the two cannot double-issue.

**Measured on the quick panel (`WORK_ORDERS=1;GRAPH_WEIGHTS=1`): byte-identical to base, again
(63,593 / 35,986 — the same two games).**

The reason is the last missing fact, and it reframes the whole "nervous system" idea:

> **For WATER, HARVEST, FEED, CARE and COLLECT the layers ALREADY emit one job per precondition
> object.** `crop_plan.jobs` emits a WATER job for *every* thirsty tile; the demand view confirms
> these ops read "delivered". So the graph issuing *more* of the same jobs adds nothing — the
> shortfall is zero by construction.
>
> The ops that ARE undelivered (`PLANT`, `DIG`, the `BUY_*` market orders) are blocked by **layer
> gates** — the plant queue, the seed ask, the market truncation — not by a missing graph signal.

**So the graph's real leverage is ALLOCATION, not issuance**: crew turns are fixed
(`hands × 24`) and there are already more jobs than turns, so the decision that matters is *which
op class gets the scarce turns*. That is precisely what `apply_to_jobs`/`VALUE_KERNEL` tried and
what measured harmful — but both did it as a **priority multiplier**, layering a second ranking on
top of `job.py`'s. The corrected form is a **quota on turns per op class**: the graph computes
`turns[op]` from the learned weights and `_pick` treats it as a budget (spend it, then move on),
which caps allocation **without** re-ranking the survival bands.

### Where the project actually stands

| layer | state |
|---|---|
| graph computes deviation per node/day | ✅ shipped, health-clean |
| learned node→op weights from his 359 games | ✅ R² 0.22–0.42, `src/graph_weights.py` |
| graph acts on the market | ✅ `apply_to_market` |
| graph issues crew jobs | ✅ `work_orders` — but **redundant** for the ops the layers already supply |
| graph **allocates** the scarce crew turns | ❌ **this is the one thing left** |
| three measured wins this session | A1 p=0.0066, A2 p=0.0003, A6 p=0.0000 |

**The single remaining lever is a per-op turn BUDGET driven by the learned weights** — a cap, not a
re-ranking. Everything else is either shipped, measured-rejected, or shown redundant. That is the
handover; `WORK_ORDERS` ships OFF.

---

## 20. Round 15 — the turn budget, first cut: cap-per-class starves the crew

Implemented `state_graph.turn_budget(state)` — `op -> jobs allowed per turn`, from the learned
weights (`per_day(op) = WO_SCALE * sum_node W[op][node]*(p-1)*u`, divided by 24) — and applied it in
`scheduler.plan` as a **cap on the jobs list per op class**, preserving order so `job.py`'s survival
bands still decide who takes what. This is the "cap, not a re-ranking" form.

**Measured on the quick panel: median −$32,378, 0/4, `idle_share` 40.4 % (from ~4 %), idle_units
2,795.**

Two bugs found on the way, both real:

1. **`src/graph_weights.py` had an UNTERMINATED DOCSTRING** (the normalising re-codegen dropped the
   closing `"""`). `state_graph` imports it lazily inside a `try/except`, so the `SyntaxError` was
   swallowed and `turn_budget` silently returned `{}` — the first version of the cap was inert for
   the same reason `deploy_pressure` was. Fixed.
2. **The cap shape is wrong.** The learned per-day quotas for these ops are small (2–3/day), so
   `round(per_day/24)` floors to **1 for all eleven op classes**. Eleven jobs per turn against ~12
   units means the crew runs out of work and idles at 40 %.

### The correction (one line of design)

The budget must be a **SHARE OF THE CREW**, not an absolute per-turn count:

> `cap[op] = ceil(n_units * gain[op] / sum(gain))`

so the caps **sum to the crew size** and every unit has exactly one job class to take. That is the
allocation the design is after — the graph divides the crew across op classes by the learned
weights — and it cannot starve the crew by construction, because the shares are normalised to the
number of units.

Everything else in §19's diagnosis stands: the layers already supply one job per precondition
object, so allocation (not issuance) is the lever, and a cap cannot re-rank the survival bands.
`TURN_BUDGET` ships **OFF**; the handover is the normalised-share cap above.
