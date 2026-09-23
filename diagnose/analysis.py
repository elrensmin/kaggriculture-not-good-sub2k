"""diagnose.analysis — replay → frames/days → per-game summaries.

Houses the frame builder, per-day builder, per-game/per-seed summaries (the
heavy analysis the CSVs and the grid/compare verdicts are computed from), and
the small tile/inventory helpers they share. Split from the monolith diagnose.py.
"""
from __future__ import annotations

import json
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from diagnose.config import (
    ANIMALS,
    CROPS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
    SHED_CAPACITY,
    TEST_SEAT,
    TURNS_PER_DAY,
    _GATED_WASTE,
    _SHED_ACCESS,
)
from diagnose.games import load_replay

def _dist_to_shed(x, y):
    return min(abs(x - a) + abs(y - b) for (a, b) in _SHED_ACCESS)



def _near_shed_stats(tiles: List[Any]) -> Tuple[int, int]:
    """(planted, bare) count on the NW+NE top-half near-shed ring (a tile is
    included iff it is in the top two quadrants, within Manhattan dist<=2 of the
    shed, owned (unlocked, non-LOCKED), and NOT a shed-access tile). The shed-
    access tiles are the hand-spawn hub, so they are excluded from the 'should be
    planted' target. This is the abandoned land we are growing from the shed
    outward: production currently leaves the NW/NE inner ring bare all season."""
    planted = 0
    bare = 0
    for y, row in enumerate(tiles):
        if y >= 5:  # NW + NE top half only
            continue
        for x, t in enumerate(row):
            if (x, y) in _SHED_ACCESS or _dist_to_shed(x, y) > 2:
                continue
            if t == "LOCKED":
                continue
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                planted += 1
            elif t is None:
                bare += 1
    return planted, bare


# The public opponents in public_agents/ are single-seat "cloning" agents: they
# only act when seated at seat 0. So the harness seats the public opponent at
# seat 0 and the agent under test (main.py / agent.py) at seat 1. days.csv
# tracks TEST_SEAT (the agent under test).

def _tile_copy(t):
    if t is None or t == "LOCKED":
        return t
    if isinstance(t, dict):
        return dict(t)
    return t



def _tile_brief(t):
    if t is None:
        return None
    if t == "LOCKED":
        return "LOCKED"
    k = t.get("kind")
    if k == "PLANT":
        return {
            "kind": "PLANT",
            "crop": t.get("crop"),
            "planted_day": t.get("planted_day"),
            "yield_units": t.get("yield_units"),
            "watered_today": t.get("watered_today"),
            "consecutive_unwatered": t.get("consecutive_unwatered"),
            "fertilized_until_day": t.get("fertilized_until_day"),
            "max_lifespan_step": t.get("max_lifespan_step"),
        }
    if k in ("COOP", "PASTURE"):
        return {
            "kind": k,
            "animal": t.get("animal"),
            "yield_units": t.get("yield_units"),
            "fed_today": t.get("fed_today"),
            "consecutive_unfed": t.get("consecutive_unfed"),
            "cared_today": t.get("cared_today"),
            "fertilizer_available": t.get("fertilizer_available"),
            "pending_care_bonus": t.get("pending_care_bonus"),
            "placed_day": t.get("placed_day"),
        }
    if k == "WEED":
        return {"kind": "WEED"}
    return {"kind": k}



def _copy_tiles(tiles):
    return [[_tile_copy(t) for t in row] for row in tiles]



def _unit_actions(action: Dict[str, Any]) -> List[Tuple[int, List[str]]]:
    """Return list of (unit_index, action_list). Unit 0 = farmer."""
    out = [(0, list(action.get("farmer") or ["PASS"]))]
    for i, h in enumerate(action.get("hands") or [], 1):
        out.append((i, list(h or ["PASS"])))
    return out



def _op_name(a: List[str]) -> str:
    if not a:
        return "PASS"
    return a[0]



def _op_arg(a: List[str], idx: int, default=None):
    if a and len(a) > idx:
        return a[idx]
    return default



def _tile_ready(tile, day: int) -> bool:
    """A tile has produce/animal output waiting to be harvested."""
    if not isinstance(tile, dict):
        return False
    if tile.get("kind") == "PLANT":
        cd = CROPS.get(tile.get("crop"))
        if not cd:
            return False
        if tile.get("yield_units", 0) <= 0:
            return False
        if cd["ongoing"]:
            return True
        age = day - tile.get("planted_day", 0)
        return age >= cd["max_yield_day"]
    if "animal" in tile:
        return tile.get("yield_units", 0) > 0
    return False



def _shed_total(private):
    return sum((private.get("shed") or {}).values())



def _crop_at_actor(me, unit_idx: int, tiles) -> Optional[str]:
    """Crop on the tile the given actor currently occupies, if any.

    Harvesting picks the crop on the tile the unit is standing on, so the actor's
    position -> tile -> crop gives us crop-level harvest attribution.
    """
    if unit_idx == 0:
        pos = me.get("farmer")
    else:
        hands = me.get("hands") or []
        i = unit_idx - 1
        if not (0 <= i < len(hands)):
            return None
        pos = hands[i]
    if not pos:
        return None
    x, y = int(pos[0]), int(pos[1])
    if not (0 <= y < len(tiles) and 0 <= x < len(tiles[y])):
        return None
    t = tiles[y][x]
    if isinstance(t, dict) and t.get("kind") == "PLANT":
        return t.get("crop")
    return None



