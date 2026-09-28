"""demand — the money side of the farm, as exact functions.

The agent has never had a representation of revenue. This module is that: the price curve,
the town's consumption, the marginal dollar of the next unit sold, and the shop-unlock draw,
all as closed forms taken from the engine rather than fitted.

Engine facts this encodes (all read from `kaggriculture.py`, none assumed):

  PRICE     `market_price(item, inventory)` — 1:1 with `src/market.py::price`.
  DRAIN     `_town_consume`: every `townShopSellInterval` (4) steps, each unlocked shop
            instance removes `2` units of each of its products if the shop has exactly one
            product, else `1`; every `townCenterSellInterval` (24) steps the town centre
            removes `1` of every product except FERTILIZER.
  SELLING   `_process_market` commits one unit at a time and quotes each unit from the
            CURRENT shared inventory, so the i-th unit we sell fetches
            `price(inventory + i - 1)`. Income is therefore concave by construction, and the
            marginal unit is worth strictly less than the last one.
  UNLOCKS   `_end_of_day` seeds `random.Random((seed*1_000_003) ^ day)`, then
            `_spawn_weeds` draws once per EMPTY tile of player 0's farm and then player 1's
            (`None` only -- `and` short-circuits, so structures and plants do not draw), and
            the day's shop is the next `rng.choice(sorted(SHOPS))`. So the unlock is an exact
            function of `(seed, day, empty tiles on both farms)` -- enumerable, and therefore
            something the planner can steer rather than merely react to.

Nothing here mutates state and nothing here is tuned.
"""
from __future__ import annotations

import random

from . import market
from .params import I0  # noqa: F401  (re-exported for callers that reason about I0)

# Engine defaults (kaggriculture config), named so the model is auditable.
SHOP_SELL_INTERVAL = 4
TOWN_CENTER_INTERVAL = 24
SHOP_UNLOCK_INTERVAL = 3
MAX_SHOP_INSTANCES = 8
STEPS_PER_DAY = 24

# `_end_of_day` uses a per-day RNG seeded exactly like this.
_RNG_MULT = 1_000_003


def drain_per_step(item, shops):
    """Units the town removes from the shared shelf *on a shop tick* (every 4th step)."""
    return market.shop_count(shops, item)


def drain_at_step(step, item, shops):
    """Units the town removes on the transition INTO `step` — the exact per-step rule.

    MEASURED convention (`tools/phases/model_check.py`, 10 episodes, untraded steps only):
    the drain lands at step index `t` -- the index of the observation the transition
    DEPARTS from -- when `t % 4 == 0` (shop tick) and `t % 24 == 0` (town centre). With the
    market orders read from `steps[t+1]` (the verified action pairing) this reproduces the
    observed inventory change **exactly: 43,115/43,115 = 100.00 %**, against 72.06 % for the
    `t+1` drain index.
    """
    from kaggle_environments.envs.kaggriculture.kaggriculture import PRODUCTS
    n = 0
    if step % SHOP_SELL_INTERVAL == 0:
        n += market.shop_count(shops, item)
    if item in PRODUCTS and item != "FERTILIZER" and step % TOWN_CENTER_INTERVAL == 0:
        n += 1
    return n


