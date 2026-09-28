# `docs/v0/` manifest — fresh run, 2026-09-27

Every file here is raw tool output for the **current** agent (`src/`, tree defaults,
`git rev 694e48aa8cccd71d16915186e16629331d9755cc`), regenerated from scratch because
`diag-replays/` had been emptied. Nothing in this directory is a hand-typed number.

## Addendum — phase-2 crew/visit round (later the same day)

Two phase-scoped defaults shipped after this snapshot, so the `config` row below is one
round stale: **`MAX_HIRE_PER_TURN_P2 = 6`** and **`SAME_TILE_ANIMAL_CHAIN_P2 = 1`**
(§3.1g). Phase 1 is bit-identical — re-measured in `sc-p1-shipped16.txt`.

| file | command | what it shows |
|---|---|---|
| `sc-p2-shipped16.txt` | `phase_map --phase phase2 --pa 1-4 --batch 4 --ref-from replays/Boey/v1 --ref-max 40 --team Boey` | the phase-2 table in §3 after the round |
| `sc-p1-shipped16.txt` | same, `--phase phase1` | the no-regression guard |
| `chain-shipped.txt` | `op_patterns --days 6-17 --dir diag-replays/p2-shipped --dsm-dir replays/Boey/v1 --dsm-max 4` | FEED chained 21.3 % → **56.0 %**, moves/act 1.58 → **1.52** |
| `walk-shipped.txt` | `walk_runs --days 6-17 --dir diag-replays/p2-shipped --compare-dir replays/Boey/v1 --compare-seat auto` | 3,073 walks / 7,341 tiles / mean 2.39 vs Boey 2,895 / 5,650 / 1.95 |
| `sc-fast-*.txt` | `phase_map --phase phase2 --pa 2,5 --batch 2 --ref-from replays/Boey/v1 --ref-max 20` | the 4-game screen arms: `h4 h6 h12 h4m55 h4hm14 h6ac h6acm55 h12ac ctl dist2 dist3 onb60 pb3 pb5 pb8` |

`tools/labour/walk_runs.py` is new: it reports the distribution of consecutive-MOVE run
lengths (a walk of k tiles) and the act that started each walk, which is how the "we walk
12 % farther per trip and 15 % more often than Boey" reading was obtained.

## Addendum 2 — the money round (2026-09-28)

Phase 2 had **no revenue node at all**; `dag.py` now has `revenue2` (gross, descriptive) and
`trade_net2` (the exact ledger identity, judged). Four new instruments, all seat-symmetric
so a public agent and we are measured by the same code:

