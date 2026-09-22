# Agent Development Guide (handover)

## Golden rule

**Never edit `main.py` or `route_tape.py` while experimenting.**

- `main.py` — the production agent (~6,400 lines, 45 layers). Touching it risks
  breaking its proven behavior.
- `route_tape.py` — read-only opening route tape data.

**All experiments go in `agent.py`.**

## Submissions

**The agent has NO permission to submit/push to Kaggle.** `package_agent.py` is for
*local packaging only*: building the single-file bundle and (optionally) verifying it
with `--check`. Never run `--push` yourself. Submitting the actual entry is the human's
call, run by them from a terminal. Do not auto-run a mock game before/around packaging —
the operator does not want a bundle verification run; build the file and stop.

## How the patch system works

`agent.py` is a **patch layer over `main.py`**, not a standalone replacement:

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

## Reading rivals from replays (meta‑observations from `ntbk/`)

Actionable context distilled from the four community notebooks in `ntbk/`
(`x-ray-your-agent`, `a-dna-test-for-agents`, `everyone-is-playing-the-same-opening`,
`wins-not-money`). Use these when building the routing/decision tree or reading a
replay of our own agent.

- **Turn convention in a replay (off‑by‑one trap).** The action *decided at turn
  `t`* is stored at `steps[t + 1]` of the replay; `day = turn // 24`. Reading the
  raw index shifts the whole picture by one turn. **Nothing observable differs
  before turn 48** — early agreement between any two agents is engine
  determinism, not kinship.
- **The "day barcode" (DNA test).** The engine resynchronises every unit each
  morning, so the conserved, most-own window is **hours 1–4 of each day**. Hashing
  the plan channel over that window (farmer + hands + structural/provisioning
  orders, never sells or quantities) yields a 30‑band genome: matching bands =
  shared ancestry, first differing band = the in‑game day two agents forked.
  Adaptive layers show up as *where* the barcode stops being self‑consistent.
  Practical value: we can identify which public opponents play our exact lineage
  and whether a rival forks at the shop draw (turns 72/144) or reacts live.
- **Opening monoculture.** At turn 24 the field concentrates on a handful of
  shared openings (one line historically ~15% of all seats); agreement collapses
  after ~turn 100. Most of the field shares an *opening book*, not a strategy —
  so early‑game differences are where a router can differentiate.
