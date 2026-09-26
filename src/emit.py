"""Assemble the action dict; enforce order cap + collective-PLANT guard; fallback."""
from __future__ import annotations

from . import params


def _ok(op):
    return op if (isinstance(op, list) and op) else ["PASS"]


def plant_guard(units, seeds):
    """Downgrade excess PLANT requests per crop so we never rely on the engine's
    silent collective-PLANT -> PASS (which wastes every unit's turn)."""
    demand = {}
    for o in units:
        if o[0] == "PLANT":
            demand[o[1]] = demand.get(o[1], 0) + 1
    for crop, n in demand.items():
        excess = n - int(seeds.get(crop, 0))
        if excess <= 0:
            continue
        for o in units:
            if excess <= 0:
                break
            if o[0] == "PLANT" and o[1] == crop:
                o[:] = ["PASS"]
                excess -= 1


def assemble(state, ops, market):
    """ops: list aligned to units [farmer, hand0, ...]; market: list of orders."""
    n_units = state.unit_count()
    full = [_ok(o) for o in ops]
    farmer = full[0] if full else ["PASS"]
    hands = full[1:n_units]
    # align hands to the true hand count (never emit more hand ops than hands)
    hands += [["PASS"]] * max(0, n_units - 1 - len(hands))
    units = [farmer] + hands
    plant_guard(units, state.seeds)
    mkt = [m for m in market if isinstance(m, list) and m][: params.MAX_ORDERS]
    return {"farmer": units[0], "hands": units[1:], "market": mkt}


def fallback(obs):
    """Never-crash action: a legal PASS with the correct hand count."""
    farm = obs.get("farms", [{}])
    me = farm[obs.get("player", 0)] if obs.get("player", 0) < len(farm) else {}
    n = len(me.get("hands", []))
    return {"farmer": ["PASS"], "hands": [["PASS"]] * n, "market": []}
