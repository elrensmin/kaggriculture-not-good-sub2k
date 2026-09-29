# Agent Development Guide (handover)

## Layout — read this first

| path | role | editable? |
|---|---|---|
| `src/` | **the agent.** An onion of small layers; `src/__init__.py` exposes `agent(observation, configuration)`. | **YES — this is the product** |
| `tools/diagnose/` | the harness: run the agent, write replays + CSVs, re-diagnose saves, render graphs | yes |
| `tools/` (rest) | read-only analysis: labour, market, report, gates | yes (add tools freely) |
| `public_agents/` | the 12 public "cloning" opponents | yes |
| `package.py` | builds the single-file Kaggle bundle from `src/` | yes |
| `GAME_DYNAMICS.md` | authoritative mechanics (crops, animals, market, turn order) | yes |
| `docs/DSM-vs-us(v0).md` | the data-backed diagnosis of this agent vs the #1 | yes |
| `docs/dsm_v1.md` | the #1 team's full anatomy | yes |
| `replays/DSM/v1/` | the #1's 123 leaderboard episodes (read-only reference) | **NO** |
| `diag-replays/` | output of our runs (gitignored) | n/a |

There is **no route tape, no `main.py` chassis and no patch layer.** Those were
deleted when this agent was committed to. If you find a doc or a tool that still
mentions `route_tape`, `agent.patch`, `--old`/`--new`/`--compare`, `--grid` or
`--xray`, it is stale — fix it, do not resurrect the machinery.

## Golden rule: the agent is stateless

`src/agent(observation)` computes `action(t) = f(state(t))` with **no cross-turn
memory**. Every layer reads an immutable per-turn `State` snapshot
(`src/state.py`), and `src/__init__.py` wraps the whole plan in a try/except that
degrades a bug to a legal `PASS` rather than to a crash.

Two consequences you must design around:

- **A bug is a local fix, never a corrupted trajectory.** There is no replaying
  positional recording to keep valid, so you can change any layer and re-run.
- **Anything that needs memory must be *derived* from the observation.** The
  engine hands you the whole board and shed every turn; use that instead of
  carrying state forward. (E.g. crop calendars are re-derived from
  `planted_day`/`age`, not remembered.)

## The layer stack (inside → out)

    core         params / market / state / routing
    structural   budget / crop_plan / herd_plan / layout
    execution    sell_policy / endgame / scheduler / emit

`src/scheduler.py::plan(state)` is the only thing `__init__` calls. It gathers
jobs from the policy layers (`crop_plan.jobs`, `herd_plan.jobs`, `endgame.jobs`),
assigns each unit a job via `_pick`, routes it one cell, and compiles the market
orders. **When two layers disagree, the priority constants in `src/job.py` and the
assignment kernel in `scheduler._pick` decide the winner** — that kernel is where
the agent's "personality" lives.

## `src/` — every module and what it owns

**30 modules.** The rule when adding a decision: find the module that already owns it, or state
which one is giving up ownership. Two owners of one decision is this codebase's most expensive
bug class (see `tools/audit/duplicate_owners.py`).

### core — data and arithmetic, no policy
| file | owns |
|---|---|
| `__init__.py` | the entry point `agent(observation)`. Wraps everything in `try/except` → a crash degrades to a legal `PASS`. **That is a silent-failure hazard: an all-PASS game with a $3,000 bank is a swallowed exception, not a strategy.** |
| `params.py` | every tunable constant, env-overridable via `SCRATCH_PARAMS`. Phase-scoped knobs need `NAME_P2`/`NAME_P3` **declared** and the reader must go through `params.at(name, day)`; otherwise the knob is dead. |
| `state.py` | the immutable per-turn snapshot: tiles, shed, seeds, money, units, plus derived fields (`plant_ready`, `needs_water`, `water_window`, `in_water_window`, `ongoing_produces_today`, `is_weed`, `owned`, `unlocked`, `herd_count`, `shed_total`, `unit_count`). Every layer reads this and nothing else. |
| `market.py` | price curve + demand metadata, vendored from the engine so `src/` has no `main.py` dependency. |
| `demand.py` | the money side as exact functions: `drain_at_step`, `unit_price`, `revenue_for`, `price_forecast`, `shop_unlock`. |
| `routing.py` | movement arithmetic: Manhattan, Dijkstra, A*, nearest-tile, one-step moves. `flood()` = one Dijkstra per unit per turn giving true distance + first step. |
| `value.py` | **the price list.** Dollars per tile, per animal, per op: `cycle_days`, `cycle_revenue`, `tile_dollars_per_day`, `tile_option_value`, `animal_value`, `dollars_per_turn`. Any "is this worth doing" question is answered here, in dollars. |
| `recipes.py` | the engine's *optimum* per crop, derived from the rules rather than tuned: water windows, harvest ages, `fert_urgency`, `next_step`, `best_crop_per_tile_day`. |
| `priors.py` | Boey's measured policy from `docs/boey_priors.json` (359 episodes): `CASH`, `LAND_CUM`, `TOTAL_ANIMALS`, `SPECIES_*`, `CROPS`, `HIRES`, `FERT`, `SHED_HOLD`, plus `LAND_BY_QUADRANT` / `land_due_day` / `land_lead` and the ops-chain targets `acts_target` / `water_target` / `hands_target` / `revenue_target`. **Targets, not laws.** |
| `benchmark.py` | Boey's day-wise surface from `docs/boey_bench.json` — **all 38 measured columns**, p25/p50/p75 per day. `band` / `target` / `gap` / `pressure`. GENERATED by `tools/phases/bench_codegen.py`, which now derives the metric list from the JSON so a column can never be silently dropped. |
| `job.py` | the `Job` record and the **priority constants** (`P_WATER_SURVIVAL`, `P_FEED`, `P_HARVEST`, …). **These constants encode a survival-first ordering that neither graph pressure nor a pure dollar ranking reproduces — treat as tuned state.** See below. |
| `waste.py` | 21 named zero-value-turn codes and the gate for each. |

