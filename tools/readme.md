# tools

Read-only analysis helpers plus the harness, grouped by **what you are
investigating**. Run from the repo root; the `python -m tools.*` commands need the
repo root importable, so use `PYTHONPATH=.` (or run from the root — the harness
puts it on `sys.path` itself).

| group | question it answers |
|---|---|
| `tools/diagnose/` | run the agent, write replays + CSVs, re-diagnose saves, render graphs |
| `graph/` | **is the state graph actually driving the agent, and where do we diverge from Boey?** See `graph/README.md` |
| `audit/` | which decisions have more than one owner, and what is dead? |
| `gates/` | did this change help, and what else did it break? |
| `report/` | what does the #1 actually do, and where by day do we lose? |
| `market/` | what did we sell, at what price, and who bought it? |
| `labour/` | where are the wasted turns? |
| `fetch/` | pull live tournament opponents and their replays from Kaggle |

### The graph tools — start here when the agent "feels wrong"

`tools/graph/` and `tools/audit/` are the diagnostics for the decision engine itself. They find
**structural** bugs — a node with no reader, a demand with no actuator, a knob nobody reads, a
decision with two owners — which no CSV column can show you.

```bash
PYTHONPATH=. python -m tools.graph.graph_diag   --run-dir diag-replays/<arm> --section break
PYTHONPATH=. python -m tools.graph.transplant_diff --max-games 8 --days 4-12 --section diff
PYTHONPATH=. python -m tools.audit.duplicate_owners --section ops
```

Full usage, the invariants to re-check after any change, and the measured findings behind them are
in **`tools/graph/README.md`**. The headline results so far: only 4 of 27 `src/` modules imported the
graph and none of the market layers; two graph nodes were **dead** (silently removing SELL, HARVEST
and HIRE from its reach); `dry_plants` counted *every plant at hour 0* and stayed broken from d1 in
16/17 games; and `BUY_SEED` had **seven** competing owners.

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
(d10 / d20 / the bell) and measures only *structural* metrics — land, crew, crops,
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
| `--days 0-10` | **custom day window, overrides `--phase`** (e.g. `0-10`, `0-10,12-17`); the same flag is on every labour/market/report analysis tool |
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