def build_frames(record: List[Tuple[Dict, Dict]], seat: int = 0) -> List[Dict[str, Any]]:
    """Convert raw (obs, action) pairs into rich per-step frames."""
    frames = []
    prev_obs: Optional[Dict] = None
    for obs, act in record:
        step = obs.get("step", 0)
        day = step // TURNS_PER_DAY
        hour = step % TURNS_PER_DAY
        me = obs["farms"][seat]
        private = obs.get("private") or {}
        market = obs.get("market") or {}
        town = obs.get("town") or {}

        tiles = _copy_tiles(me.get("tiles", []))
        prev_tiles = _copy_tiles(prev_obs["farms"][seat]["tiles"]) if prev_obs else None

        # Per-tile crop/animal/weed inventory
        crops = []
        animals = []
        weeds = 0
        structures = {"COOP": 0, "PASTURE": 0}
        for y, row in enumerate(tiles):
            for x, t in enumerate(row):
                if t is None or t == "LOCKED":
                    continue
                b = _tile_brief(t)
                if b["kind"] == "PLANT":
                    crops.append({"pos": (x, y), **b})
                elif b["kind"] in ("COOP", "PASTURE"):
                    structures[b["kind"]] += 1
                    if b.get("animal"):
                        animals.append({"pos": (x, y), **b})
                elif b["kind"] == "WEED":
                    weeds += 1

        # Transition detection vs previous step
        transitions = defaultdict(list)
        money_delta = 0.0
        if prev_obs is not None:
            prev_me = prev_obs["farms"][seat]
            prev_priv = prev_obs.get("private") or {}
            money_delta = me.get("money", 0.0) - prev_me.get("money", 0.0)

            # Tile diffs
            for y, row in enumerate(tiles):
                for x, t in enumerate(row):
                    pt = prev_tiles[y][x] if prev_tiles else None
                    if t == pt:
                        continue
                    transitions["tile_change"].append({"pos": (x, y), "from": _tile_brief(pt), "to": _tile_brief(t)})

            # Shed / seed / inventory diffs
            for item in PRODUCTS:
                d = (private.get("shed") or {}).get(item, 0) - (prev_priv.get("shed") or {}).get(item, 0)
                if d != 0:
                    transitions["shed_delta"].append({"item": item, "delta": d})
            for crop in CROPS:
                d = (private.get("seeds") or {}).get(crop, 0) - (prev_priv.get("seeds") or {}).get(crop, 0)
                if d != 0:
                    transitions["seed_delta"].append({"crop": crop, "delta": d})

            # Worker / land / shop diffs
            dh = len(me.get("hands", [])) - len(prev_me.get("hands", []))
            if dh > 0:
                transitions["hired"].append({"delta": dh})
            dl = len(me.get("unlocked_quadrants", [])) - len(prev_me.get("unlocked_quadrants", []))
            if dl > 0:
                transitions["bought_land"].append({"delta": dl})
            ds = len(town.get("unlocked_shops", [])) - len((prev_obs.get("town") or {}).get("unlocked_shops", []))
            if ds > 0:
                transitions["shop_unlock"].append({"shops": list(town.get("unlocked_shops", []))[-ds:]})

        # Action-based transitions
        for unit_idx, ua in _unit_actions(act):
            op = _op_name(ua)
            if op == "PASS":
                transitions["pass"].append({"unit": unit_idx})
            elif op in ("NORTH", "SOUTH", "EAST", "WEST"):
                transitions["move"].append({"unit": unit_idx, "dir": op})
            elif op == "PLANT":
                transitions["plant"].append({"unit": unit_idx, "crop": _op_arg(ua, 1)})
            elif op == "WATER":
                transitions["water"].append({"unit": unit_idx})
            elif op == "HARVEST":
                transitions["harvest"].append({"unit": unit_idx, "crop": _crop_at_actor(me, unit_idx, tiles)})
            elif op == "FERTILIZE":
                transitions["fertilize"].append({"unit": unit_idx})
            elif op == "DIG":
                transitions["dig"].append({"unit": unit_idx})
            elif op in ("BUILD_COOP", "BUILD_PASTURE"):
                transitions["build"].append({"unit": unit_idx, "kind": op})
            elif op == "PLACE":
                transitions["place"].append({"unit": unit_idx, "item": _op_arg(ua, 1)})
            elif op == "FEED":
                transitions["feed"].append({"unit": unit_idx})
            elif op == "CARE":
                transitions["care"].append({"unit": unit_idx})
            elif op == "COLLECT_FERTILIZER":
                transitions["collect_fertilizer"].append({"unit": unit_idx})
            elif op == "DROP":
                transitions["drop"].append({"unit": unit_idx})
            elif op == "PICKUP":
                transitions["pickup"].append({"unit": unit_idx, "item": _op_arg(ua, 1), "qty": int(_op_arg(ua, 2, 1))})
            else:
                transitions["other"].append({"unit": unit_idx, "op": op, "args": ua[1:]})

        for o in act.get("market") or []:
            if not o:
                continue
            transitions["market_order"].append({"order": list(o)})

        # Derived signals
        shed = dict(private.get("shed") or {})
        seeds = dict(private.get("seeds") or {})
        shed_total = sum(shed.values())
        prices = dict(market.get("prices") or {})
        inventory = dict(market.get("inventory") or {})
        hands = [list(h) for h in me.get("hands", [])]
        farmer_pos = tuple(me.get("farmer", [0, 0]))
        hand_positions = [tuple(h) for h in hands]

        frames.append({
            "step": step,
            "day": day,
            "hour": hour,
            "seat": seat,
            "money": me.get("money"),
            "money_delta": money_delta,
            "farmer": list(act.get("farmer") or ["PASS"]),
            "hands": [list(h) for h in act.get("hands") or []],
            "market_orders": [list(o) for o in act.get("market") or []],
            "shed": shed,
            "shed_total": shed_total,
            "seeds": seeds,
            "inventories": [dict(i or {}) for i in private.get("inventories") or []],
            "prices": prices,
            "market_inventory": inventory,
            "crops": crops,
            "animals": animals,
            "weeds": weeds,
            "structures": structures,
            "n_hands": len(hands),
            "farmer_pos": farmer_pos,
            "hand_positions": hand_positions,
            "tiles": tiles,
            "unlocked_quadrants": list(me.get("unlocked_quadrants", [])),
            "unlocked_shops": list(town.get("unlocked_shops", [])),
            "transitions": dict(transitions),
        })
        prev_obs = obs
    return frames