### the graph — the diagnostic frame and the market decision engine
| file | owns |
|---|---|
| `state_graph.py` | the causal DAG evaluated **in-state**: live readers (`_LIVE`), `deviation`, `roots`, `urgency` (hour/day ramp), `pressures`, `apply_to_jobs`, `apply_to_market` (**the one market choke point**), `projected_empty`, `schedule`/`preposition` (**lead time**), `deficit_jobs`, `value_kernel`, `report`. **A node with no `_LIVE` reader is DEAD** — it never evaluates, never pressures. `set(NODES) - set(_LIVE)` must be empty. |
| `state_graph_data.py` | the DAG itself: `NODES` (source, direction, deadline class, licensed ops), `EDGES` (causality), `HALF_LIFE`-style constants. GENERATED by `tools/phases/dag_codegen.py`. |

### structural — what to build, buy and plant
| file | owns |
|---|---|
| `budget.py` | **land + hires.** `_fill_capital` (working capital to fill a quadrant), the land-buy condition (due day from `priors.LAND_BY_QUADRANT`, cash gate, one quadrant per turn, `LAND_QUADRANT_MAX`), and the crew ramp. |
| `crop_plan.py` | the crop calendar and the field jobs: `plant_queue` (**the live PLANT quota**), `seed_ask` (**an ask, not an order** — see `plan.seed_intents`), fertilizer jobs, `jobs()`. |
| `herd_plan.py` | species mix, buy/place, FEED/CARE/COLLECT; `feed_reserve` (**the cash the herd must keep**); builds housing **only to house animals already owned**. |
| `layout.py` | the structural board plan and the per-worker slice partition. |
| `opening.py` | the d0–d5 opening tape, the measured script. `crop_target`/`CROP_BY_DAY` is the **d5-clamped 25-tile-era table** (its `plant_jobs` owner was deleted — `scheduler._plant_jobs` is live). `seed_ask` returns the tape's seed ask as tuples. |
| `tasks.py` | the whole decision surface enumerated: every scenario as a task with a deadline, `loss_rate`, `route`, `plan_visits`, `reserve_ok`. |
| `plan.py` | **the allocation actuator**: `seed_intents` (**the single owner of every `BUY_SEED`**), `capex` (value-ranked claims: land, animals, seed), `fill_gates`/`fill_report` (the four gates of fill), `hand_target`, `seed_need`, `allocation`. |
| `risk.py` | P7: the sign of the variance we want, read from the live margin (`margin`, `behind`, `lam`, `weight`). |
| `roots.py` | the binding-root controller (`apply`). |

### execution — who does what, and the action dict
| file | owns |
|---|---|
| `scheduler.py` | **`plan(state)` — the only thing `__init__` calls.** Gathers jobs from the layers, assigns each unit via `_pick` (minimise `walk_cost - priority`), routes one cell, and compiles the market list. **The market list IS the funding order** (`emit` truncates at `MAX_ORDERS=10` and drops the tail silently). |
| `crew.py` | **the crew is paid in dollars**: `job_value`, `score` (dollars per unit-turn — "the whole basis of the ranking"), `turn_price`, `steer`, `deviation_report`, `hand_budget`. |
| `sell_policy.py` | the demand-aware sell rule (inventory targets). |
| `trade.py` | the wheat carry — sell high, buy back low. |
| `endgame.py` | d26–29 retirement: stop feeding, walk the herd away, liquidate. |
| `emit.py` | assembles the action dict; enforces `MAX_ORDERS`, the **collective-PLANT guard** (over-asking a crop voids the whole batch), the `GRAPH_MARKET` choke point, and the crash fallback. |

### The one thing to know before touching `job.py`
Two independent attempts to override the crew's ordering **both failed**:

* multiply priorities by graph pressure — harmful at **every** cap
  (1.0 $58,899 / 1.1 $50,716 / 1.25 $47,228 / 1.5 $37,175);
* replace the kernel with normalised `crew.job_value` × graph urgency — $42,446, **deaths 59 → 94**.

Conclusion: `job.py`'s constants are **tuned state**, not a placeholder. The graph's proven role is
the **market** (a funding order is a sequence, and sequences are smooth in weights) and the
**diagnostic frame** for everything else.

## THE STATE GRAPH IS THE DECISION ENGINE (read before adding any rule)

`src/state_graph.py` is the central nervous system. Every decision — which job a hand
takes, when to buy seed, when to buy land, what to plant, what to sell, when to hire —
must be a **consequence of a pressure the graph emits**, never a rule written beside it.
`src/state_graph_data.py` holds the nodes; `tools/graph/graph_diag.py` troubleshoots the
whole graph across every modality, step by step, against the ideal trajectory in
`docs/boey_priors.md` / `docs/boey_bench.md`.

**The rule this replaces — do not do this again.** Every "fix" that hardcoded *when* to
act (`SEED_LEAD_DAYS`, `HARVEST_AGE_WHEAT_P2`, a day table clamped at d5) became a new
owner of a decision the graph already had an opinion about, and the two then disagreed
silently. Measured cost of that class: the crop target was authored for a 25-tile farm and
clamped at d5, so from d6 the plan asked for **16 plants while we owned 75 tiles** and the
planting layer emitted **zero jobs**. No knob would have found that.

