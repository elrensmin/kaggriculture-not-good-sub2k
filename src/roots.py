"""src/roots.py — the binding-root controller.

The DAG in ``tools/phases/dag.py`` names the *structural* roots of the season (empty
tiles, water coverage, feed arrears, harvest backlog, shed pressure). This module
answers the runtime question those nodes imply but the code never asked: **which
root is binding this turn**, derived from the observation alone, and converts it into
a priority multiplier for the scheduler.

It does not replace the base priorities in ``job.py`` — it re-weights them, so a class
of work that is currently behind its own requirement outranks one that is not. The
shape of the plan (which crop, which animal) stays where it is: in the policy layers.

Stateless by construction: ``binding(state)`` reads only the per-turn ``State``
snapshot, so it is safe under ``action(t) = f(state(t))``.

Knobs (``SCRATCH_PARAMS``):
  * ``URGENCY_SLOPE``  — 0.0 (default) disables the controller entirely.
  * ``URGENCY_WEIGHTS`` — per-op multiplier on the urgency (dict, code-set).

Measured before enabling: see ``docs/v0/step*.txt`` and ``docs/DSM-vs-us(v0).md`` §7.
"""
from __future__ import annotations

from . import params

_BUILD_OPS = ("BUILD_COOP", "BUILD_PASTURE")


def binding(state) -> dict:
    """Urgency in [0, 1] per op class: the share of that class's demand still unmet."""
    owned = planted = empty = weeds = structures = 0
    unwatered = ready = 0
    animals = unfed = uncared = fert_ready = 0

    for row in state.tiles:
        for t in row:
            if t == "LOCKED":
                continue
            owned += 1
            if t is None:
                empty += 1
                continue
            if not isinstance(t, dict):
                continue
            kind = t.get("kind")
            if kind == "PLANT":
                planted += 1
                if state.plant_ready(t):
                    ready += 1
                elif state.needs_water(t) and state.in_water_window(t):
                    unwatered += 1
            elif kind == "WEED":
                weeds += 1
            elif kind in ("COOP", "PASTURE"):
                structures += 1
            if "animal" in t:
                animals += 1
                if state.animal_ready(t):
                    ready += 1
                if state.animal_needs_feed(t):
                    unfed += 1
                if state.animal_needs_care(t):
                    uncared += 1
                if state.animal_has_fert(t):
                    fert_ready += 1

    units = max(1, state.unit_count())
    need_struct = max(0, animals - structures)
    return {
        "PLANT": min(1.0, empty / owned) if owned else 0.0,
        "WATER": min(1.0, unwatered / planted) if planted else 0.0,
        "HARVEST": min(1.0, ready / units),
        "FEED": min(1.0, unfed / animals) if animals else 0.0,
        "CARE": min(1.0, uncared / animals) if animals else 0.0,
        "COLLECT_FERTILIZER": min(1.0, fert_ready / animals) if animals else 0.0,
        "DIG": min(1.0, weeds / owned) if owned else 0.0,
        "BUILD": min(1.0, need_struct / max(1, animals)),
        "SHED": min(1.0, state.shed_total() / params.SHED_CAP),
    }


def multiplier(op: str, urg: dict) -> float:
    """Priority multiplier for one op under the current urgency vector."""
    if not params.URGENCY_SLOPE:
        return 1.0
    key = "BUILD" if op in _BUILD_OPS else op
    weight = params.URGENCY_WEIGHTS.get(key, 1.0)
    return 1.0 + params.URGENCY_SLOPE * weight * urg.get(key, 0.0)


def apply(jobs, state):
    """Return ``jobs`` with priorities re-weighted by the binding-root urgency."""
    if not params.URGENCY_SLOPE:
        return jobs
    urg = binding(state)
    return [j._replace(priority=j.priority * multiplier(j.op, urg)) for j in jobs]