| file | tool | what it shows |
|---|---|---|
| `phase2-revenue-96.txt` | `tools.report.phase_revenue --days 6-17 --dir step10-pre --compare step10-ship` | our d6–17 revenue **$33,434 → $42,670**, trade net **$31,254 → $37,224**, vs the field's $61k |
| `phase2-sells.txt`, `phase2-sells-vs-public.txt` | `tools.report.phase_sells --days 6-17 ...` | per-item sell/buy/net. **Read the caveat**: the SELL estimate is capped by the shed and under-counts an opponent that over-orders |
| `ready-by-crop.txt`, `ready-by-crop-boey.txt` | `tools.labour.ready_by_crop --days 6-17 ...` | ripe tiles at hour 0 / harvested / still ripe at hour 23, per crop — **strawberry: 16.2 tiles standing, 0.32 ripe per day** |
| `water-geometry.txt` | `tools.labour.water_geometry --days 6-17 ...` | demand set shape: ours 148 tiles / 2.80 per cluster / 21 % isolated / 95 % watered vs Boey 184 / 4.10 / 8 % / 97 % |
| `wheat-flow-p2.txt` | `tools.labour.wheat_flow --days 6-17 ...` | wheat fed/sold/bought and the per-day standing-tile ramp |
| `sc-p2-r1.txt`, `sc-p1-r1.txt` | `phase_map --phase phase2/phase1 --pa 1-4 --batch 4 --ref-max 60` | the tree after this round: phase 2 unchanged from `sc-p2-shipped16.txt`, phase 1 bit-identical |
| `sc-sp-*.txt`, `sc-ba-*.txt`, `sc-og-*.txt`, `sc-tm-*.txt` | 4-game screens | the rejected arms of §3.1h |
| `sc-cf-*.txt`, `sc-hh-*.txt`, `sc-ex2-*.txt`, `sc-lr-*.txt`, `sc-mo-*.txt`, `sc-fe-*.txt` | 4-game screens | the 14 rejected arms of §3.1i (the knob search is exhausted) |
| `r2-season-armdiff.txt`, `r2-phase2-revenue.txt` | `arm_diff` + `phase_revenue` on `diag-replays/r2-g0` vs `r2-g1` | **the midgame trade net predicted the season**: −$2,986 midgame vs −$14,954 median season (3/16, p=0.021) |
| `production-p2.txt` | `tools.labour.production --days 6-17 ... --ref-from replays/Boey/v1` | output per tile-day and per animal-day from shed inflow: **we out-produce the reference ~2x on every animal line**, 0.58x strawberry, 0 tomatoes/carrots |
| `herd_gate_r3.txt` | `tools.phases.herd_gate --pa 1-4 --batch 4 --days 6-17` | the feed gate fails **every day d11–d17** with $18,546 idle at d17 |
| `sc-tm2-*.txt`, `sc-hc-*.txt` | 4-game screens | the rejected arms of §3.1j |
| `wheat-cycle.txt` | `tools.labour.wheat_cycle --days 6-17 ... --ref-from replays/Boey/v1` | our wheat 2.94 units at age 4 on a 4-day cycle (0.75/tile-day); the reference 3.90 at age 3.2 (1.15) with 35 % fertilised harvests |
| `sc-fc-*.txt`, `sc-cf2-*.txt`, `sc-wp-*.txt` | 4-game screens | the rejected arms of §3.1k (incl. the band-remap no-op) |
| `herd_gate_w45.txt` | `tools.phases.herd_gate` with `WHEAT_TARGET=45;STRAWBERRY_TARGET=8` | the wheat requirement scales with the herd — a treadmill |
| `sc-wt-*.txt`, `sc-hsc-*.txt`, `sc-comp-*.txt` | 16-game screens | §3.1l: the shed-wheat credit and its compositions — animals 16 → 18, net −$2,072 |
| `r5-season-armdiff.txt` | `arm_diff` on `r5-g0` vs `r5-g1` | season margin for the best round-5 composition |
| `sc-wh2-*.txt`, `sc-wh3-*.txt`, `sc-hd-*.txt`, `sc-sl-*.txt`, `sc-g1t-*.txt`, `sc-f6-*.txt` | 16-game screens | §3.1m: the herd-target / wheat-target / ratio / shed-limit portfolio search |
| `r6-season-armdiff.txt`, `r6-phase2-revenue.txt` | `arm_diff` + `phase_revenue` on `r6-g0` vs `r6-g1` (straw 15) | midgame +$6,399 revenue, +$2,736 net, season **−$7,664** |
| `r6b-season-armdiff.txt`, `r6b-phase2-revenue.txt` | same on `r6b-g0` vs `r6b-g1` (straw kept) | midgame +$5,643 revenue, +$1,757 net, season **−$6,539 (3/16, p=0.021)** |
| `r6b-{g0,g1}-p3.txt` | `phase_map --phase phase3 --replay-dir diag-replays/r6b-<arm>` | phase-3 cause: **animals at the bell 17 → 22** (target 15), HARVEST/planted 1.22 → 1.57 |
| `r7-season-armdiff.txt`, `r7-phase2-revenue.txt` | `arm_diff` + `phase_revenue` on `r7-g0` vs `r7-g1` (reserve P2-only) | phase-scoping the reserve made the season **worse**: −$14,004 (2/16, p=0.0042) |
| `sc-r7-*.txt` | 16-game screens | the phase-scoped-reserve arms of §3.1n |
| `sc-mix-*.txt` | 16-game screens | §3.1o: herd composition shifted off GOOSE — no effect |
| `p3-water.txt`, `p3-ready.txt` | `water_geometry`/`ready_by_crop --days 18-29` | §3.1q: phase-3 water demand **46 vs Boey's 189** — the farm ages out |
| `step13-armdiff.txt`, `step13-phases.txt` | `arm_diff` + phase split on `step13-pre` vs `step13-ship` (96 games) | §3.1s: `MAX_HIRE_PER_TURN_P3` — **+$6,758, 94/96, p=0.0000**, phase-isolated to p3 |
| `step13b-armdiff.txt`, `step14-armdiff.txt` | 96-game confirms | §3.1s: hire-first P3 (+$5,342 — worse) and `SAME_TILE_ANIMAL_CHAIN_P3` (byte-identical — inert) both rejected |
| `sc-phase{1,2,3}-r12.txt` | `phase_map --phase phase1/2/3` | post-fix guards: p1 and p2 byte-identical; p3 HARVEST 162 → 192, WATER 126 → 198 |
| `r11-{wf,wfh,hc}-vs-shipped.txt` | `arm_diff` vs `r7-g0` | §3.1r: ready-tile watering and critical harvest in phase 3 — worse or noise |
| `r10-d{60,90,120}-vs-shipped.txt`, `r10-d{60,90,120}-p3.txt` | `arm_diff` + `phase_map --phase phase3` | §3.1q: `P_DIG_P3` — weeds fall 42.5 → 9.5 and the money falls monotonically; +$480/10-16 at 60 is inside noise |
| `r10-{e23,e24}-vs-shipped.txt`, `r10-{e23,e24}-p3.txt` | `arm_diff` + `phase_map --phase phase3` | §3.1q: extended crop calendar — **0/16, p=0.0000**, a consistent loss |
| `r10-{b30,b60,b90}-vs-shipped.txt` | `arm_diff` vs `r7-g0` | §3.1p: lowering the sell ceiling — no-op / noise / worse; the milk trap has no sell-side escape |
| `r9-{g1,g2,b40,b120}-vs-shipped.txt` | `arm_diff` vs `r7-g0` | §3.1p: `SELL_TRICKLE_FRACTION_P3`, `TRICKLE_P3` and `SELL_CEILING_BOOST` on the portfolio — **all inert** (−$14.0k vs shipped) |
| `phase2-revenue-96.txt` (paired block), `r6b-phase2-revenue.txt`, `r7-phase2-revenue.txt` | `tools.report.phase_revenue ... --compare` | §3.1o: the **paired** revenue/net readout, and the round-1 arm re-confirmed at **+$6,936 revenue / +$4,794 net, 96/96** |
| `sc-p2-r2.txt`, `sc-p1-r2.txt` | `phase_map --phase phase2/phase1 --pa 1-4 --batch 4 --ref-max 60` | post-round-2 audits, **byte-identical** to `sc-p2-r1.txt`/`sc-p1-r1.txt` |