**How to add a decision:**

1. **Name the node.** If the quantity you want to act on is not a node in `state_graph_data.py`,
   add it, with its source (`priors` / `bench` / `derived`), direction, deadline class and the
   **op classes it licenses**. A node with no ops is a report; a node with ops is a decision.
2. **Give it a live reader.** A node in `NODES` with no entry in `_LIVE` is **DEAD**: it never
   evaluates, so it is never deficient, so it never emits a pressure. Measured: `revenue_per_day`
   and `labour` were both dead, which silently removed **SELL, HARVEST and HIRE** from the graph's
   reach entirely and severed `output_per_day -> revenue_per_day -> money` in the middle. Run
   `python -c "from src import state_graph as s; print(set(s.NODES)-set(s._LIVE))"` — it must be empty.
3. **Pressure, not a switch.** The layer reads `state_graph.pressures(state)[op]` and weights its
   own value kernel by it. Ordering, funding priority and job priority all follow from the same
   number, so a change in the graph moves everything consistently.
4. **Market orders go through the choke point.** `emit.assemble` calls
   `state_graph.apply_to_market`, which orders the list by graph pressure (sells stay first —
   they are the only inflow). `emit` truncates at `MAX_ORDERS`, so **the order of that list IS the
   funding priority**. Add a market decision by giving its op a pressure, not by reordering the
   concatenation in `scheduler`.
5. **Divisible vs atomic claims.** Seed is divisible ($10 a unit, half a quadrant sown beats
   none); land and animals are atomic. A pure NPV ranking lets the divisible claim eat the atomic
   one — measured: $2,800 of strawberry seed against a $1,000 quadrant cost $17,231 on one seed.
   Atomics keep a reservation; divisible claims spend the surplus above it.

**The chain to protect — `acts -> watering -> production -> revenue`.** A break at `acts`
propagates downstream, so never read the money row before the acts row, and never read money
without `empty`. Diagnose with:

```bash
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section break
PYTHONPATH=. python -m tools.graph.graph_diag --run-dir diag-replays/<arm> --section demand
```

`--section plug` audits which modules still bypass the graph; `--section seed` prints the seed
mechanics as the graph sees them (gap, lead, band, budget). A node that **breaks and stays
broken** is a root the graph failed to close — that is a structural bug, not a tuning problem.

## HOW TO EXPERIMENT AND FIND THINGS TO WORK ON (IMPORTANT)

> Read this before writing any experiment. It exists because dozens of
> experiments silently "found nothing" while re-deriving machinery that already
> existed, or while chasing a proxy metric that does not score.

0. **Find the ROOT with the phase tool before writing anything.** Margins say *that*
   we are behind; they never say *what to change*.
   `PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 --pa 1,2 --batch 1`
   (or `--phase all --ref-from replays/DSM/v1 --ref-max 4`) labels each deficient
   structure. A metric is a **ROOT** when it is deficient and every upstream cause is
   healthy, and the tool prints how many other deficient metrics that root explains.
   An experiment aimed at a *symptom* is the single most common way to spend a day
   and "find nothing" — the graph tells you which chain to cut, and which metrics are
   merely downstream of a root you have not touched.
1. **Point at a measured defect first.** Hunt in `games.csv` /
   `days_seed<S>.csv` for a concrete, seed-independent leak: stranded stock at the
   bell, endgame conversion, overflow discards, missed harvests, unwatered plants,
   a bad `avg_price_<p>` on a specific day, idle units on a ready tile. If you
   can't name the defect you watched, you don't have an experiment yet. The
   current open list is §6 of `docs/DSM-vs-us(v0).md`.
2. **Read the layer that owns it before changing it.** Every defect has a home:
   market timing lives in `sell_policy`, the crop calendar in `crop_plan` and
   `params.CROP_PLAN`, herd sizing in `herd_plan`, "who walks where" in
   `scheduler._pick` and `layout`, endgame in `endgame`. Make an *informed
   surgical* change to the owner, not a from-scratch guess in a new file.
3. **Make the smallest change that attacks that one defect and nothing else.**
   Prefer a `params.py` knob (env-overridable via `SCRATCH_PARAMS`, see below) so
   the same seeds can be A/B'd without editing code.
4. **Judge on `result` (WIN/LOSS), never on a proxy mean.** A target column
   moving the "right" way with the guards green is NOT a win signal. Read
   win/loss and the per-game margin; check the defect you were attacking actually
   moved, and that nothing else regressed.
5. **Respect the shared market.** Any change to how much we produce or sell
   reprices what *both* players see, so holding or cutting our own supply can hand
   the opponent the premium. Prove a real benefit before touching it.
6. **Reuse, don't rebuild.** `src/market.py` already encodes the price curves and
   which products are knife-edge; `src/state.py` already derives plant readiness,
   water windows and ongoing-crop production days. Fighting those with a private
   copy of the logic is how a "fix" becomes two bugs.

**Non-goals:** changes that only move a proxy mean; optimising a cross-game
average; a patch whose only effect is to alter a metric we do not score on;
recreating the deleted tape/chassis/patch machinery.

## A/B testing without editing code

`src/params.py` reads an env override at import, so you can measure two
configurations on identical seeds from one tree:

