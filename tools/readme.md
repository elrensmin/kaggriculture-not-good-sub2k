# tools

Read-only analysis helpers plus the harness, grouped by **what you are
investigating**. Run from the repo root; the `python -m tools.*` commands need the
repo root importable, so use `PYTHONPATH=.` (or run from the root — the harness
puts it on `sys.path` itself).

| group | question it answers |
|---|---|
| `tools/diagnose/` | run the agent, write replays + CSVs, re-diagnose saves, render graphs |
| `gates/` | did this change help, and what else did it break? |
| `report/` | what does the #1 actually do, and where by day do we lose? |
| `market/` | what did we sell, at what price, and who bought it? |
| `labour/` | where are the wasted turns? |
| `fetch/` | pull live tournament opponents and their replays from Kaggle |

## Read this before quoting any number

The env's **market audit** (`_diagnose_meta.audit`) exists only on replays *our*
runs save. Leaderboard replays — all of `replays/DSM/v1` — have none, so for DSM
these are unavailable and anything built on them is *modelled*:
`discarded_units_total`, `sell_revenue_total`, `revenue_*`, realised `avg_price_*`,
`land_cost_total`. Three rules, learned by getting them wrong:

1. **Never promote a modelled number to a KPI.** If it cannot be audited or read
   straight off an observation, it cannot be a target.
2. **Calibrate a model against the audited arm first.** Our discard model lands the
   *total* within −10 % and the *composition* badly wrong; tools that model print
   the model and its calibration side by side.
3. **`land_cost_total` is wrong on both arms** — it reports $10,000 against a real
   $7,000 ceiling (the order is re-issued every turn and re-charged). Cross-check
   the money ledger before quoting any land figure.

Also: **the shop draw is a function of our own play.** `_spawn_weeds` draws the RNG
once per empty tile of both farms and the day's shop unlock comes from that same
RNG, so leaving different ground empty moves which shops appear (measured: 18/18
games differed between two arms on identical seeds). Any shop-conditioned metric
must carry the shop mix next to it; `market/shop_response.py --vs` tells you when a
comparison is uncontrolled.

And one engine convention that bites every tile-conditioned tool: a
kaggle_environments step records the action that *produced* its observation, so the
action decided from `steps[t]["observation"]` is at `steps[t+1]["action"]`
(verified: 97.1 % of moves satisfy `pos[t+1] == pos[t] + action[t+1]`, vs 53.3 %
same-index). `labour/op_patterns.py` and `labour/ready_idle.py` use the shifted
form. The harness's own `replay_to_record` still uses the same index, so the CSV
columns `idle_units_ready_total`, `locked_steps`, `missed_harvest_eod` and
`near_shed_*` are measured against the wrong step — read them as indicative.

---

## 0. `diagnose/` — the harness — "run it and get the numbers"

| task | command |
|---|---|
| run the agent vs a batch of public opponents (parallel) | `python -m tools.diagnose --scratch --pa 2 --batch 12 --seed 700 [--run-dir D]` |
| the whole public field | `python -m tools.diagnose --scratch --pa 1-12 --batch 8 --seed 4362837462` |
| re-diagnose saved replays into the CSVs (no games re-run) | `python -m tools.diagnose --replay-dir D` |
| …and print the day-by-day report for the last replay | `python -m tools.diagnose --replay-dir D --render` |
| leaderboard replays (no seed → keyed on episode id, both seats) | `python -m tools.diagnose --replay-dir replays/DSM/v1 --lb` |
| dashboards + farm-board GIFs (and the animal CARE payback chart) | `python -m tools.diagnose --replay-dir D --graph` / `--animals` |

Outputs per run dir: **replay JSONs** (one per game, both seats), **`days_seed<S>.csv`**
(one row per day for the agent under test = seat 1), and **`games.csv`** (one row
per game). The agent's replays are named `scratch_vs_<opponent>_seed<N>.json` and
its `games.csv` rows carry `agent=scratch` — the historical name of the
from-scratch agent, kept so the globs and `--agent` filters below keep working.