# ---------------------------------------------------------------------------
# Day rollup
# ---------------------------------------------------------------------------



def build_days(frames: List[Dict[str, Any]], audit: Optional[Dict[int, Dict[int, Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    days: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
        "day": 0,
        "start_money": 0.0,
        "end_money": 0.0,
        "money_delta": 0.0,
        "revenue": 0.0,
        "expenses": 0.0,
        "start_shed_total": 0,
        "end_shed_total": 0,
        "max_shed_total": 0,
        "shed_items_start": {},
        "shed_items_end": {},
        "shed_deltas": defaultdict(int),
        "seed_deltas": defaultdict(int),
        "seed_cost": 0.0,
        "animal_cost": 0.0,
        "product_cost": 0.0,
        "hire_cost": 0.0,
        "land_cost": 0.0,
        "plants_planted": defaultdict(int),
        "plants_watered": 0,
        "plants_harvested": defaultdict(int),
        "harvests_unknown": 0,
        "plants_fertilized": 0,
        "plants_died": 0,
        "animals_placed": defaultdict(int),
        "animals_fed": 0,
        "animals_cared": 0,
        "fertilizer_collected": 0,
        "animals_escaped": 0,
        "animals_escaped_by": defaultdict(int),
        "weeds_start": 0,
        "weeds_end": 0,
        "weeds_max": 0,
        "idle_turns": 0,
        "idle_units": 0,
        "idle_units_ready": 0,
        "unit_turns": 0,
        "floor_sales": defaultdict(int),
        "below_base_sales": defaultdict(int),
        "sell_qty": defaultdict(int),
        "revenue_per_item": defaultdict(float),
        "avg_price_per_item": {},
        "sell_qty_source": "requested",
        "discarded_units": 0,
        "discarded_items": defaultdict(int),
        "buy_qty": defaultdict(int),
        "hires": 0,
        "land_unlocks": 0,
        "shop_unlocks": [],
        "hands_start": 0,
        "hands_end": 0,
        "n_pass": 0,
        "n_move": 0,
        "market_orders": [],
        "near_shed_planted": 0,
        "near_shed_bare": 0,
        "first_step": None,
        "last_step": 0,
    })

    if not frames:
        return []

    for f in frames:
        d = f["day"]
        day = days[d]
        day["day"] = d
        if day["first_step"] is None:
            day["first_step"] = f["step"]
        day["last_step"] = f["step"]
        if day["start_money"] == 0.0 and f["step"] % TURNS_PER_DAY == 0:
            day["start_money"] = f["money"]
        day["end_money"] = f["money"]
        day["end_shed_total"] = f["shed_total"]
        day["max_shed_total"] = max(day["max_shed_total"], f["shed_total"])
        day["weeds_end"] = f["weeds"]
        day["weeds_max"] = max(day["weeds_max"], f["weeds"])
        day["hands_end"] = f["n_hands"]
        if f["step"] % TURNS_PER_DAY == 0:
            day["hands_start"] = f["n_hands"]
            day["start_shed_total"] = f["shed_total"]
            day["weeds_start"] = f["weeds"]
            day["shed_items_start"] = dict(f["shed"])
        day["shed_items_end"] = dict(f["shed"])
        if f["hour"] == TURNS_PER_DAY - 1:
            day["near_shed_planted"], day["near_shed_bare"] = _near_shed_stats(f["tiles"])

        # Transitions aggregation
        tr = f.get("transitions", {})
        for p in tr.get("plant", []):
            day["plants_planted"][p["crop"]] += 1
        day["plants_watered"] += len(tr.get("water", []))
        day["plants_fertilized"] += len(tr.get("fertilize", []))
        for h in tr.get("harvest", []):
            # Crop-level attribution when the harvested tile is known.
            crop = h.get("crop")
            if crop:
                day["plants_harvested"][crop] += 1
            else:
                day["harvests_unknown"] += 1
        day["animals_fed"] += len(tr.get("feed", []))
        day["animals_cared"] += len(tr.get("care", []))
        day["fertilizer_collected"] += len(tr.get("collect_fertilizer", []))
        day["n_pass"] += len(tr.get("pass", []))
        day["n_move"] += len(tr.get("move", []))
        for p in tr.get("place", []):
            item = p["item"]
            if item in ANIMALS:
                day["animals_placed"][item] += 1
        for h in tr.get("hired", []):
            day["hires"] += h["delta"]
        for l in tr.get("bought_land", []):
            day["land_unlocks"] += l["delta"]
        for s in tr.get("shop_unlock", []):
            day["shop_unlocks"].extend(s["shops"])
        day["market_orders"].extend(tr.get("market_order", []))

        # Every live work-unit is one turn of (potential) labour; PASS = idle.
        day["unit_turns"] += f["n_hands"] + 1
        # Idle = every unit passes and no market orders (a whole idle turn; rare)
        all_pass = all(_op_name(ua) == "PASS" for _, ua in _unit_actions({"farmer": f["farmer"], "hands": f["hands"]}))
        if all_pass and not f["market_orders"]:
            day["idle_turns"] += 1

        # Unit-level idle: PASS on any tile (idle_units), plus PASS while standing
        # on ready produce / animal (idle_units_ready). idle_share = idle/unit-turns
        # is the real labour-efficiency signal; idle_turns understates it badly.
        for pos, cmd in zip([f["farmer_pos"], *f["hand_positions"]], [f["farmer"], *f["hands"]]):
            if _op_name(cmd) == "PASS":
                day["idle_units"] += 1
                if _tile_ready(f["tiles"][pos[1]][pos[0]], f["day"]):
                    day["idle_units_ready"] += 1

        # Shed/seed deltas from state diff
        for sd in tr.get("shed_delta", []):
            day["shed_deltas"][sd["item"]] += sd["delta"]
        for sd in tr.get("seed_delta", []):
            day["seed_deltas"][sd["crop"]] += sd["delta"]

        # Money attribution: crude but useful
        if f["money_delta"] > 0:
            day["revenue"] += f["money_delta"]
        else:
            day["expenses"] += -f["money_delta"]

        # Market order classification: use committed audit data when available
        seat = f["seat"]
        use_audit = audit is not None
        step_audit = audit.get(f["step"], {}).get(seat, {}) if use_audit else {}
        if use_audit:
            day["sell_qty_source"] = "committed"
            for item, rec in (step_audit.get("sells") or {}).items():
                day["sell_qty"][item] += rec["qty"]
                day["floor_sales"][item] += rec["floor"]
                day["below_base_sales"][item] += rec["below"]
                day["revenue_per_item"][item] += rec["revenue"]
            day["discarded_units"] += step_audit.get("discards", 0)
            for it, n in (step_audit.get("discard_items") or {}).items():
                day["discarded_items"][it] += n
        else:
            day["sell_qty_source"] = day.get("sell_qty_source") or "requested"
            for o in f["market_orders"]:
                op = o[0] if o else None
                item = o[1] if len(o) > 1 else None
                qty = int(o[2]) if len(o) > 2 else 1
                if op == "SELL" and item in PRODUCTS:
                    day["sell_qty"][item] += qty
                    price = f["prices"].get(item, MARKET_PARAMS[item]["base"])
                    if price <= PRICE_FLOOR:
                        day["floor_sales"][item] += qty
                    if price < MARKET_PARAMS[item]["base"]:
                        day["below_base_sales"][item] += qty

        # BUY orders and atomic orders (raw qty is still informative)
        for o in f["market_orders"]:
            op = o[0] if o else None
            item = o[1] if len(o) > 1 else None
            qty = int(o[2]) if len(o) > 2 else 1
            if op == "BUY_SEED" and item in CROPS:
                day["buy_qty"][item] += qty
                day["seed_cost"] += qty * CROPS[item]["seed"]
            elif op == "BUY_ANIMAL" and item in ANIMALS:
                day["buy_qty"][item] += qty
                day["animal_cost"] += qty * ANIMALS[item]["cost"]
            elif op == "BUY_PRODUCT" and item in PRODUCTS:
                day["buy_qty"][item] += qty
                price = f["prices"].get(item, MARKET_PARAMS[item]["base"])
                day["product_cost"] += qty * price
            elif op == "HIRE":
                # Hires are counted once, from the actual hand-count increase
                # (the "hired" transition above). The HIRE order is only a
                # request; it can fail, so it is not an authoritative count.
                pass
            elif op == "BUY_LAND":
                # Land prices: 1000, 2000, 4000 for the three extra quadrants
                n = len(f["unlocked_quadrants"])
                price = [0, 1000, 2000, 4000][min(n, 3)]
                day["land_cost"] += price
                day["land_unlocks"] += 1

        # Detect animal escapes from tile changes
        for tc in tr.get("tile_change", []):
            fr = tc["from"]
            to = tc["to"]
            if fr and isinstance(fr, dict) and fr.get("animal") and (to is None or to == "LOCKED" or (isinstance(to, dict) and not to.get("animal") and to.get("kind") in ("COOP", "PASTURE"))):
                day["animals_escaped"] += 1
                day["animals_escaped_by"][fr.get("animal")] += 1
            if fr and isinstance(fr, dict) and fr.get("kind") == "WEED" and to is None:
                pass  # weed removed
            if fr and isinstance(fr, dict) and fr.get("kind") == "PLANT" and isinstance(to, dict) and to.get("kind") == "WEED":
                day["plants_died"] += 1

    # Convert defaultdicts to plain dicts and compute hire/land cost more accurately
    result = []
    for d in sorted(days.keys()):
        day = days[d]
        # Hire cost: Fibonacci sequence for cumulative hires within the day.
        if day["hires"] > 0:
            # Sum fib(0..hires-1) where fib = 1,1,2,3,5,...
            a, b = 1, 1
            cost = 0
            for _ in range(day["hires"]):
                cost += a
                a, b = b, a + b
            day["hire_cost"] = cost
        day["money_delta"] = day["end_money"] - day["start_money"]
        day["plants_planted"] = dict(day["plants_planted"])
        day["plants_harvested"] = dict(day["plants_harvested"])
        day["animals_placed"] = dict(day["animals_placed"])
        day["shed_deltas"] = dict(day["shed_deltas"])
        day["seed_deltas"] = dict(day["seed_deltas"])
        day["sell_qty"] = dict(day["sell_qty"])
        day["buy_qty"] = dict(day["buy_qty"])
        day["floor_sales"] = dict(day["floor_sales"])
        day["below_base_sales"] = dict(day["below_base_sales"])
        day["discarded_items"] = dict(day["discarded_items"])
        day["animals_escaped_by"] = dict(day["animals_escaped_by"])
        # Real labour efficiency: idle share (idle_turns is a rare whole-turn idle).
        day["idle_share_pct"] = round(100.0 * day["idle_units"] / day["unit_turns"], 1) if day["unit_turns"] else 0.0
        # Feed self-sufficiency. Harvest attribution is unreliable (see
        # _crop_at_actor -> harvests_unknown), so wheat produced is ESTIMATED from
        # the reliable audit flows: produced = sold + fed - bought.
        day["wheat_sold"] = day["sell_qty"].get("WHEAT", 0)
        day["wheat_bought"] = day["buy_qty"].get("WHEAT", 0)
        day["wheat_fed"] = day["animals_fed"]
        # Daily wheat net (sold+fed-bought); can be negative on buy-heavy days.
        # The authoritative produced total is computed in summarize() from the
        # game totals, because harvest attribution is unreliable.
        day["feed_surplus"] = day["wheat_sold"] + day["wheat_fed"] - day["wheat_bought"]
        # Premium-good below-base realisation fraction (glut-crash detection).
        _prem = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
        _prem_sold = sum(day["sell_qty"].get(p, 0) for p in _prem)
        _prem_below = sum(day["below_base_sales"].get(p, 0) for p in _prem)
        day["premium_below_base_frac"] = round(_prem_below / _prem_sold, 3) if _prem_sold else 0.0
        day["revenue_per_item"] = dict(day["revenue_per_item"])
        # Average realised price per item (only where something was sold)
        day["avg_price_per_item"] = {
            p: round(day["revenue_per_item"].get(p, 0.0) / day["sell_qty"].get(p, 1), 2)
            if day["sell_qty"].get(p, 0) else 0.0
            for p in PRODUCTS
        }
        # Zero-fill every known item so the CSV schema is stable across runs.
        shed_items = sorted(set(PRODUCTS) | set(ANIMALS))   # animals live in the shed too
        for it in shed_items:
            day["shed_items_start"].setdefault(it, 0)
            day["shed_items_end"].setdefault(it, 0)
            day["shed_deltas"].setdefault(it, 0)
        buy_items = sorted(set(PRODUCTS) | set(CROPS) | set(ANIMALS))
        for it in buy_items:
            day["buy_qty"].setdefault(it, 0)
        for p in PRODUCTS:
            day["sell_qty"].setdefault(p, 0)
            day["floor_sales"].setdefault(p, 0)
            day["below_base_sales"].setdefault(p, 0)
            day["revenue_per_item"].setdefault(p, 0.0)
            day["avg_price_per_item"].setdefault(p, 0.0)
        # Flatten per-item revenue/price for stable CSV schema
        for p in PRODUCTS:
            day[f"revenue_{p}"] = day["revenue_per_item"].get(p, 0.0)
            day[f"avg_price_{p}"] = day["avg_price_per_item"].get(p, 0.0)
        del day["revenue_per_item"]
        del day["avg_price_per_item"]
        for c in CROPS:
            day["seed_deltas"].setdefault(c, 0)
            day["plants_planted"].setdefault(c, 0)
            day["plants_harvested"].setdefault(c, 0)
        for a in ANIMALS:
            day["animals_placed"].setdefault(a, 0)
        day["shop_unlocks"] = list(day["shop_unlocks"])
        result.append(day)
    return result


# ---------------------------------------------------------------------------
# Inefficiency / summary engine
# ---------------------------------------------------------------------------



def summarize(days: List[Dict[str, Any]], frames: Optional[List[Dict[str, Any]]] = None) -> OrderedDict:
    if not days:
        return OrderedDict()

    total_steps = sum(1 for _ in frames) if frames else days[-1]["last_step"] + 1
    idle_steps = sum(d["idle_turns"] for d in days)
    shed_pressure_days = sum(1 for d in days if d["max_shed_total"] >= SHED_CAPACITY - 5)
    shed_overflow_days = sum(1 for d in days if d["max_shed_total"] >= SHED_CAPACITY)
    floor_sales = defaultdict(int)
    below_base = defaultdict(int)
    sell_qty = defaultdict(int)
    for d in days:
        for item, n in d["floor_sales"].items():
            floor_sales[item] += n
        for item, n in d["below_base_sales"].items():
            below_base[item] += n
        for item, n in d["sell_qty"].items():
            sell_qty[item] += n

    animal_escapes = sum(d["animals_escaped"] for d in days)
    plants_died = sum(d["plants_died"] for d in days)
    weeds_max = max((d["weeds_max"] for d in days), default=0)

    # Per-frame animal/crop trouble, but only flag at end-of-day or near escape.
    unfed_eod = 0
    unwatered_eod = 0
    missed_harvest_eod = 0
    at_risk_escape = 0
    if frames:
        for f in frames:
            if f["hour"] == TURNS_PER_DAY - 1:
                for a in f["animals"]:
                    if a.get("consecutive_unfed", 0) >= 1:
                        unfed_eod += 1
                for c in f["crops"]:
                    if not c.get("watered_today"):
                        unwatered_eod += 1
                    cd = CROPS.get(c["crop"])
                    if cd and not cd["ongoing"]:
                        age = f["day"] - c.get("planted_day", 0)
                        if age >= cd["max_yield_day"] and c.get("yield_units", 0) > 0:
                            missed_harvest_eod += 1
            # Near-escape (>=2 consecutive unfed) counted once regardless of hour.
            for a in f["animals"]:
                if a.get("consecutive_unfed", 0) >= 2:
                    at_risk_escape += 1

    # Endgame hygiene: dollars stranded at the bell (destbreso's x-ray "stranded
    # $" macro indicator). Unsold inventory does NOT count toward the score, so
    # shed + unit inventories still holding sellable product at FINAL prices is
    # money that died in the shed. Animals are structures, not sellable stock, so
    # they are excluded (they also live in the shed slot).
    stranded = 0
    locked_steps = 0
    locked_units_at_bell = 0
    if frames:
        lp = frames[-1].get("prices", {})
        _shed = frames[-1].get("shed", {}) or {}
        for k, v in _shed.items():
            if k not in ANIMALS:
                stranded += v * lp.get(k, 0)
        for inv in (frames[-1].get("inventories", []) or []):
            for k, v in (inv or {}).items():
                if k not in ANIMALS:
                    stranded += v * lp.get(k, 0)
        # Locked-tile check: any farmer/hand step that stands on unbought (LOCKED)
        # land wastes a worker-turn (since 1.32.3 units can walk across unbought
        # tiles, a bot that routes through them leaves hands standing on locked tiles).
        for f in frames:
            tiles = f.get("tiles") or []
            for (x, y) in [f.get("farmer_pos")] + list(f.get("hand_positions") or []):
                try:
                    if tiles[y][x] == "LOCKED":
                        locked_steps += 1
                except (IndexError, TypeError):
                    pass
        lt = frames[-1].get("tiles") or []
        for (x, y) in [frames[-1].get("farmer_pos")] + list(frames[-1].get("hand_positions") or []):
            try:
                if lt[y][x] == "LOCKED":
                    locked_units_at_bell += 1
            except (IndexError, TypeError):
                pass

    out = OrderedDict()
    out["days"] = len(days)
    out["final_money"] = round(days[-1]["end_money"], 1)
    out["stranded_at_bell"] = round(stranded)
    out["locked_steps"] = locked_steps          # farmer/hand worker-turns standing on unbought land
    out["locked_units_at_bell"] = locked_units_at_bell  # workers still on unbought land at the bell
    out["near_shed_planted_max"] = max((d["near_shed_planted"] for d in days), default=0)
    out["near_shed_bare_final"] = days[-1]["near_shed_bare"]
    out["avg_daily_delta"] = round(sum(d["money_delta"] for d in days) / len(days), 1)
    idle_units_total = sum(d.get("idle_units", 0) for d in days)
    unit_turns_total = sum(d.get("unit_turns", 0) for d in days)
    idle_share = (100.0 * idle_units_total / unit_turns_total) if unit_turns_total else 0.0
    out["idle_steps"] = idle_steps           # whole-turn idle (rare; low-signal)
    out["idle_share_pct"] = round(idle_share, 1)
    out["idle_pct"] = f"{idle_share:.1f}%"   # unit-level idle share (the real signal)
    out["idle_by_day"] = {d["day"]: d["idle_units"] for d in days if d.get("idle_units")}
    out["idle_units_total"] = idle_units_total
    out["idle_units_ready_total"] = sum(d.get("idle_units_ready", 0) for d in days)
    out["unit_turns_total"] = unit_turns_total
    out["shed_pressure_days"] = shed_pressure_days
    out["shed_overflow_days"] = shed_overflow_days
    out["discarded_units_total"] = sum(d.get("discarded_units", 0) for d in days)
    _di = defaultdict(int)
    for d in days:
        for it, n in d.get("discarded_items", {}).items():
            _di[it] += n
    out["discarded_items"] = dict(sorted(_di.items()))
    out["max_shed_total"] = max((d["max_shed_total"] for d in days), default=0)
    out["floor_sales"] = dict(sorted(floor_sales.items()))
    out["below_base_sales"] = dict(sorted(below_base.items()))
    out["premium_waste_units"] = sum(below_base.get(p, 0) for p in _GATED_WASTE)
    out["sell_qty"] = dict(sorted(sell_qty.items()))
    out["animal_escapes"] = animal_escapes
    _eb = defaultdict(int)
    for d in days:
        for a, n in d.get("animals_escaped_by", {}).items():
            _eb[a] += n
    out["animals_escaped_by"] = dict(sorted(_eb.items()))
    out["plants_died_to_weeds"] = plants_died
    out["harvests_total"] = sum(sum(d["plants_harvested"].values()) for d in days) + sum(d["harvests_unknown"] for d in days)
    out["weeds_peak"] = weeds_max
    out["unfed_animal_signals"] = unfed_eod        # >=1 unfed at end-of-day
    out["unfed_at_eod"] = unfed_eod
    out["at_risk_of_escape"] = at_risk_escape       # >=2 consecutive unfed (no double count)
    out["unwatered_crop_eod"] = unwatered_eod
    out["missed_harvest_eod"] = missed_harvest_eod
    out["hires_total"] = sum(d["hires"] for d in days)
    out["land_unlocks_total"] = sum(d["land_unlocks"] for d in days)
    # Feed self-sufficiency (wheat cycle is the #1 lever). wheat_produced is an
    # estimate from reliable audit flows (sold+fed-bought); harvest attribution is
    # unreliable (see _crop_at_actor -> harvests_unknown).
    out["wheat_sold_total"] = sum(d.get("wheat_sold", 0) for d in days)
    out["wheat_fed_total"] = sum(d.get("wheat_fed", 0) for d in days)
    out["wheat_bought_total"] = sum(d.get("wheat_bought", 0) for d in days)
    wheat_produced = max(0, out["wheat_sold_total"] + out["wheat_fed_total"] - out["wheat_bought_total"])
    out["wheat_produced_total"] = wheat_produced
    out["feed_surplus_total"] = wheat_produced - out["wheat_fed_total"]
    out["wheat_market_dependence"] = out["wheat_bought_total"]
    # Economics: revenue from committed sells, expenses from itemized costs.
    # (The sign-split of money_delta mislabels both when a step both buys & sells.)
    sell_revenue = sum(sum(d.get(f"revenue_{p}", 0) for p in PRODUCTS) for d in days)
    item_costs = sum(
        d.get("seed_cost", 0) + d.get("animal_cost", 0) + d.get("product_cost", 0)
        + d.get("hire_cost", 0) + d.get("land_cost", 0)
        for d in days)
    out["sell_revenue_total"] = round(sell_revenue, 1)
    out["itemized_costs_total"] = round(item_costs, 1)
    out["seed_cost_total"] = round(sum(d.get("seed_cost", 0) for d in days), 1)
    out["animal_cost_total"] = round(sum(d.get("animal_cost", 0) for d in days), 1)
    out["product_cost_total"] = round(sum(d.get("product_cost", 0) for d in days), 1)
    out["hire_cost_total"] = round(sum(d.get("hire_cost", 0) for d in days), 1)
    out["land_cost_total"] = round(sum(d.get("land_cost", 0) for d in days), 1)
    out["revenue_total"] = round(sell_revenue, 1) if sell_revenue > 0 else round(sum(d["revenue"] for d in days), 1)
    out["expenses_total"] = round(item_costs, 1) if item_costs > 0 else round(sum(d["expenses"] for d in days), 1)
    # Premium-good below-base realisation fraction (glut-crash on strawberry/melon/milk/wool).
    _prem = [p for p in PRODUCTS if MARKET_PARAMS[p].get("above_target", 0.0) > 1.0]
    _prem_sold = sum(sum(d.get("sell_qty", {}).get(p, 0) for p in _prem) for d in days)
    _prem_below = sum(sum(d.get("below_base_sales", {}).get(p, 0) for p in _prem) for d in days)
    out["premium_below_base_frac"] = round(_prem_below / _prem_sold, 3) if _prem_sold else 0.0
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------



def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key + "_"))
        elif isinstance(v, list):
            out[key] = json.dumps(v)
        else:
            out[key] = v
    return out