```bash
# baseline arm
SCRATCH_PARAMS='PLANT_RAMP=0;MOVE_WEIGHT=0' python -m tools.diagnose --scratch \
    --pa 1-12 --batch 8 --seed 4362837462 --run-dir diag-replays/arm-a
# candidate arm (same seeds, same opponents)
python -m tools.diagnose --scratch \
    --pa 1-12 --batch 8 --seed 4362837462 --run-dir diag-replays/arm-b
# matched-pair diff with a sign test + defect watchlist
PYTHONPATH=. python -m tools.report.arm_diff --a diag-replays/arm-a --b diag-replays/arm-b
```

`BOOLEANS` accept `1/0/true/false`; ints and floats are parsed by type.

## Submissions

**The agent has NO permission to submit/push to Kaggle.** `package.py` is for
*local packaging only*: it builds the single-file bundle from `src/` and can verify
it with `--check` (one seeded game, asserting the bundle's bank equals the local
`src.agent`'s). Never run `--push` yourself. Submitting the actual entry is the
human's call, run by them from a terminal. Do not auto-run a mock game around
packaging either — build the file and stop.

## Anti-goal: never trust cross-game averages

**Do not optimize the average score.** The environment is dynamic — random-seeded
games, live moving prices, and a different public opponent every match. An average
of scores is misdirection: it regresses our rating.

Always hunt for **inefficiencies in the system** and tackle **system-level
issues**:

- idle steps, shed overflow, plants dying, missed harvests
- unfed / unwatered animals, animal escapes
- floor-price / below-base sales, poor market timing
- structural defects in scheduling, routing, stock/inventory, crop & animal
  lifecycle handling

Signal = a concrete defect observed in a specific game / day / step that hurts
every game regardless of seed or opponent. If you can't point at one, it isn't an
improvement — even if some mean moved.

### Confound you must read every table with: the shop draw is a function of OUR play

`_spawn_weeds` draws `rng.random()` once per **empty tile of both farms**, and the
day's shop unlock is drawn from that **same RNG** immediately afterwards
(`_end_of_day`). So the number of empty tiles we leave moves the shop RNG stream.

Measured: the shop draw differs between arms in **18/18 games** (same seeds, same
opponents). Concretely, `YARN_STORE` appeared in **9/18** games in one arm and
**15/18** in another.

Consequences, for every table you read:
- A metric conditioned on a shop (e.g. "SHEEP in YARN worlds") is **not a
  controlled comparison across arms** — the worlds themselves changed.
- Seed+opponent pairing still holds (the episode seed is fixed); what diverges is
  everything downstream of the RNG.
- Always print the shop mix beside a shop-conditioned metric
  (`tools/market/shop_response.py` prints it first, and `dsm_profile.py` reports
  the arm's YARN mix), and prefer unconditional metrics when judging a change.

## Why "never trust averages" runs deeper: the win-vs-money objective

Distilled from the community notebook `wins-not-money.ipynb` (destbreso) — the
single most instructive result in this folder, and the *reason* the anti-goal
above is not just a workflow preference.

- **The ladder pays for wins, not dollars.** A win by $1 and a win by $50k move
  the rating the same way (measured: after a submission's first ~15 games the
  margin/rating link vanishes; below ~40 games a win rate is pure binomial ~11pt
  noise). The quantity to maximise is **Pr[win] ≈ Φ(μ/σ)** — the
  *mean-over-spread* of the margin — not the mean margin. **Money is a
  lower-noise estimator of the same thing, not the objective.** So: *judge a
  change on margin (low-noise measurement), but choose the change that raises
  Pr[win]*. A change can raise the median bank and still lose more games than it
  wins; that exact failure is documented in the notebook.
- **Optimise consistency, not magnitude.** A µ/σ maximiser beats the opponent
  narrowly instead of crushing half the field. The strongest agents cited win by
  leaving the rival less (median bank within 0.5% of their predecessor).
- **Signed risk preference.** Additional variance *increases* Pr[win] only when
  you expect to finish **behind** (ℓ+μ<0) and *decreases* it when **ahead**. Both
  banks are public, so ℓ is observable every turn. A variance term with a fixed
  sign is wrong half the time; the sign flips at ℓ+μ=0.
- **Non-composition — why greedy hill-climbing lies.** E[M] is linear and
  composable, but Pr[win] is a *ratio*: dispersions of independent effects add
  while means do not (revenue is concave — selling into a market you already moved
  fetches less). **Evaluate combinations, never components.**
- **Aggregate per opponent, then average — never the other way round.** A single
  pooled Φ folds between-opponent spread into σ and flatters you (~4pt here).
- **Practical translation:** `tools/report/arm_diff.py` diffs the **same seed**
  (matched opponents cancel) with a sign test; `tools/gates/margin.py` prints the
  five-number ladder; `tools/report/day_gap.py` and `dsm_profile.py` normalise
  **per-opponent median → median across opponents**. Trust `result` (WIN/LOSS);
  treat `final_money` as the noisy-but-high-resolution readout, never the score.

## How the leaderboard is ranked (what we actually maximize)

- **The leaderboard score is a win/loss rating, not money.** Live top-50 scores
  sit in a tight band (~2801–3163, mean ≈2894) — the signature of an
  Elo/Glicko-style rating computed from head-to-head matches, **not** a sum of
  bank balances (those are ~10⁴–10⁵ per game).
- **Each *episode* is exactly one match between two teams.** A leaderboard
  `games.csv` shows a submission *both* as seat 0 and seat 1 with mirrored
  WIN/LOSS — two rows for the SAME game. **Never count an episode twice.**
- **Money is only the tie-break that decides who wins a match.** The dollar
  magnitude of your bank never enters your score — a win by $1 and a win by $50k
  move your rating the same. Your bank merely *decides* each match's winner, so
  it's a lower-noise signal of your win probability — not the objective.
- **#1 ground truth:** DSM tops the ladder with **117W–5L (95.9%)**, mean margin
  **+$17,721**, median **+$14,144**, normalised (median-of-per-opponent-medians)
  **+$20,351**, worst game **−$3,570**, and **0.0%** of games lost by more than
  $4k. **The thing to copy is not the margin, it is the floor.**

**So "maximize for this" means: maximize `Pr[win] = Φ(μ/σ)` over the match-making
pool — beat the field reliably, not post a bigger bank.** Rules:
1. Judge every change on **`result` (WIN/LOSS)**; a higher median bank that loses
   more games is a regression.
2. Treat margin as the diagnostic readout, never the score.
3. **Optimise consistency, not magnitude** — the leaders sit within ±80 rating
   points, so wins (not blowouts) decide who is #1.
4. When diagnosing an opponent from `--lb` replays, both seats are the same match;
   tally one win/loss per episode for the team under study.

## Game dynamics — read `GAME_DYNAMICS.md`

All engine mechanics — crops & watering windows, animals/feed/care, the full
market and price tables, town & shop demand, hiring, turn-processing order, config
knobs, and the measured crop-payoff guide — live in `GAME_DYNAMICS.md`.
**Read it before designing any experiment, and include it in context.**

Two mechanics that bite often in `src/`:

- **A newly planted crop has `consecutive_unwatered = 1`**, so it must be watered
  the same day or it becomes a WEED that night. `state.plant_ready` is checked
  before `state.needs_water`, so a ripe tile is harvested, not watered.
- **The CARE bonus is only paid on a *fed* production day** (`_daily_refresh_animals`
  pops `pending_care_bonus` only when `fed_today`, and resets it otherwise), so
  feeding every other day silently halves herd output.

## Workflow

> **Running the harness / long jobs (operator preference):** do NOT launch long
> game runs (a multi-seed sweep) in the background and leave them running. Hand the
> operator the exact foreground command (`make scratch PA=1-12 BATCH=8`,
> `./scripts/sweep.sh 4362837462 15`, ...) and let them run it. Use all cores by
> default (omit `--workers`); only cap concurrency when asked. The 60 s shell
> timeout applies to foreground commands, so anything longer is a command the
> operator runs themselves.

1. **Find the root.** `python -m tools.phases.phase_map --phase <p>` (add
   `--ref-from replays/DSM/v1` for measured targets). Work the phases in order; fix
   phase 1's roots, then move on. Do not patch a symptom the graph already explains.
2. Write the change in the layer the tool names as the owner (`src/<layer>.py`), or
   add a knob to `src/params.py`.
3. Run it. Quick loop: `make scratch PA=2 BATCH=12`. Structural claim:
   `./scripts/sweep.sh <seed> <batch>` (all 12 public agents × batch seeds).
4. **Re-run the phase tool** and confirm the root is gone. If it is, its downstream
   symptoms should have moved with it — that is the causal link, verified, and it is
   the check a CSV diff cannot give you. If the root is unchanged, the patch missed.
5. Inspect the JSON replays / CSVs for **concrete** per-game / per-day / per-step
   inefficiencies. **Never average anything across games** — see the anti-goal.
6. Compare arms with `tools/report/arm_diff.py` (matched pairs) and read the
   defect surface with `tools/gates/balance.py`.
7. When the change is clearly better and stable, it is already in the product —
   `src/` is the agent. Record what you learned as a new edge in
   `tools/phases/dag.py`, and keep `docs/DSM-vs-us(v0).md`'s open list current.

### Harness commands

```bash
make scratch PA=2 BATCH=12                 # run the agent vs PA 2 over 12 seeds
make scratch PA=1-12 BATCH=8               # the whole public field
make diag ARGS="--pa 1-12 --batch 4 --seed 4362837462"
make replay DIR=diag-replays/v0-us         # re-diagnose saved replays (no games)
make replay-lb DIR=replays/DSM/v1          # leaderboard replays (no seed)
make graph  DIR=diag-replays/v0-us         # dashboards + farm-board GIFs
make sweep SEED=4362837462 BATCH=15        # all opponents + per-opponent summary
make verify                                # compile + import the agent and harness
```

The agent under test is always the `src` package; its replays are named
`scratch_vs_<opponent>_seed<N>.json` and its `games.csv` rows carry
`agent=scratch` (the historical name of the from-scratch agent, kept so existing
tools and globs keep working).

## Phased structural development — `tools/phases/phase_map.py`

Margins tell you *that* you are behind; they do not tell you *what to change*. The
phase tool is the one to reach for when deciding what to work on:

```bash
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 --pa 1,2 --batch 1   # quick
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 --pa 1-12 --batch 4  # the field
PYTHONPATH=. python -m tools.phases.phase_map --phase all --pa 1-12 --batch 2
PYTHONPATH=. python -m tools.phases.phase_map --dag        # the causal graph itself

# replay modes: analyse saved games, and/or take the #1's own games as the target
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 \
    --replay-dir replays/DSM/v1 --max-games 6 --seat auto          # audit the targets
PYTHONPATH=. python -m tools.phases.phase_map --phase phase1 \
    --pa 1,2 --batch 1 --ref-from replays/DSM/v1 --ref-max 4       # live us vs his replays
```

`--ref-from` is the strongest setting: the targets become the #1's *measured* reduction
instead of the transcribed per-day table, so every metric gets a target (including
`cash committed` and `PLANT ops`) and there is no transcription risk. The table is the
fast fallback. Running the #1's own replays through the same DAG is a self-check that
should read all-OK — it is how the `structs=10` error in `docs/dsm_v1.md` was caught
(his replays show 5 pastures at d5, all five occupied, 20 plants, 25 tiles full, and
`dag.py` now models his housing as build-to-order).

It runs the agent **in-memory** with the episode truncated at the phase boundary
(d10 / d20 / the bell) — the agent is stateless and never reads the horizon, so a
truncated game has the same d0..N behaviour at a fraction of the cost — measures only
**structural** metrics against the #1's measured per-day state, and then walks the
causal DAG in `tools/phases/dag.py` to label each deficient metric as a **ROOT** (no
deficient ancestor) or a **symptom**, with the root's **blast radius**.

Work the game in order: fix phase 1's roots, re-run `--phase phase1`, then move to
phase 2 and check that its roots shrank. A phase-1 root that shows up as a phase-2 or
phase-3 symptom is the "everything downstream has roots in the beginning" case, and
the trace prints the chain that connects them. Edit `dag.py` (metrics, targets, edges
and their mechanism text) whenever you learn a new dependency — the graph is the
durable artefact, the tool just evaluates it.

Worked example (2 opponents, `--phase all --ref-from replays/DSM/v1 --ref-max 3`):
phase 1's root is **opening cash committed** (0.33 vs 1.00); phase 2's roots are
**animals on board** (0 vs 20) and **WATER ops** (426 vs 588); phase 3's are **WATER
ops** (571 vs 677), **animals at the bell** (0 vs 11) and **FERTILIZE ops** (0 vs
153). The trace prints the chain that ties them together, ending in phase 1:

    animals at the bell [p3] <- animals on board [p2] <- owned tiles [p2]
      <- opening cash committed [p1]

Two things it also settles cheaply: **`owned tiles` is 100/100 = OK by phase 2**, so
the land gap is purely an opening-*timing* artefact rather than a midgame problem;
and we water 0.72 ops per planted tile against his 0.83, which comes out as **26 plant
deaths against his 1** — the C5 chain (`water -> plants died -> weeds -> harvest`),
which is the midgame's own root and owes nothing to cash.

**A root is a hypothesis, not a verdict.** When a phase experiment contradicts the
graph (measured: enabling the opening herd is the phase-1 root the graph finds, yet it
costs $15,020 at 25 tiles), that contradiction is the finding — encode it as an edge
mechanism and re-order the roadmap.

### `--days 0-10` — every tool can be scoped to the opening

`phase_map --days 0-10` replaces `--phase` with a custom window; `--dag phase1` prints
only the opening subgraph plus the edges *leaving* it. Every analysis tool in
`tools/labour/`, `tools/market/` and `tools/report/day_gap.py` takes the same `--days`
flag, so "the opening only, nothing else" is one argument everywhere. Use it: a
whole-season aggregate buries a d0–d5 defect under 24 days of noise.

**`open_dist` is descriptive, not an objective.** It is the L1 distance from the #1's
invariant d5 signature (10 MELON + 10 STRAWBERRY, 2 COW + 3 SHEEP, 25 tiles, 1 quadrant)
and it went 13 → 5 when the opening script shipped. The residual 5 is **4 MELON +
1 STRAWBERRY** tiles, and closing it is a **loss**: `WHEAT_LANDS_DAY=2` takes it 5 → 1
while `dterm` falls **−$15,452 (0/8, p=0.005)**, because the herd's feed reserve is what
stops the farm spending itself to zero and then buying feed at retail (C2). Never report
this metric without that number beside it.

**The latent nodes are live now.** `_stock` records `town.unlocked_shops`, so
`shops unlocked` / `YARN_STORE unlocked` are real. Measured by d5: **exactly one shop**
in 36/36 of our games and 30/30 of the #1's; YARN in **0/36** ours and **4/30 (13%)**
his. So "react to the shop reveal" is **vacuous in the opening** — one draw, and the wool
buyer one time in eight. Reactivity is a d6+ question. (This also explains why an early
`HERD_EXPAND_ON_YARN` probe read exactly inert: with P(no YARN) ≈ 0.87, eight YARN-free
games happen ~33 % of the time.)

### `state_value.py` — price the d5 state, and test which d5 feature predicts the finish

`phase_map` counts structures; this **prices** them. Rationale: the opening is only
~6.5% of the season's revenue gap, and a whole-game margin has sigma ≈ $10k on 12
games, so both opening A/Bs so far were underpowered by construction. Three readouts:

1. **The d5 state price.** `liquid = cash + shed at the d5 price` is exact and
   policy-free; `nav` adds standing crops and herd production minus feed.
2. **Frozen continuations.** The prefix roll-out is deterministic, so the first 144
   steps can be re-run exactly and the rest handed to another policy
   (`--cont live,nobuy,liquidate`). `max(term) - min(term)` is the option value still
   embedded in the d5 position.
3. **A regression of the terminal bank on the d5 state.** Standardised coefficients say
   which d5 quantity the market actually pays for; `R^2` says how much of the finish was
   already set by day 5.

```bash
PYTHONPATH=. python -m tools.phases.state_value --pa 1-2 --batch 2
PYTHONPATH=. python -m tools.phases.state_value --ref-from replays/DSM/v1 --ref-max 40
# THE decisive one: separate a better d5 STATE from a better post-d5 POLICY
PYTHONPATH=. python -m tools.phases.state_value --cross 'HERD_ENABLED=1;OPENING_SCRIPT=1' \
    --pa 1-8 --batch 1
```

`--cross` runs the 2×2 (neutral/neutral, arm/arm, **arm prefix + a fixed continuation**).
`C − A` is the value of the arm's d5 **state** with the policy held fixed; `B − C` is the
value of its post-d5 **policy** from a fixed state. Measured on the opening script + herd,
with a fixed continuation that can *service* the herd it was handed
(`--cross-post 'HERD_ENABLED=1;HERD_BUY_FROM_DAY=99'`): **d_state +$7,410 (7/8), d_policy
−$16,775 (0/8)** — the state is good and the post-d5 expansion policy is what destroys it.

**The fixed continuation must be able to service whatever the arm's state contains.** Run
the same cross against the tree default and cell C lets the herd starve: **d_state flips
to −$8,671 (0/8)**. That inversion, not the arm, is what a naive cross measures. Always
pass `--cross-post` when the prefix leaves behind resources the default policy cannot
maintain. **A d5-state objective must be validated by a continuation, never by the mark
alone** — and the continuation has to be a *valid policy for that state*.

### `shadow_prices.py` — one more unit of each resource, in dollars

A root with a large blast radius is **not** automatically worth fixing (that is how the
opening herd, the graph's #1 phase-1 root, lost $15,020). Counting descendants cannot
rank jointly-scarce resources; a price can. `shadow_prices` is a paired finite
difference: baseline vs baseline + one `SCRATCH_PARAMS` override, same seeds, reporting
`dNAV_d5` beside `dterm`. Rows where the two disagree in sign are flagged — a
perturbation that buys d5 NAV and sells the terminal is a *paper* improvement.
(Measured on the first pair: `HERD_ENABLED=1` gives **dNAV_d5 +$2,264** and
**dterm −$18,133** — the graph's root, priced negative.)

```bash
PYTHONPATH=. python -m tools.phases.shadow_prices --pa 1-3 --batch 4
PYTHONPATH=. python -m tools.phases.shadow_prices --pa 1,2 --batch 6 \
    --perturb 'herd|HERD_ENABLED=1||'
```

## Reading the harness output — columns & signals

The harness writes three things per run directory (`diag-replays/run-N/` by
default, or your `--run-dir`):

- **replay JSONs** — one per game, the full per-step observations+actions for both
  seats.
- **`days_seed<S>.csv`** — one file per seed, one row **per day** for the agent
  under test (seat 1; the public agent sits at seat 0). Per-day timeline, **not**
  aggregated.
- **`games.csv`** — one row **per game** for the agent under test, plus a compact
  per-game readout printed to the terminal.

Re-diagnose saved replays with `python -m tools.diagnose --replay-dir <dir>`;
add `--render` to print the day report (with a board-symbol legend up front).
`--replay-dir <dir> --graph` renders a 1×2 dashboard PNG per game **plus an
animated farm-board GIF** (`_board.gif`) — one frame per in-game day showing BOTH
farms' 10×10 maps with farmer/hand dots, **per-species animal triangles**
(GOOSE/COW/SHEEP, colour-coded), a legend, and a money-race panel, so you can
watch *when* a defect appears. GIF speed defaults to **1.5 fps (≈0.67 s/day)**;
pass `--gif-fps 4-5` for a quicker skim. `--animals` renders the season-constant
`animal_care_payback.png` separately.

> **Near-shed land is the ANIMAL zone, not wasted crop land.** The inner ring
> (within ~2 of the shed) is ~100% livestock + pastures/coops in every DSM replay
> (it's the cheapest feed/care round-trip). Don't read a bare-looking GIF there as
> "crops should grow from the shed outward" — animals are drawn as triangles.
> `near_shed_planted_max`/`near_shed_bare` (top-half ring crops) correctly stay ≈1/0.

### `games.csv` columns (one row per game)

| column | meaning | read it as |
|---|---|---|
| `final_money` / `opponent_final` / `result` | end bank balances; `WIN`/`LOSS`/`TIE` | W/L/T only — margins don't score |
| `idle_share_pct` | % of work-unit turns that were `PASS` (**the** labour-efficiency signal) | high ⇒ idle hands/wasted labour |
| `idle_units_total` | unit-PASS turns, any tile | how many work-slots did nothing |
| `idle_units_ready_total` | unit-PASS while standing on ready produce/animal | **missed-harvest idling** |
| `idle_steps` | whole-turn idle (all units PASS, no market) | ~always 0 — low-signal, ignore |
| `shed_pressure_days` / `shed_overflow_days` | days shed ≥95 / ==100 | near/at cap ⇒ overflow risk |
| `discarded_units_total` / `discarded_items` | shed-overflow units discarded; which item | what actually got thrown away |
| `floor_sales` | units sold at the $1 floor | gluts dumped into the floor |
| `stranded_at_bell` | $ value of sellable stock at FINAL prices (animals excluded) | endgame hygiene — leader tolerates ~$450 |
| `locked_steps` / `locked_units_at_bell` | worker-turns standing on unbought `LOCKED` tiles | wasted labour; should be small |
| `premium_below_base_frac` | share of premium-good units sold below base | bad timing on crash-prone goods |
| `animal_escapes` / `escaped_by_type` | animal losses; `at_risk_of_escape` = ≥2 consec. unfed | near-miss precursor |
| `plants_died` / `missed_harvest_eod` / `unwatered_eod` | decayed crops / unharvested at day-end / unwatered at EOD | lifecycle defects |
| `seed/animal/product/hire/land_cost_total` | itemized spend per game | `land_cost_total` is **unreliable** — see below |
| `sell_revenue_total` | committed revenue from sold produce | **the** revenue number (audit-backed) |
| `wheat_fed` / `feed_surplus` | wheat fed; `produced - fed` | feed self-sufficiency |
| `harvests` | harvest ops | throughput |

### `days_seed<S>.csv` — the day-by-day columns to look at
`revenue`/`expenses` (sign-split — approximate), `seed_cost`/`animal_cost`/
`product_cost`/`hire_cost`/`land_cost` (exact), `shed_items_start_*/_end_*`, `max_shed_total`,
`weeds_max`, `hires`, `idle_units`/`unit_turns`/`idle_share_pct`,
`plants_watered`/`plants_fertilized`, `animals_fed`/`animals_cared`/`animals_escaped`, `shop_unlocks`,
`sell_qty_<p>`/`avg_price_<p>`/`revenue_<p>`, `below_base_sales_<p>`,
`discarded_items_<p>`, `feed_surplus`, `wheat_sold`/`wheat_fed`/`wheat_bought`.

### How to hunt structural issues (never average across games)
1. **Same-seed paired diff.** Run two arms (see `SCRATCH_PARAMS` above) and use
   `python -m tools.report.arm_diff --a A --b B`: it joins on `(opponent, seed)`,
   reports the margin delta ladder, a **sign test**, the verdict flips, a
   per-opponent table, and a defect-column watchlist. `tools/gates/balance.py`
   gives the full paired balance sheet.
2. **Chase a non-zero signal.** Any of `idle_share_pct`, `idle_units_ready`,
   `shed_overflow_days`, `discarded_items`, `floor_sales`, `premium_below_base_frac`,
   `animal_escapes`, `at_risk_of_escape`, `plants_died`, `weeds_peak`,
   `missed_harvest_eod`, `feed_surplus < 0` in a **specific game** is a defect worth
   fixing. **Not `unwatered_eod`** — it counts out-of-window plants; see the caveats.
3. **Locate the day.** Open that seed's `days_seed<S>.csv`, find where the signal
   spikes, and correlate with `shop_unlocks`, `avg_price_<p>`, and `shed_items_*`.
4. **Price timing.** `avg_price_<p>` vs the product base shows when you sold. A
   premium-good `avg_price` well under base (or a high `premium_below_base_frac`)
   means selling into the glut instead of the scarcity spike.

### Caveats / which numbers to trust
- **Trust audit-backed fields** (`sell_revenue_total`, `floor_sales`,
  `below_base_sales`, `avg_price_<p>`, `discarded_*`, the cost totals except land)
  on any replay saved by our runs, which run with the market audit.
- **`land_cost_total` is NOT trustworthy** (ours or DSM's). It reports $10,000
  against a real $7,000 ceiling because the purchase order is re-issued every turn
  and the derivation re-charges it. Cross-check with the money ledger before
  quoting any land figure.
- **Observation↔action pairing.** A kaggle_environments step records the action
  that *produced* its observation, so the action decided from
  `steps[t]["observation"]` lives at `steps[t+1]["action"]` (verified: 97.1% of
  moves satisfy `pos[t+1] == pos[t] + action[t+1]`, vs 53.3% same-index). The
  harness's `replay_to_record` still pairs them at the same index, so
  **tile-conditioned** metrics (`idle_units_ready_total`, `locked_steps`,
  `missed_harvest_eod`, `near_shed_*`) are measured against the wrong step.
  `tools/labour/op_patterns.py` and `tools/labour/ready_idle.py` use the correct
  shifted form. Op-count and revenue aggregates are unaffected.
- **Harvest attribution is unreliable**: `plants_harvested_<crop>` misses most
  harvests. Prefer `sell_qty_<p>`/`avg_price_<p>`.
- **`idle_steps` is near-useless**; use `idle_share_pct` and
  `idle_units_total`/`idle_units_ready_total`.
- **`unwatered_eod` is NOT a defect metric** (median **622** on the shipped arm, and it
  looks alarming). `analysis.py` counts *every* crop without `watered_today` at hour 23,
  including plants **outside their water window** (a melon at age 13, a wheat at 6+) that
  will never need water again — those dominate it. Chase `plants_died` and `weeds_peak`.
- **Raising `P_WATER_SURVIVAL` does not cut plant deaths.** 90 (default), 105 and 120
  give byte-identical results; 105/120 are marginally *worse*. The death chain is not
  priority-limited — the crew lacks unit-turns (see the act-chaining note above). The
  knob is in `params.P_WATER_SURVIVAL` (read by `job.py`) if you want to test again.
- **`revenue`/`expenses`** (sign-split of money delta) undercount a step that buys
  and sells — prefer `sell_revenue_total` + the itemized `*_cost_total` columns.

## What to change

| file | role | editable? |
|------|------|-----------|
| `src/*.py` | the agent (onion layers) | **YES — the product** |
| `src/params.py` | every tunable knob (env-overridable) | YES |
| `tools/diagnose/` | the harness | yes, when a feature is missing |
| `tools/` (rest) | analysis tools | yes |
| `Makefile`, `scripts/sweep.sh` | run entry points | yes |
| `package.py` | local bundle build | yes |
| `docs/DSM-vs-us(v0).md` | the diagnosis + open fix list | yes — keep it current |
| `GAME_DYNAMICS.md`, `AGENTS.md`, `README.md`, `tools/readme.md` | docs | yes |
| `replays/DSM/v1/` | the #1's replays (reference data) | **NO** |