The agent under test is the `src` package. There is no `--old`/`--new`/`--compare`
any more; A/B testing is two run dirs plus `report/arm_diff.py` (below).

## 0b. `phases/` — phased structural development — "what is the ROOT of this?"

`phase_map` is the tool for **fixing the game from the beginning**. It runs the agent
in-memory against the public field with the episode **truncated at a phase boundary**
(d5 / d17 / the bell) and measures only *structural* metrics — land, crew, crops,
animals, water, feed, weeds, shed, throughput — against the #1's measured per-day
state. Then it walks an explicit **causal DAG** (`tools/phases/dag.py`) and separates
**roots** (deficient with a healthy upstream) from **symptoms** (deficient because an
ancestor is), reporting each root's *blast radius*.

No replay files and no CSVs: the metrics are read straight out of the in-memory env,
and because the agent is stateless a truncated game has the same d0..N behaviour as a
full one — so a phase run costs a fraction of a full sweep.

| | |
|---|---|
| `--phase phase1` | opening, d0–d5 (144 steps) |
| `--phase phase2` | midgame, d6–d17 (432 steps) |
| `--phase phase3` | endgame, d18–29 (720 steps) |
| `--phase all` | one full run, all three tables + the cross-phase trace |
| `--dag` | print the whole causal graph with each edge's mechanism |
| `--pa` `--batch` `--seed` `--workers` | same sampling knobs as the harness |
| `--replay-dir D` / `--replay F` | analyse SAVED games instead of running them |
| `--seat auto\|0\|1` | which seat to analyse (`auto` finds the team named DSM) |
| `--ref-from D` `--ref-max N` | derive the targets from another arm's replays |
| `--days 0-5` | **custom day window, overrides `--phase`** (e.g. `0-5`, `0-5,12-17`); the same flag is on every labour/market/report analysis tool |
| `--spread` | also print **p10 / p25 / median / p75 / p90 / min / max** per metric for ours and the reference arm. Use it: a median over a bimodal population hides the defect you are hunting. The opening is near-deterministic (every metric `min == max`), but d6+ is not — **run d6+ at `--batch 4 --spread`, never `--batch 1`** |
| `--dag phase1` | print only that phase's subgraph plus the edges **leaving** it |

```bash
# the opening, quick check (2 opponents, 1 seed) or the field
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 --pa 1,2 --batch 1
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 --pa 1-12 --batch 4
# all three phases in one full run, and the graph itself
PYTHONPATH=. python -m tools.phases.phase_map --phase all --pa 1-12 --batch 2
PYTHONPATH=. python -m tools.phases.phase_map --dag

# the two audit modes that make the targets trustworthy:
#  (a) run the #1's OWN replays through the same DAG -- every metric should read OK;
#      this is how the structs=10 error in docs/dsm_v1.md was caught (his replays
#      show 5 pastures at d5, all occupied, 20 plants, 25 tiles exactly full).
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 \
    --replay-dir replays/DSM/v1 --max-games 6 --seat auto
#  (b) use his replays AS the target instead of the transcribed table -- complete
#      (every metric gets a target) and measured, so prefer it when it matters
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 \
    --pa 1,2 --batch 1 --ref-from replays/DSM/v1 --ref-max 4
#  (c) analyse an opponent's games on their own (no live run at all)
PYTHONPATH=. python -m tools.phases.phase_map --phase phase2 \
    --replay-dir replays/DSM/v1 --max-games 12 --seat auto
```

`--phase all` runs each game **once** to the bell and slices the three phases out of
that single run, so the whole-game view costs the same as one full sweep.

Reading it: a `BAD` metric with no `BAD` ancestor is where to intervene; its "explains
N other deficient metrics" line is the payoff. The trace shows each deficient metric
traced **up** its causes, so a chain that begins in phase 1 and ends in phase 3 *is*
the "everything downstream has roots in the beginning" claim, made checkable:

    animals at the bell [p3] <- animals on board [p2] <- owned tiles [p2]
      <- opening cash committed [p1]

