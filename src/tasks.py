"""tasks — the whole decision surface, enumerated: every scenario as a task with a DEADLINE.

Why this replaces the priority race
-----------------------------------
Every op in this engine has a hard latest-turn. Miss it and something is permanently lost:
a tile that is dry tonight becomes a weed, a wheat tile past `max_lifespan_step` decays unit
by unit, an animal unfed twice escapes. A PRIORITY can be outranked; a DEADLINE cannot. That
is why tuning priorities never worked and why `P_WATER_BONUS=120` outranking
`P_WATER_SURVIVAL=90` silently waters a tile for +1 while another tile dies.

So the decision is not "which job is best" but "what is about to be lost, and can the crew
reach it in time". This module enumerates that:

  * `tasks(state)`      every scenario, each with a deadline TURN (day*24+hour), a dollar
                        value, its turn cost, and whether missing it is irreversible
  * `route(state, ...)` the per-unit VISIT: an ordered list of tasks one unit services in one
                        trip, so 2-3 adjacent ops cost 3 turns instead of 1 + 3 walks. This is
                        first-class -- routing is planned here, not improvised per turn.
  * `slack(task)`       deadline - now - travel. Negative = already lost, and surfaced rather
                        than silently dropped.

Deadlines are DERIVED from the engine constants (`CROPS`, `max_lifespan_step`, the water
window, the planting window) plus the observation, so nothing here is a tuned constant.

Where routing lives: `route()` takes a seed unit and greedily extends a trip over nearby tasks
while the marginal dollars per turn stay above the best alternative. The scheduler then walks
each unit one step along its visit, and the visit is recomputed next turn from the
observation -- stateless, and self-correcting when a target vanishes.
"""
from __future__ import annotations

import collections

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS, CROPS

from . import params, recipes, routing, value

Task = collections.namedtuple(
    "Task", "tile op item deadline value turns critical kind")
Visit = collections.namedtuple(
    "Visit", "tasks value turns slack unit route")

LAST_TURN_OF_DAY = 23


def now(state):
    """The current turn index."""
    return int(state.day) * 24 + int(state.hour)


def _day_end(day):
    return int(day) * 24 + LAST_TURN_OF_DAY


def _decay_start(tile):
    """The last turn before `_decay_plants` begins eating this tile's yield."""
    cd = CROPS[tile["crop"]]
    if cd["ongoing"]:
        return None
    return (int(tile.get("planted_day", 0)) + cd["max_yield_day"] + 1) * 24 - 1


def _harvest_deadline(tile, state):
    """Harvest by the recipe age at the latest, and before decay at the hardest."""
    r = recipes.recipe(tile["crop"])
    if not r:
        return None
    if r["ongoing"]:
        return _day_end(state.day)              # the cap discards if held too long
    want = int(tile.get("planted_day", 0)) + r["harvest_age"]
    hard = _decay_start(tile)
    return _day_end(want) if hard is None else min(_day_end(want), hard)


def _plant_deadline(crop, state):
    plan = params.CROP_PLAN.get(crop)
    return _day_end(plan["end"]) if plan else None


def _water_deadline(tile, state, risk):
    """A dry tile that dies tonight has ONE turn; a window water has until the window shuts."""
    if risk:
        return _day_end(state.day)
    crop = tile["crop"]
    cd = CROPS[crop]
    if cd["ongoing"]:
        return _day_end(state.day)              # survival + the production credit
    w = value.water_window(crop)
    if not w:
        return _day_end(state.day)
    age = state.crop_age(tile)
    if age > w[1]:
        return _day_end(state.day)
    return _day_end(int(tile.get("planted_day", 0)) + w[1])


def task_kind(op, critical):
    if critical:
        return "irreversible-now"
    if op in ("HARVEST", "PLANT", "PLACE", "BUILD_COOP", "BUILD_PASTURE"):
        return "revenue"
    if op in ("DIG", "FERTILIZE"):
        return "upkeep"
    return "throughput"