| field | value |
|---|---|
| **ours** | `diag-replays/v1-us` — `python -m tools.diagnose --scratch --pa 1-12 --batch 8 --seed 4362837462` = **96 games**, 12 public opponents × 8 seeds, `agent=scratch` |
| **config** | current tree defaults, **no `SCRATCH_PARAMS`**: `MOVE_WEIGHT=20`, `DIST_CAP=1`, `HERD_ENABLED=True`, `HERD_BUY_UNTIL=12`, `HERD_BUY_FROM_DAY=0`, `OPENING_SCRIPT=True`, **`OPENING_TAPE=True`** (the d0–d5 opening tape is the shipping default), **`OPENING_TAPER_BOEY=True`** + **`OPENING_HERD_BOEY=True`** (the measured Boey script), **`SAME_TILE_FIRST=True`** at `SAME_TILE_MIN_PRIORITY=70`, **`P_WATER_BONUS=120`** (now a real param; was a bare 50 in `job.py`), **`MAX_HIRE_PER_TURN=1`**, **opening crew 5**, `OPENING_WHEAT_KEEP_DAYS=2`, `OPENING_OWNS_SELLS=False`, **`TRADE_ENABLED=True`** (the wheat carry, `src/trade.py`: buy at `base+4`, sell at `base+4`, `TRADE_FROM_DAY=1`), `STRUCTURE_HOLDBACK=12`, `PLANT_RAMP=True`, `FERTILIZE_FROM_DAY=99`, `CROP_SCALE=1.0`. Snapshot in `config.txt`/`HEAD.txt`. |
| **DSM** | `replays/DSM/v1` — **123 replays / 122 episodes** (+1 self-play), 66 opponents. Every tool that samples DSM is passed `--dsm-max 123` or `--max 0` (note: `--dsm-max 0` is an **empty** slice). |
| **audit** | ours audit-backed; DSM leaderboard replays carry **no market audit**, so `sell_revenue_*`, `avg_price_*`, `discarded_*`, `land_cost_*` are 0/modelled for DSM. |

