# tools

Read-only analysis helpers, grouped by **what you are investigating**. Run from the
repo root; the `python -m tools.*` ones need `PYTHONPATH=src:.` (they import
`diagnose` and, for a few, `main`).

## Read this before quoting any number

The env's **market audit** (`_diagnose_meta.audit`) exists only on replays *our*
runs save. Leaderboard replays — all of `replays/DSM/v1` — have none, so for DSM
these are unavailable and anything built on them is *modelled*:
`discarded_units_total`, `sell_revenue_total`, `revenue_*`, realised `avg_price_*`,
`land_cost_total` (which reports up to 88,000 against a real 7,000 ceiling).

Two rules, learned by getting them wrong:

1. **Never promote a modelled number to a KPI.** If it cannot be audited or read
   straight off an observation, it cannot be a target. (`docs/dsm_v1.md` §7 was
   retracted for exactly this.)
2. **Calibrate a model against the audited arm first.** Our discard model gets the
   *total* within −10 % and the *composition* ~7× wrong. Tools that model print the
   model and its calibration side by side.

Also: **the shop draw is a function of our own play.** `_spawn_weeds` draws the RNG
once per empty tile of both farms and the day's shop unlock comes from that same
RNG, so leaving different ground empty moves which shops appear (measured: 18/18
games differed between two arms on identical seeds). Any shop-conditioned metric
must carry the shop mix next to it, and `shop_response.py --vs` will tell you when a
comparison is uncontrolled.

---

## 1. `gates/` — gates and baselines — "did this patch help?"

| tool | what it does | run |
|---|---|---|
| `targets.py` | **The acceptance gate.** One block per workstream (W0–W8) with its TARGET metric and a regression WATCHLIST, diffed against a baseline run. Non-zero exit if any watch regressed. Structural success — not revenue — is the pass condition. | `PYTHONPATH=src:. python -m tools.gates.targets --run-dir diag-replays/w7-b --baseline diag-replays/w7-final` |
| `margin.py` | **The fast readout**: W/L/T, median margin, median WIN and median LOSS, percentiles, guards, and a paired same-seed delta with `--vs`. No cross-game averaging. | `.venv/bin/python tools/gates/margin.py diag-replays/w7-b diag-replays/w7-final` |

## 2. `report/` — DSM and ours, the behavioural record — "what does the top player actually do?"

| tool | what it does | run |
|---|---|---|
| `dsm_profile.py` | **The main behavioural map**, ours vs DSM: herd, structures, **shed + carried + system peak**, crops by day, crop rotation share, selling (units / px / floor%), the market-inventory curve table, discards, revenue mix, wheat buy-vs-feed, YARN split, labour. Reports median [p25–p75] + p90, never bare means. | `PYTHONPATH=src:. python -m tools.report.dsm_profile --compare --run-dir diag-replays/w7-b` |
| `dsm_extract.py` | Parse every replay ONCE into a compact JSON cache so analysis never re-reads the 4.2 GB of raw replays. | `PYTHONPATH=src:. python tools/report/dsm_extract.py --dir replays/DSM/v1 --dump /tmp/dsm_cache.json` |
| `dsm_report.py` | Render that cache as the markdown tables behind `docs/dsm_v1.md`. | `python tools/report/dsm_report.py --cache /tmp/dsm_cache.json` |
| `dsm_flows.py` | WHEAT and MILK specifics: planted / harvested / bought / fed / sold, market-inventory band, price-at-sell, cows & shops, YARN vs no-YARN. | `PYTHONPATH=src:. python tools/report.dsm_flows.py --dir replays/DSM/v1 --summary` |
| `footprint.py` | Narrower decision readout: shed, weeds, fertilizing, endgame herd, price-at-sell. | `PYTHONPATH=src:. python -m tools.report.footprint --compare` |
| `herd_hold.py` | Per-day COW/SHEEP/GOOSE + feed/carry + animal-product floor sales. | `PYTHONPATH=src:. python -m tools.report.herd_hold --compare --max-games 40` |

## 3. `market/` — selling, pricing, demand — "what did we sell, at what price, and who bought it?"