def _day_columns() -> List[str]:
    """Canonical, stable day column set — identical columns on every run so
    runs (old vs new, and across seeds) can be diffed directly."""
    cols = [
        "agent", "opponent", "seed",
        "day", "first_step", "last_step",
        "start_money", "end_money", "money_delta",
        "revenue", "expenses", "seed_cost", "animal_cost", "product_cost",
        "start_shed_total", "end_shed_total", "max_shed_total",
        "weeds_start", "weeds_end", "weeds_max",
        "hands_start", "hands_end", "hires", "hire_cost",
        "land_unlocks", "land_cost",
        "idle_turns", "n_pass", "n_move", "idle_units", "unit_turns", "idle_share_pct",
        "plants_watered", "plants_fertilized", "plants_died", "harvests_unknown",
        "near_shed_planted", "near_shed_bare",
        "animals_fed", "animals_cared", "animals_escaped", "fertilizer_collected",
        "shop_unlocks", "market_orders",
        "sell_qty_source", "discarded_units", "idle_units_ready",
        "wheat_sold", "wheat_fed", "wheat_bought", "feed_surplus",
        "premium_below_base_frac",
    ]
    for p in PRODUCTS:
        cols += [f"sell_qty_{p}", f"floor_sales_{p}", f"below_base_sales_{p}",
                 f"revenue_{p}", f"avg_price_{p}"]
    shed_items = sorted(set(PRODUCTS) | set(ANIMALS))  # animals live in the shed
    for it in shed_items:
        cols += [f"shed_items_start_{it}", f"shed_items_end_{it}", f"shed_deltas_{it}",
                 f"discarded_items_{it}"]
    buy_items = sorted(set(PRODUCTS) | set(CROPS) | set(ANIMALS))
    for it in buy_items:
        cols += [f"buy_qty_{it}"]
    for c in CROPS:
        cols += [f"seed_deltas_{c}", f"plants_planted_{c}", f"plants_harvested_{c}"]
    for a in ANIMALS:
        cols += [f"animals_placed_{a}", f"animals_escaped_by_{a}"]
    return cols