## Files

| file | command | n ours / dsm |
|---|---|---|
| `HEAD.txt`, `config.txt` | `git status` / `git diff src/params.py` / import check | — |
| `sweep-run.txt` | `tools.diagnose --scratch --pa 1-12 --batch 8 --seed 4362837462` | 96 / — |
| `margin.txt` | `tools.gates.margin diag-replays/v1-us` | 96 / — |
| `dsm_profile.txt` | `tools.report.dsm_profile --compare --run-dir diag-replays/v1-us --agent scratch` | 96 / 123 |
| `day_gap.txt` | `tools.report.day_gap --ours diag-replays/v1-us --ours-agent scratch` | 96 / 123 |
| `movement.txt` | `tools.labour.movement --dir diag-replays/v1-us --glob 'scratch_vs_*.json' --dsm-max 123` | 96 / 123 |
| `op_patterns.txt` | `tools.labour.op_patterns ... --dsm-max 123 --day 12 --unit 0` | 96 / 123 |
| `ready_idle.txt` | `tools.labour.ready_idle --dir diag-replays/v1-us --dsm-max 123` | 96 / 123 |
| `missed_work.txt` | `tools.labour.missed_work ... --summary-only` | 96 / — |
| `idle_pool.txt` | `tools.labour.idle_pool ... --summary-only` | 96 / — |
| `leverage.txt` | `tools.labour.leverage ... --horizon 8` | 96 / — |
| `visit_trace.txt` | `tools.labour.visit_trace --dsm diag-replays/crew-dsm --us diag-replays/crew-us --phase 2` | 96 / 123 |
| `move_trace.txt` | `tools.labour.move_trace --dir diag-replays/v1-us --glob '*.json' --max-games 12 --compare --dsm-max 123` | 12 / 123 |
| `wheat_flow.txt` | `tools.labour.wheat_flow --days 0-29 --dir diag-replays/v1-us --max-games 12 --compare --dsm-max 123` | 12 / 123 |
| `crew_patterns.txt`, `crew_chains.txt` | `tools.report.crew_patterns --dsm diag-replays/crew-dsm --us diag-replays/crew-us` (+ `--chains --phase 2`) | 96 / 123 |
| `crop_demand.txt` | `tools.market.crop_demand --dir diag-replays/v1-us --dsm-max 123` | 96 / 123 |
| `discards.txt` | `tools.market.discards --dir diag-replays/v1-us --dsm-max 123` | 96 / 123 |
| `sell_price.txt` | `tools.market.sell_price --dir ... --glob 'scratch_vs_*.json' --seat 1 --summary` | 96 (both seats) |
| `floor_sell.txt` | `tools.market.floor_sell --dir ... --glob 'scratch_vs_*.json' --seat 1 --summary` | 96 |
| `shop_response.txt` | `tools.market.shop_response --dir diag-replays/v1-us` | 96 |
| `footprint.txt` | `tools.report.footprint --compare --run-dir diag-replays/v1-us --max-games 96` | 96 / 96 |
| `herd_hold.txt` | `tools.report.herd_hold --compare --run-dir diag-replays/v1-us --max-games 96` | 96 / 96 |
| `herd_econ_us.txt`, `herd_econ_dsm.txt` | `tools.report.herd_econ --dir <arm> --max 0 --seat 1 --label US` / `--dir replays/DSM/v1 --max 0` | 96 / 123 |
| `ring_occupancy_us.txt`, `ring_occupancy_dsm.txt` | `tools.report.ring_occupancy --dir <arm> --max 0 --seat 1 --label US` / `--dir replays/DSM/v1 --max 0` | 96 / 123 |
| `fertilizer_flow_us.txt`, `fertilizer_flow_dsm.txt` | `tools.market.fertilizer_flow --dir <arm> --max 0 --seat 1 --label US` / `--dir replays/DSM/v1 --max 0` | 96 / 123 |
| `dsm_flows.txt` | `tools.report.dsm_flows --dir replays/DSM/v1 --summary --max-games 123` | — / 123 |
| `phase1.txt`, `phase2.txt`, `phase3.txt` | `tools.phases.phase_map --phase <p> --pa 1-12 --batch 2 --ref-from replays/DSM/v1 --ref-max 123` | 24 live / 123 ref |
| `sc-cur-tape-dsm.txt` | `phase_map --phase phase1 --pa 1-12 --batch 2 --ref-from replays/DSM/v1 --ref-max 123` with the current default (**`OPENING_TAPE=True`**) | 24 live / 123 ref |
| `sc-cur-tape.txt` | same, `--pa 1-4 --batch 4 --ref-from diag-replays/boey-lb --ref-max 60` (Boey reference, 16 games) | 16 live / 60 ref |
| `sc-p1-boeyscript.txt` | the Boey-script screen before the water cluster (PLANT 27 / WATER 53 / animals 7) | 16 live / 60 ref |
| `sc-p1-water.txt` | **the current Phase-1 readout**: `phase_map --phase phase1 --pa 1-4 --batch 4 --ref-from replays/Boey/v1 --ref-max 60 --team Boey` with the shipped defaults (PLANT 29 / WATER 68 / animals 8 / idle 8.91 / **revenue $7,086 vs $11,624 = 0.61x** / **trade net $2,443 vs $2,438 = 1.00x ok**) | 16 live / 60 ref |
| `sc-season-trade.txt`, `sc-season-notrade.txt` | `phase_map --days 0-29 --pa 1-4 --batch 2 --ref-from replays/Boey/v1 --ref-max 60` with the all-season carry ON vs `TRADE_ENABLED=0`; shows the season revenue gap is production-led (HARVEST 245 vs 540) | 8 live / 60 ref |
| `sc-p1-water-dsm.txt` | the same tree against `--ref-from replays/DSM/v1 --ref-max 123` | 24 live / 123 ref |
| `sc-p2-current.txt` | **the current Phase-2 readout**: `phase_map --phase phase2 --pa 1-4 --batch 4 --ref-from replays/Boey/v1 --ref-max 60 --team Boey` — animals 13/21, WATER 248/464, weeds 27/0, shed peak WARN. Anchored to Boey (no DSM column) | 16 live / 60 ref |
| `herd_gate_before.txt` | `tools.phases.herd_gate --pa 1-4 --batch 4 --days 6-17` — the three-gate herd probe (§3.1b) | 16 live / — |
| `sc-w1-*.txt`, `sc-w2-*.txt`, `sc-w3-*.txt`, `sc-w4-*.txt` | the Phase-2 workstream screens (W1 herd ramp, W2 water/attrition, W3 fertilize, W4 harvest) | 16 live / 30-60 ref |
| `sc-w1-guard.txt`, `sc-w2-guard.txt`, `sc-w3-guard.txt` | the Phase-1 guards for each shipped W-step | 16 live / 30 ref |
| `sc-p1-chain.txt` | the `SAME_TILE_MIN_PRIORITY=0` chaining arm — the regression that the 70 threshold fixes (MELON 9→7, empty 3.5→5, idle 0.78→11.0) | 16 live / 60 ref |
| `sc-p1-base.txt` | the same 16-game Boey screen with the pre-tape defaults (`OPENING_TAPE=0`) | 16 live / 60 ref |
| `phase_all_vs_dsm.txt` | same, `--phase all ... --spread` | 24 live / 123 ref |
| `phase_dag.txt` | `tools.phases.phase_map --dag` | — || `phase_dsm_selfcheck.txt` | `tools.phases.phase_map --phase all --replay-dir replays/DSM/v1 --max-games 123 --seat auto` | — / 123 |
| `probe-fert.txt` | `SCRATCH_PARAMS='FERTILIZE_FROM_DAY=6'` arm vs baseline, `tools.report.arm_diff` | 96 paired |
| `probe-herd5.txt` | `SCRATCH_PARAMS='HERD_BUY_UNTIL=5'` arm vs baseline, `tools.report.arm_diff` | 96 paired |
| `crew-dsm/`, `crew-us/` (in `diag-replays/`) | `tools.labour.crew_extract` work-stream caches | 123 / 96 |