# --------------------------------------------------------------------------- enumeration
def tile_tasks(state, prices):
    """Every crop-tile scenario. Order of the branches IS the engine's precedence."""
    out = []
    empty_owned = []
    for y, row in enumerate(state.tiles):
        for x, t in enumerate(row):
            pos = (x, y)
            if t is None and state.owned(pos):
                empty_owned.append(pos)
                continue
            if isinstance(t, dict) and t.get("kind") == "WEED":
                # A weed blocks the tile until cleared, so it has no deadline but a growing
                # opportunity cost: every cycle the tile cannot run.
                out.append(Task(pos, "DIG", None, None,
                                value.tile_option_value(_days_left(state), prices, state.day),
                                value.op_turns(0), False, "upkeep"))
                continue
            if not (isinstance(t, dict) and t.get("kind") == "PLANT"):
                continue
            # 1. ripe / past the recipe age -> harvest banks the yield AND frees the tile
            if recipes.harvest_now(state, t) and t.get("yield_units", 0) > 0:
                out.append(Task(pos, "HARVEST", t["crop"], _harvest_deadline(t, state),
                                t.get("yield_units", 0) * prices.get(t["crop"], 0.0),
                                1, False, "revenue"))
                continue
            # 2. dry tonight -> irreversible
            risk = t.get("consecutive_unwatered", 0) >= 1
            if not t.get("watered_today"):
                # 2a. fertilise BEFORE the water, so the water pays +2 instead of +1
                if (recipes.recipe_fert_due(state, t)
                        and state.fert_window_open(t)):
                    gain = value.fertilize_gain(t["crop"], _waters_left(state, t))
                    if gain > 0:
                        out.append(Task(pos, "FERTILIZE", None, _water_deadline(t, state, risk),
                                        gain * prices.get(t["crop"], 0.0)
                                        - prices.get("FERTILIZER", 0.0),
                                        1, risk, "upkeep"))
                if risk or recipes.next_step(state, t) == "WATER":
                    out.append(Task(pos, "WATER", t["crop"],
                                    _water_deadline(t, state, risk),
                                    _water_value(state, t, prices),
                                    1, risk, task_kind("WATER", risk)))
    # planting: one task per empty tile, crop chosen by the recipe rate
    if empty_owned:
        crop, rate = recipes.best_crop_per_tile_day(prices, state.day)
        if crop and state.seeds.get(crop, 0) > 0:
            r = recipes.recipe(crop)
            for pos in empty_owned:
                out.append(Task(pos, "PLANT", crop, _plant_deadline(crop, state),
                                r["yield"] * prices.get(crop, 0.0) - r["seed"],
                                1, False, "revenue"))
    return out


def _waters_left(state, tile):
    w = value.water_window(tile["crop"])
    if not w:
        return 0
    age = state.crop_age(tile)
    return max(0, w[1] - max(w[0], age) + 1)


def _water_value(state, tile, prices):
    """The tile's option value when it is at risk, else the marginal unit(s) it banks."""
    if tile.get("consecutive_unwatered", 0) >= 1:
        return value.tile_option_value(_days_left(state), prices, state.day)
    gain = 0
    if not CROPS[tile["crop"]]["ongoing"] and not tile.get("watered_today"):
        gain = 2 if tile.get("fertilized_until_day", -1) >= state.day else 1
    elif CROPS[tile["crop"]]["ongoing"]:
        gain = 1
    return gain * prices.get(tile["crop"], 0.0)


def animal_tasks(state, prices):
    out = []
    for y, row in enumerate(state.tiles):
        for x, t in enumerate(row):
            if not (isinstance(t, dict) and "animal" in t):
                continue
            pos = (x, y)
            sp = t["animal"]
            item = {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}[sp]
            daily = value.animal_output_per_day(sp) * prices.get(item, 0.0)
            if t.get("consecutive_unfed", 0) >= 1:
                out.append(Task(pos, "FEED", None, _day_end(state.day),
                                ANIMALS[sp]["cost"] + daily, 1, True, "irreversible-now"))
            elif not t.get("fed_today"):
                out.append(Task(pos, "FEED", None, _day_end(state.day), daily, 1, False,
                                "throughput"))
            if not t.get("cared_today"):
                out.append(Task(pos, "CARE", None, _day_end(state.day), daily, 1, False,
                                "throughput"))
            if t.get("yield_units", 0) >= ANIMALS[sp]["max_held"]:
                out.append(Task(pos, "HARVEST", None, _day_end(state.day),
                                t.get("yield_units", 0) * prices.get(item, 0.0), 1, False,
                                "revenue"))
            if t.get("fertilizer_available"):
                out.append(Task(pos, "COLLECT_FERTILIZER", None, _day_end(state.day),
                                prices.get("FERTILIZER", 0.0), 1, False, "throughput"))
    return out


def _days_left(state):
    return max(0, 29 - int(state.day))


def tasks(state, prices):
    """The whole surface: crop tiles + animal tiles."""
    return tile_tasks(state, prices) + animal_tasks(state, prices)


def slack(state, task, from_pos):
    """Turns of room left: deadline - now - travel. Negative means already lost."""
    if task.deadline is None:
        return 10_000
    travel = routing.manhattan(from_pos, task.tile) if task.tile else 0
    return task.deadline - now(state) - travel