def _game_columns() -> List[str]:
    return ["agent", "opponent", "seed",
            "final_money", "opponent_final", "result",
            "idle_steps", "idle_units_total", "idle_share_pct",
            "idle_units_ready_total", "shed_pressure_days", "shed_overflow_days",
            "discarded_units_total", "discarded_items", "floor_sales", "stranded_at_bell",
            "locked_steps", "locked_units_at_bell", "near_shed_planted_max", "near_shed_bare_final",
            "animal_escapes", "escaped_by_type", "plants_died", "harvests",
            "weeds_peak", "unfed_signals", "at_risk_of_escape", "unwatered_eod",
            "missed_harvest_eod",
            "seed_cost_total", "animal_cost_total", "product_cost_total",
            "hire_cost_total", "land_cost_total", "sell_revenue_total",
            "wheat_fed", "feed_surplus", "premium_below_base_frac", "premium_waste_units"]

# ---------------------------------------------------------------------------
# Replay -> frames / days helper
# ---------------------------------------------------------------------------



def replay_to_record(replay: Dict[str, Any], seat: int = 0) -> List[Tuple[Dict, Dict]]:
    record = []
    for i, step_data in enumerate(replay.get("steps", [])):
        state = step_data[seat]
        obs = state.get("observation", {})
        act = state.get("action") or {}   # an opponent's action may be None
        if obs is None or not isinstance(obs, dict):
            obs = {}
        obs = dict(obs)
        # The observer's observation carries `step`/`day`/`hour`; the opponent's
        # stored observation may omit them. Fall back to the step index so day
        # attribution and hour work for every seat.
        obs.setdefault("step", i)
        record.append((obs, act))
    return record