## Read this before quoting a number

1. **Run-dir names.** `v1-us` is the fresh **current-default** arm. The old `v0-us` arm
   (`SCRATCH_PARAMS='PLANT_RAMP=0;MOVE_WEIGHT=0'`, 0W–96L, zero animals) no longer exists on
   disk; every historical number that referenced it is superseded. `archive-2026-09-26/`
   holds the pre-herd raw logs, kept only as provenance.
2. **`land_cost_total` is not trustworthy** on either arm (reports $10,000 against a $7,000
   ceiling; the order is re-issued and re-charged). Do not quote it.
3. **`herd_hold.txt` "ours" selling block is unreliable** — it reports our WOOL/MILK/EGG
   units as 0 and `wheat_fed=0`, contradicting the audit-backed `dsm_profile.txt`,
   `wheat_flow.txt` and `fertilizer_flow_us.txt`. Use the audit-backed tools for our herd
   revenue; `herd_hold`'s herd *counts* match.
4. **Act/observation pairing is off by one** in the harness CSVs; `op_patterns`,
   `ready_idle`, `move_trace`, `visit_trace` and `crew_patterns` use the corrected shifted
   form. Tile-conditioned CSV columns are indicative only.
5. **The shop draw is a function of our own play** (`_spawn_weeds` shares the RNG stream).
   Our fresh arm draws YARN_STORE in **95/96** games against DSM's 78/123, so no
   shop-conditioned comparison across the two arms is controlled. `shop_response.txt`
   prints the mix first.
