"""Patch layer for the new agent candidate.

The new agent is NOT a standalone replacement for main.py. It is the full
production agent from main.py with this patch layered *on top*: the harness
(diagnose.py) runs the production agent (``main._original_agent``) and then
hands the produced action to ``patch()``, which may alter it.

So `python diagnose.py --new` runs **everything in main.py + this patch**, and
the ``--new`` side of ``python diagnose.py --compare`` does the same, so every
improvement/regression is measured relative to the exact production behavior.

Edit ``patch()`` for your experiment. Returning ``action`` unchanged is a no-op.

--------------------------------------------------------------------------------
NEVER TRUST AVERAGES ACROSS GAMES.
This environment is dynamic: random-seeded games across the whole public
leaderboard, with live, moving prices. Averaging a score is NOT signal --- it
regresses our score. Judge on concrete system-level defects you can point at
in a specific game / day / step, never on a mean.
--------------------------------------------------------------------------------

EXPERIMENT (WHEAT/CARROT WATERING): The env's WATER bonus applies only to
one-time crops (WHEAT/CARROT/MELON) when the plant *age* is inside the yield
window:
    window_start = (max_yield_day + 1)//2 ;  bonus window = [window_start .. max_yield_day]
  - WHEAT max_yield_day=4 -> window ages 2-4
  - CARROT max_yield_day=3 -> window ages 2-3
Watering a wheat/carrot at an OUT-OF-WINDOW age adds 0 to the harvest AND is
not needed for survival when consecutive_unwatered==0 (the plant-day/age-0 water
already reset it). The base agent wastes worker-turns watering these. This patch:
  - Leaves WHEAT/CARROT waters alone when they are in-window or survival-needed.
  - Suppresses a WHEAT/CARROT water at a wasteful age (age==1 with
    consecutive_unwatered==0, or age > max_yield_day) and repurposes the turn to
    HARVEST (if the tile holds harvestable yield) else PASS.
"""
from __future__ import annotations

import main as _main

# One-time crop yield windows (authoritative env formula window_start=(max_yield_day+1)//2).
_WINDOW = {
    "WHEAT": (2, 4),   # max_yield_day 4
    "CARROT": (2, 3),  # max_yield_day 3
    "MELON": (6, 12),  # max_yield_day 12 (not touched by this experiment)
}


def _is_wasteful_crop_water(tile, day):
    """Return True if WATER on this wheat/carrot tile adds 0 yield and is not
    needed to avoid an upcoming weed death."""
    crop = tile.get("crop")
    if crop not in _WINDOW:
        return False
    ws, we = _WINDOW[crop]
    planted = tile.get("planted_day")
    if planted is None:
        return False
    age = day - int(planted)
    # survival-needed if the plant would otherwise hit consecutive_unwatered==2
    # tonight -> i.e. it is already at risk. Plant-day (age 0) is always watered.
    cu = int(tile.get("consecutive_unwatered", 0) or 0)
    survival_needed = cu >= 1
    in_window = ws <= age <= we
    if in_window or survival_needed:
        return False
    # Pure waste: out-of-window and not needed for survival.
    return age >= 1


# Which crop fertilization we push onto idle/wasted worker-turns.
# FERTILIZE sets fertilized_until_day = day+2, so applying it as a wheat/carrot
# enters its yield window makes every window water pay +2 instead of +1.
_FERT_TARGETS = {"WHEAT": (2, 4), "CARROT": (2, 3)}


def _repurpose_worker(action, index, is_farmer, tile, fertilizer_held=False, day=0):
    """Rewrite the unit at `index`'s command.

    Priority for the freed turn:
      1. FERTILIZE  -- if standing on an in-window, not-yet-fertilized wheat/carrot
                       AND the unit is actually carrying fertilizer. Applying it now
                       (age entering/exiting window) is what lifts wheat 4->6.
      2. HARVEST    -- if the tile holds a ready, harvestable yield.
      3. PASS       -- otherwise.
    """
    new_cmd = ["PASS"]
    crop = tile.get("crop") if tile else None
    in_win_unfert = False
    if tile and crop in _FERT_TARGETS:
        ws, we = _FERT_TARGETS[crop]
        age = day - int(tile.get("planted_day", day))
        cur_fert_until = int(tile.get("fertilized_until_day", -1) or -1)
        in_win_unfert = (ws <= age <= we) and cur_fert_until < day

    if fertilizer_held and in_win_unfert:
        new_cmd = ["FERTILIZE"]
    elif bool(tile) and (tile.get("yield_units", 0) or 0) > 0:
        new_cmd = ["HARVEST"]
    else:
        new_cmd = ["PASS"]

    if is_farmer:
        action["farmer"] = new_cmd
    else:
        hands = action.get("hands")
        if isinstance(hands, list) and 0 <= index < len(hands):
            hands[index] = new_cmd


