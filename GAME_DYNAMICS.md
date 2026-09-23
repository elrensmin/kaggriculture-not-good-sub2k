# Kaggriculture Game Dynamics

Authoritative engine mechanics and measured payoff data. This file is referenced
from `AGENTS.md` and is meant to be read (and included in context) whenever you
design an experiment, read a replay, or reason about prices, yields or timing.
Engine `kaggle_environments.__version__ == 1.32.7` (what the ladder runs).

---

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

