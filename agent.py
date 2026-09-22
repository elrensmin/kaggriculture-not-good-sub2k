"""Patch layer for the new agent candidate.

The new agent is NOT a standalone replacement for main.py. It is the full
production agent from main.py with this patch layered *on top*: the harness
(diagnose.py) runs the production agent (``main._original_agent``) and then
hands the produced action to ``patch()``, which may alter it.

So `python diagnose.py --new` runs **everything in main.py + this patch**, and
the ``--new`` side of ``python diagnose.py --compare`` does the same, so every
improvement/regression is measured relative to the exact production behavior.

Experiment E1: stop selling **premium goods (STRAWBERRY/MELON/MILK/WOOL) and
FERTILIZER into a glut / at the $1 floor**. The shared market prices every
product; premium goods crash to the floor on a small glut, and fertilizer is a
means of production that should never be liquidated below its $100 base. So we
GATE each SELL: sell when the current price is at/above base (a not-yet-crashed
or scarcity shelf), HOLD when below base — but with hard invariants so holding
can't cause shed overflow (E4), tank revenue, strand stock, or emit invalid
actions.

The whole behaviour is driven by the module-level ``E1_PARAMS`` dict, which
``diagnose --grid`` overwrites per combination. Defaults reproduce the identity
baseline at the exact base threshold with a small hold, so ``--new`` unchanged
matches ---old`` until a grid combo is injected.

--------------------------------------------------------------------------------
NEVER TRUST AVERAGES ACROSS GAMES. Judge on concrete, per-opponent same-seed
evidence; never on a pooled mean.
--------------------------------------------------------------------------------
"""
from __future__ import annotations

import main as _main

# ---------------------------------------------------------------------------
# E1 params (read live by patch() every call; --grid overwrites these).
#   min_sell_frac : below this fraction of base, a gated product is held not sold.
#                   (1.0 = cut everything selling below base; 0.8 = let 20% under go)
#   shed_cap_frac : shed total occupancy (of the 100-cap) at/above which we force
#                   the base SELLs to drain (anti-overflow relief valve).
#   hold_cap      : how many units of one product we may hold while below base
#                   before we resume draining it (bounds over-holding).
#   use_fert      : if 1, a below-base FERTILIZER sale is redirected into applying
#                   fertilizer to an in-window crop when a carrying unit can do it.
#   shop_aware    : if 1, only hold-and-wait for a gated product that a shop bought
#                   in THIS season (unlocked_shops). Products nobody is buying
#                   (melon has no shop; wool unless Yarn Store is up) never recover,
#                   so holding them is pure shed-waste — leave their sells alone.
# ---------------------------------------------------------------------------
BASE_PRICE = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
              "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
_PREMIUM = {"STRAWBERRY", "MELON", "MILK", "WOOL"}
_GATED = _PREMIUM | {"FERTILIZER"}
# Which shops demand each gated product (town/unlocked_shops -> price recovery).
_PRODUCT_BUYER_KEYWORDS = {
    "STRAWBERRY": ["brunch", "ice cream", "smoothie", "farmers"],
    "MILK": ["pizza", "ice cream", "smoothie"],
    "WOOL": ["yarn"],
    # MELON and FERTILIZER have no shop buyer — the town center is their only drain.
}
_ENDGAME_DAY = 27      # from here on, let the base agent liquidate (avoid stranding)
_SHED_CAP = 100

E1_PARAMS = {"min_sell_frac": 1.0, "shed_cap_frac": 0.90, "hold_cap": 45, "use_fert": 0,
             "shop_aware": 0}


# ---------------------------------------------------------------------------
# Fertilizer application helper (only used when E1_PARAMS["use_fert"]).
# ---------------------------------------------------------------------------

def _fert_window(tile, day):
    """True if this one-shot crop is inside its watering window and not yet
    fertilized (so FERTILIZE now doubles every window water, +2/day)."""
    if not isinstance(tile, dict):
        return False
    c = tile.get("crop")
    if c == "WHEAT":
        ws, we = 2, 4
    elif c == "CARROT":
        ws, we = 2, 3
    elif c == "MELON":
        ws, we = 6, 12
    else:
        return False
    planted = tile.get("planted_day")
    if planted is None:
        return False
    age = day - int(planted)
    if not (ws <= age <= we):
        return False
    if int(tile.get("fertilized_until_day", -1) or -1) >= day:
        return False
    return True


def _inventories(observation):
    private = observation.get("private")
    if isinstance(private, dict):
        invs = private.get("inventories")
        if isinstance(invs, (list, tuple)):
            return invs
    return None


def _has_fert(invs, idx):
    if not invs or not (0 <= idx < len(invs)):
        return False
    inv = invs[idx]
    return isinstance(inv, dict) and int(inv.get("FERTILIZER", 0) or 0) > 0