6. **`--dsm-max 0` returns nothing** for the `[:N]` tools; all DSM sampling here uses an
   explicit `123` or a tool whose `0` means all.
7. **Reference revenue is an ESTIMATE, and it was zero before this run.** Leaderboard replays
   (DSM/Boey) carry no market audit, and `tools/diagnose/analysis.py` never populated
   `revenue_per_item` on the non-audit path — so every reference reported `revenue_<p>` = 0.
   `phase_map.extract` now values each SELL order at the step's observed quote, capped by the
   shed and `MAX_ORDERS`, for **both** arms. Validated on our 96 audit-backed games: median
   ratio **0.970** (p10 0.967, p90 0.974). Two consequences: the reference figure is a
   **lower bound** for a market-making team like Boey (his intraday buy/resell churn is
   invisible to the shed cap), and the DAG's `d0-d5 sell revenue` node is a new BAD node that
   earlier read 0 for everyone.
8. **DAG nodes can be `descriptive`.** `M(..., descriptive=True)` reports a metric without
   judging it. `d0-d5 sell revenue` is the case: gross turnover *rewards churn* (Boey's is 4x
   ours while his net is within a few hundred dollars), so the judged node is
   `d0-d5 trade net $` — exact from the ledger identity
   `d_money + fixed spend (seed/animals/hire/land) = sells - product buys`.
