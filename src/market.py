"""Price curve + demand metadata, vendored from the engine (no main.py dependency).

The engine already exposes MARKET_PARAMS / market_price; we re-export them plus a
few derived helpers so the rest of the agent reasons about "what the price curve
does to this product" without touching the engine internals.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS, CROPS, MARKET_PARAMS, PRICE_FLOOR, PRODUCTS, SHOPS,
    market_price,
)

I0 = 10000

# The town center buys 1/day of every product except fertilizer (flat all season).
TOWN_CENTER_BUYS = [p for p in PRODUCTS if p != "FERTILIZER"]


def base(item: str) -> float:
    return MARKET_PARAMS[item]["base"]


def above_func(item: str) -> str:
    return MARKET_PARAMS[item]["above_func"]


def below_func(item: str) -> str:
    return MARKET_PARAMS[item]["below_func"]


def is_knife_edge(item: str) -> bool:
    """True if a small glut crashes the price to $1 (linear/sq above-curve)."""
    return above_func(item) in ("linear", "sq")


def sells_freely(item: str) -> bool:
    """True if the above-curve is gentle (log) so oversupply is absorbed cheaply."""
    return above_func(item) in ("log",)


def price(item: str, inventory: float, params=None) -> int:
    return market_price(item, inventory, params)


def price_after(item: str, inventory: float, extra: float, params=None) -> int:
    """Price of the `extra`-th unit sold into the current shelf (marginal)."""
    return market_price(item, inventory + extra, params)


def has_volume_buyer(shops, item: str) -> bool:
    """Whether some shop (beyond the 30-unit town center) buys `item`."""
    return any(item in SHOPS.get(s, ()) for s in shops)


def shop_count(shops, item: str) -> int:
    """Number of shop instances that demand `item` (single-product shops eat 2x)."""
    n = 0
    for s in shops:
        if item in SHOPS.get(s, ()):
            n += 2 if len(SHOPS[s]) == 1 else 1
    return n