Add `--days 0-10` (or `0-10,12-17`) to override `--phase` with a custom window, and
`--dag phase1` to print only the opening subgraph plus the edges *leaving* it (the
opening's downstream reach). Every analysis tool in `tools/` takes `--days` too, so
"the opening only" is one flag everywhere.

### `divergence.py` — WHEN does each metric go bad? (a date, not a ratio)

`phase_map` reduces a phase to one number per metric, and that hides the phase's **shape
in time**. A phase-aggregate table says "phase 2 is 0.54×", which is true and useless: the
phase-2 gap does not exist before d11. `divergence` prints, for every metric the DAG
knows, the **first day in the window where it reads BAD** against the reference, plus the
per-day series behind it — turning a ratio into a date, and a date into a mechanism.

```bash
PYTHONPATH=. python -m tools.phases.divergence --pa 2,3 --batch 4 \
    --ref-from replays/Boey/v1 --ref-max 60
# one metric's full series, to see the crossing not just the date
PYTHONPATH=. python -m tools.phases.divergence --phase phase3 --pa 2,3 --batch 4 \
    --ref-from replays/Boey/v1 --ref-max 60 --metric revenue2
```

Both arms are reduced **identically** — our games through `extract_games`, the reference
through its saved replays, and the same `_series` / `_agg` / `_status` the phase tool uses.
Across games the reduction is always a **median** (`_daily_medians`); applying the metric's
own `agg` across games instead **sums** them, which inflated every count by the number of
games (the first version reported 977 FEED/day against a true 15). If you re-use this code,
keep that reduction.

**The measurement it was built for** (2026-09-28, d0–d29 vs Boey's 60 replays). Cumulative
bank gap is **−$74 at d5 and −$162 at d10 — level** — and then Boey runs **+$3–6k/day from
d11**, compounding to **+$39,032 by d29**. So the d5 handoff is *not* where the season is
lost; d11 is a cliff, and we have negative days (d11: −$1,830 where Boey makes +$9,824).

What the first-BAD column named: `sell revenue`, `planted tiles`, `PLANT ops` and
`STRAWBERRY tiles` all cross at **d6**; `move share %` at **d8**; `weeds` at **d13**. Rows
showing `-` (DROP, MOVE, PICKUP, PLACE) are BAD in aggregate but **never cross tolerance on
any single day** — a uniform, season-long deficit rather than a cliff, which is a different
kind of problem from the d11 one and should not be bucketed with it.

### `crop_cycle.py` — per-crop agronomy: cycle, harvest age, yield, and FERTILIZATION

`wheat_cycle` reports the wheat cycle; `phase_map` reports `FERTILIZE ops 0 vs N`; neither
**joins the two**, and that is exactly how the biggest midgame root stayed invisible. This
generalizes `wheat_cycle` to every crop and both seats and adds the columns that explain the
gap: the share of harvests that were **fertilized**, the fertilized-vs-unfertilized yield
split, water-days per cycle, missed bonus-window days, and the implied units/tile-day.

```bash
PYTHONPATH=. python -m tools.labour.crop_cycle --days 11-20 --dir diag-replays/arm \
    --ref-from replays/Boey/v1 --ref-max 40 --team Boey
```

**The measurement it was built for** (2026-09-29, d6-17, 8 of our games vs 40 Boey replays):

| | ours | Boey |
|---|---|---|
| WHEAT harvest yield | **2.93** (only 2s and 3s) | **4.41** (852 5s, 519 6s) |
| WHEAT fertilized share / ops | **0 % / 0** | **57 % / 1,390** |
| WHEAT harvest age | 4.0 d | **3.0 d** |
| WHEAT units/tile-day | **0.59** | **1.10** |
| FERTILIZE moves/op | — (0 ops) | **0.09** |

The engine pays `+2` instead of `+1` on a window water when `fertilized_until_day >= day`,
and one `FERTILIZE` lasts three days, so a fertilized wheat tile peaks at 5 on age 3. Two
consequences the old tooling could not see: **fertilizing is a yield multiplier, and our
`FERTILIZE` cost 4.35 moves/op because of a shed-pickup round trip**, which is why the op
was measured out. `--days` and `--ref-from` work exactly as in the other tools.

`cycle` is reported as **age + replant gap**, never from plant->plant action alignment: the
measured ~8 % action<->position mismatch makes the raw plant cycle read *below* the harvest
age (impossible).

### `turn_budget.py` — can our crew do the reference's workload? (the closure arithmetic)

`phase_map` says "phase 2 is 0.6x"; `divergence` says when. Neither answers the roadmap
question: **can 12 hands do Boey's day-17 workload at OUR conversion rate?** This reduces both
arms to `unit-turns / acts / moves / pass`, prints the per-op act deficit, and then prices the
closure: the reference's act demand at our `moves/act` vs the turns we actually have, plus the
hand-equivalent. MEASURED 2026-09-29 (d6-17, 8 games each): `unit-turns 3,077 vs 3,044`
(**equal**), `acts 1,068 vs 1,670`, `moves 1,900 vs 1,294`, `moves/act 1.78 vs 0.77` — the
reference workload needs **4,653 turns (16.2 hands)** at our rate and fits at ≤0.8 moves/act.

```bash
PYTHONPATH=. python -m tools.phases.turn_budget --pa 2,3 --batch 4 --ref-from replays/Boey/v1 --ref-max 60
PYTHONPATH=. python -m tools.phases.turn_budget --dir diag-replays/stepN --ref-from replays/Boey/v1 --ref-max 60
```

### `target_check.py` — the d17 acceptance vector

The goal is parity **by the end of the midgame**, so the check is a fixed vector of day-17
values reduced exactly as `phase_map` does (per-day series -> one number per game -> median
across games). Prints PASS/FAIL per metric and exits non-zero on any FAIL. `--ref-from`
re-derives the targets from the reference's own replays instead of the frozen table, so the
target and the arm are measured identically. Baseline (shipped tree, 8 games): **1/16 PASS**.

```bash
PYTHONPATH=. python -m tools.phases.target_check --run-dir diag-replays/stepN --ref-from replays/Boey/v1 --ref-max 60
PYTHONPATH=. python -m tools.phases.target_check --pa 2,3 --batch 4 --ref-from replays/Boey/v1 --ref-max 60
```

### `propagate.py` — compose a structural change through the graph, without a game

`dag`/`divergence` say what is behind and when; they do not say what a change **composes
to**. "+8 wheat tiles" opens the herd gate, buys ~5 animals, which is +5 FEED +5 CARE +5
COLLECT every day, which is ~26 acts, which must fit inside `pass + avoidable walking`.
That is arithmetic over known mechanics — an engine rule or a measured rate per edge —
not a simulation. The model is the editable data file `tools/phases/propagation_rules.py`
(`exact` / `measured` / `threshold` / `capacity`); this file is only the day-stepped
resolver. It is explicitly **not** a simulator: revenue, prices and the shop draw are out
of scope, and `--validate` is the honesty gate (feed a recorded arm's measured upstream
delta in and score the prediction; it scores 5–16 % error on the exact edges).

```bash
PYTHONPATH=. python -m tools.phases.propagate --dir /tmp/arm --set wheat_tiles2=+8 --from-day 6
PYTHONPATH=. python -m tools.phases.propagate --dir /tmp/arm --to-target
PYTHONPATH=. python -m tools.phases.propagate --validate /tmp/arm-base /tmp/arm-herd
```

### `boey_model.py` — induce the reference's heuristics into a knowledge graph

Parses an arm's replays into `(context → action)` records and induces the thresholds and
targets that arm actually runs, with support and confidence, then emits
`docs/boey_kg.json` + `docs/boey_kg.md`. Run it with `--seat 1` over our own arm and the two
graphs diff straight into the clone worklist. Its first output was the round's biggest
finding: the reference's animal-buy rate **falls** as the standing wheat base rises (95 % at
a wheat/(animals+1) ratio of 0.0–0.5, 44 % at 2.0–2.5), so our `WHEAT_TILES_PER_ANIMAL=1.7`
gate is our own policy, not his — he stocks bought feed instead.

```bash
PYTHONPATH=. python -m tools.phases.boey_model --ref-from replays/Boey/v1 --ref-max 120 \
    --out-json docs/boey_kg.json --out-md docs/boey_kg.md
PYTHONPATH=. python -m tools.phases.boey_model --dir diag-replays/stepN --seat 1 --label ours
```

### `transplant.py` — separate a midgame STATE from a midgame POLICY

Nine structural arms lost money while moving their mechanism, and `state_value --cross` can
only split state from policy at **d5**. This replays a reference episode in a fresh engine,
replays both seats' recorded actions to a cut day, **overwrites our seat's live state with his
observation** (the engine keeps everything inside the observation objects — farms, private
shed/seeds/inventories, market, town), then plays **our** agent in *his* seat for the rest
while the opponent's recorded actions continue: same opponent, same world at the cut,
different policy.

`control` replays both seats to the bell with no transplant and **must** reproduce the replay
exactly — that is the validity gate. `treatment` is the counterfactual. MEASURED (24 random
non-mirror episodes, cut d10): **control 24/24 exact**; treatment loses **−$59,966 median**,
out-earning him in **0/24**. The divergence it reports is the clone worklist: on his own farm
our policy runs `moves/act 1.50 vs 0.80`, `WATER 307 vs 784`, `died 52 vs 9`,
`FERTILIZE 40 vs 204`. Use it as a **fixed-state, low-noise evaluation loop** — 24 games is 24
policy measurements on a world we know is his.

```bash
PYTHONPATH=. python -m tools.phases.transplant --ref-from replays/Boey/v1 --n 24 --cut-day 10 --workers 8
PYTHONPATH=. python -m tools.phases.transplant --ref-from replays/Boey/v1 --all --workers 8
```

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
| `fertilizer_flow.py` | **Where the herd's fertilizer goes** — collected (`COLLECT_FERTILIZER` ops), fertilized, **sold units and revenue**, shed at end, and discarded, via the exact identity `collected + bought − fertilized − sold − Δshed = discarded`. Exists because `sell_policy.py`'s header claims "FERTILIZER (nobody buys it)" and `market.py` excludes it from `TOWN_CENTER_BUYS` — **both false**: the #1 sells a median **257 units for $14,296 a game**. Measuring the same on our side showed we already sell **100 %** of what we collect, and that per animal the collection is identical (20.6 vs 21.6) — so the whole fertilizer gap is herd size, not policy. | `python -m tools.market.fertilizer_flow --dir replays/DSM/v1 --max 30` · `--agent --pa 1-6 --batch 2` |
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
| `wheat_flow.py` | **Where the wheat goes.** Tiles -> PLANT ops -> HARVEST ops -> units fed / bought / sold, plus **wheat tiles that died unharvested** and a **per-hire work split** (FEED vs FIELD vs CARE), so "is the feeding scheduled onto the right worker" is answerable. It found that we lose 25 wheat tiles a game to weeds against the #1's 1, and that he spreads feeding across 13 units while we funnel 81 % of it onto the farmer. | `python -m tools.labour.wheat_flow --days 11-20 --dir diag-replays/arm --compare --dsm-max 4` |
| `stack_trace.py` | **Tile-day completion: does a visit finish the tile, or split it?** Groups every op into visits (one unit, one tile, consecutive turns) and reports `ops/visit`, `extra trips`, revisit %, and the **split-pair matrix** — the last op of one visit against the first op of the next on the same tile-day. MEASURED (d6-17, 8 games): ops/visit **1.55 vs 1.93**, tile-days touched **3,480 vs 5,238**, and our top split pair is `WATER -> FERTILIZE` (175), which the reference does in one visit. | `python -m tools.labour.stack_trace --days 11-20 --dir diag-replays/arm --ref-from replays/Boey/v1 --ref-max 8 --team Boey` |
| `hop_regret.py` | **Geometry vs kernel.** For every act reached by a walk: `hop` (MOVEs since the previous act), `nearest` (distance from where the walk started to the closest tile offering the same op), and `regret = hop - nearest`. `sum(regret)/moves` is the share of walking a nearest-job rule would save. MEASURED: **30.2 % ours vs 21.1 % Boey**, with **78 % of our regret in WATER (2,773) + HARVEST (862)** — the work was nearby, the choice was not. FEED/CARE/COLLECT regret is ~0.3, i.e. geometric. | `python -m tools.labour.hop_regret --days 11-20 --dir diag-replays/arm --ref-from replays/Boey/v1 --ref-max 8 --team Boey` |
| `move_trace.py` | **The midgame cost sheet.** Charges every MOVE turn to the act that preceded it, so you get `WATER: 408 ops, 2.55 moves each, 50 % of all moves` instead of a single aggregate. Also splits moves by carried state (empty vs carrying) -- the two need different fixes. Found that the #1 carries something on 70 % of his moves against our 25 %. | `python -m tools.labour.move_trace --days 11-20 --dir diag-replays/arm` · `... --compare --dsm-max 4` to put his games beside ours |
| `crop_cycle.py` | **Per-crop agronomy, and the instrument that found the fertilize root.** Every crop and both seats: harvest count, age and yield distributions, **% fertilized at harvest**, plant->plant cycle, replant gap, water-days per cycle, missed bonus-window days, units/tile-day, and FERTILIZE **moves/op**. Cycle is reported as `age + gap`, never from plant->plant action alignment (the ~8 % mismatch makes the raw cycle read below the harvest age). Found that the reference fertilizes 57 % of its wheat (1,390 ops) at 0.09 moves/op while we run 0 at 3.3. | `python -m tools.labour.crop_cycle --days 11-20 --dir diag-replays/arm --ref-from replays/Boey/v1 --ref-max 40 --team Boey` |
| `leverage.py` | Counterfactual: what is an idle hand about to do next (read from the replay's own committed trajectory), and what would re-routing it forfeit? | `python -m tools.labour.leverage --dir D --glob 'scratch_vs_*.json'` |
| `crew_extract.py` | **The per-unit-turn work-stream cache** every crew analysis reads from. Parses each replay once into `[turn, unit, op, x, y, crop, age, watered, yield, kind]`. Key insight: **every op is performed on the tile the unit stands on** — the engine action is `["WATER"]` with no coordinates, because the target lives in our own Job, which a replay does not record. So the only replay-visible measure of allocation quality is the **transition between a unit's consecutive work tiles**, which works identically on the #1's replays and on ours. 123 games parse in ~20 s with all cores. | `python -m tools.labour.crew_extract --dir replays/DSM/v1 --out diag-replays/crew-dsm` · `--agent --pa 1-12 --batch 3 --out diag-replays/crew-us` |
| `crew_patterns.py` (lives in `report/`) | **The crew/plant/move breakdown by phase**, over that cache: unit-turn budget, op mix, walk share, **chain distance** between consecutive work tiles, walk-turns between them, tiles touched per unit-day, op radius from the shed, harvest age/yield per crop. `--chains` prints the **consecutive-op transition matrix** — the crew-management fingerprint. | `python -m tools.report.crew_patterns --dsm diag-replays/crew-dsm --us diag-replays/crew-us` · `--chains --phase 2` |
| `herd_econ.py` (lives in `report/`) | **Per-animal economics, measured identically on the #1 and on us.** One pass yields animal-days, **production days** (`(day - placed_day - first_yield_day) % interval == 0`), **fed-on-production-day** and **bonus-earned** rates, escapes, ready/fertilizer-available animal-days, feed units and whether they were home-grown or bought, moves charged to animal tiles, and revenue by product vs the engine's theoretical base rate. It exists because the engine's rule is asymmetric: `fertilizer_available = True` is set **every day regardless of feeding**, while `pending_care_bonus` is **wiped on every production day** and the bonus is only paid if that day was fed — so the quantity that matters is not "care ops" but whether the *production* day was fed. Run the same command on his replays and on ours; the two tables are directly comparable. | `python -m tools.report.herd_econ --dir replays/DSM/v1 --max 30` · `--agent --pa 1-12 --batch 2` · `--daily` for the per-day series |
| `visit_trace.py` | **The tile visit** — the metric that explains the moves-per-op gap. A **stop** is a maximal run of work ops by one unit on one tile with `gap <= 1` turns (`FEED -> CARE -> COLLECT_FERTILIZER` is one stop of 3; water-and-walk-off is a stop of 1). A **tile-day** is every op any unit did on that tile that day; it is *one-stop* if they all fall inside a single visit, otherwise **split**, and `extra_trips = stops - 1` prices the split. Needs no rule re-implementation, because every op is performed on the tile the unit stands on. Output: ops per stop, the ≥2/≥4-op stop shares, extra trips per tile-day, and the most-split op-pairs. | `python -m tools.labour.visit_trace --dsm diag-replays/crew-dsm --us diag-replays/crew-us --phase 2` |
| `ring_occupancy.py` (lives in `report/`) | **Who claims the shed ring — the herd or the crops?** Chebyshev rings around the shed centre `(4.5,4.5)`: band 0 = the 4 shed-access tiles, 1 = 12, 2 = 20, ... For each band it reports animal / plant / empty counts at d17 and d29, the **first day** the band saw an animal vs a plant, and the share of the herd inside radius 2. Found that **we plant the ring his herd occupies** (band 2: 16.4 crop tiles vs 1 animal; band 0: 2.9 of 4 tiles planted), and that `params.STRUCTURE_HOLDBACK` — the knob that pulls the nearest-to-shed tiles out of the crop slices — was set to 0. | `python -m tools.report.ring_occupancy --dir replays/DSM/v1 --max 20` · `--agent --pa 1-12 --batch 2` · `--daily` |

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

### Three traps that produced a *false number* twice in one session (2026-09-29)

Every one of these reads as a real, alarming defect and is pure measurement error. Check
them before you report any op-level ratio.

1. **Never sum a metric across games.** Aggregate with a **median across games**, then
   read the days. Summing inflated wheat "shed throughput" to 2,843 units/day for the
   reference against a true ~205, which then drove a whole round of "volume" work off a
   6× gap that was really 1.4×. `divergence._daily_medians` carries the same warning;
   `phase_map.analyse` already does it right.
2. **`HARVEST` takes NO crop argument.** The engine action is `["HARVEST"]` — the crop
   comes from the tile the unit stands on. `tools/labour/wheat_flow.py` counts
   `ops[("HARVEST", c[1])]`, so it reports a harvest count for an arm that *echoes* the
   crop in its own action (ours does) and **0 for one that does not** (Boey's). The
   `HARVEST/PLANT` ratio is therefore only valid within one arm. Use `PLANT` commands
   (which do carry the crop) or a tile-state transition instead.
3. **`farms[seat].farmer` / `hands` do not align positionally with `action`.** Pairing a
   unit's action to its tile by list index gives ~8 % agreement even on the correct
   `obs[t-1] -> obs[t]` offset (only `obs[t-1+1] -> obs[t+1]` beats `obs[t-1] -> obs[t]`
   at all, at 8.2 % vs 0 %). It manufactured a **"86.6 % of PLANT commands land on an
   occupied tile"** finding — 652 wasted unit-turns/game — against a true figure of
   **~5 %**. Measure success **position-free**: count PLANT commands from the action
   stream, and count successes as tiles whose `planted_day` becomes today. That gives
   ours 94 cmds → 89 planted (5 % waste), Boey 121 → 118 (2 %).

The general rule: if a measurement says an arm is doing something *absurd* (a 13×
volume gap, an 86 % failure rate), first re-derive it a second, independent way. The
absurd number is usually the tool, not the agent.

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