The same run also settles questions a CSV diff cannot: `owned tiles` reads **100/100 OK
by phase 2**, so the land gap is an opening-*timing* artefact, not a midgame problem;
and we water **0.72 ops per planted tile against his 0.83**, which shows up as **26
plant deaths against his 1** — the C5 chain, and the midgame's own root.

**Use it as the first and last step of every experiment**: find the root before you
patch, then re-run the phase and confirm the root is gone and its symptoms moved with
it. Record anything new you learn as an edge in `tools/phases/dag.py` — the graph is
the durable artefact; the tool only evaluates it.

The targets are the #1's measured state (`docs/dsm_v1.md` §3 + `dsm_profile`'s per-day
idle%/crop tiles), reduced over the phase with the **same aggregation** as ours, so the
comparison is tool-internal. Metrics with no counterpart in his table are reported
**without a status** and can never be roots.

Add `--days 0-5` (or `0-5,12-17`) to override `--phase` with a custom window, and
`--dag phase1` to print only the opening subgraph plus the edges *leaving* it (the
opening's downstream reach). Every analysis tool in `tools/` takes `--days` too, so
"the opening only" is one flag everywhere.

### `state_value.py` — what is the d5 state worth, and what predicts the finish?

`phase_map` counts; this **prices**. The opening is only ~6.5% of the season's revenue
gap, so a change judged on the terminal bank needs a sample far larger than anyone has.
This tool buys the power back three ways:

1. **Price the d5 state.** `liquid = cash + shed` marked at the d5 price is exact and
   policy-free — a low-variance readout of the opening. `nav` adds standing crops and
   herd production minus feed (assumptions, printed as such).
2. **Continue from d5 under a frozen policy.** The prefix roll-out is deterministic, so
   the first 144 steps can be re-run exactly and the remaining 576 handed to a different
   policy. `--cont live,nobuy,liquidate` brackets the position: `term_liquidate - liquid`
   is what the season has left to add, and `max(term) - min(term)` is the option value
   still embedded in the d5 state.
3. **Regress the terminal bank on the d5 state.** Standardised coefficients on d5 cash /
   shed value / crop units / herd units / land say which structural quantity the market
   actually pays for; `R^2` says how much of the finish was decided by day 5. The DAG
   asserts these links; this measures them.

```bash
PYTHONPATH=. python -m tools.phases.state_value --pa 1-2 --batch 2
PYTHONPATH=. python -m tools.phases.state_value --pa 1-2 --batch 2 \
    --cont live,nobuy,liquidate
PYTHONPATH=. python -m tools.phases.state_value --ref-from replays/DSM/v1 --ref-max 40
```

### `shadow_prices.py` — what is one more unit of each resource worth?

A root with a big blast radius is not automatically worth fixing — that is exactly how
the opening herd (the DAG's #1 phase-1 root) got built and lost $15,020. Counting
descendants cannot rank jointly-scarce resources; a **price** can.

`shadow_prices` is a paired finite-difference design: for every `(opponent, seed)` it
runs the baseline and then the baseline plus **one `SCRATCH_PARAMS` override**, and
reports the paired `dNAV_d5` (the low-variance phase-1 objective) and `dterm` (the
season). When the two disagree in sign the perturbation is a *paper* improvement, and
the tool counts those pairs explicitly.

```bash
# the default opening menu: liquidity, wheat tiles, hands, herd, movement, ramp, fert
PYTHONPATH=. python -m tools.phases.shadow_prices --pa 1-3 --batch 4
# custom: LABEL|KEY=VAL;KEY=VAL|unit|unit-name
PYTHONPATH=. python -m tools.phases.shadow_prices --pa 1,2 --batch 6 \
    --perturb 'herd|HERD_ENABLED=1||' \
    --perturb 'liquidity|CASH_RESERVE=1000|500|dollar of spendable cash'
```

Each task re-executes `src/` from scratch (a param change is a different module state),
so it costs two full roll-outs per pair; hand the big ones to the operator.

## 1. `gates/` — gates and baselines — "did this patch help?"

| tool | what it does | run |
|---|---|---|
| `targets.py` | **The acceptance gate.** One block per workstream with its TARGET metric and a regression WATCHLIST, diffed against a baseline run. Non-zero exit if any watch regressed. Structural success — not revenue — is the pass condition. | `python -m tools.gates.targets --run-dir D --baseline diag-replays/v0-us` |
| `balance.py` | **The per-fix readout.** Pairs two of OUR arms on the shared `(opponent, seed)` games and diffs the whole surface: margin percentiles, every guard, the investment ledger, structures, herd, planted tiles per crop per day, labour shares, shed, wheat. Flags each row OK/WARN and prints a regression list. | `python -m tools.gates.balance --baseline diag-replays/arm-a --candidate diag-replays/arm-b --agent scratch` |
| `margin.py` | **The fast readout**: W/L/T, median margin, median WIN/LOSS, percentiles, guards. | `python -m tools.gates.margin diag-replays/v0-us` |

## 2. `report/` — DSM and ours, the behavioural record

| tool | what it does | run |
|---|---|---|
| `dsm_profile.py` | **The main behavioural map**, ours vs DSM: herd, structures, **shed + carried + system peak**, crops by day, crop rotation share, selling (units / px / floor%), the market-inventory curve table, discards, revenue mix, wheat buy-vs-feed, YARN split, labour. Reports the **five-number ladder `p10 p25 p50 p75 p90`**, never bare means. | `python -m tools.report.dsm_profile --compare --run-dir D --agent scratch` |
| `day_gap.py` | **Where, by day, we lose.** Per-day side-by-side of work and output, summed into day bands with the revenue gap and idle work-units each contributes, and cumulative revenue so the day our curve breaks away is visible. | `python -m tools.report.day_gap --ours D --ours-agent scratch` |
| **`arm_diff.py`** | **The A/B tool.** Joins two run dirs' `games.csv` on `(opponent, seed)`, reports the margin-delta ladder, a **sign test**, the verdict flips, a per-opponent table, and a defect-column watchlist. Only matched pairs are used. | `python -m tools.report.arm_diff --a diag-replays/arm-a --b diag-replays/arm-b` |
| `footprint.py` | Narrower decision readout: shed, weeds, fertilizing, endgame herd, price-at-sell. | `python -m tools.report.footprint --compare --run-dir D --max-games 40` |
| `herd_hold.py` | Per-day COW/SHEEP/GOOSE + feed/carry + animal-product floor sales. | `python -m tools.report.herd_hold --compare --run-dir D --max-games 40` |
| `dsm_extract.py` | Parse every DSM replay ONCE into a compact JSON cache so analysis never re-reads the 4.2 GB of raw replays. | `python tools/report/dsm_extract.py --dir replays/DSM/v1 --dump /tmp/dsm_cache.json` |
| `dsm_report.py` | Render that cache as the markdown tables behind `docs/dsm_v1.md`. | `python tools/report/dsm_report.py --cache /tmp/dsm_cache.json` |
| `dsm_flows.py` | WHEAT and MILK specifics: planted / harvested / bought / fed / sold, market-inventory band, price-at-sell, cows & shops, YARN vs no-YARN. | `python -m tools.report.dsm_flows --dir replays/DSM/v1 --summary` |

### `dsm_profile.py` — the comparability contract

It prints five things you must read before quoting any number, because an arm
measured against **one** opponent is not the same object as an arm measured
against a field:

| block | what it tells you |
|---|---|
| **POOL** | replay JSONs, games.csv rows, **episodes**, opponents, the W/L/T episode tally, and the YARN_STORE mix. A single-opponent arm prints a warning: its p10/p90 describe seed variance inside one matchup, not a field. |
| **ladder** | `p10 p25 p50 p75 p90` on every per-game metric. p10 is the one that decides the loss tail. |
| **MARGIN** | the target in its own terms: p10, max loss, share of games losing >$4k, median win, share of wins >$30k, win%. |
| **PER-OPPONENT** | per-opponent n / W-L-T / p10 / p50 / p90 / worst, then the **median-of-per-opponent-medians**. Aggregate per opponent, *then* average. |
| **GUARDS** | the defect columns, with p10. The DSM arm only has these because `replays/DSM/v1/games.csv` is read and filtered to `agent == "DSM"`. |

- **games.csv is filtered by `agent`.** Our runs carry `agent=scratch` (pass
  `--agent scratch`); a leaderboard games.csv holds *both seats* of every episode,
  so pooling every row would fold the opponent's bank into ours.
- **Episodes, not rows, are the unit of a win tally.** A pool run reuses the same
  seed list for every opponent, so `(opponent, seed)` is the episode key.

**Our arm must span opponents.** `--pa 2 --batch 24` is 24 games against one agent;
DSM's 123 episodes span 66 teams. For any structural claim:

```bash
./scripts/sweep.sh 4362837462 15        # -> diag-replays/sweep_s4362837462_b15/
PYTHONPATH=. python -m tools.report.dsm_profile --compare \
  --run-dir diag-replays/sweep_s4362837462_b15 --agent scratch
```

## 3. `market/` — selling, pricing, demand

| tool | what it does | run |
|---|---|---|
| `sell_price.py` | Per-product **price-at-sell for BOTH seats** (units, avg price, floor%, under/ahead flags). Answers "are we being undercut?". | `python -m tools.market.sell_price --dir D --glob 'scratch_vs_*.json' --seat 1 --summary` |
| `floor_sell.py` | Per-game floor-sale inspector: which products floor, shop consumer counts, herd d10/16/29, peak, coop count. | `python -m tools.market.floor_sell --dir D --glob 'scratch_vs_*.json' --seat 1 --summary` |
| `shop_response.py` | **Shop-conditioned supply/demand for every animal→product→shop and crop→shop pair**, by unlock-day bucket. Prints the shop mix first (the RNG confound) and `--vs` flags when two arms' worlds differ. | `python -m tools.market.shop_response --dir D [--vs D2]` |
| `crop_demand.py` | **Supply side**: per crop and per day, our tiles vs DSM's, the number of buying shops open, implied daily absorption, and a SUPPLY/DEMAND ratio — plus a peak/rotation summary. | `python -m tools.market.crop_demand --dir D --dsm-max 30` |
| `discards.py` | **What** the hour-23 force-drop throws away, ours (exact audit) vs DSM (modelled, bias calibrated in-line). | `python -m tools.market.discards --dir D --dsm-max 30` |

## 4. `labour/` — wasted turns and movement structure

| tool | what it does | run |
|---|---|---|
| `movement.py` | The movement modality: movement/PASS/productive share, moves-per-act, movement by hour-of-day, empty-handed vs carrying moves, ours vs DSM. | `python -m tools.labour.movement --dir D --glob 'scratch_vs_*.json' --dsm-max 12` |
| `op_patterns.py` | **How the turns are arranged**: act-run length distribution, what follows each act, per-op chaining, and a raw op trace for a chosen day/unit — the artifact behind "DSM finishes the tile, we don't". | `python -m tools.labour.op_patterns --dir D --glob 'scratch_vs_*.json' --dsm-max 12 --day 12 --unit 0` |
| `ready_idle.py` | **PASSes while standing on a ready tile** (crop/animal yield, fertilizer) and LOCKED-tile turns, ours vs DSM, with the value left on the tile. | `python -m tools.labour.ready_idle --dir D --dsm-max 12` |
| `missed_work.py` | Enumerates, per turn, the farm work that exists but is not being done (WATER / HARVEST / FEED / CARE / FERT / DIG), incl. the exact steps. | `python -m tools.labour.missed_work --dir D --glob 'scratch_vs_*.json' --summary-only` |
| `idle_pool.py` | Classifies every idle (PASS) turn by how it could be recovered — no-movement vs needs-movement vs not recoverable. | `python -m tools.labour.idle_pool --dir D --glob 'scratch_vs_*.json' --summary-only` |
| `unit_trace.py` | **The one that found the d0 livelock.** Per-unit, per-turn op + inventory timeline (farmer + hands), with a per-unit `(op, item)` tally, `PICKUP -> DROP` round trips (carried for nothing) and turns spent holding an item while only moving. Live or replay, so it runs on the #1's games too. Aggregate tools cannot see this: a PICKUP and a DROP both look like work. | `python -m tools.labour.unit_trace --days 0-0 --max-turns 26` · `... --dir replays/DSM/v1 --glob '*.json'` · `... --no-turns` for the summary |
| `leverage.py` | Counterfactual: what is an idle hand about to do next (read from the replay's own committed trajectory), and what would re-routing it forfeit? | `python -m tools.labour.leverage --dir D --glob 'scratch_vs_*.json'` |

## 5. `fetch/` — data acquisition

| tool | what it does | run |
|---|---|---|
| `fetch_top_players.py` | Kaggle API: the top N tournament players (team name / id / score). | `python tools/fetch/fetch_top_players.py --top 3 --json replays/top_players.json` |
| `pull_top_submissions.py` | Kaggle API: download a team's top-submission episode replays. | `python tools/fetch/pull_top_submissions.py --top 3 --episodes all --out replays` |

---

## Where the reports live

| path | contents |
|---|---|
| `docs/v0/` | the raw tool output behind `docs/DSM-vs-us(v0).md` |
| `docs/DSM-vs-us(v0).md` | the data-backed diagnosis: opening / midgame / endgame, the coupling map, and the open fix roadmap |
| `docs/dsm_v1.md` | DSM's full anatomy, with the provenance convention at the top |
| `diag-replays/` | run dirs: replay JSONs + `games.csv` + `days_seed<S>.csv` |

## Conventions

- `--dir` / `--run-dir` point at a harness run (`diag-replays/<arm>`). `--dsm-dir`
  defaults to `replays/DSM/v1`.
- The fast paired loop is `--pa 2 --batch 12` (12 games, one matchup). **Believe a
  small effect only with more seeds and more opponents** — with shops moving
  between arms, the shop-draw confound is larger than several effects worth
  chasing.
- Judge on structural targets achieved **without** watchlist regression; revenue is
  reported alongside and is never the pass condition.

### Pitfall: a stale `SCRATCH_PARAMS` screen silently reports "no effect"

`tools/diagnose/agents.py::load_agent(fresh=True)` calls `importlib.reload(src)`, which
re-executes only `src/__init__.py` — **not** `src.params` / `src.job` / `src.crop_plan`.
So an ad-hoc probe that sets `os.environ["SCRATCH_PARAMS"]` and then calls
`load_agent(fresh=True)` **keeps the old constants** and reports byte-identical results
for every value you try. This cost a full round here: `P_BUILD` at 95/102/105/110,
`BUILD_PER_TURN=8`, `OPENING_FEED_DAYS=0` and `OPENING_SEED_FLOOR=0` all "did nothing",
and two conclusions were drawn from it that were simply false.

Use a **full reload** — this is what `tools/phases/shadow_prices.py::_fresh_agent` and
`tools/phases/state_value.py::_load_with` do:

```python
for m in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[m]
import src                      # params/job/crop_plan re-execute with the new env
```

Two related traps worth remembering:
- `src/job.py` binds priorities at **import** time (`P_BUILD = params.P_BUILD`), so a
  priority change needs the full reload even though `params` itself is re-read.
- `tools/phases/shadow_prices.py` and `state_value --cross` already do this correctly —
  **their numbers are trustworthy; hand-rolled probes are the risk.**
