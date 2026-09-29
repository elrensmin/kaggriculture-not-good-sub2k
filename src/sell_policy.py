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
    # PHASE-SCOPED. MEASURED (round 6-7): cutting the reserve to 5 for the whole season
    # sells 955 extra wheat units in d6-17 (+$37k over 16 games) and then has to buy the
    # feed back at the bell -- `product_cost_total` +$10,670 and a season median of
    # -$6,539. The midgame wants a thin reserve (wheat is the deepest, most liquid
    # line); the endgame wants the old one.
    _reserve = params.at("WHEAT_SELL_RESERVE", state.day)
    # FEED_STOCK_DAYS keeps a bought feed buffer in the shed. WITHOUT this line the sell
    # policy liquidates that buffer every day and the herd layer rebuys it -- a round trip
    # that loses the spread. MEASURED 2026-09-29 (`gates`/games.csv, 8 games): with
    # `FEED_STOCK_DAYS_P2=2` the bundle bought **+$45,029 of product** and fed only 24 more
    # wheat units, which is where the -$10,593 season cost came from. The stock IS the
    # reserve, so hold it.
    _stock = params.at("FEED_STOCK_DAYS", state.day)
    if _stock:
        _reserve = max(_reserve, state.herd_count() * _stock)
    sellable = max(0, wheat - unfed - _reserve)
    if sellable > 0 and (liquidating or state.inventory.get("WHEAT", params.I0) < params.I0):
        out.append(["SELL", "WHEAT", min(sellable, params.at("TRICKLE", state.day))])

    for item in ("STRAWBERRY", "MELON", "CARROT", "TOMATO", "EGG", "MILK", "WOOL"):
        n = int(state.shed.get(item, 0))
        if n <= 0:
            continue
        inv = state.inventory.get(item, params.I0)
        if not liquidating and not _sellable(item, inv):
            continue
        # SELL_FLOOR_BASE: never sell a knife-edge good below its base price. The inventory
        # gate alone admits the part of the curve that has already crashed below base (the
        # measured 0.9 premium-below-base leak). Hold instead; the town drain lifts the price.
        if (not liquidating and params.at("SELL_FLOOR_BASE", state.day)
                and market.is_knife_edge(item) and market.price(item, inv) < market.base(item)):
            continue
        # SELL_LOOKAHEAD: hold unless today's price beats the best price the town drain will
        # produce within the rest of the day. The floor alone over-holds (overflow); this is
        # the timed half -- sell at the peak, hold through the trough.
        if not liquidating and params.at("SELL_LOOKAHEAD", state.day):
            from . import demand
            sell_now = demand.best_sell_now(item, inv, n, state.shops,
                                            max(1, 24 - state.hour),
                                            floor=market.base(item))
            if sell_now <= 0:
                continue
        # ADAPTIVE RATE. `TRICKLE` is a per-turn cap, and MEASURED it is BELOW our own
        # late-game production: phase-3 MILK sells 104 units at $116.8 in the shipped arm
        # and 100 units at **$73.2** in the round-6 portfolio -- same volume, 37 % worse
        # price. The ceiling gate (`_sellable`) stops us selling once the market inventory
        # passes `I0 + CEILING`, so the surplus banks in the shed and dumps at
        # `LIQUIDATE_DAY`. Selling a FRACTION of the shed each turn keeps the pipe clear
        # instead of letting it back up behind the ceiling.
        rate = params.at("TRICKLE", state.day)
        frac = params.at("SELL_TRICKLE_FRACTION", state.day)
        if frac:
            rate = max(rate, int(n * frac + 0.999))
        out.append(["SELL", item, min(n, rate)])

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
