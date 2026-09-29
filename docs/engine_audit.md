# Engine-vs-agent structural audit (from `kaggriculture.py`)

Reverse-engineering the engine's exact rules and checking whether the agent complies.
"Fixed" = a knob flipped this session; "compliant" = the agent already derives the rule.

## Turn / action semantics

| engine rule | agent status |
|---|---|
| Unit actions (farmer then hands) resolve FIRST; `_process_market` runs AFTER | The market list's *internal* order (sells before buys) funds same-turn, which is correct; unit-produced goods are NOT sellable until next turn or a DROP | compliant |
| One action per unit per turn, 24 turns/day | `scheduler.plan` emits one op per unit per turn | compliant |
| Atomic PLANT validation: if total PLANT for a crop > seeds held, the WHOLE batch becomes PASS | `PLANT_CAP_BY_SEEDS` was OFF → we asked 51.5 WHEAT/game, sowed 46.9 (9 % wasted). **FIXED: `PLANT_CAP_BY_SEEDS=True`** | fixed |
| Market list capped at `MAX_ORDERS=10` (tail dropped silently) | `emit` truncates at 10; the market list is the funding order | compliant |

## Watering

| engine rule | agent status |
|---|---|
| WATER on an already-watered tile is a no-op (returns early) | `state.needs_water` returns False when `watered_today` — no wasted WATER | compliant |
| Non-ongoing crop: watering only adds yield inside `[window_start, max_yield_day]`; outside it is survival-only | `state.in_water_window` + `WATER_BONUS` vs `WATER_SURVIVAL` split already encodes this | compliant |
| `consecutive_unwatered >= 2` at day-end → WEED (a plant starts at 1, so d0 sow must be watered same day) | `state.plant_ready` is checked before `needs_water`; survival water exists | compliant |

## Harvest / feed / care

| engine rule | agent status |
|---|---|
| HARVEST on a tile with `yield_units <= 0` is a no-op | `state.plant_ready` requires `yield_units > 0` | compliant |
| CARE bonus pays only on a FED production day (`_daily_refresh_animals` pops `pending_care_bonus` only when `fed_today`) | documented in AGENTS.md; feeding every other day silently halves herd output | known |
| COLLECT_FERTILIZER requires `fertilizer_available` (1/animal/day) | `herd_plan` emits COLLECT per animal | compliant |

## Movement / shed

| engine rule | agent status |
|---|---|
| `_end_of_day` clears every unit's inventory into the shed for free (`_drop_inventories_to_shed`) | we DROP once per harvest (99 vs Boey's 32) — a mid-day shed trip is only needed to free hands for a deliverable | known tuning-exhausted |
| PICKUP has no empty-handed rule (only needs shed adjacency + stock) | `PICKUP_WITH_PRODUCE` knob (off) allows fetch while carrying produce | knob available |

## Market / drain

| engine rule | agent status |
|---|---|
| Shops drain 2 (single-product) or 1 unit every 4 steps; town centre drains 1/day (not fertilizer) | `demand.drain_at_step` / `drain_per_day` reproduce this exactly | compliant |
| Price is concave in inventory; each sold unit fetches `price(inv + i - 1)` | `demand.unit_price` / `revenue_for` already model it | compliant |
| Shop unlock is `Random((seed*1_000_003)^day)` after one draw per empty tile of BOTH farms | `demand.shop_unlock` reproduces it; but our empty-tile count moves the draw | known confound |

## Structural fixes applied this session

- `PLANT_CAP_BY_SEEDS=True` — stop the engine from voiding over-requested WHEAT batches (9 % waste → ~2 %).
- `LAND_FROM_PRIORS=True` — land schedule from `priors.LAND_BY_QUADRANT` (NE d6, SW d8, SE d9), retiring the hand-set `LAND_TARGET_DAY` duplicate owner.
- `SELL_FLOOR_BASE` / `SELL_LOOKAHEAD` knobs (off) — the sell-timing machinery (`demand.best_sell_now` + base floor) wired into `sell_policy` for A/B.
