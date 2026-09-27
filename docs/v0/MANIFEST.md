# `docs/v0/` manifest — fresh run, 2026-09-27

Every file here is raw tool output for the **current** agent (`src/`, tree defaults,
`git rev 694e48aa8cccd71d16915186e16629331d9755cc`), regenerated from scratch because
`diag-replays/` had been emptied. Nothing in this directory is a hand-typed number.

| field | value |
|---|---|
| **ours** | `diag-replays/v1-us` — `python -m tools.diagnose --scratch --pa 1-12 --batch 8 --seed 4362837462` = **96 games**, 12 public opponents × 8 seeds, `agent=scratch` |
| **config** | current tree defaults, **no `SCRATCH_PARAMS`**: `MOVE_WEIGHT=20`, `DIST_CAP=1`, `HERD_ENABLED=True`, `HERD_BUY_UNTIL=12`, `HERD_BUY_FROM_DAY=0`, `OPENING_SCRIPT=True`, **`OPENING_TAPE=True`** (the shipping default), **`OPENING_TAPER_BOEY=True`** + **`OPENING_HERD_BOEY=True`** (the measured d0–d5 script), **`MAX_HIRE_PER_TURN=1`** (was 99 — 5-at-once HIREs silently dropped the tape's sells/seeds past `MAX_ORDERS=10`), **opening crew 5** (`target_hands`, Boey's measured median), `STRUCTURE_HOLDBACK=12`, `PLANT_RAMP=True`, `FERTILIZE_FROM_DAY=99`, `CROP_SCALE=1.0`. Snapshot in `config.txt`/`HEAD.txt`. The 96-game `dterm` confirmation for the tape is **still open**. |
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
| `sc-p1-boeyscript.txt` | the CURRENT top readout: `phase_map --phase phase1 --pa 1-4 --batch 4 --ref-from diag-replays/boey-lb --ref-max 60 --team Boey`, with `OPENING_TAPER_BOEY`/`OPENING_HERD_BOEY` on | 16 live / 60 ref |
| `sc-cur-tape2-dsm.txt` | the same tree, `--pa 1-12 --batch 2 --ref-from replays/DSM/v1 --ref-max 123` | 24 live / 123 ref |
| `sc-p1-chain.txt` | `SCRATCH_PARAMS='SAME_TILE_FIRST=1;SAME_TILE_MIN_PRIORITY=0'` — the Step-4 water-chain diagnostic (WATER 53→58, but MELON 9→7, idle 0.78→11.0) | 16 live / 60 ref |
| `sc-p1-base.txt` | the same 16-game Boey screen with the pre-tape defaults (`OPENING_TAPE=0`) | 16 live / 60 ref |
| `phase_all_vs_dsm.txt` | same, `--phase all ... --spread` | 24 live / 123 ref |
| `phase_dag.txt` | `tools.phases.phase_map --dag` | — |
| `phase_dsm_selfcheck.txt` | `tools.phases.phase_map --phase all --replay-dir replays/DSM/v1 --max-games 123 --seat auto` | — / 123 |
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