def _apply_fert_on_idle(action, observation):
    """If a farmer/hand is idle on an in-window, unfertilized crop and carries
    fertilizer, rewrite that unit to FERTILIZE (turning a would-be discounted
    fertilizer sale into a yield boost). Only touches PASS commands, so we never
    break a real WATER/HARVEST. Returns True if any unit was redirected."""
    if not isinstance(observation, dict):
        return False
    day = int(observation.get("day") or 0)
    player = observation.get("player")
    farms = observation.get("farms")
    if not isinstance(farms, list) or not isinstance(player, int) or not (0 <= player < len(farms)):
        return False
    fam = farms[player]
    if not isinstance(fam, dict):
        return False
    tiles = fam.get("tiles")
    if not isinstance(tiles, (list, tuple)):
        return False
    invs = _inventories(observation)
    changed = False

    def tile_at(x, y):
        if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
            t = tiles[y][x]
            return t if isinstance(t, dict) else None
        return None

    def try_unit(idx, is_farmer):
        nonlocal changed
        pos = fam.get("farmer") if is_farmer else (fam.get("hands") or [])[idx] if idx < len(fam.get("hands") or []) else None
        cmd = action.get("farmer") if is_farmer else (action.get("hands") or [])[idx] if idx < len(action.get("hands") or []) else None
        if not isinstance(cmd, (list, tuple)) or not cmd or cmd[0] != "PASS":
            return
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            return
        inv_idx = 0 if is_farmer else idx + 1
        if not _has_fert(invs, inv_idx):
            return
        t = tile_at(int(pos[0]), int(pos[1]))
        if t and _fert_window(t, day):
            if is_farmer:
                action["farmer"] = ["FERTILIZE"]
            else:
                action["hands"][idx] = ["FERTILIZE"]
            changed = True

    try_unit(0, True)
    hands = fam.get("hands")
    if isinstance(hands, (list, tuple)) and isinstance(action.get("hands"), list):
        for idx in range(min(len(hands), len(action["hands"]))):
            try_unit(idx, False)
    return changed


# ---------------------------------------------------------------------------
# The sell gate
# ---------------------------------------------------------------------------

def _e1_patch(action, observation):
    p = E1_PARAMS
    if not isinstance(observation, dict):
        return action
    day = int(observation.get("day") or 0)
    # Endgame: let the base agent's own liquidation run so we never strand stock.
    if day >= _ENDGAME_DAY:
        return action
    market = observation.get("market")
    prices = market.get("prices") if isinstance(market, dict) else None
    if not isinstance(prices, dict):
        return action
    private = observation.get("private")
    shed = (private.get("shed") if isinstance(private, dict) else None) or {}

    total_occ = sum(int(v or 0) for v in shed.values() if isinstance(v, (int, float)))
    threshold = int(_SHED_CAP * float(p.get("shed_cap_frac", 0.90)))
    pressure = total_occ >= threshold          # shed is filling -> must drain, not hold
    min_frac = float(p.get("min_sell_frac", 1.0))
    hold_cap = int(p.get("hold_cap", 45))
    use_fert = int(p.get("use_fert", 0)) != 0
    shop_aware = int(p.get("shop_aware", 0)) != 0

    if use_fert:
        _apply_fert_on_idle(action, observation)

    # Which gated products are worth holding for a price recovery this season?
    # shop_aware: only those with a shop buyer actually unlocked. Otherwise all.
    holdable = set(_GATED)
    if shop_aware:
        town = observation.get("town")
        unlocked = [str(s).lower() for s in ((town.get("unlocked_shops") if isinstance(town, dict) else None) or [])]
        holdable = {prod for prod in _GATED
                    if any(any(kw in u for kw in _PRODUCT_BUYER_KEYWORDS.get(prod, [])) for u in unlocked)}

    orders = action.get("market")
    if not isinstance(orders, list):
        return action

    def is_gated_sell(o):
        return (isinstance(o, (list, tuple)) and len(o) >= 3 and o[0] == "SELL" and o[1] in _GATED)

    # Per-product selling target for gated goods that are worth holding.
    #  - price at/above base -> sell the lot into the premium/shelf.
    #  - price below base    -> HOLD (don't dump into the glut)... but two hard
    #                           invariants override holding:
    #       (a) shed pressure -> drain the whole holding (discard at cap = 100%
    #                           loss, worse than any floor sale);
    #       (b) a single gated product must not hog more than `hold_cap` of the
    #                           shared 100-cap shed -> dump the excess above it.
    target = {}
    for prod in _GATED:
        if prod not in holdable:
            continue  # nobody's buying it this season -> leave the base agent's sells alone
        held = int(shed.get(prod, 0) or 0)
        if held <= 0:
            continue
        px = prices.get(prod)
        base = BASE_PRICE.get(prod)
        if not isinstance(px, (int, float)) or not isinstance(base, (int, float)):
            continue  # unknown price/not sellable -> leave base's orders untouched
        if px >= base * min_frac:
            target[prod] = held
        elif pressure:
            target[prod] = held
        else:
            target[prod] = max(0, held - hold_cap)
    # Rebuild: keep every non-gated order and every gated sell we aren't gating
    # (non-holdable, or a product we hold nothing/unknown-price for); replace only
    # the gated sells we computed a target for.
    new_orders = []
    for o in orders:
        if is_gated_sell(o) and o[1] in target:
            continue  # re-added below from the target
        new_orders.append(o)
    for prod, qty in target.items():
        if qty > 0:
            new_orders.append(["SELL", prod, int(qty)])
    # Hedge: keep the 10-order cap, keeping non-gated orders and the biggest gates.
    action["market"] = new_orders[:10]
    return action


def patch(action, observation, configuration=None):
    """Post-process the action produced by the full main.py agent.

    This is the experiment hook. Currently the E1 sell gate (see module doc).
    Returning ``action`` unchanged is a no-op.
    """
    return _e1_patch(action if isinstance(action, dict) else {}, observation)


# Keep a plain `agent(observation, configuration)` entry point so main.py's own
# is_new_agent toggle (in case anyone flips it manually) resolves to the same
# behaviour: full main agent, then this patch. diagnose.py uses patch() directly.
def agent(observation, configuration=None):
    base = getattr(_main, "_original_agent", None)
    if base is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    return patch(base(observation, configuration), observation, configuration)