| tool | what it does | run |
|---|---|---|
| `sell_price.py` | Per-product **price-at-sell for BOTH seats** (units, avg price, floor%, under/ahead flags). This is the tool that answers "are we being undercut?". | `PYTHONPATH=src:. python -m tools.market.sell_price --dir diag-replays/w7-b --summary` |
| `floor_sell.py` | Per-game floor-sale inspector: which products floor, shop consumer counts, herd d10/16/29, peak, coop count. | `PYTHONPATH=src:. python -m tools.market.floor_sell --dir diag-replays/w7-b --summary` |
| `shop_response.py` | **Shop-conditioned supply/demand for every animal→product→shop and crop→shop pair**, by unlock-day bucket. Prints the shop mix first (the RNG confound) and `--vs` flags when two arms' worlds differ. | `PYTHONPATH=src:. python -m tools.market.shop_response --dir diag-replays/w7-b --vs diag-replays/w7-final` |
| `crop_demand.py` | **Supply side**: per crop and per day, our tiles vs DSM's, the number of buying shops open, implied daily absorption, and a SUPPLY/DEMAND ratio — so "we are Nx over demand" is a number. | `PYTHONPATH=src:. python -m tools.market.crop_demand --dir diag-replays/w7-final --dsm-max 30` |
| `discards.py` | **What** the hour-23 force-drop throws away, ours (exact audit) vs DSM (modelled, bias calibrated in-line), plus what was held at the drop and at what price. | `PYTHONPATH=src:. python -m tools.market.discards --dir diag-replays/w7-b --dsm-max 30 --out docs/w5/discards.txt` |

## 4. `labour/` — wasted turns — "where are the wasted turns?"

| tool | what it does | run |
|---|---|---|
| `ready_idle.py` | **PASSes while standing on a ready tile** (crop/animal yield, fertilizer) and LOCKED-tile turns, ours vs DSM, with the value left on the tile. | `PYTHONPATH=src:. python -m tools.labour.ready_idle --dir diag-replays/w7-b --dsm-max 30 --out docs/w3/ready_idle.txt` |
| `missed_work.py` | Enumerates, per turn, the farm work that exists but is not being done (WATER / HARVEST / FEED / CARE / FERT / DIG), incl. the exact steps. | `PYTHONPATH=src:. python -m tools.labour.missed_work --dir diag-replays/w7-b` |
| `idle_pool.py` | Classifies every idle (PASS) turn by how it could be recovered — no-movement vs needs-movement vs not recoverable. | `PYTHONPATH=src:. python -m tools.labour.idle_pool --dir diag-replays/w7-b` |
| `leverage.py` | Counterfactual to `missed_work`: what is an idle hand about to do next, and what would re-routing it forfeit? | `PYTHONPATH=src:. python -m tools.labour.leverage --dir diag-replays/w7-b` |

## 5. `utils/` — data acquisition

| tool | what it does | run |
|---|---|---|
| `fetch_top_players.py` | Kaggle API: the top N tournament players (team name / id / score). | `python tools/utils/fetch_top_players.py --top 3 --json replays/top_players.json` |
| `pull_top_submissions.py` | Kaggle API: download a team's top-submission episode replays. | `python tools/utils/pull_top_submissions.py --top 3 --episodes all --out replays` |

---

## Where the reports live

| path | contents |
|---|---|
| `docs/baseline/` | the frozen pre-W0 baseline (`run-1` profile + targets) |
| `docs/w0/` … `docs/w7/` | per-workstream `dsm_profile` / `targets` / trace output |
| `docs/dsm_v1.md` | DSM's full anatomy, with the provenance convention at the top |
| `docs/current-plan.md` | the plan, the per-path measured results, and the open items |

## Conventions

- `--dir` / `--run-dir` point at a harness run (`diag-replays/<arm>`). `--dsm-dir`
  defaults to `replays/DSM/v1`.
- The fast paired loop is `--pa 2,3,5 --batch 6` (18 games). **More seeds than that
  are needed before believing a small effect** — with three shops moving between
  arms, the shop-draw confound is larger than several effects we have chased.
- Judge on structural targets achieved **without** watchlist regression; revenue is
  reported alongside and is never the pass condition.