def loss_rate(state, task, from_pos):
    """DOLLARS LOST PER TURN OF DELAY -- the one ranking key for every task class.

    A weed is unlike every other task, and the old model could not say so. Everything else is a
    CLIFF: nothing is lost until the deadline, then the whole value goes. A weed is a RENT: no
    deadline at all, but every day it stands costs one tile-cycle. With `deadline=None` mapping
    to infinite slack, weeds sorted LAST BY CONSTRUCTION -- which is why `weeds_max` ran 1, 1,
    2, 0, 1, 1, 3, 4, 6 against the reference's 0 every day, starting at d4, six days before the
    money wedge. The scheduler was not failing, it was being asked the wrong question.

    `value / max(1, slack)` is the Critical-Ratio rule: it spreads a cliff's eventual loss over
    the turns left to prevent it, so a $451 tile dying tonight outranks a $30 tile dying in ten
    days, and a deep weed backlog -- whose rent compounds -- rises on its own as it grows.
    """
    if task.op == "DIG":
        # accruing: `tile_option_value` IS `tile_dollars_per_day x days_left`, so this is the
        # rent, per turn, with no tuning.
        return task.value / max(1.0, float(_days_left(state)))
    if task.deadline is None:
        return task.value / 10.0
    sl = slack(state, task, from_pos)
    if sl <= 0:
        return task.value            # already late: the whole value is at stake now
    return task.value / max(1.0, float(sl))


def urgency(state, tasks_, from_pos):
    """Rank by loss per turn of delay, irreversible losses first."""
    def key(t):
        return (0 if t.critical else 1, -loss_rate(state, t, from_pos),
                slack(state, t, from_pos), -t.value)
    return sorted(tasks_, key=key)


def visit_turns_map(visit):
    """{tile: amortised turns} for a visit -- the trip is paid ONCE and shared.

    A task is normally scored with its own walk (`manhattan + 1`). If that tile is one of three
    adjacent thirsties and ONE unit services all three, the walk is shared, so the honest cost
    is `visit.turns / n_stops` rather than the standalone walk. That is why clustering can win
    on merit with no bonus: it does not make the task worth more, it makes it COST LESS.

    Only valid while a single unit owns the trip -- which is why the scheduler RESERVES the
    visit in `preop` rather than offering it as a loose candidate. If three units each took one
    stop, each would pay the full walk and the amortisation would be a fiction.
    """
    n = max(1, len(visit.tasks))
    per = max(1, int(round(visit.turns / float(n))))
    return {t.tile: per for t in visit.tasks if t.tile is not None}


def reserve_ok(state, pos, visit, all_tasks):
    """Should this unit's first stop be RESERVED, or should it fall through to the kernel?

    The visit must not become a bypass again -- that is what made PLANT jobs vanish and left 24
    empty owned tiles at d10. So the reservation needs a reason, and all three are derived:
      1. the stop is `critical` (a tile dies tonight, an animal escapes tonight);
      2. `local_is_free` -- the walk costs nothing, it breaks no reachable deadline;
      3. it has the highest `loss_rate` on the farm -- it is the most urgent thing anyway.
    """
    if not visit or not visit.tasks:
        return False
    first = visit.tasks[0]
    if first.tile is None:
        return False
    if first.critical:
        return True
    if local_is_free(state, pos, first, all_tasks):
        return True
    mine = loss_rate(state, first, pos)
    return all(loss_rate(state, t, pos) <= mine for t in all_tasks)


def local_is_free(state, pos, local_task, all_tasks):
    """FEASIBILITY TEST: is working the local task free, or does it break a deadline?

    MEASURED, three independent arms: every reduction in walking cost money and deaths --
    moves 60.1 % -> 52.0 % and moves/act 1.64 -> 1.16 while the bank fell $47,032 -> $23,861
    and `died` rose 50 -> 61. Locality was bought by servicing whatever was NEARBY instead of
    whatever was URGENT, and a missed deadline costs the tile's whole option value (~$451 at
    d10) while the walk saved is worth ~2 turns.

    So locality is not preferred and not forbidden -- it is CHECKED. Working the adjacent task
    costs `turns_local` turns; if any still-reachable deadline-bound task would fall out of
    reach because of those turns, the local work is not free and the unit walks instead.

    Tasks already past their deadline are ignored: we did not cause that loss and cannot
    un-cause it, so blocking on it would freeze the crew.
    """
    if local_task is None or local_task.tile is None:
        return False
    now_t = now(state)
    turns_local = value.op_turns(routing.manhattan(pos, local_task.tile))
    for t in all_tasks:
        if t is local_task or t.tile is None or t.deadline is None:
            continue
        before = t.deadline - now_t - routing.manhattan(pos, t.tile)
        if before < 0:
            continue                       # already lost, not our doing
        if before - turns_local < 0:
            return False                   # our one local turn breaks it
    return True


