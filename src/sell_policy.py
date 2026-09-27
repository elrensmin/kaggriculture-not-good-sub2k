"""Demand-aware sell policy — the DSM inventory-target rule (the market layer).

Sell INTO scarcity, hold IN a glut. The dividing line is the market inventory
relative to I0 and each product's curve shape (``market.is_knife_edge`` /
``market.sells_freely``), not a fixed price fraction:

  - WHEAT: hold for scarcity — sell only below I0 (63% of DSM's volume).
  - MILK/WOOL/STRAWBERRY (knife-edge): sell below I0+100; literally 0 units above it.
  - MELON: sell below I0 (its quadratic curve floors at 158 net units).
  - EGG (log): sell freely. FERTILIZER (nobody buys it): dump past a reserve.
  - CARROT/TOMATO (hinge scarcity): sell below I0.

Wheat is reserved first for feeding (``WHEAT_SELL_RESERVE`` + unfed animals).
"""
from __future__ import annotations

from . import market, params


def _unfed(state):
    return sum(
        1
        for row in state.tiles
        for t in row
        if isinstance(t, dict) and "animal" in t and not t.get("fed_today", False)
    )


def _sellable(item: str, inv: int) -> bool:
    if item == "WHEAT":
        return inv < params.I0
    if item in params.CEILING_GOODS:        # MILK / WOOL / STRAWBERRY
        return inv < params.I0 + params.CEILING + params.SELL_CEILING_BOOST
    if item == "MELON":
        return inv < params.I0 + params.MELON_CEILING  # quadratic floor at ~158 net
    if item == "EGG" or item == "FERTILIZER":
        return True                          # gentle curves — sell continuously
    return inv < params.I0                   # CARROT / TOMATO: hinge scarcity


def _liquidating(state) -> bool:
    return state.day >= params.LIQUIDATE_DAY


def market_intents(state):
    out = []

    liquidating = _liquidating(state)

    # wheat: feed reserve FIRST, then sell the surplus only into scarcity (or at
    # the end, when we liquidate everything).
    unfed = _unfed(state)
    wheat = int(state.shed.get("WHEAT", 0))
    sellable = max(0, wheat - unfed - params.WHEAT_SELL_RESERVE)
    if sellable > 0 and (liquidating or state.inventory.get("WHEAT", params.I0) < params.I0):
        out.append(["SELL", "WHEAT", min(sellable, params.TRICKLE)])

    for item in ("STRAWBERRY", "MELON", "CARROT", "TOMATO", "EGG", "MILK", "WOOL"):
        n = int(state.shed.get(item, 0))
        if n <= 0:
            continue
        if not liquidating and not _sellable(item, state.inventory.get(item, params.I0)):
            continue
        out.append(["SELL", item, min(n, params.TRICKLE)])

    # fertilizer: the town's own produce, but it IS a market product with a real
    # price curve (floor at I0+493). The #1's earliest cash engine is 3-5 units/day
    # from d1 -- funded by the herd. The season reserve (5) is exactly what 5 animals
    # make per day, so with a herd running it sold nothing; use the herd reserve then.
    fert = int(state.shed.get("FERTILIZER", 0))
    reserve = (params.FERT_RESERVE_WITH_HERD if state.herd_count() > 0
               else params.FERT_RESERVE)
    if fert > reserve:
        out.append(["SELL", "FERTILIZER", min(fert - reserve, params.TRICKLE)])

    return out