- **Macro shape of a top agent (measured #1, 2026‑08‑30).** 2nd quadrant bought on
  **day 5**; ~**280 CARE** actions/season; herd ≈ **7 COW**; leaves ~**13 tiles
  fallow** late and **~$442 stranded** at the bell. A 4th‑quadrant line appears
  in ~12% of a top‑30 agent's games, always on **day 18**, always ~10 tomato tiles.
  Field staffing reference (490 seat‑seasons): **4 hands by day 4, 8 by day 6, 11
  by day 10, 12 from day 13 to the bell**, IQR 0–2 hands all season. Compare our
  own numbers against these as *shapes to understand*, not targets.
- **Market crate (don't sell into the hole you just dug).** A large sale reprices
  the shared book for *both* players. If we dump a product and then (or the rival
  then) sells the same product within ~a day into the depressed window, that volume
  eats the price drop — quantified damage = victim qty × Δprice. This is the
  concrete mechanism behind "bundle premium‑goods and time sales"; a glut you
  create stays cheap for a while (a $1 sale adds no supply).
- **Labour is movement.** Measured split: the #1 spends **53.8% of unit‑turns
  walking, 3.8% idle**; a mid‑table agent 42.9% walking / 11.8% idle. Wasted
  labour mostly *shows up as idle in place* rather than extra walking — so
  `idle_share_pct`/`idle_units_ready_total` are the real defect signals.

## Net‑new mechanics from `kaggriculture-visualized-what-every-crop-pays` (georgymamarin, 15 Sep 2026)

This is the strongest *measured* mechanics guide in `ntbk/`; each line below is a
number it verified against the engine or the ladder, not an assumption. Where it
shadows the reference above, prefer the measured number.

- **The engine version is load‑bearing.** The ladder runs **1.32.7** (our local env
  matches — check `kaggle_environments.__version__`). Three behaviours hinge on it:
  fertilizer **is** sellable, units **can** walk across unbought tiles (since
  1.32.3), and the **scarcity side of carrot/tomato/egg was bent into `hinge` on
  2026‑08‑15**. Any strategy writeup dated before 15 Aug priced carrot under a
  $43 ceiling (older rule); since the change the *median* carrot game peaks ~$57
  and one in ten clears $100. Reading the engine repo is worth more than tuning.
- **Selling into SCARCITY is the single biggest lever, not selling on a schedule.**
  A market running short pays multiples of base: ~1000 units short = **~15× base for
  carrot, ~54× for tomato**. Tomato's knee sits at 200 units short, carrot's at
  450. The *curve that can spike is worthless unless something empties the shelf
  and you refill in time* — shops + town center are what empty it (see odds below).
  Realise `avg_price_<p> << base` = we sold into a glut instead of the spike.
- **Melon has no shop buyer.** It is on **none** of the 8 shop menus; its only
  buyer all season is the town center (1/day = 30 units). Its price floors at
  $1 after **158 net units sold** — so melon is great when the field under‑grows
  it, and a trap when they don't (both players' melon dumps share the same shelf).
- **Shop demand odds (draw is with replacement, 8 shops, unlock every 3d).**
  Median season opens only **5 distinct** types. **Wool is on one menu only (Yarn
  Store)** → ~1/3 of seasons have *no* wool buyer. Fertilizer is bought by nobody
  (town center included). Typical season demand: **~270 carrot, ~180 tomato**,
  carrot's buyer (Pet Cafe) is single‑product so eats double. **By day 6 you have
  seen 2 of the 8 shops — a real sample of the season**; use the opening pair to
  choose what to plant rather than betting blind.
- **Watering efficiency is the cheapest win on a worker‑turn‑bound farm.**
  "Half of a careful bot's watering does nothing." On **ongoing** crops
  (tomato/strawberry) water adds **no fruit by itself** (the schedule fruits
  watered or not) — the only exception is fertilised days, which double that
  day's fruit *on a watered day*. Unfertilised ongoing crops need water only
  **every other day** (their survival cadence). On one‑shot crops, water inside
  the window adds yield, outside it is survival‑only (see watering window above).
  A daily‑water‑everything rule that our agent may follow is wasting worker‑turns.
- **Land is cheap; *worked* land is not.** Extra tiles with the same crew are
  *worth nothing* (measured). Hands pay only when **both** change together: give
  each worker **its own tiles** AND **more ground to work**. Either alone is
  ~worthless; hands wired to the shared job list even hurt (idle expensively).
  Hands are extra **actions**, not extra judgement. (Confirm our main.py grows
  crew and ground in lock‑step, not one before the other.)
- **`PLANT` is validated collectively & silently.** If the total `PLANT` requests
  for a crop this turn exceed the seeds held, **ALL** of them convert to `PASS` —
  including the farmer's. It counts *requests*, so a unit standing on an already‑
  occupied tile still consumes a request. A mass‑missed‑planting day is this bug.
- **Same‑seed A/B is not strictly clean.** The town lottery's RNG stream is shared
  with weed spawning (one roll per *bare* tile at night), so two versions that
  differ in ground coverage draw different shops. Matched seeds still cancel
  *most* noise, but a big planting‑coverage change can decouple the shop draw.
- **Cheat‑sheet gotchas.** The engine runs the **last callable** in your file, not
  the one named `agent` (a helper below your agent silently becomes it). Budget:
  **1 s/turn, 60 s total overage → timeout ends the episode**. `BUY_PRODUCT` is
  wheat/fertilizer only; $1‑floor sales add no market inventory; seeds are an
  uncapped separate slot; 10 market orders max per turn (extras dropped);
  invalid actions are silent no‑ops.

## Game Environment Reference

Authoritative summary distilled from the installed environment
(`kaggle_environments/envs/kaggriculture/kaggriculture.py` and its `README.md`);
tables and formulas cross-checked against the source. Use this when designing a
patch — every price, yield, cost and turn-ordering rule below directly decides
what our agent should do.

### Season, board, win condition
- Two players, **720 turns = 30 days × 24 turns/day** (default). Most money in the
  bank at the end wins; ties possible. **Unsold inventory does not count** toward
  the score.
- Board is **10×10 → four 5×5 quadrants**. Only **NW** is unlocked at the start.
  Buy the rest via `BUY_LAND` in this fixed order: **NE $1,000, SW $2,000, SE
  $4,000**. Start with **$3,000**.
- The **shed** sits at the board center and is *not* a tile. It is reachable from
  the four center tiles `(4,4),(5,4),(4,5),(5,5)` (one in each quadrant). Hold up
  to **100 non-seed items**; anything beyond the cap is discarded (no overflow).
  Seeds live in a separate uncapped slot and are consumed directly by `PLANT`.
- Both players' **farms are public** (money, tiles, positions). Opponent private
  state (shed, seeds, inventories) is hidden. The market and town are shared —
  our sells and buys move the price both players see, and town demand is a shared,
  reliable drain we can lean on.

### Crops
| Crop | Type | Seed | Base | 1st yield (day) | Max day | Interval | Max yield | Unfert. peak | Yield/tile/day |
|---|---|---|---|---|---|---|---|---|---|
| Wheat | one-time | $10 | $25 | 2 | 4 | – | 6 | 4 | 0.80 |
| Carrot | one-time | $20 | $35 | 2 | 3 | – | 4 | 3 | 0.75 |
| Tomato | ongoing | $50 | $60 | 8 | 11 | daily ×4 | 4 | – | 0.33 |
| Strawberry | ongoing | $100 | $120 | 10 | 16 | alt-day ×4 | 4 | – | 0.24 |
| Melon | one-time | $80 | $250 | 10 | 12 | – | 6 | – | 0.55 |

- **Watering bonus (one-time crops):** watering in the bonus window — starting at
  `(max_yield_day+1)//2` (wheat/carrot day 2, melon day 6) — adds **+1/day** to
  harvestable yield; **fertilized adds +2/day**. Wheat peaks at 4 watered / 6
  fertilized; carrot 3 / 4; melon reaches 6 by age 10 (age 8 fertilized).
- **Ongoing crops (tomato, strawberry):** scheduled production yields **1**, but
  **2 if fertilized AND watered that day**. Not indefinite: capped at 4 scheduled
  yields (tomato ages 8–11; strawberry ages 10, 12, 14, 16), then the plant
  decays into a weed.
- **Decay:** once a plant passes max lifespan (one-time = 1 day after max_yield_day;
  ongoing = 1 day after its 4th scheduled yield), `yield_units` drops **1 every
  other turn** until 0 → tile becomes a weed. Harvest before decay kills it.
- **Watering:** must be watered ~ every day. **Two consecutive missed end-of-day
  refreshes → weed.** The planting day already counts as day 1 unwatered, so a
  seed left unwatered the same day it's planted dies that night — always water on
  plant day.
- **Watering bonus window (one-time crops) — CRITICAL for watering efficiency.**
  Env source (`_do_action` WATER branch) adds yield only when the plant's *age*
  is inside `window_start <= age_days <= max_yield_day`, where
  `window_start = (max_yield_day + 1) // 2`; bonus is `+2` if fertilized else `+1`.
  For **WHEAT** (`max_yield_day=4`) the window is **ages 2–4**; for **CARROT**
  (`max_yield_day=3`) the window is **ages 2–3**. This means:
  - A one-time crop's **first-day water (age 0) buys survival only — 0 yield bonus**.
  - Watering on **age 1 adds 0 to the harvest** for both WHEAT and CARROT; the first
    bonus-paying water is on **age 2**.
  - So the *minimal survival* schedule (no yield loss) is: water age 0/1 enough to
    avoid consecutive-unwatered (`>=2`) death, then **water ages 2–4 (WHEAT) /
    2–3 (CARROT)** to bank the yield. Any extra water on age 1 that isn't needed to
    skip-death is wasted worker-turn (yields nothing) — it only ever delays a weed.
    Fertilizer ($100) multiplies the window bonus to +2/day, which is what lets wheat
    reach its 6-unit cap (4 is the unfertilized watered peak).

### Animals
| Animal | Structure | Cost | Product | Base | 1st yield (day) | Interval | Max held | Steady yield/day |
|---|---|---|---|---|---|---|---|---|
| Goose | Coop | $300 | Egg | $50 | 4 | daily | 4 | 1.00 |
| Cow | Pasture | $400 | Milk | $160 | 8 | every 2 days | 6 | 0.50 |
| Sheep | Pasture | $500 | Wool | $200 | 6 | every 3 days | 6 | 0.33 |

- Each occupies one tile: `BUILD_COOP` / `BUILD_PASTURE` (1 turn), then stand on a
  matching **empty** structure and `PLACE` the animal from inventory. `max_held` =
  cap on *unharvested* product on the tile, **not** lifetime output — fed animals
  produce indefinitely.
- **Must be fed 1 wheat/day.** Two consecutive unfed end-of-day refreshes →
  **animal escapes, unrecoverable** (structure remains). A newly placed animal
  starts `consecutive_unfed = 0`, so it survives its first day unfed.
- **CARE:** banks **+1** `pending_care_bonus` per fed-and-cared day (unfed days
  don't bank); the whole bank is paid into the next scheduled production *if fed*
  that day, then resets. If unfed on a production day, base 1 is still produced
  but the bank isn't applied and resets.
- **Fertilizer:** every surviving animal makes **1 fertilizer available at
  end-of-day** (fed or not). Uncollected fertilizer does **not** stack — an
  animal left alone still yields just 1. `COLLECT_FERTILIZER` grabs it. Fertilizer
  is worth $100 base and can be sold or used to double watering bonuses.

### Market & price action (the core strategy input)
- Shared market, each product starts at inventory **`I0 = 10,000`**. Selling adds
  supply; buying (`BUY_PRODUCT`, **only WHEAT and FERTILIZER can be bought back**)
  and town demand drain supply. Prices are recomputed from inventory each turn.
- **Price function:** `price(inv) = base + sign · amp · f(|inv − I0|)`, floor **$1**,
  rounded. `sign = +1` below I0 (scarcity → premium), `−1` above I0 (glut → cheap).
  `amp = target·base/f(T)`; each side has its own shape f ∈ {linear, sq, sqrt,
  log, hinge}. Moving T units past I0 shifts price by `target × base`.
- **Order execution:** market orders process **one unit at a time across both
  players simultaneously** (lockstep), max 10 orders/turn/player (extras dropped).
  `HIRE`/`BUY_LAND` are atomic and handled first. `SELL` is quoted at pre-sell
  inventory, `BUY_PRODUCT` at post-buy — a buy-then-sell round-trip nets zero.
  A sale **at $1 adds no supply** (keeps the floor responsive).

| Resource | Base | I0 | T | Below func / target | Above func / target | P(I0−T) | P(I0+T) | P(I0+2T) |
|---|---|---|---|---|---|---|---|---|
| Wheat | 25 | 10k | 400 | sqrt / 0.80 | log / 0.20 | $45 | $20 | $19 |
| Carrot | 35 | 10k | 450 | hinge / 1.00 | sqrt / 0.70 | $70 | $10 | $1 |
| Tomato | 60 | 10k | 200 | hinge / 0.40 | sqrt / 0.60 | $84 | $24 | $9 |
| Strawberry | 120 | 10k | 100 | sqrt / 0.70 | linear / 1.60 | $204 | $1 | $1 |
| Melon | 250 | 10k | 300 | log / 0.20 | sq / 3.60 | $300 | $1 | $1 |
| Egg | 50 | 10k | 332 | hinge / 0.40 | log / 0.20 | $70 | $40 | $39 |
| Milk | 160 | 10k | 122 | sqrt / 0.60 | linear / 1.60 | $256 | $1 | $1 |
| Wool | 200 | 10k | 105 | log / 0.20 | sq / 3.20 | $240 | $1 | $1 |
| Fertilizer | 100 | 10k | 200 | linear / 0.40 | linear / 0.40 | $140 | $60 | $20 |

- **Strategic reading:** premium goods (base > $100: strawberry, melon, milk, wool)
  use `above_target > 1` — a small glut craters them straight to the $1 floor, so
  **bundling and timing sales matters most for these** (batch-sell at the peak, and
  remember selling at $1 no longer adds supply, so a glut stays cheap). Staples
  (wheat) absorb oversupply gently. **Carrot, tomato, egg use `hinge` on the
  scarcity side**: calm near base, then spike steeply once town demand runs past T
  — watch `unlocked_shops` to know *which* scarce spikes are coming. Wheat
  panics on scarcity; melon/wool ignore scarcity but crash on oversupply.

### Town demand (drives prices down, shared by both)
- **Town center:** consumes 1 of every non-fertilizer product every **24 turns**
  (once/day), flat all season.
- **Shops:** unlock every **3 days**, drawn uniformly **with replacement** (so a
  season can have several bakeries and no yarn store), capped at **8 instances**.
  Each instance consumes its products every **4 turns**; single-product shops
  consume **2×**. Total demand grows monotonically as shops unlock → prices drift.
- | Shop | Demands |
  |---|---|
  | Bakery | egg, wheat |
  | Pizza Shop | milk, tomato, wheat |
  | Brunch Spot | egg, wheat, strawberry |
  | Yarn Store | wool (2×) |
  | Ice Cream Shop | strawberry, milk, wheat |
  | Pet Cafe | carrot (2×) |
  | Smoothie Shop | strawberry, milk |
  | Farmers Market | wheat, carrot, tomato, strawberry |

### Hiring & farm hands
- `HIRE` is a market order. Cost = `farmHandCostMult · fib(n)`, `n` = hires so far
  today; default mult 1 → **1, 1, 2, 3, 5, 8, 13…**, resets each day. Hands last
  **one day**, then are let go (re-hire daily). They spawn on a shed-adjacent free
  tile (NWSE preferréd). Each unit acts once per turn and has its own inventory.

### Turn-processing order (important for timing)
1. Validate actions.
2. Apply each player's farmer/hand tile actions simultaneously.
3. Process market (atomic `HIRE`/`BUY_LAND` first, then one-unit lockstep orders).
4. Town center + shop consumption.
5. Per-plant decay check.
6. On the last turn of a day: refresh plants/animals (fed/watered reset, unwatered/unfed counters, ongoing production, care bonus), spawn weeds, drop inventories into the shed, dismiss hands, reset hires.

### Config knobs (defaults; competition uses these)
`episodeSteps=720`, `boardSize=10`, `startingMoney=3000`,
`maxMarketOrdersPerTurn=10`, `turnsPerDay=24`, `shedCapacity=100`,
`weedSpawnChance=0.005`, `townShopUnlockInterval=3`,
`townShopSellInterval=4`, `townCenterSellInterval=24`.

### Where the lever is
Money = harvest-and-sell **at the right time** minus inputs (seeds, animals,
fertilizer, wheat, hires, land). The dynamic parts are the shared **market
(price timing / glut vs scarcity)** and **shop mix (which products get a
scarcity spike)**. The agent's edge is picking a profitable crop/animal mix the
shops actually demand, watering/feeding/care efficiently, and **selling into
scarcity before the glut** — i.e. a system-level timing/placement problem, not a
per-seed luck issue.

## Workflow

1. Write a patch in `agent.py` (a `patch(action, observation, configuration=None)`
   function; there is no standalone agent to implement).
2. Run the harness to test it. The full CLI reference, seating convention,
   outputs and reproducibility live in `diagnose.py`'s module docstring, and
   `python -m diagnose --help` prints the flags. The project overview lives in
   `README.md`. For a quick overall performance read, sweep against all 13
   public agents over several seeds:
   `./sweep.sh new` (or `./sweep.sh old`).
3. Inspect the JSON replays / CSVs for **concrete** per-game / per-day / per-step
   inefficiencies. **Never average anything across games** — see the anti-goal
   above. Judge on system-level defects you can point at, not on a mean.
4. When the patch is clearly better and stable, promote it into `main.py` as the
   new baseline, then clear `agent.py` for the next experiment.

## Using `diagnose.py` — columns & how to read the signals

The harness writes three things per run directory (`diag-replays/run-N/` by default,
or your `--run-dir`):

- **replay JSONs** — one per game, the full per-step observations+actions for both seats.
- **`days_seed<S>.csv`** — one file per seed, one row **per day** for the agent under
  test (seat 1 with the public agents). Per-day timeline, **not** aggregated.
- **`games.csv`** — one row **per game** for the agent under test (its seat), plus a
  compact per-game readout printed to the terminal.

Re-diagnose saved replays with `python diagnose.py --replay-dir <dir> --render`
(regenerates the CSVs; `--render` prints the day report, with a board-symbol legend up
front). `--graph` renders a 1×2 dashboard PNG per game **plus an animated farm-board
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
> route tape it runs on, the 45-layer patch stack built on top of it, and what
> each of those layers changed in the metrics below (idle, feed surplus, floor
> sales, shed overflow, escapes, plants died, …) — read
> [`PATCH_ITERATION_ANALYSIS.md`](PATCH_ITERATION_ANALYSIS.md). It is the
> data-based, per-layer iterative walkthrough (BASE → patch → new game state →
> … → final `_ASTRA_I1` patch) generated by `analyze_patches.py`, so the same
> columns you read in the tables/CSVs below are the ones that layer-by-layer
> numbers trace. Use it as the reference for what each metric is telling you
> and which layer introduced or fixed it.

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
1. **Same-seed paired diff.** `python diagnose.py --compare --pa N --seed S --batch K`, then
   diff the SAME-seed rows of `old` vs `new` in `games.csv`. `--compare` now prints a
   **paired verdict** per opponent (and overall): `KEEP` iff the mean Δ is more than **2
   standard errors** from zero **AND** a majority of seeds agree in sign (the
   `wins-not-money` rule) — plus a win/tie/loss tally. Use `--batch 12` (≈ a minute) so
   the SE is estimable; with 1 seed per opponent it says so and refuses to decide. A patch
   must *reduce* a concrete defect without raising another — not just move that mean.
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

## Public agent mapping

`diagnose.py` maps numbers to files in `public_agents/`. Indices are assigned by
alphabetical filename order at runtime (`diagnose._refresh_public_agent_map`), so
they are derived, not fixed:

| # | file |
|---|------|
| 1 | `kaggriculture-cloning-agent.py` |
| 2 | `kaggriculture-master-engine-v3.py` |
| 3 | `kaggriculture-one-more-wheat.py` |
| 4 | `kaggriculture-pipe16-idle-workers.py` |
| 5 | `kaggriculture-pipe7-wheat-microstructure.py` |
| 6 | `kaggriculture-public-state-router-74-5-win-rate.py` |
| 7 | `kaggriculture-reactive-router.py` |
| 8 | `kaggriculture-top-2-master-engine-v4.py` |
| 9 | `kaggriculture-v38-smarter-feed-stronger-margins.py` |
| 10 | `kaggriculture-v47-reactive-market-coordination.py` |
| 11 | `kaggriculture-v53-opening-signature.py` |
| 12 | `market-smart-farming-kaggriculture.py` |
| 13 | `shop-router-0909.py` |

Run `python -c "import diagnose; print(diagnose.public_agent_names())"` for the
live mapping.

## What to change

| file | role | editable? |
|------|------|-----------|
| `main.py` | current production agent | **NO** |
| `route_tape.py` | opening route tape data | **NO** |
| `agent.py` | your patch over `main.py` ('new') | **YES** |
| `diagnose.py` | diagnostic harness | yes, when the harness itself needs a feature |
| `fetch_lb_tapes.py` | pull full lb replays of our top-scoring submission | yes |
| `diagnose_lb.py` | per-game efficiency report, our & opponent seats | yes |
| `sweep.sh` | run `new`/`old` against all 13 public agents over many seeds | yes |
| `analyze_patches.py` | static survey + empirical BASE→layer→final prefix loop (feeds `PATCH_ITERATION_ANALYSIS.md`) | yes |
| `PATCH_ITERATION_ANALYSIS.md` | data-based reference for how the 45 layers change the metric columns | yes |
| `ERRORS.md` | living list of concrete gameplay errors found in our replays (see it before writing any patch) | yes |
| `README.md`, `AGENTS.md` | docs | yes |
