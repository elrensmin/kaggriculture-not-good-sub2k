"""src/trade.py — the wheat carry (market layer).

**What the reference actually does.** Boey's opening is not a bigger production
opening; it is a high-turnover, thin-margin *carry*. Measured on 60 of his replays
(`replays/Boey/v1`), d0-d5 medians:

    gross sell revenue   $11,624      <- 4x ours, and pure CHURN
    product buy cost     $ 9,286
    product trade NET    $ 2,438      <- the number that matters
    animal spend         $ 4,000      <- $800 more than ours
    net cash             $-2,974      (bank 3,000 -> 26)

Ours is gross $2,834 / net $1,753 / animals $3,200. So the whole Phase-1 gap is
**$685 of trade net**, and it is exactly the extra animal spend that buys his 9th-10th
animal. `tools/phases/dag.py` carries both nodes, and `trade_net` is the one to move.

**Where the edge is.** Not a large mispricing. The shared wheat inventory sits in a
~25-unit band around `I0` for the whole opening (p10 9,967 / median 9,981 / p90 9,991),
and the wheat curve (base $25, T=400, sqrt) prices that band at **$28-$30**. The carry
buys the top of the band and sells the bottom of it, many times, using the town's
continuous drain to restore inventory between cycles. It is a spread of ~$2/unit over
~25 units/step, not a jackpot.

**Why thresholds, not inventory levels.** Gating on `price` keeps this independent of
the exact curve shape and of which side of `I0` the market happens to sit on: buy under
`base + TRADE_BUY_MARGIN`, sell over `base + TRADE_SELL_MARGIN`, hold in between. The
tape's previous leg gated on `inventory > I0 + 50` and was therefore INERT -- measured,
the basket never trades that far into a glut during d0-d5.

**What it must not do.** Touch the herd's feed (reserve first), crowd out the animals
(the buy leg is emitted LAST, so it is the marginal user of cash), or sell into a glut
(the sell leg requires a premium). Sells are emitted EARLY because they are the inflow.
"""
from __future__ import annotations

from . import market, params


def _unfed(state):
    return sum(1 for row in state.tiles for t in row
               if isinstance(t, dict) and "animal" in t and not t.get("fed_today", False))


def _price(state):
    return float(market.price("WHEAT", state.inventory.get("WHEAT", params.I0)))


def sell_intents(state, keep_extra=None, floor_margin=None, keep_none=False):
    """Sell WHEAT surplus above the feed reserve -- normally only into a premium.

    `keep_extra` and `floor_margin` let the herd's owner LIQUIDATE the position instead:
    the carry exists to fund the herd, so when the day's animal target is unmet and
    unaffordable, the position is sold down to the unfed count at any price above base.
    That is worth a few dollars a unit -- a $500 SHEEP returns ~$1,600 of wool over the
    season. It works the same turn because the sell sits BEFORE the animal order in the
    market list and the engine funds orders positionally.
    """
    if not params.TRADE_ENABLED:
        return []
    px = _price(state)
    margin = params.TRADE_SELL_MARGIN if floor_margin is None else floor_margin
    if px < params.MARKET_PARAMS["WHEAT"]["base"] + margin:
        return []
    extra = params.TRADE_FEED_RESERVE if keep_extra is None else keep_extra
    keep = 0 if keep_none else _unfed(state) + int(extra)
    have = int(state.shed.get("WHEAT", 0))
    if have <= keep:
        return []
    return [["SELL", "WHEAT", min(have - keep, int(params.TRADE_CHUNK))]]


def buy_intents(state, reserve=0.0):
    """Buy WHEAT into a discount, with shed headroom and the OTHER claims on cash held back.

    `reserve` is what the rest of the opening still needs this turn (the day's un-bought
    herd plus its feed) and is passed in by the owner of that plan. Without it the carry
    spent the herd's cash: measured, `animals` fell 8 -> 7 and GOOSE 2 -> 0.5 while the
    trade net rose only $125. The carry is the RESIDUAL claimant -- it may only cycle
    money the opening does not otherwise need.
    """
    if not params.TRADE_ENABLED or state.day < int(params.TRADE_FROM_DAY):
        return []
    px = _price(state)
    ceiling = params.MARKET_PARAMS["WHEAT"]["base"] + params.TRADE_BUY_MARGIN
    if px > ceiling:
        return []
    headroom = int(params.SHED_CAP) - int(state.shed_total())
    cash = state.money - float(reserve) - float(params.TRADE_CASH_FLOOR)
    if headroom <= 0 or cash <= 0:
        return []
    qty = min(headroom, int(params.TRADE_CHUNK), int(cash // max(1.0, px)))
    return [["BUY_PRODUCT", "WHEAT", qty]] if qty > 0 else []
