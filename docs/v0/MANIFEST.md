# `docs/v0/` manifest — fresh run, 2026-09-27

Every file here is raw tool output for the **current** agent (`src/`, tree defaults,
`git rev 694e48aa8cccd71d16915186e16629331d9755cc`), regenerated from scratch because
`diag-replays/` had been emptied. Nothing in this directory is a hand-typed number.

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
