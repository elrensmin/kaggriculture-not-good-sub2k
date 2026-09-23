# Agent Development Guide (handover)

## Golden rule

**Never edit `src/route_tape.py` while experimenting.**

- `src/route_tape.py` — read-only opening route tape data.
- `src/main.py` — **editable.** It's the production agent (~6,400 lines, a ~45-layer
  patch stack over a `make_agent` chassis). Improvements to its own layers are
  valid experiments, not just `agent.py` patches. Just don't break it, and keep
  `route_tape.py` untouched.

Most experiments still go in `src/agent.py` (the safest late-hook surface), but
editing `main.py`'s layers directly is allowed when the lever lives there.

## HOW TO EXPERIMENT AND FIND THINGS TO WORK ON (IMPORTANT)

> Read this before writing any experiment. It exists because dozens of
> experiments silently found "nothing valid" while re-deriving machinery the
> production agent already has. Don't repeat that.

**Understand the real architecture first.** `src/main.py` is not a naive agent;
it is a **`Chassis`** (built by `make_agent`) that (1) picks a **route tape** from
`src/route_tape.py` (`ROUTES` / `SHOP_ROUTES` — read-only data, one action-plan
per shop-draw / opening), and (2) runs a **~45-layer onion of `layer_XX_*`
functions** that each transform the action, tapping shared machinery
(`_View`, `projected_shed`, `_r37_market_price`, `_r37_similarity`, `FarmView`,
plus a `router` that switches routes mid-game — e.g. shop-aware yarn vs
non-yarn policies, and an endgame route flip). The base is already shop-aware
and market-timed at the route level. Our `agent.py` patch runs *after* all of
this and sees only `(action, observation, configuration)`.

**The patch surface is not "the whole agent" — it is one late hook.** A
post-hoc tweak that re-implements something the layers already do (a price
threshold for a product, culling an animal the router already specializes on,
a market-timing rule that `_r37` already computes from a forecast) will either
(no-op) duplicate the tuned behavior or (worse) fight it and regress. That is
why so many patches "find nothing": they are crude re-builds of existing
machinery, fighting a data-tuned system.

**How to actually find a valid experiment:**
1. **Point at a measured defect first.** Hunt in `games.csv`/
   `days_seed<S>.csv` for a concrete, seed-independent leak (stranded stock at
   the bell, endgame conversion, overflow discards, missed harvests, unwatered,
   a bad `avg_price_<p>` on a specific day). If you can't name a defect you
   watched, you don't have an experiment yet.
2. **Read the layer / route that owns it before overriding.** Use `main.py`'s
   own helpers (`import main as _main` → `_main._IMPL.chassis`, `projected_shed`,
   `_r37_market_price`, the route the chassis selected) so your override speaks
   the same model the base uses — make an *informed surgical* change, never a
   from-scratch guess.
3. **Make the smallest override that attacks that one defect and nothing else.**
   Prefer reusing the base's own state/forecast over re-deriving from
   `observation`.
4. **Judge on `result` (WIN/LOSS), never on a proxy mean.** A target column
   (floor_sales, revenue, a guard) moving the "right" way with the guards green
   is NOT a win signal — the grid ACCEPTs those. Read `wins_new`, and check the
   per-game margin still helps before promoting anything. A patch that reduces a
   metric while making us lose by more is a regression, not a success.
5. **Respect the shared market.** Any change to how much we produce/sell of a
   product reprices what *both* players see; holding or cutting our own supply
   can hand the opponent the premium. Prove a real benefit before touching it.
6. **Reuse, don't rebuild.** If the layers already handle something (shop-aware
   routes, market timing, endgame), fighting it is not an experiment.

**Non-goals:** no-ops that mirror the base; overrides that only move a proxy
mean; touching `route_tape.py`; optimizing cross-game averages; a
patch whose only effect is "reduces a metric we don't score on."

## Submissions