# ------------------------------------------------------------------- VISIT / ROUTE (first class)
def route(state, seed_pos, pool, prices, max_radius=2, max_stops=3):
    """One unit's VISIT: an ordered trip over nearby tasks.

    Routing is planned here rather than improvised per turn. The trip starts at the most
    urgent reachable task, then extends to tasks within `max_radius` of the current end while
    the marginal dollars per turn stays above what the turn is worth elsewhere -- which is what
    turns "water one tile then walk three" into "clear three tiles in one sweep".
    """
    if not pool:
        return None
    ordered = urgency(state, pool, seed_pos)
    # SEED ON DENSITY, NOT ON URGENCY ALONE. Measured: seeding on the most urgent task gave
    # 3 waters over **19 turns** (6.3 turns per act) when the urgent tile was isolated, while
    # an animal tile with three ops underfoot cost **1 turn per act**. The trip is what is
    # expensive, so the seed must be chosen for the CLUSTER it opens, and urgency then orders
    # the stops INSIDE the trip. `neighbourhood` is the dollars reachable from that tile.
    seed = _seed(state, ordered, seed_pos, max_radius)
    if seed is None or slack(state, seed, seed_pos) < 0:
        return None
    stops = [seed]
    used = {seed}
    cur = seed.tile
    turns = value.op_turns(routing.manhattan(seed_pos, cur))
    total = seed.value
    best_alt = _best_alt_rate(state, ordered, seed_pos)
    while len(stops) < max_stops:
        cands = [t for t in ordered
                 if t not in used and t.tile is not None
                 and routing.manhattan(cur, t.tile) <= max_radius
                 and slack(state, t, cur) >= 0]
        if not cands:
            break
        nxt = min(cands, key=lambda t: (slack(state, t, cur), -t.value))
        add_turns = value.op_turns(routing.manhattan(cur, nxt.tile))
        rate = nxt.value / max(1, add_turns)
        if rate < best_alt:                    # the turn is worth more elsewhere
            break
        stops.append(nxt)
        used.add(nxt)
        turns += add_turns
        total += nxt.value
        cur = nxt.tile
    return Visit(stops, total, turns, slack(state, stops[-1], seed_pos), None,
                 _path(state, seed_pos, [t.tile for t in stops]))


def _seed(state, ordered, pos, radius):
    """The task that opens the best CLUSTER: dollars reachable per turn of travel to it."""
    best, best_key = None, None
    for t in ordered:
        if t.tile is None:
            continue
        travel = routing.manhattan(pos, t.tile)
        reach = t.value
        for o in ordered:
            if o is t or o.tile is None:
                continue
            if routing.manhattan(t.tile, o.tile) <= radius:
                reach += o.value
        key = reach / max(1.0, float(value.op_turns(travel)))
        # an irreversible loss still outranks a richer cluster, but only just
        if t.critical:
            key *= 1.5
        if best_key is None or key > best_key:
            best_key, best = key, t
    return best


def _best_alt_rate(state, ordered, pos):
    """The dollars-per-turn of the best task NOT in this neighbourhood."""
    best = 0.0
    for t in ordered:
        if t.tile is None:
            continue
        turns = value.op_turns(routing.manhattan(pos, t.tile))
        best = max(best, t.value / max(1, turns))
    return best * 0.5                          # extend while we beat half the best alternative


def _path(state, start, targets):
    """The tile sequence the unit walks; the scheduler emits one step at a time."""
    return [start] + list(targets)


def plan_visits(state, prices, n_units=None):
    """Assign every unit a visit, most urgent first, so the crew sweeps rather than scatters."""
    n = int(n_units if n_units is not None else state.unit_count())
    pool = tasks(state, prices)
    if not pool:
        return []
    visits = []
    remaining = list(pool)
    for i in range(n):
        pos = tuple(state.positions[i]) if i < len(state.positions) else None
        if pos is None:
            continue
        # a unit that already has work underfoot seeds from there
        own = [t for t in remaining if t.tile == pos]
        v = route(state, pos, own or remaining, prices)
        if v is None and own:
            v = route(state, pos, remaining, prices)
        if v is None:
            continue
        v = v._replace(unit=i)
        visits.append(v)
        remaining = [t for t in remaining if t not in v.tasks]
    return visits
