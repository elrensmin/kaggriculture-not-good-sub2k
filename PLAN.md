# PLAN — Fix measurement first, then evolve the tape (v2) lever by lever

Status: **ready for review**. Evidence from `diag-replays/sweep_old_s42_b3/`
plus instrumented re-runs of the env. Decisions from the user:

1. Start by **hand-patching** the existing schedule (v2 = variant of v1);
   tape *generation* is the stated longer-term direction.
2. **Fix measurement before touching the tape.**
3. Use `diagnose.py --tape {v1,v2}` to A/B two tape modules *before* wiring v2 in
   via import. `main.py` stays frozen unless a change is promoted.
4. Work **one lever at a time**, changing → verifying across seeds × all 13
   public agents → only then moving on.

## Context

`main.py` is a route-replay chassis: 45 layers wrap a pre-computed 719-step
tape. `_router` (main.py:733) picks the tape from **the first two shops**
(`unlocked_shops[:2]`, day 6) and the tape is replayed; farm/hand actions follow
it ~98.7% (farmer 709/718, market 596/718). The rest is market micro-timing.

`route_tape_v2.py` is currently **byte-identical** to `route_tape.py`
(`md5 fc29a5de…`); `main.py:722` imports `route_tape`.

### The key measured fact (shapes the whole plan)

seed42 vs `master-engine-v3`, instrumented committed sells — **identical
quantities both seats**:

| item | our qty | our avg | opp qty | opp avg | base |
|---|---|---|---|---|---|
| WHEAT | 407 | $40.6 | 406 | $40.6 | $25 |
| MILK | 145 | $36.1 | 145 | $36.1 | $160 |
| WOOL | 259 | **$121.6** | 259 | **$122.7** | $200 |
| FERTILIZER | 310 | **$43.8** | 310 | **$45.0** | $100 |
| STRAWBERRY | 246 | $121.1 | 246 | $120.7 | $120 |
| MELON | 72 | $198.2 | 72 | $198.2 | $250 |

→ That opponent runs the **same tape**. The game is a symmetric
prisoner's-dilemma equilibrium; the entire margin (91678 vs 92166, ~$490) is
**micro price capture** on wool/fertilizer — who sells earlier in the decay
curve. Against a *different* opponent (`cloning-agent`) the numbers diverge
completely (WHEAT 3,592; CARROT 178 at $95; EGG 160; WOOL only 99), so the plan
must be validated across all opponents, not one.

## Findings

### Tier 1 — measurement/software defects (blockers)

- **F1. Market metrics count *requested* qty, not *committed*.** The tape uses
  sentinel `SELL <item> 1000` = "dump everything"; `build_days` sums the raw qty,
  so `sell_qty_*`/`floor_sales_*`/`below_base_sales_*` are ~40× inflated.
  Proof: `sell_qty_FERTILIZER=10,324` vs max supply ≈434; `sell_qty_EGG=8,018`
  with **0 geese placed**. Truth (seed42/master): committed units are
  `WHEAT 407, CARROT 96, TOMATO 80, STRAWBERRY 246, MELON 72, EGG 0, MILK 145,
  WOOL 259, FERTILIZER 310`.
- **F2. `main.py` is not import-idempotent.** Fresh process:
  `load_old_agent(fresh=False)` → **91882**, `fresh=True` (reload) → **91678**,
  same seed/opponent. First divergence is a pure **market-order reorder** at
  agent call 312 (`SELL FERTILIZER 13, WOOL 4` vs `SELL WOOL 4, FERTILIZER 13`).
  The market is order-sensitive per-unit, so this cascades. Given the clone
  finding above, this ~$300-500 wobble **is** the deciding margin. Harness
  masks it via `fresh=True`; suspects `_r37_reorder_sales`/`_r37_quote_priority`
  (main.py:1580,1606).
- **F3. `idle_steps` is meaningless (always 4)** — needs all units PASS **and**
  `market == []` (diagnose.py:618). Real idleness is unit-level: we measured
  **125 PASSes standing on a ready tile**.
- **F4. "Overflow days" ≠ discards.** `max_shed_total>=100` fires 3 days, but
  instrumented actual discards are **19 units/season** total.

### Tier 2 — business/market defects