**The agent has NO permission to submit/push to Kaggle.** `package.py` is for
*local packaging only*: building the single-file bundle and (optionally) verifying it
with `--check`. Never run `--push` yourself. Submitting the actual entry is the human's
call, run by them from a terminal. Do not auto-run a mock game before/around packaging —
the operator does not want a bundle verification run; build the file and stop.

## How the patch system works

`src/agent.py` is a **patch layer over `src/main.py`**, not a standalone replacement:

- `--old`  → runs the full agent built into `main.py` alone.
- `--new`  → runs the full `main.py` agent, then `agent.patch(action,
  observation, configuration)` receives the action `main.py` produced and may
  alter it. Editing `patch()` is how you try ideas.
- `--compare` → runs `--old` and `--new` on the same seeds.

So every `--new` / `--compare` run does *everything `main.py` does, then applies
your patch* — measured against real production behavior, not an isolated stub.
Returning `action` unchanged from `patch()` is a no-op.

## Anti-goal: never trust cross-game averages

**Do not optimize the average score.** The environment is dynamic — random-seeded
games across the whole public leaderboard, with live moving prices. Which public
agent we face and any one seed's price action can swing any run. Trusting an
average of scores is misdirection: it regresses our score.

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

## Why "never trust averages" runs deeper: the win‑vs‑money objective

Distilled from the community notebook `wins-not-money.ipynb` (destbreso) — the
single most instructive result in this folder, and the *reason* the anti‑goal
above is not just a workflow preference.

- **The ladder pays for wins, not dollars.** A win by $1 and a win by $50k move
  the rating the same way (measured: after a submission's first ~15 games the
  margin/rating link vanishes; below ~40 games a win rate is pure binomial
  ~11pt noise). The quantity to maximise is **Pr[win] ≈ Φ(μ/σ)** — the
  *mean-over-spread* of the margin — not the mean margin. **Money is a
  lower‑noise estimator of the same thing, not the objective.** So: *judge a
  change on margin (low‑noise measurement), but choose the change that raises
  Pr[win]*. A patch can raise the median bank and still lose 28/28 games it
  changed — that exact failure is documented in the notebook.
- **Optimise consistency, not magnitude.** A µ/σ maximiser beats the opponent
  narrowly instead of crushing half the field. The strongest agent cited wins
  by leaving the rival less (median bank within 0.5% of its predecessor).
- **Signed risk preference (Corollary 3).** Additional variance *increases*
  Pr[win] only when you expect to finish **behind** (ℓ+μ<0) and *decreases* it
  when **ahead**. Both banks are public, so ℓ is observable every turn. A
  variance term with a fixed sign is wrong half the time; the sign flips at
  ℓ+μ=0.
- **Non‑composition — why greedy hill‑climbing lies.** E[M] is linear and
  composable (accepting any improving step converges), but Pr[win] is a *ratio*:
  dispersions of independent effects add while means do not (revenue is
  concave — selling into a market you already moved fetches less). Two changes
  that each raise μ/σ can jointly lower it. **Evaluate combinations, never
  components** (accept an idea only from a run of its actual patch, not from
  "each layer looked good alone").
- **Aggregate per opponent, then average — never the other way round.** A single
  pooled Φ folds between‑opponent spread into σ and flatters you (~4pt here).
- **Practical translation for our harness:** this is *why* `--compare` diffs
  the **same seed** (matched opponents cancel) and why `--old`/`--new` are
  judged per‑game on concrete defects rather than on a mean: a mean is the
  *wrong objective's* summary of the *wrong sample*. Trust `result` (WIN/LOSS);
  treat `final_money` as the noisy-but-high-resolution readout, never the score.

## How the leaderboard is ranked (what we actually maximize)

Confirmed from the live ladder + our own analysis of the #1's replays (`replays/DSM/`):

- **The leaderboard score is a win/loss rating, not money.** Pulling the live
  leaderboard gives scores in a tight rating band (observed top-50 span ~2801–3163,
  mean ≈2894) — the signature of an Elo/Glicko-style rating computed from
  head‑to‑head matches, **not** a sum/average of bank balances (those are ~10⁴–10⁵
  per game) and not a raw win count.
