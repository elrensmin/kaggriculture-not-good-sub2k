# `docs/v0-boey/` — Boey reference arm

Second leaderboard reference, so the diagnosis can read **us vs two top agents**. Same extractors,
same aggregation, same rules as `docs/v0/MANIFEST.md`. The only difference is the reference arm and
`--team Boey`.

| field | value |
|---|---|
| **Boey** | `replays/Boey/v1` — **359 replays / 359 episodes**, 148 opponents, **W 305 – L 56 (84.9 %)**, median margin **+$9,812**, normalised **+$23,101** |
| **CSVs** | the raw dir had no `games.csv`/day CSVs, so they were generated **without touching `replays/`**: `diag-replays/boey-lb/` is a directory of symlinks to `replays/Boey/v1/*.json`, then `tools.diagnose --replay-dir diag-replays/boey-lb --lb` wrote the CSVs there |
| **us** | `diag-replays/v1-us` (unchanged, 96 games, tree defaults) |
| **audit** | Boey's replays carry **no market audit** — `sell_revenue_*`, `avg_price_*`, `discarded_*`, `land_cost_*` are 0/modelled |

## Tool changes shipped for this (`--team`, default `DSM`)

Every tool that hardcoded the #1's name now resolves the arm through `tools/team.py`
(precedence `--team` > `$KAGG_OPPONENT` > `"DSM"`), and `margin` gained `--team` so a leaderboard
`games.csv` is scored on **one arm's rows** instead of both seats.

| file | what changed |
|---|---|
| `tools/team.py` | **new** — `get/set_team`, `matches`, `seat_of_names`, `seats_of_names` |
| `tools/phases/phase_map.py` | `_seat_of` uses the resolver; `--team` (covers `move_trace`, `wheat_flow`, `unit_trace` which import it) |
| `tools/gates/margin.py` | **`--team` row filter** (a leaderboard CSV carries both seats; unfiltered it scores 50 %) |
| `tools/labour/{movement,op_patterns,ready_idle,crew_extract}.py`, `tools/report/{herd_econ,ring_occupancy,dsm_flows,dsm_profile,footprint,herd_hold,dsm_extract}.py`, `tools/market/{fertilizer_flow,crop_demand,sell_price,discards,floor_sell}.py` | seat detection + row filter + labels use the resolver; `--team` added |
| `tools/report/day_gap.py` | `--dsm-agent` defaults to the resolved team; `--team` added |
| `tools/report/crew_patterns.py`, `tools/labour/visit_trace.py` | `--label` so the reference header is not printed as "DSM (#1)" |

## Files

| file | command (with `--team Boey`) |
|---|---|
| `margin.txt` | `tools.gates.margin diag-replays/boey-lb --team Boey` |
| `dsm_profile.txt` | `tools.report.dsm_profile --compare --run-dir diag-replays/v1-us --agent scratch --dsm-dir diag-replays/boey-lb --team Boey` |
| `day_gap.txt` | `tools.report.day_gap --ours diag-replays/v1-us --dsm diag-replays/boey-lb --dsm-agent Boey --team Boey` |
| `movement.txt`, `op_patterns.txt`, `ready_idle.txt`, `move_trace.txt`, `wheat_flow.txt` | `tools.labour.*` with `--dsm-dir diag-replays/boey-lb --dsm-max 359 --team Boey` |
| `crew_extract.txt` | `tools.labour.crew_extract --dir diag-replays/boey-lb --team Boey --out diag-replays/crew-boey` |
| `crew_patterns.txt`, `visit_trace.txt` | `tools.report.crew_patterns --dsm diag-replays/crew-boey --us diag-replays/crew-us --label Boey` · `tools.labour.visit_trace ... --label Boey` |
| `crop_demand.txt`, `discards.txt` | `tools.market.*` with `--dsm-dir diag-replays/boey-lb --dsm-max 359 --team Boey` |
| `herd_econ.txt`, `ring_occupancy.txt`, `fertilizer_flow.txt`, `dsm_flows.txt` | `tools.report/market.* --dir diag-replays/boey-lb --team Boey --max 0` |
| `phase_all_vs_boey.txt` | `tools.phases.phase_map --phase all --pa 1-12 --batch 2 --ref-from diag-replays/boey-lb --ref-max 359 --team Boey --spread` |
| `phase_boey_selfcheck.txt` | `tools.phases.phase_map --phase all --replay-dir diag-replays/boey-lb --seat auto --team Boey --max-games 359` |

## Caveats

- **The DAG's transcribed fallback (`DSM_DAILY`) is DSM-specific.** `phase_boey_selfcheck.txt` reads
  `STRAWBERRY tiles 4 vs 10`, `owned tiles 75 vs 100` as BAD against that table — that is Boey's
  different strategy, not an error. Always use `--ref-from` when the reference is not DSM.
- **Boey's `margin.txt` guard totals are summed over 359 all-seat games**; per-game medians in
  `dsm_profile.txt` are the comparable ones.
- Boey's `herd_econ` revenue is inflated by **bought-and-resold fertilizer**: it buys 728/game, sells
  487/game shed-capped at $41.1 — that is a trading line, not herd output. Read
  `fertilizer_flow.txt` beside it.
- **Volume figures are now shed-capped.** Boey's replays carry no audit, and they send
  sentinel-sized `SELL <item> 1000` orders, so the old requested-order sums (`6,786` wheat,
  `2,025` egg, `4,622` fertilizer per game) overstated executed volume ~2x. `dsm_profile`
  labels the estimator `src=action (shed-capped)`; the corrected medians are wheat **2,542**,
  egg **147**, fertilizer **487**, milk **17**, wool **53**. `tools/report/phase_sells.py`
  prints the same caveat.