def drain_per_day(item, shops):
    """Units the town removes per day: the shops plus the town centre.

    FERTILIZER is the one product the town centre does NOT buy.
    """
    from kaggle_environments.envs.kaggriculture.kaggriculture import PRODUCTS
    n = drain_per_step(item, shops) * (STEPS_PER_DAY // SHOP_SELL_INTERVAL)
    if item in PRODUCTS and item != "FERTILIZER":
        n += STEPS_PER_DAY // TOWN_CENTER_INTERVAL
    return n


def unit_price(item, inventory, k):
    """Price fetched by the k-th unit we sell (k >= 1) from `inventory`."""
    return market.price(item, inventory + (k - 1))


def marginal_revenue(item, inventory, k):
    """Dollars the k-th unit adds."""
    return unit_price(item, inventory, k)


def revenue_for(item, inventory, qty, floor=None):
    """Total dollars from selling `qty` units, honouring an optional price floor.

    Returns (dollars, units). `floor` stops the sale when the unit price drops below it,
    which is how a glut is refused instead of dumped.
    """
    total = 0
    sold = 0
    for k in range(1, int(qty) + 1):
        p = unit_price(item, inventory, k)
        if floor is not None and p < floor:
            break
        total += p
        sold += 1
    return total, sold


def break_even_qty(item, inventory, floor):
    """How many units can be sold from `inventory` before the price drops below `floor`."""
    k = 0
    while k < 10_000 and unit_price(item, inventory, k + 1) >= floor:
        k += 1
    return k


def inventory_after(item, inventory, sold, bought, shops, steps=1):
    """The shelf after `steps` steps of our trades plus the town's drain.

    The opponent's supply is a separate argument at the call site because it is observed,
    not controlled; this keeps the function honest about what it does and does not know.
    """
    drain = drain_per_step(item, shops) * steps
    return max(0, inventory + sold - bought - drain)


def price_forecast(item, inventory, shops, horizon_steps, our_sells=(), opp_sells=()):
    """Price per step from now, given planned sells and observed opponent supply.

    `our_sells` and `opp_sells` are per-step quantities (may be shorter than the horizon;
    the tail is treated as zero). This is the "dynamic demand" the planner reasons about:
    the town's drain RAISES the price, our own sales LOWER it, and the two race.
    """
    out = []
    inv = float(inventory)
    for t in range(horizon_steps):
        out.append(market.price(item, inv))
        inv += (our_sells[t] if t < len(our_sells) else 0)
        inv += (opp_sells[t] if t < len(opp_sells) else 0)
        inv -= drain_per_step(item, shops)
        inv = max(0.0, inv)
    return out


def shop_unlock(seed, day, empty_tiles_p0, empty_tiles_p1, current_shops=()):
    """The shop `_end_of_day` unlocks for day+1, or None.

    Exact reproduction: the per-day RNG consumes one draw per empty (`None`) tile on farm 0
    then farm 1, and the shop is the next `choice(sorted(SHOPS))`. Returns the shop name, or
    None when the day is not an unlock day or the instance cap is already reached.
    """
    from kaggle_environments.envs.kaggriculture.kaggriculture import SHOPS
    nxt = day + 1
    if nxt <= 0 or nxt % SHOP_UNLOCK_INTERVAL != 0:
        return None
    if len(current_shops) >= MAX_SHOP_INSTANCES:
        return None
    rng = random.Random((int(seed) * _RNG_MULT) ^ int(day))
    for _ in range(int(empty_tiles_p0) + int(empty_tiles_p1)):
        rng.random()
    return rng.choice(sorted(SHOPS))


def shop_unlock_plan(seed, day, empties_by_day, current_shops=()):
    """Enumerate the unlock for a series of days given `{day: (empty_p0, empty_p1)}`."""
    shops = list(current_shops)
    out = {}
    for d in sorted(empties_by_day):
        s = shop_unlock(seed, d, empties_by_day[d][0], empties_by_day[d][1], shops)
        if s:
            shops.append(s)
        out[d] = s
    return out, shops


def counts_empty(farm_tiles):
    """`None` tiles on one farm — the exact number of RNG draws `_spawn_weeds` makes."""
    return sum(1 for row in farm_tiles for t in row if t is None)


def best_sell_now(item, inventory, have, shops, steps_left, floor=1,
                  opp_rate=0.0):
    """Sell now or hold?  Marginal-revenue greedy with the town's drain priced in.

    The town will remove `drain_per_step` units every 4 steps, which raises the price; a
    unit held for `h` steps is worth at most `price(inventory - drain*h)`. We sell the unit
    now if today's price beats the best price we expect to see within the horizon, else we
    hold. `opp_rate` is the opponent's observed sell rate per step, which lowers the future
    price and is therefore subtracted from the expected gain.
    """
    now = market.price(item, inventory)
    held = []
    inv = float(inventory)
    for t in range(1, max(1, steps_left)):
        inv -= drain_per_step(item, shops)
        inv += opp_rate
        held.append(market.price(item, max(0.0, inv)))
    future = max(held) if held else 0
    if now >= future or now <= floor:
        return int(have)
    return 0