def replay_to_summary(replay: Dict[str, Any], seat: int = 0) -> Tuple[List[Dict], List[Dict], OrderedDict]:
    record = replay_to_record(replay, seat)
    frames = build_frames(record, seat)
    audit = replay.get("_diagnose_meta", {}).get("audit")
    if audit:
        # JSON turns integer keys into strings; rebuild them.
        audit = {
            int(step): {int(s): v for s, v in (seats or {}).items()}
            for step, seats in audit.items()
        }
    days = build_days(frames, audit=audit)
    summary = summarize(days, frames)
    return frames, days, summary


# ---------------------------------------------------------------------------
# Per-game compact summary (for terminal tables, no cross-game aggregation)
# ---------------------------------------------------------------------------



def game_summary(path: Path, seat: Optional[int] = None) -> Dict[str, Any]:
    """Return a compact dict of key metrics for a single replay file.

    Analyzes the agent under test (meta seat, or seat 0 for legacy runs), and
    also reports the opponent's final revenue plus a WIN / LOSS / TIE tag."""
    replay = load_replay(path)
    return game_summary_from(replay, seat=seat)


def game_summary_from(replay: Dict[str, Any], seat: Optional[int] = None,
                      days: Optional[List] = None, summary: Optional[Dict] = None) -> Dict[str, Any]:
    """game_summary, but built from an already-loaded replay (and optional
    precomputed frames/days/summary) so a caller that already analyzed a replay
    does not load it a second time. Falls back to analyzing when not provided."""
    meta = replay.get("_diagnose_meta", {})
    if seat is None:
        seat = _agent_seat(replay)
    opp_seat = 1 - seat
    if days is None or summary is None:
        _, days, summary = replay_to_summary(replay, seat)
    our_final = summary.get("final_money", 0)
    opp_final = None
    try:
        opp_final = replay["steps"][-1][opp_seat].get("reward")
        if opp_final is not None and isinstance(opp_final, (int, float)):
            opp_final = round(float(opp_final), 1)
    except Exception:
        opp_final = None
    if opp_final is None:
        result = "?"
    elif our_final > opp_final:
        result = "WIN"
    elif our_final < opp_final:
        result = "LOSS"
    else:
        result = "TIE"
    return {
        "agent": meta.get("agent", "unknown"),
        "opponent": meta.get("opponent", "unknown"),
        "seed": meta.get("seed", "unknown"),
        "final_money": our_final,
        "opponent_final": opp_final if opp_final is not None else "",
        "result": result,
        "idle_steps": summary.get("idle_steps", 0),
        "idle_units_total": summary.get("idle_units_total", 0),
        "idle_share_pct": summary.get("idle_share_pct", 0.0),
        "idle_units_ready_total": summary.get("idle_units_ready_total", 0),
        "shed_pressure_days": summary.get("shed_pressure_days", 0),
        "shed_overflow_days": summary.get("shed_overflow_days", 0),
        "discarded_units_total": summary.get("discarded_units_total", 0),
        "discarded_items": json.dumps(summary.get("discarded_items", {}), sort_keys=True),
        "floor_sales": sum(summary.get("floor_sales", {}).values()),
        "stranded_at_bell": summary.get("stranded_at_bell", 0),
        "locked_steps": summary.get("locked_steps", 0),
        "locked_units_at_bell": summary.get("locked_units_at_bell", 0),
        "near_shed_planted_max": summary.get("near_shed_planted_max", 0),
        "near_shed_bare_final": summary.get("near_shed_bare_final", 0),
        "animal_escapes": summary.get("animal_escapes", 0),
        "escaped_by_type": " ".join(f"{k}:{v}" for k, v in summary.get("animals_escaped_by", {}).items()),
        "plants_died": summary.get("plants_died_to_weeds", 0),
        "harvests": summary.get("harvests_total", 0),
        "weeds_peak": summary.get("weeds_peak", 0),
        "unfed_signals": summary.get("unfed_at_eod", 0),
        "at_risk_of_escape": summary.get("at_risk_of_escape", 0),
        "unwatered_eod": summary.get("unwatered_crop_eod", 0),
        "missed_harvest_eod": summary.get("missed_harvest_eod", 0),
        "seed_cost_total": summary.get("seed_cost_total", 0),
        "animal_cost_total": summary.get("animal_cost_total", 0),
        "product_cost_total": summary.get("product_cost_total", 0),
        "hire_cost_total": summary.get("hire_cost_total", 0),
        "land_cost_total": summary.get("land_cost_total", 0),
        "sell_revenue_total": summary.get("sell_revenue_total", 0),
        "wheat_fed": summary.get("wheat_fed_total", 0),
        "feed_surplus": summary.get("feed_surplus_total", 0),
        "premium_below_base_frac": summary.get("premium_below_base_frac", 0.0),
        "premium_waste_units": summary.get("premium_waste_units", 0),
    }



def _agent_seat(replay) -> int:
    """The seat occupied by the agent under test (defaults to TEST_SEAT)."""
    return int(replay.get("_diagnose_meta", {}).get("seat", TEST_SEAT))