- **Each *episode* is exactly one match between two teams.** Why `games.csv --lb`
  shows a submission *both* as seat 0 and seat 1 with mirrored WIN/LOSS and swapped
  final/opponent amounts: two rows for the SAME game, one per seat. Seat 0/1 is just
  random orientation — irrelevant to scoring. **Never count an episode twice or read
  the mirror as evidence of two outcomes** (one `replays/DSM` episode is even DSM vs
  DSM, a self-play/mirror game: both rows flip identically).
- **Money is only the tie-break that decides who wins a match.** The env's reward is
  `final_money` per seat; the higher-reward seat takes the match. **The dollar
  magnitude of your bank never enters your score** — a win by $1 and a win by $50k
  move your rating the same (the `wins-not-money` point). Your bank merely *decides*
  each match's winner, so it's a lower-noise signal of your win probability — not the
  objective.
- **#1 ground-truth:** DSM tops the ladder (3163.2) with a **118W–6L record (95.2%
  win rate) across its 124 ladder games, mean margin +$17,435** (tallied from
  `replays/DSM/games.csv`). The ranking follows who wins more across the field.

**So "maximize for this" means: maximize `Pr[win] = Φ(μ/σ)` over the match‑making
pool — beat the field reliably, not post a bigger bank.** Rules:
1. Judge every change on **`result` (WIN/LOSS)**; a higher median bank that loses
   more games is a regression (the documented 28/28-loss failure mode).
2. Treat **margin as the diagnostic readout, never the score**: use it to *measure* a
   candidate's win probability; accept it only when it raises win rate.
3. **Optimise consistency, not magnitude** — a µ/σ maximiser wins narrowly but
   reliably; the leaders sit within ±80 rating points, so wins (not blowout margins)
   decide who is #1.
4. When diagnosing an opponent from `--lb` replays, both seats are the same match;
   tally one win/loss per episode for the team under study. (Our harness
   `--old`/`--new`/`--compare` already judge same-seed `result`, matching this.)


## Game dynamics — read `GAME_DYNAMICS.md`

All engine mechanics — crops & watering windows, animals/feed/care, the full market
and price tables, town & shop demand, hiring, turn-processing order, config knobs,
and the measured crop-payoff guide — moved out of this file into `GAME_DYNAMICS.md`.
**Read `GAME_DYNAMICS.md` before designing any experiment, and include it in context.**

## Workflow

> **Running the harness / long jobs (operator preference):** do NOT launch long
> game runs (a `--grid`, a multi-seed `--sweep`/`--compare`, a `--graph` batch) in
> the background and leave them running. Hand the operator the exact foreground
> command (`make grid ...`, `./sweep.sh new`, ...) and let them run it. Use all
> cores by default (omit `--workers` / leave `WORKERS` empty — the grid defaults to
> all cores); only cap concurrency when asked. The 60 s shell-timeout applies to
> foreground commands, so anything longer is a command the operator runs themselves.

1. Write a patch in `src/agent.py` (a `patch(action, observation, configuration=None)`
   function; there is no standalone agent to implement).
2. Run the harness to test it. The full CLI reference, seating convention,
   outputs and reproducibility live in `diagnose/cli.py`, and
   `python -m diagnose --help` prints the flags. The project overview lives in
   `README.md`. For a quick overall performance read, sweep against all 13
   public agents over several seeds:
   `./sweep.sh new` (or `./sweep.sh old`).
3. Inspect the JSON replays / CSVs for **concrete** per-game / per-day / per-step
   inefficiencies. **Never average anything across games** — see the anti-goal
   above. Judge on system-level defects you can point at, not on a mean.
4. When the patch is clearly better and stable, promote it into `src/main.py` as the
   new baseline, then clear `src/agent.py` for the next experiment.

## Using the diagnose package — columns & how to read the signals

The harness writes three things per run directory (`diag-replays/run-N/` by default,
or your `--run-dir`):

- **replay JSONs** — one per game, the full per-step observations+actions for both seats.
- **`days_seed<S>.csv`** — one file per seed, one row **per day** for the agent under
  test (seat 1 with the public agents). Per-day timeline, **not** aggregated.
