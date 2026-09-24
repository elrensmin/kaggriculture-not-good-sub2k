# tools

Read-only analysis helpers. Run from the repo root. The `python -m tools.*` ones
need `PYTHONPATH=src:.` (they import `diagnose` and, for a few, `main`).

| tool | what it does | run |
|---|---|---|
| `margin.py` | **The fast readout**: W/L/T, median margin, median WIN and median LOSS ("and by how much"), percentiles, the structural guards, and a paired same-seed delta with `--vs`. No averaging across games. | `.venv/bin/python tools/margin.py diag-replays/ctl-rate diag-replays/consol-base` |
| `dsm_extract.py` | Parse every replay ONCE into a compact JSON cache (board, shed, inventories, market, shops, per-step orders) so analysis needs no re-parse of the raw replays. | `PYTHONPATH=src:. python tools/dsm_extract.py --dir replays/DSM/v1 --dump /tmp/dsm_cache.json` |
| `dsm_report.py` | Render the cache as the markdown data tables behind `docs/dsm_v1.md`. | `python tools/dsm_report.py --cache /tmp/dsm_cache.json` |
| `dsm_flows.py` | What DSM actually DOES with WHEAT and MILK: planted / harvested / bought / fed / sold, market-inventory band, price-at-sell, cows & shops, split YARN vs no-YARN. Reconstructed from the replay action+observation stream (LB replays have no audit). | `PYTHONPATH=src:. python tools/dsm_flows.py --dir replays/DSM/v1 --summary` |
| `sell_price.py` | Per-game, per-product **price-at-sell for BOTH seats** (units, avg price, floor%, under/ahead flags) — no averaging. | `PYTHONPATH=src:. python -m tools.sell_price --dir diag-replays/consol-new8 --summary` |
| `floor_sell.py` | Per-game floor-sale inspector: which products floor, shop consumer counts (YARN/MILK/EGG/STRAW), herd d10/16/29, peak, coop count — **no averaging**. | `PYTHONPATH=src:. python -m tools.floor_sell --dir diag-replays/noyarn-base-all --summary` |
| `herd_hold.py` | Per-day COW/SHEEP/GOOSE + feed/carry + animal-product floor sales, DSM vs ours. | `PYTHONPATH=src:. python -m tools.herd_hold --compare --max-games 40` |
| `dsm_profile.py` | Full behavioural map of DSM vs us (herd, structures, shed, lifecycle, selling, labour). | `PYTHONPATH=src:. python -m tools.dsm_profile --compare` |
| `footprint.py` | DSM-vs-us decision readout: shed, weeds, fertilizing, endgame herd, price-at-sell. | `PYTHONPATH=src:. python -m tools.footprint --compare` |
| `missed_work.py` | Enumerates, per turn, the farm work that exists but is not being done. | `PYTHONPATH=src:. python -m tools.missed_work --dir diag-replays/run-5` |
| `idle_pool.py` | Classifies every idle (PASS) work-unit turn by how it could be recovered. | `PYTHONPATH=src:. python -m tools.idle_pool --dir diag-replays/run-5` |
| `leverage.py` | Whether an idle hand can safely be re-routed (counterfactual to `missed_work`). | `PYTHONPATH=src:. python -m tools.leverage --dir diag-replays/run-5` |
| `fetch_top_players.py` | Kaggle API: the top N tournament players (team name / id / score). | `python tools/fetch_top_players.py --top 3 --json replays/top_players.json` |
| `pull_top_submissions.py` | Kaggle API: download a team's top-submission episode replays. | `python tools/pull_top_submissions.py --top 3 --episodes all --out replays` |

Notes:

- `--run-dir` / `--dir` point at a harness run (e.g. `diag-replays/run-5`); the DSM
  profiles read `replays/DSM/v1` by default (`--dsm-dir` to change).
- Leaderboard replays carry no market audit, so their day-CSV `revenue_*` is 0;
  `herd_hold` estimates DSM revenue from the replay price series and says so.