def _patch_watering(action, observation, configuration=None):
    if not isinstance(observation, dict):
        return action
    day = int(observation.get("day") or 0)
    player = observation.get("player")
    farms = observation.get("farms")
    if not isinstance(farms, list) or not isinstance(player, int) or not (0 <= player < len(farms)):
        return action
    fam = farms[player]
    if not isinstance(fam, dict):
        return action
    tiles = fam.get("tiles")
    if not isinstance(tiles, (list, tuple)):
        return action

    def tile_at(x, y):
        if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
            t = tiles[y][x]
            return t if isinstance(t, dict) else None
        return None

    # Unit inventories: farmer -> inventories[0], hand j -> inventories[j+1].
    inventories = observation.get("private", {}).get("inventories") if isinstance(observation.get("private"), dict) else None

    def holds_fert(idx):
        if not isinstance(inventories, (list, tuple)) or not (0 <= idx < len(inventories)):
            return False
        inv = inventories[idx]
        return isinstance(inv, dict) and int(inv.get("FERTILIZER", 0) or 0) > 0

    # Farmer + hands positions (public), command lists in the action.
    farmer_pos = fam.get("farmer")
    farmer_cmd = action.get("farmer")
    if isinstance(farmer_cmd, (list, tuple)) and farmer_cmd and farmer_cmd[0] == "WATER" and isinstance(farmer_pos, (list, tuple)) and len(farmer_pos) >= 2:
        t = tile_at(int(farmer_pos[0]), int(farmer_pos[1]))
        if t and _is_wasteful_crop_water(t, day):
            _repurpose_worker(action, 0, True, t, fertilizer_held=holds_fert(0), day=day)

    hand_pos = fam.get("hands")
    hand_cmds = action.get("hands")
    if isinstance(hand_pos, (list, tuple)) and isinstance(hand_cmds, (list, tuple)):
        for i in range(min(len(hand_pos), len(hand_cmds))):
            cmd = hand_cmds[i]
            pos = hand_pos[i]
            if not isinstance(cmd, (list, tuple)) or not cmd or cmd[0] != "WATER":
                continue
            if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                continue
            t = tile_at(int(pos[0]), int(pos[1]))
            if t and _is_wasteful_crop_water(t, day):
                _repurpose_worker(action, i, False, t, fertilizer_held=holds_fert(i + 1), day=day)
    return action


def _patch_fertilize(action, observation, configuration=None):
    """Push FERTILIZE onto idle/watering worker-turns standing on an in-window,
    not-yet-fertilized WHEAT/CARROT that the unit is carrying fertilizer for.

    Fertilizer lasts day+2, so applying it as the crop is inside its yield window
    makes each window water pay +2 (wheat reaches 6 instead of the 4-unit
    unfertilized peak). We only rewrite turns that already have nothing better to
    do (PASS) or are a wasteful out-of-window water, so we don't steal fertilizer
    from the base agent's own higher-ROI strawberry fertilization.
    """
    if not isinstance(observation, dict):
        return action
    day = int(observation.get("day") or 0)
    player = observation.get("player")
    farms = observation.get("farms")
    if not isinstance(farms, list) or not isinstance(player, int) or not (0 <= player < len(farms)):
        return action
    fam = farms[player]
    if not isinstance(fam, dict):
        return action
    tiles = fam.get("tiles")
    if not isinstance(tiles, (list, tuple)):
        return action
    private = observation.get("private")
    inventories = private.get("inventories") if isinstance(private, dict) else None

    def tile_at(x, y):
        if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
            t = tiles[y][x]
            return t if isinstance(t, dict) else None
        return None

    def holds_fert(idx):
        if not isinstance(inventories, (list, tuple)) or not (0 <= idx < len(inventories)):
            return False
        inv = inventories[idx]
        return isinstance(inv, dict) and int(inv.get("FERTILIZER", 0) or 0) > 0

    def fertilize_if_worth(idx, is_farmer, pos, command):
        if not isinstance(command, (list, tuple)) or not command:
            return
        op = command[0]
        # Only claim genuinely idle (PASS) turns. NEVER replace a WATER/harvest
        # — replacing an in-window water would leave the crop unwatered and cause
        # it to die / under-yield, which is worse than the fertilizer gain.
        if op != "PASS":
            return
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            return
        t = tile_at(int(pos[0]), int(pos[1]))
        if not t or t.get("crop") not in _FERT_TARGETS:
            return
        ws, we = _FERT_TARGETS[t["crop"]]
        planted = t.get("planted_day")
        if planted is None:
            return
        age = day - int(planted)
        if not (ws <= age <= we):
            return
        cur_fert_until = int(t.get("fertilized_until_day", -1) or -1)
        if cur_fert_until >= day:
            return
        # Index into inventories: farmer -> 0, hand j -> j+1.
        inv_idx = 0 if is_farmer else idx
        if not holds_fert(inv_idx):
            return
        if is_farmer:
            action["farmer"] = ["FERTILIZE"]
        else:
            hands = action.get("hands")
            if isinstance(hands, list) and 0 <= idx - 1 < len(hands):
                hands[idx - 1] = ["FERTILIZE"]

    farmer_pos = fam.get("farmer")
    farmer_cmd = action.get("farmer")
    if isinstance(farmer_cmd, (list, tuple)) and farmer_cmd and farmer_cmd[0] == "PASS" and isinstance(farmer_pos, (list, tuple)) and len(farmer_pos) >= 2:
        fertilize_if_worth(0, True, farmer_pos, farmer_cmd)

    hand_pos = fam.get("hands")
    hand_cmds = action.get("hands")
    if isinstance(hand_pos, (list, tuple)) and isinstance(hand_cmds, (list, tuple)):
        for i in range(min(len(hand_pos), len(hand_cmds))):
            cmd = hand_cmds[i]
            pos = hand_pos[i]
            # Hand j -> command list index i, inventories index i+1.
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "PASS":
                fertilize_if_worth(i + 1, False, pos, cmd)
    return action