- **`games.csv`** — one row **per game** for the agent under test (its seat), plus a
  compact per-game readout printed to the terminal.

Re-diagnose saved replays with `python -m diagnose --replay-dir <dir> --render`
(regenerates the CSVs; `--render` prints the day report, with a board-symbol legend up
front). The per-replay analysis is split across all cores by default (`--workers` to cap).
For **leaderboard replays** (downloaded from Kaggle, no seed — `info/configuration.seed`
are null) pass `--lb`: the per-day CSVs are then keyed on the episode id from each
filename (`days_seed<episodeid>.csv`), both seats are analysed, seats are labeled with the
real team names from `info.TeamNames`, and a `seat` column prefixes both CSVs. `--graph` renders a 1×2 dashboard PNG per game **plus an animated farm-board
GIF** (`_board.gif`) — one frame per in-game day showing BOTH farms' 10×10 maps with
farmer/hand dots, **per-species animal triangles** (GOOSE/COW/SHEEP, colour-coded), a
legend, and a money-race panel, so you can watch *when* a defect appears. GIF speed
defaults to **1.5 fps (≈0.67 s/day)**; pass `--gif-fps 4-5` for a quicker skim.
`--graph` also emits a season-constant `animal_care_payback.png` (cumulative cash per
animal, fed-only dotted vs fed+cared solid, with break-even days); render it standalone
with `--animals`. `games.csv` also carries `locked_steps`/`locked_units_at_bell`
(farmer/hand turns standing on unbought `LOCKED` tiles — wasted labour since 1.32.3).

> **Near-shed land is the ANIMAL zone, not wasted crop land.** The NW/NE inner ring
> (within ~2 of the shed) is ~100% livestock + pastures/coops in every replay (it's the
> cheapest feed/care round-trip). Don't read a bare-looking GIF there as "crops should
> grow from the shed outward" — the animals are drawn as triangles but were previously
> invisible because the tile cell is tiny. The `near_shed_planted_max`/`near_shed_bare`
> games.csv columns (top-half ring crops) correctly stay ≈1/0 for that reason.

> **Context for these metrics:** to see *how* the agent got here — the base
> route tape it runs on and the 45-layer patch stack built on top of it — the
> `games.csv` columns below are the layer-by-layer numbers each patch iteration
> moved. Read them as the per-metric defect ledger, and use `--grid` / `--compare`
> to measure any change against the same seed rather than trusting a mean.

### `--grid` — sweep an experiment's param space (paired, hedged)
Grid-search a parametrised patch instead of one hand-tuned `--compare`. Pick which
experiment to sweep with `--exp` (registry in `diagnose/config.py::EXPERIMENTS`):
- `--exp floor` (default): MILK/WOOL sell at `price_frac × base` vs hoarding —
  sweeps the sell-price fraction and the per-product hold cap. Example:
```
python -m diagnose --grid --exp floor --pa 1,2,8 --seed 700 --batch 8 \
  --grid-params 'price_frac=[0.0,0.4,0.7,1.0];hold_cap=[0,5,10,20]'
```
- `--exp e1`: the older E1 below-base premium/fertilizer sell gate (`min_sell_frac`
  × `shed_cap_frac` etc., target `premium_waste_units`).
- `--grid` runs the **`old` batch once** (combo-independent) and reuses it as the paired
  baseline for every combo; each combo injects `agent.py`'s module `E1_PARAMS` (the live
  param namespace the patch reads every call) and runs only `new`. Writes `grid/grid.csv`
  + a ranked accept/reject table. The game batches (old baseline + each combo) execute
  **in parallel across cores** (default all cores) via `run_parallel_tasks`; cap with `--workers N`.
