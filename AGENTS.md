# Agent Development Guide (handover)

## Golden rule

**Never edit `main.py` or `route_tape.py` while experimenting.**

- `main.py` — the production agent (~6,400 lines, 45 layers). Touching it risks
  breaking its proven behavior.
- `route_tape.py` — read-only opening route tape data.

**All experiments go in `agent.py`.**

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
| `sweep.sh` | run `new`/`old` against all 13 public agents over many seeds | yes |
| `README.md`, `AGENTS.md` | docs | yes |