- **F5. Premium "glut" goods realise a fraction of base** (instrumented, seed42):
  MILK $36 (0.23×), FERTILIZER $44 (0.44×), WOOL $122 (0.61×), MELON $198
  (0.79×); while scarcity goods earn premia: TOMATO 2.10×, CARROT 1.66×,
  WHEAT 1.62×. Observed price collapse: MILK→$1 by day 19, WOOL→$1 by day 25,
  FERTILIZER→$4 by day 29; CARROT→$63, TOMATO→$106-128, WHEAT→$39-44.
  **Caveat:** vs a clone this is symmetric — it is a *mix* defect, not a
  *timing-only* defect, unless we break symmetry.
- **F6. Route selected from only the first two shops.** Seed42 drew
  `YARN_STORE, BAKERY, FARMERS_MARKET×4, ICE_CREAM_SHOP` → route 9 (yarn); yet
  4× Farmers Market + Ice Cream demand carrot/tomato/strawberry/milk, and the
  tape planted only **36 carrot / 10 tomato**, both ending at 1.66×/2.10× base.
  Also `_router` forces route 9 for any yarn pair via `_V92_TABLE`, and
  `_V93_ROUTE_BY_RIVAL` (keyed on rival money+wheat at step 2) can redirect it.
- **F7. Milk enterprise marginal:** 6 cows → $5.2k milk revenue vs $2.4k animals
  + feed; market can't absorb milk.

### Tier 3 — farm/tape microstructure

- **F8. Wheat yield 3.59 mean vs 4 (watered) / 6 (fertilized).** 158 plantings,
  dist {2:28, 3:53, 4:50, 5:9, 6:18}; in-window waters ≈2.25/3. ~119 wheat
  (~$4.8k) unclaimed.
- **F9. Fertilizer allocation is incidental.** 369 collected + 65 bought, only
  **113 applied** (27 wheat, 61 strawberry, 20 tomato, 5 carrot); ~321 sold at
  $44. Applying to the 131 unfertilised wheat tiles = +2 wheat each (~$80) vs
  $44 sold → ~$4-5k available, labour permitting.
  **Correction:** `agent.py`'s note that fertilising ongoing crops is
  "yield-capped / worthless" is **inconsistent with observed data** —
  strawberry mean harvest is 1.92 (the fertilised 2/production) and 33 plantings
  produced ~249 units ≈7.5/planting. Re-verify before trusting that note.
- **F10.** 19 overflow discards; 125 PASS-on-ready; EGG sells scheduled with
  **0 geese** (dead order slots).

## Co-design reading

- **Business** = demand model (shop multiset → per-product demand → mix + sell
  windows). **Software** = replay chassis + layers. Today a *static memoised
  lookup* keyed on 2 shops drives a *dynamic shared market*; layers patch
  symptoms at the margin, the macro plan is frozen.
- Two mismatches: **(i) selection** — the tape should be chosen from the full
  shop multiset with a demand forecast, not the first two shops; **(ii)
  execution** — selling is a scheduling/race problem and fertilizer an
  allocation problem, not a fixed ladder.
- **Design constraint discovered:** against a same-tape clone, macro changes
  break symmetry and can gain, but timing-only changes just trade margin. So
  each lever's hypothesis must say whether it wins *symmetrically* (better
  allocation) or *asymmetrically* (racing a clone).

## Approach (staged, one lever at a time)

**Phase 0 — truthful measurement (no agent change).**
Commit-quantity + discard instrumentation in `diagnose.py`; per-item realised
price vs base; unit-level idle metric. Re-run the baseline sweep so replays
carry the audit.

**Phase 1 — determinism + tape plumbing.**
Regression anchor (seed42/master == 91678); locate/guard F2; add
`diagnose.py --tape {v1,v2}` that swaps `main._ROUTES`, `main._R108_SHOP_ROUTES`,
rebuilds `main._IMPL` with `main._router`, recomputes `main._ALT_RAW`, clears
`chassis._future_sells`, and records the tape name in replay metadata.
Smoke-test: `--tape v1` must be bit-identical to `--old`.

**Phase 2 — levers, in this order** (cheapest/most isolated first; each is a
separate v2 revision, kept only if it passes the gate):

- **L1. Sell-timing / price capture (F5-race).** Hypothesis: against clones we
  sell wool/fertilizer marginally later in the decay; moving the tape's sell
  steps earlier (or fixing order sequencing) recovers ~$1/unit. Isolated edits to
  `market` ladders in v2, farm plan untouched. Targets: `avg_price/base` for
  WOOL/FERTILIZER and head-to-head vs same-tape opponents.