- For each combo it computes **per-opponent** `_paired_verdict` (same seed) on the
  experiment's target column (`floor_sales` for `--exp floor`, `premium_waste_units` for
  `--exp e1`) and **guard** metrics. A combo is `ACCEPT` only if it moves the target in the
  experiment's `target_dir` **for every opponent** AND no guard regresses past tolerance:
  `discarded_units_total`/`shed_overflow_days`, `animal_escapes`, `stranded_at_bell`,
  `premium_below_base_frac`, and `sell_revenue_total` (≥ -10% vs that opponent's baseline).
  Anything else prints `REJECT: <which guard regressed>` — never pooled.
- The `floor` gate itself is hedged in `agent.py`: WOOL/MILK below `price_frac` of base are
  HELD (don't dump into the glut / don't floor), but holding is bounded so it can't hoard or
  overflow — only up to `hold_cap` units per product, only while the shared shed still has room
  (`shed_cap_frac` of the 100-cap), and never from `endgame_day` on (base liquidates). Only
  market `SELL` orders of WOOL/MILK are ever rewritten — never `PLANT`/`BUY`/`HIRE`/seeds —
  so the collective-PLANT and invalid-action traps can't fire from this patch.

### `games.csv` columns (one row per game)

| column | meaning | read it as |
|---|---|---|
| `final_money` / `opponent_final` / `result` | end bank balances; `WIN`/`LOSS`/`TIE` | W/L/T only — margins don't score |
| `idle_share_pct` | % of work-unit turns that were `PASS` (**the** labor-efficiency signal) | high ⇒ idle hands/wasted labour |
| `idle_units_total` | unit-PASS turns, any tile | how many work-slots did nothing |
| `idle_units_ready_total` | unit-PASS while standing on ready produce/animal | **missed-harvest idling** |
| `idle_steps` | whole-turn idle (all units PASS, no market) | ~always 0 — low-signal, ignore |
| `shed_pressure_days` / `shed_overflow_days` | days shed ≥95 / ==100 | near/at cap ⇒ overflow risk |
| `discarded_units_total` / `discarded_items` | shed-overflow units discarded; which item (`{}`/`{WHEAT:…}`) | what actually got thrown away (often all FERTILIZER) |
| `floor_sales` | units sold at the $1 floor | gluts dumped into the floor |
| `stranded_at_bell` | $ value of sellable shed + unit-inventory stock at FINAL prices (animals excluded) | endgame hygiene — unsold stock doesn't score, so a non-zero here is money that died in the shed; leader tolerates ~$442 |
| `locked_steps` / `locked_units_at_bell` | farmer/hand worker-turns standing on unbought `LOCKED` tiles; workers still on locked land at day 30 | hands routed across or parked on land you don't own (legal since 1.32.3) = wasted labour; both should be 0 or tiny |
| `premium_below_base_frac` | share of premium-good (strawberry/melon/milk/wool) units sold below base | bad timing on crash-prone goods |
| `animal_escapes` / `escaped_by_type` | animal losses (`COW:1`); `at_risk_of_escape` = ≥2 consec. unfed | near-miss precursor to chase |
| `plants_died` / `missed_harvest_eod` / `unwatered_eod` | decayed crops / unharvested at day-end / unwatered at EOD | lifecycle defects |
| `seed/animal/product/hire/land_cost_total` | itemized spend per game | the economics of the gap ledger |
| `sell_revenue_total` | committed revenue from sold produce | **the** revenue number (audit-backed) |
| `wheat_fed` / `feed_surplus` | wheat fed to animals; `produced - fed` | feed self-sufficiency (see caveats) |

### `days_seed<S>.csv` — the day-by-day columns to look at
`revenue`/`expenses` (sign-split — approximate), `seed_cost`/`animal_cost`/
`product_cost`/`hire_cost`/`land_cost` (exact), `shed_items_start_*/_end_*`, `max_shed_total`,
`weeds_max`, `hires`, `idle_units`/`unit_turns`/`idle_share_pct`,
`plants_watered`/`plants_fertilized`, `animals_fed`/`animals_cared`/`animals_escaped`, `shop_unlocks`,
`sell_qty_<p>`/`avg_price_<p>`/`revenue_<p>` (realized price & revenue per product per day),
`below_base_sales_<p>`, `discarded_items_<p>`, `feed_surplus`, `wheat_sold`/`wheat_fed`/`wheat_bought`.

### How to hunt structural issues (never average across games)
1. **Same-seed paired diff.** `python -m diagnose --compare --pa N --seed S --batch K`, then
   diff the SAME-seed rows of `old` vs `new` in `games.csv`. `--compare` now prints a
   **paired verdict** per opponent (and overall): `KEEP` iff the mean Δ is more than **2
   standard errors** from zero **AND** a majority of seeds agree in sign (the
   `wins-not-money` rule) — plus a win/tie/loss tally. Use `--batch 12` (≈ a minute) so
   the SE is estimable; with 1 seed per opponent it says so and refuses to decide. A patch
   must *reduce* a concrete defect without raising another — not just move that mean.
   `--compare` (and `--new`/`--old`) share the same `run_parallel_tasks` core as `--grid`, so
   the batch of games is split across cores by default; cap it with `--workers N`.
   `--workers` defaults to all cores and is accepted by every multi-game flag.
2. **Chase a non-zero signal.** Any of `idle_share_pct`, `idle_units_ready`,
   `shed_overflow_days`, `discarded_items`, `floor_sales`, `premium_below_base_frac`,
   `animal_escapes`, `at_risk_of_escape`, `plants_died`, `missed_harvest_eod`,
   `unwatered_eod`, `feed_surplus < 0` in a **specific game** is a defect worth fixing.
3. **Locate the day.** Open that seed's `days_seed<S>.csv`, find where the signal spikes,
   and correlate with `shop_unlocks`, `avg_price_<p>`, and `shed_items_*` (e.g. overflow on
   a strawberry glut, escapes after a weed-spawned pasture dig).
4. **Price timing.** `avg_price_<p>` vs the product base shows when you sold. A premium-good
   `avg_price` well under base (or `premium_below_base_frac` high) = sold into the glut instead
   of the scarcity spike.

### Caveats / which numbers to trust
- **Trust audit-backed fields** (`sell_revenue_total`, `floor_sales`, `below_base_sales`,
  `avg_price_<p>`, `discarded_*`, the cost totals) on any replay saved by our runs, which all
  run with the market audit. Non-audit fallbacks silently report `avg_price`=0.
- **Harvest attribution is unreliable**: `plants_harvested_<crop>` misses most harvests
  (nearly all land in `harvests_unknown`, including all wheat). So **feed/wheat numbers are
  estimated from audit flows** — `wheat_produced ≈ wheat_sold + wheat_fed − wheat_bought`
  (`feed_surplus = produced − fed`). Do not trust per-crop `plants_harvested`; prefer
  `sell_qty_<p>`/`avg_price_<p>`.
- **`idle_steps` is near-useless** (whole-turn idle almost never fires). Use `idle_share_pct`
  and `idle_units_total`/`idle_units_ready_total`.
- **`revenue`/`expenses`** (sign-split of money delta) undercount both when a step buys and
  sells — prefer `sell_revenue_total` + the itemized `*_cost_total` columns.

## What to change

| file | role | editable? |
|------|------|-----------|
| `src/main.py` | current production agent (editable layers) | **YES** |
| `src/route_tape.py` | opening route tape data | **NO** |
| `src/agent.py` | your patch over `main.py` ('new') | **YES** |
| `diagnose/` | diagnostic harness (package, `python -m diagnose`) | yes, when the harness itself needs a feature |
| `Makefile` | run any harness command (new/old/compare/grid/xray/graph/animals/sweep/package) | yes |
| `sweep.sh` | run `new`/`old` against all 13 public agents over many seeds | yes |
| `package.py` | build + verify (+ human-only push) the single-file submission | yes |
| `docs/ERRORS.md` | living list of concrete gameplay errors found in our replays (see it before writing any patch) | yes |
| `GAME_DYNAMICS.md` | authoritative mechanics & measured payoff data (referenced from `AGENTS.md`; read before designing experiments) | yes |
| `README.md`, `AGENTS.md` | docs | yes |