def _patch_sell_scarcity(action, observation, configuration=None):
    """Sell our surplus WHEAT/CARROT into the shared market while it is ABOVE
    base (scarcity premium), instead of hoarding it in the shed and letting the
    opponent capture the same premium.

    Also suppresses BUY_PRODUCT WHEAT when we already hold enough wheat in the
    shed/units (we were observed buying produce we already own).

    Feed safety: we only sell WHEAT above a reserve covering today's animals,
    so we never starve livestock.
    """
    if not isinstance(observation, dict):
        return action
    base = {"WHEAT": 25, "CARROT": 35}
    day = int(observation.get("day") or 0)
    player = observation.get("player")
    farms = observation.get("farms")
    market = observation.get("market")
    private = observation.get("private")
    if not (isinstance(market, dict) and isinstance(private, dict) and isinstance(farms, list)):
        return action
    prices = market.get("prices") if isinstance(market, dict) else None
    if not isinstance(prices, dict):
        return action
    shed = private.get("shed") if isinstance(private, dict) else {}
    shed = shed if isinstance(shed, dict) else {}

    # Count animals for a feed reserve. Feeding needs ~1 wheat/day/animal; keep
    # a comfortable buffer so we never sell the feed.
    n_animals = 0
    if isinstance(player, int) and 0 <= player < len(farms):
        fam = farms[player]
        if isinstance(fam, dict):
            for row in (fam.get("tiles") or []):
                for t in row:
                    if isinstance(t, dict) and ("animal" in t or t.get("kind") in ("COOP", "PASTURE")) and t.get("animal"):
                        n_animals += 1
    wheat_reserve = n_animals + 6  # today's feed + buffer

    orders = action.get("market")
    if not isinstance(orders, list):
        orders = []
        action["market"] = orders

    wheat_held = int(shed.get("WHEAT", 0) or 0)
    carrot_held = int(shed.get("CARROT", 0) or 0)
    wheat_px = prices.get("WHEAT", 0)
    carrot_px = prices.get("CARROT", 0)

    additions = []
    # Sell surplus wheat into the premium if there is any and it is above base.
    if wheat_px > base["WHEAT"] and wheat_held > wheat_reserve:
        qty = wheat_held - wheat_reserve
        additions.append(["SELL", "WHEAT", qty])
    # Sell carrot above base (carrot has no feed use).
    if carrot_px > base["CARROT"] and carrot_held > 6:
        qty = carrot_held - 6
        additions.append(["SELL", "CARROT", qty])

    # NOTE: we do NOT suppress BUY_PRODUCT WHEAT here. Early experiments showed
    # the base agent uses market wheat to keep ~16 animals fed; suppressing
    # those buys starved animals and caused escapes (1 -> 3). Selling surplus
    # into scarcity alone is the safe lever.
    action["market"] = orders
    # Append our sell additions, honoring the 10-order cap.
    room = 10 - len(action["market"])
    for add in additions:
        if room <= 0:
            break
        action["market"].append(add)
        room -= 1
    # Ensure the market cap is not exceeded by the base orders we retained.
    action["market"] = action["market"][:10]
    return action


def patch(action, observation, configuration=None):
    """Post-process the action produced by the full main.py agent.

    This is the experiment hook. Write your idea here. You may inspect
    ``observation`` (the full per-step state: farms, private, market prices,
    shops, unlocked quadrants, step/day/hour) and the ``action`` main.py just
    produced, then return a possibly-modified action dict.

    Returning ``action`` unchanged is a no-op.
    """
    if isinstance(observation, dict):
        action = _patch_watering(action, observation, configuration)
        action = _patch_fertilize(action, observation, configuration)
        action = _patch_sell_scarcity(action, observation, configuration)
    return action


# Keep a plain `agent(observation, configuration)` entry point so main.py's own
# is_new_agent toggle (in case anyone flips it manually) resolves to the same
# behaviour: full main agent, then this patch. diagnose.py uses patch() directly.
def agent(observation, configuration=None):
    base = getattr(_main, "_original_agent", None)
    if base is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    return patch(base(observation, configuration), observation, configuration)