- **L2. Router / crop-&-animal mix (F6/F7).** Remap `SHOP_ROUTES` in v2 to use
  the full shop multiset (and test new v2 routes), plus reduce the milk line.
  Targets: units + realised price of CARROT/TOMATO/EGG/WHEAT vs the F5 table.
- **L3. Farm labour & fertilizer (F8/F9).** Rewrite worker actions in v2:
  fertilise the 131 wheat tiles, close the in-window water gap. Targets: wheat
  mean yield, fertilizer applied vs sold, and no new misses.
- **L4. Micro-cleanups (F10):** remove dead EGG orders; re-time the 125
  PASS-on-ready; keep discards ≤19.

## Files to modify

- `diagnose.py` — F1/F4 audit, per-item price/idle columns, `--tape` flag,
  anchor check, metadata.
- `route_tape_v2.py` — the tape under test (one lever per revision).
- `agent.py` — only for patch-layer experiments that `--tape` can't express.
- `main.py` — **frozen**; anything requiring it (e.g. an F2 fix, native v2
  import, `_V92_TABLE` unblock) is raised for approval, not done silently.

## Reuse

- `diagnose.py`: `replay_to_summary`, `build_days`, `summarize`, `_day_columns`,
  `game_summary`, `write_run_csv`, `batch_run`, `compare_batch`,
  `load_public_agent`, `load_old_agent(fresh=True)`, `run_game`, `_make_seeds`,
  `save_replay`, `load_replay`.
- Env: `_commit_unit`, `_process_market`, `market_price`, `_apply_unit_action`,
  `_drop_inventories_to_shed`, `CROPS`, `ANIMALS`, `MARKET_PARAMS`.
- Agent: `main._IMPL.chassis.routes`, `chassis._future_sells`,
  `main._R108_SHOP_ROUTES`, `main._router`, `main._ALT_RAW`,
  `route_tape.ROUTES/SHOP_ROUTES`.

## Steps

- [x] **P0.1** `_MarketAudit` context manager in `diagnose.py` (wrap
      `_commit_unit` / `_apply_unit_action` / `_drop_inventories_to_shed`),
      recording per-step, per-seat committed sells `(item, qty, price)` and
      discards.
- [x] **P0.2** `run_game(..., audit=True)`; persist the audit in
      `_diagnose_meta`; `build_days` prefers committed qty and adds
      `sold_committed_{p}`, `revenue_{p}`, `avg_price_{p}`, `discards_{p}`,
      `sell_qty_source`, `idle_units_ready`.
- [x] **P0.3** Re-run baseline sweep (`./sweep.sh old`); assert EGG committed==0,
      FERTILIZER≈310 for seed42/master, and floor/below match instrumentation.
- [ ] **P1.1** Add a regression anchor (seed42/master == 91678, twice in-process
      identical); fail loudly if it drifts.
- [ ] **P1.2** Bisect F2: log the pre-sort inputs of `_r37_reorder_sales` at call
      312 in both modes; fix or guard (guard-only if it needs `main.py`).
- [ ] **P1.3** `--tape {v1,v2}` plumbing + `--tape v1` bit-identity smoke test.
- [ ] **P2.L1** Sell-timing revisions in v2 + gate.
- [ ] **P2.L2** Router/mix revisions in v2 + gate.
- [ ] **P2.L3** Labour/fertilizer revisions in v2 + gate.
- [ ] **P2.L4** Micro-cleanups + gate.
- [ ] **P3** Promote accepted revisions (v2 → import), update AGENTS.md/README.

## Verification (the gate — apply identically to every lever)

1. **Anchor first:** `python diagnose.py --old --pa 2 --batch 1 --seed 42` must
   print `91678 / 92166`; identical on a repeat run in the same process.
2. **A/B across the board:** `./sweep.sh` for baseline and candidate over all 13
   public agents × ≥3 seeds (39 games each), plus an explicit same-tape clone
   head-to-head (`--pa 2`-style) to isolate the $/unit timing margin.
3. **Per-game defect checklist, never an average** (per AGENTS.md): for each
   game diff baseline vs candidate on — final money; committed revenue; realised
   `avg_price/base` per item; floor/below-base committed units; discards;
   `plants_died`; animal escapes; unfed signals; `idle_units_ready`.
4. **Accept only if** the *targeted* defect improves in the large majority of
   games **and** no game acquires a new structural defect (no new escape,
   overflow, or floor dump). Otherwise revert v2 to the last accepted revision.
5. Record which games regressed and why before moving to the next lever.
