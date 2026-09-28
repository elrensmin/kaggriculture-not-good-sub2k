"""Job generation, greedy assignment, routing. The execution layer.

Each turn: gather field jobs (harvest/water/plant/dig/feed/care/collect/place/...)
from the policy layers, greedily assign each worker the nearest eligible job, route
it one cell, and compile the market orders. Eligibility depends on what a worker is
carrying (FEED needs WHEAT, PLACE needs an animal, FERTILIZE needs FERTILIZER), so
a carrying worker prefers its delivery job and otherwise deposits at the shed.
``action(t) = f(state(t))`` only — no cross-turn positional memory.
"""
from __future__ import annotations

import collections

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS

from . import (budget, crop_plan, emit, endgame, herd_plan, layout, opening, roots,
               routing, sell_policy, trade)
from . import params
from . import job as job_mod
from .job import Job, P_PLANT

_DELIVER_OPS = ("FEED", "PLACE", "FERTILIZE")
# The ops a unit can perform on an animal tile it already occupies. See
# params.SAME_TILE_ANIMAL_CHAIN -- FEED/CARE/COLLECT are one visit, not three trips.
_ANIMAL_VISIT_OPS = ("FEED", "CARE", "COLLECT_FERTILIZER")
# The crop companions of a visit: fertilizing the tile a unit just watered/harvested.
# See params.SAME_TILE_CROP_CHAIN.
_CROP_VISIT_OPS = ("FERTILIZE",)
# Same-tile jobs that are never worth chaining: clearing a weed buys no output this turn.
# See params.COMPLETE_TILE.
_BUSYWORK_OPS = ("DIG",)
# Ops whose value is a pure BONUS, so the walk to them is priced linearly and uncapped --
# see params.BONUS_WALK_WEIGHT. FERTILIZE is the measured one: we spend 9.2 % of all our
# moves on it at 2.36 moves/op against the reference's 0.13.
_BONUS_OPS = ("FERTILIZE",)


def _move_or_act(state, pos, job, cost, first=None):
    if pos == job.tile:
        op = [job.op]
        if job.item is not None:
            op.append(job.item)
        if job.qty is not None:
            op.append(job.qty)
        return op
    if first is not None and job.tile in first:
        # FLOOD ROUTING: the first step of the true shortest path, not a greedy choice.
        return [routing.step_of(pos, first[job.tile])]
    op = routing.step_toward(pos, job.tile, cost)
    return [op] if op else ["PASS"]


def _deposit_op(state, pos, cost, first=None):
    """Route a carrying unit toward the shed; drop once adjacent."""
    if pos in params.SHED_ACCESS_SET:
        return ["DROP"]
    target = routing.nearest_shed_access(pos, cost)
    if target is None:
        return ["PASS"]
    if first is not None and target in first:
        return [routing.step_of(pos, first[target])]
    op = routing.step_toward(pos, target, cost)
    return [op] if op else ["DROP"]


def _eligible(inv, job, day=0):
    """Whether a worker carrying `inv` can perform `job`."""
    if job.op == "FEED":
        return inv.get("WHEAT", 0) > 0
    if job.op == "PLACE" and job.item in ANIMALS:
        return inv.get(job.item, 0) > 0
    if job.op == "FERTILIZE":
        return inv.get("FERTILIZER", 0) > 0
    if job.op == "PICKUP":
        # THE ENGINE HAS NO EMPTY-HANDED RULE (`_do_action` PICKUP only needs shed
        # adjacency and stock), so this was ours, and it is the other half of the shed
        # loop: a unit holding one harvested strawberry could not fetch the wheat it was
        # standing next to. MEASURED: PICKUP 152 vs Boey's 91. Allow the fetch when the
        # unit holds only PRODUCE; a deliverable (wheat/fertilizer/animal) still blocks it,
        # because fetching on top of that would strand the delivery.
        if params.at("PICKUP_WITH_PRODUCE", day):
            return not _carrying_deliverable(inv)
        return not inv  # pick up only empty-handed
    return True


def _carrying_deliverable(inv):
    return any(
        k in ANIMALS or k in ("WHEAT", "FERTILIZER")
        for k in inv if inv.get(k, 0) > 0
    )


def _nearest_empty_to_shed(state, used):
    """Nearest empty owned tile to the shed (shed-outward fill, like DSM)."""
    best, bd = None, None
    for y in range(params.BOARD):
        for x in range(params.BOARD):
            p = (x, y)
            if state.is_empty_owned(p) and p not in used:
                d = min(routing.manhattan(p, s) for s in params.SHED_ACCESS)
                if bd is None or d < bd:
                    bd, best = d, p
    return best


def _nearest_empty_in_slice(state, used, band):
    """Nearest empty owned tile within a worker's band (shed-outward within it)."""
    best, bd = None, None
    for p in band:
        if state.is_empty_owned(p) and p not in used:
            d = min(routing.manhattan(p, s) for s in params.SHED_ACCESS)
            if bd is None or d < bd:
                bd, best = d, p
    return best


def _band_crop(state, band, crops, i):
    """Which crop worker `i` should sow in its band, keeping the band MONOCROPPED.

    Why: `crops` is the *daily deficit queue*, so `crops[i % len(crops)]` gives band i a
    different crop each day. Every crop type then ends up scattered across every band,
    and tiles that share a water window are never adjacent. MEASURED with
    `tools/labour/move_trace.py`: WATER costs **2.55 moves per op** against the #1's
    **1.22**, and it is 50 % of all midgame moves -- and the slice assignment is NOT at
    fault (85 % of waters already land in the unit's own band, at mean distance 1.8).
    The distance is the scattered demand, not the routing.

    So: if the band already grows a crop the queue still wants, keep that crop and let
    the band fill up as one block. Only start a new crop when the queue stops asking for
    the old one. The band's first crop is `crops[i % len(crops)]` so the overall mix
    stays balanced across workers.
    """
    counts = collections.Counter()
    for pos in band:
        t = state.plant_at(pos)
        if t:
            counts[t["crop"]] += 1
    if counts:
        cur = counts.most_common(1)[0][0]
        if cur in crops:
            return cur
    return crops[i % len(crops)] if crops else None


def _plant_jobs(state, used, slices, n, limit=None, force_global=False):
    """One PLANT job per worker, on its OWN band (aligned: crops live where the
    worker works), kept monocropped per `_band_crop` so water windows cluster.

    `PLANT_BLOCK = k > 1` sows a band in ONE day instead of one tile per day. See the
    param: MEASURED (consecutive watered tiles, d6-17) ours are **1.72 tiles apart against
    Boey's 1.07**, and the cause is that a band filled one-tile-per-day carries six
    different water windows, so the day's thirsty tiles are never neighbours -- WATER is
    47.9 % of all our moves at 2.62 moves/op.

    The first attempt at this (round 1) failed by filling a band with whatever crop sat at
    the head of the queue, which over-planted it and starved WHEAT. This version CONSUMES
    the per-crop deficit: every tile sown decrements that crop's remaining `plant_queue`
    slot, so the farm-wide mix is exactly what the queue asked for.
    """
    crops = crop_plan.plant_queue(state)
    if not crops:
        return []
    block = int(params.at("PLANT_BLOCK", state.day))
    jobs = []
    all_band = [p for s in slices for p in s]
    cap = n if limit is None else min(n, limit)
    remaining = collections.Counter(crops) if block > 1 else None
    order = [c for c in params.PLANT_ORDER if c in (remaining or {})]
    # PLANT_CAP_BY_SEEDS. The engine validates PLANT **collectively per crop**: if the
    # total requests for a crop this turn exceed the seeds held, ALL of them (including
    # the farmer's) become PASS. MEASURED (`boey_model` + the request/success counters):
    # our WHEAT PLANT commands are 51.5/game against 46.9 planted (9 % wasted) while the
    # reference wastes 2.4 %, and the queue asks for a ~15-22 tile wheat deficit while
    # `crop_plan` holds only `SEED_BUFFER = 6` seeds per crop. Capping the requests at the
    # seeds held turns a wiped-out batch into a partial one. See params.PLANT_CAP_BY_SEEDS.
    cap_by_seeds = bool(params.at("PLANT_CAP_BY_SEEDS", state.day))
    seeds_left = collections.Counter({c: int(state.seeds.get(c, 0)) for c in set(crops)})
    for i in range(n if limit is None else min(n, limit)):
        if block > 1:
            if (state.day % block) != (i % block):
                continue                    # this band's sowing day is not today
            if len(jobs) >= cap:
                break
        if block > 1:
            # keep the band's existing crop when the queue still wants it; else take the
            # crop with the largest remaining deficit so the mix tracks the plan.
            counts = collections.Counter()
            for pos in slices[i]:
                t = state.plant_at(pos)
                if t:
                    counts[t["crop"]] += 1
            cur = counts.most_common(1)[0][0] if counts else None
            if cur is not None and remaining.get(cur, 0) > 0:
                crop = cur
            else:
                live = [c for c in order if remaining.get(c, 0) > 0]
                if not live:
                    continue
                crop = max(live, key=lambda c: (remaining[c], -order.index(c)))
        else:
            crop = (_band_crop(state, slices[i], crops, i) if params.BAND_MONOCROP
                    else crops[i % len(crops)])
        if crop is None:
            continue
        if cap_by_seeds and seeds_left.get(crop, 0) <= 0:
            continue        # no seed for this crop: a request would void the whole batch
        # WORK MUST NOT BE BOUND TO A BAND THAT DOES NOT CONTAIN IT. With ~13 opening
        # crop tiles and 6 bands some workers have no empty tile in their slice and
        # plant nothing while the script has a deficit. PLANT_GLOBAL lets any worker
        # take the nearest empty on the farm.
        band = all_band if (params.PLANT_GLOBAL or force_global) else slices[i]
        quota = 1 if block <= 1 else max(1, min(block, len(slices[i]) or block))
        for _ in range(quota):
            if block > 1 and len(jobs) >= cap:
                break
            if block > 1 and remaining.get(crop, 0) <= 0:
                break                       # that crop's plan slots are used up today
            tile = _nearest_empty_in_slice(state, used, band)
            if tile is None:
                break
            used.add(tile)
            if block > 1:
                remaining[crop] -= 1
            if cap_by_seeds:
                seeds_left[crop] -= 1
            jobs.append(Job(P_PLANT, tile, "PLANT", crop))
            if block <= 1:
                break
    return jobs


_FIELD_OPS = ("PLANT", "WATER", "HARVEST", "DIG", "FERTILIZE")
# Ops that honour the per-worker band in `_pick` pass 1. The animal trio joins only
# when `BAND_ANIMALS` has put the holdback ring into the bands (see layout).
_ANIMAL_OPS = ("FEED", "CARE", "COLLECT_FERTILIZER")


def _pick(jobs, assigned, pos, inv, only_delivery, prefer=None, claimed=None,
          owner=None, me=None, day=0, deliver_margin=None, horizon=None,
          vals=None, floor=0.0, quota=None, taken=None, vmap=None):
    """Choose the best job for a unit: minimise ``walk_cost - priority``.

    Distance is priced (``MOVE_WEIGHT`` per tile) rather than used as a tie-break,
    so a unit finishes the ops on its own tile/neighbour before crossing the farm
    (DSM's ~0.76 moves/act). ``claimed`` stops two units walking to the same tile
    for two different ops, which would burn one of the two turns.

    ``only_delivery`` restricts the candidate set to delivery ops. With
    ``deliver_margin`` it stops being a wall and becomes a penalty on everything else
    -- see params.CARRY_DELIVERY_MARGIN for the measurement.

    ``horizon`` = the moves left before the day ends. A job farther than that is
    unreachable (hands are wiped at `_end_of_day`), so it is dropped from the choice --
    see params.HORIZON_FILTER.

    ``vals`` = per-job DOLLARS (from `src/crew.py`), computed once per turn by `plan`. With
    it the ranking becomes dollars per unit-turn instead of `dcost - priority`, and `floor`
    is the budget rule: a hand will not start work below that many dollars per turn unless
    the job is `critical`. See params.VALUE_KERNEL.
    """
    band_ops = (_FIELD_OPS + _ANIMAL_OPS
                if params.at("BAND_ANIMALS", day) else _FIELD_OPS)
    # WATER OWNER-LOCALITY. MEASURED (consecutive watered tiles, d6-17): ours are **1.72
    # tiles apart, Boey's 1.07**, and WATER is **47.9 % of all our moves at 2.62 moves/op**.
    # The pass-2 global fallback is the suspect: it lets any unit anywhere take a BONUS
    # water, so a band's tiles get watered by whoever is nearest rather than in sequence.
    # With this on, a non-critical water is only visible to the unit whose band contains it;
    # CRITICAL (survival) waters keep the global fallback, because a tile about to die must
    # be rescued from anywhere.
    owner_water = (prefer is not None and bool(params.at("WATER_OWNER_ONLY", day)))

    # two passes: band-local field work first (adjacent tasks, DSM-like), then a
    # global fallback so a worker never idles while cross-band work exists.
    #
    # BAND_LOSS_TOL softens pass 1. MEASURED (`hop_regret --exclude-claimed`, d6-17, 8
    # games): 29.5 % of our walking is STILL avoidable-by-nearest with tiles another unit
    # serves removed (WATER mean regret 1.64/op, FERTILIZE 1.68, HARVEST 1.52), because
    # pass 1 returns the best BAND-LOCAL job as soon as it finds one -- so a farther
    # in-band water beats a nearer out-of-band one. With this set, a same-priority
    # out-of-band tile wins when it is closer by more than `tol` tiles, so the band stays
    # a preference rather than a wall. `None` = off (the old hard restriction).
    # `USE_SLICES_P2=0` (drop the band entirely) is NOT the fix: measured moves/act
    # 1.81 -> 2.35, because priority (not distance) then decides across the whole farm.
    tol = params.at("BAND_LOSS_TOL", day)
    # BAND_CRITICAL_BYPASS: a job that stops an irreversible loss is visible farm-wide.
    # Without this the band wall (the `continue` below) runs BEFORE the `j.critical` cost
    # waiver a few lines down, so an in-band DIG 8 tiles away beat a survival WATER 1 tile
    # away. See params.BAND_CRITICAL_BYPASS for the measurement.
    crit_bypass = bool(params.at("BAND_CRITICAL_BYPASS", day))
    # FERT_DELIVER_RADIUS: a bonus delivery op is not worth a commute. See the param.
    _fr = params.at("FERT_DELIVER_RADIUS", day)
    fert_radius = None if _fr is None else int(_fr)
    for restrict in (True, False):
        best, best_key = None, None
        alt, alt_key = None, None          # nearest out-of-band, same priority class
        for jidx, j in enumerate(jobs):
            if assigned[jidx] or j.tile is None:
                continue
            # ALLOCATION ACTUATOR: a class whose hands are spent is closed for the turn, so
            # the graph reallocates the crew instead of biasing a preference. See src/plan.py.
            if quota is not None and taken is not None and j.op in quota \
                    and taken.get(j.op, 0) >= quota[j.op]:
                continue
            if only_delivery and j.op not in _DELIVER_OPS:
                if deliver_margin is None:
                    continue
                dmargin = deliver_margin
            else:
                dmargin = 0
            if not _eligible(inv, j, day):
                continue
            in_band = not (prefer is not None and j.op in band_ops
                           and j.tile not in prefer)
            if restrict and not in_band and tol is None and not (crit_bypass and j.critical):
                continue
            if not restrict and owner_water and j.op == "WATER" and not j.critical:
                continue      # no global fallback for a bonus water: its band owner waters it
            d = routing.manhattan(pos, j.tile)
            if vmap and j.tile in vmap:
                # AMORTISED COST: the trip is paid once and shared across the cluster, so a
                # clustered task is scored as if it were nearer. Correct arithmetic, not a
                # bonus -- see `tasks.visit_turns_map`.
                d = min(d, max(0, vmap[j.tile] - 1))
            if (only_delivery and j.op == "FERTILIZE"
                    and fert_radius is not None and d > fert_radius):
                continue      # never commute to spend a fertilizer -- FERT_DELIVER_RADIUS
            if horizon is not None and d > horizon:
                continue      # unreachable before the day ends -- see HORIZON_FILTER
            if claimed is not None and d > 0 and j.tile in claimed:
                continue
            if (params.OWNER_FIRST and owner is not None and d > 0
                    and owner.get(j.tile) not in (None, me)):
                continue      # the unit standing there gets first refusal
            if (restrict and not in_band and tol is None
                    and not (crit_bypass and j.critical)):
                k2 = (-j.priority, d)
                if alt_key is None or k2 < alt_key:
                    alt_key, alt = k2, (jidx, j, d)
                continue
            # Distance prices the tile cluster but is capped so local busywork can
            # never starve a far high-value job; a job that stops an irreversible
            # loss (tonight's weed/escape) pays no walk cost at all.
            bw = params.at("BONUS_WALK_WEIGHT", day)
            if bw and j.op in _BONUS_OPS and not j.critical:
                dcost = bw * d          # a bonus op must be walked to at its true cost
            else:
                dcost = params.at("MOVE_WEIGHT", day) * min(d, params.at("DIST_CAP", day))
            if j.critical:
                dcost *= params.CRITICAL_FREE_WALK_FRAC
            # Finishing the visit: a job on the tile the unit already occupies costs no
            # movement, so it is strictly better than walking away and returning -- yet on
            # the score below it still loses to any distant job more than MOVE_WEIGHT*DIST_CAP
            # priority points higher (a distant PICKUP_WHEAT 101 beats the CARE 70 underfoot).
            # See params.ON_TILE_BONUS for the measured visit trace. 0 = off.
            if vals is not None:
                # DOLLARS PER UNIT-TURN. `d` is the walk, +1 for the act itself.
                v = vals[jidx]
                if v <= 0 and not j.critical:
                    continue          # worth nothing on its own; never spend a turn
                s = v / max(1.0, float(d + 1))
                if j.critical:
                    # A tile that becomes a weed tonight, or an animal that escapes, is a
                    # DIFFERENT KIND of loss from a forgone yield: the tile is gone for the
                    # season. Rank dominance rather than a floor, because otherwise a
                    # $1,500 melon harvest outranks a $451 tile save and the wheat dies.
                    s *= params.at("CRITICAL_VALUE_BOOST", day)
                elif s < floor:
                    continue          # below what a turn is worth elsewhere: the budget
                key = (-s, d, -j.priority)
            else:
                on_tile = params.at("ON_TILE_BONUS", day) if d == 0 else 0
                key = (dcost - j.priority - on_tile + dmargin, d, -j.priority)
            if best_key is None or key < best_key:
                best_key, best = key, (jidx, j, d)
        if best is not None:
            if (tol is not None and alt is not None
                    and alt[1].priority == best[1].priority
                    and alt[2] + tol < best[2]):
                return alt
            return best
    return None


def _urgent_window_seeds(state):
    """BUY_SEED orders for crops whose planting window closes within WINDOW_URGENT_DAYS.

    Returned so `plan` can place them immediately after the sells (and ahead of hires,
    the herd and the discretionary seed buffer), because the market list is capped at
    MAX_ORDERS=10 and the seed ask is otherwise the first entry dropped.
    """
    out = []
    for crop in params.PLANT_ORDER:
        plan = params.CROP_PLAN.get(crop)
        if plan is None:
            continue
        if plan["end"] - state.day > params.WINDOW_URGENT_DAYS:
            continue
        have = int(state.seeds.get(crop, 0))
        deficit = plan["target"] - have     # coarse: the market layer buys the rest
        if deficit > 0:
            out.append(["BUY_SEED", crop, min(deficit, 8)])
    return out


def plan(state):
    cost = routing.default_cost(state)
    n = state.unit_count()
    used = set()
    slices = layout.slice_partition(state, n)
    slice_sets = [set(s) for s in slices]
    # USE_SLICES=False drops the band preference so assignment is purely
    # distance-priority (see the param).
    use_slices = params.at("USE_SLICES", state.day)
    # HOLD POSITION WHILE CARRYING (see the step-4 note in the carrying branch below). This
    # must live in `plan`: `_pick` has its own scope and a flag set there never reached the
    # branch that uses it -- which made the first `CARRY_PASS_IN_FIELD_P2=1` arm byte-identical.
    _hold = bool(params.at("CARRY_PASS_IN_FIELD", state.day))
    pref = slice_sets if use_slices else [None] * n

    field_jobs = crop_plan.jobs(state)
    plant_limit = n
    if params.at("PLANT_WATER_CAP_DIVISOR", state.day):
        # don't create new tiles while the survival backlog is already too big to serve
        n_surv = sum(1 for j in field_jobs if j.op == "WATER" and j.critical)
        plant_limit = max(0, n - n_surv // params.at("PLANT_WATER_CAP_DIVISOR", state.day))
    if params.OPENING_TAPE and state.day <= params.OPENING_HERD_UNTIL_DAY:
        # `opening.jobs` owns the tape's job list: field work + named-tile plant jobs +
        # herd + endgame, with the herd's daily loop re-prioritised. It was DEAD CODE
        # until now -- the scheduler rebuilt the same list without the herd bonus, so
        # BUILD/PICKUP/PLACE (60/60/95) lost the race to PLANT/WATER (85/90) and only
        # 1 of the 5 d0 animals got placed, against Boey's 5.
        jobs = opening.jobs(state)
    else:
        # EMPTY DEFICIENT -> PLANT GLOBALLY. With `PLANT_GLOBAL=0` a worker may only sow inside
        # ITS OWN BAND, so an empty tile whose band has no spare worker never gets sown -- which
        # is the last link in the chain seed->empty. MEASURED: end-of-day empty was 18 % at d8
        # against the reference's 0 %, with the seed already covered (adding a seed order changed
        # the run BYTE-IDENTICALLY). The graph says `empty` is deficient, so the band wall comes
        # down for PLANT specifically: any hand may sow any empty owned tile.
        _plant_global = False
        if params.at("PLANT_GLOBAL_WHEN_EMPTY", state.day):
            try:
                from . import state_graph as sg
                _plant_global = any(r[0] == "empty" for r in sg.roots(state))
            except Exception:                             # noqa: BLE001
                _plant_global = False
        jobs = field_jobs + _plant_jobs(state, used, slices, n, limit=plant_limit,
                                        force_global=_plant_global)
        if params.HERD_ENABLED:
            jobs += herd_plan.jobs(state)
        jobs += endgame.jobs(state)
    # FEED PICKUPS IN FLIGHT. `herd_plan.jobs` sizes the wheat fetch from `_unfed_count`
    # alone and is rebuilt EVERY TURN, so as long as any animal is unfed it re-offers
    # `ceil(unfed/qty)` PICKUP WHEAT jobs on all 24 turns -- and any empty unit near the
    # shed takes one. MEASURED (d6-17 per game, ours vs Boey's 60 replays): **WHEAT pickups
    # 142.8 vs 74.2**, against ~11 feeds/day. Every one is a shed visit plus the walk back
    # out, which is where PICKUP 152 vs 91 and DROP 99 vs 32 come from.
    # The scheduler can see what the herd jobs cannot: what the OTHER units are already
    # carrying. Cap the per-turn offer at what is genuinely still short.
    if params.at("FEED_PICKUP_INFLIGHT", state.day):
        carried = sum(state.unit_inv(i).get("WHEAT", 0) for i in range(n))
        short = max(0, herd_plan._unfed_count(state) - carried)
        qty = max(1, int(params.at("WHEAT_PICKUP_QTY", state.day)))
        allow = (short + qty - 1) // qty if short else 0
        kept, out = 0, []
        for j in jobs:
            if j.op == "PICKUP" and j.item == "WHEAT":
                if kept >= allow:
                    continue
                kept += 1
            out.append(j)
        jobs = out
    # PHASE-SCOPED PRIORITY BANDS. A band re-tuned for the midgame (`params.P_*_P2`)
    # would otherwise also move the opening -- which is how `P_COLLECT_FERT=70` was a
    # phase-2 win and a phase-1 regression at the same time. Remapping here, in one
    # place, keeps every job constructor ignorant of phases and leaves phase 1
    # bit-identical while no `_P2` override is set.
    if params.phase_of(state.day) >= 2:
        remapped = []
        for j in jobs:
            b = job_mod.phase_band(j, state.day)
            remapped.append(j if b is None or b == j.priority else j._replace(priority=b))
        jobs = remapped
    # STATE GRAPH: the benchmark heuristics (docs/boey_bench.md / docs/boey_priors.md) as a
    # causal graph evaluated IN-STATE with a time dimension, re-weighting priorities so the
    # machine is forced toward his curves. See src/state_graph.py.
    if params.at("STATE_GRAPH", state.day):
        from . import state_graph
        jobs = state_graph.apply_to_jobs(jobs, state)
    # Binding-root controller: re-weight every job by how far its op class is behind
    # its own requirement this turn (see src/roots.py). URGENCY_SLOPE=0 disables it.
    jobs = roots.apply(jobs, state)
    jobs.sort(key=lambda j: -j.priority)
    assigned = [False] * len(jobs)
    claimed = set()  # tiles another unit is already walking to this turn
    ops = []

    # Pre-pass: a unit standing on a tile with pending work takes it, before the
    # per-unit loop lets a unit further away claim it. `_pick` runs in index order, so
    # without this the same-tile rate is only ~31 % (22 % for CARE) and the work does
    # not chain -- MEASURED with a `_pick` wrapper. Pure ordering; no priority changes.
    visit_first, visit_turns = {}, {}
    if params.at("VISIT_PLANNER", state.day):
        try:
            from . import tasks as tasks_mod
            from . import crew as crew_mod
            pr_v = crew_mod.prices(state)
            all_tasks = tasks_mod.tasks(state, pr_v)
            for i in range(n):
                # CROSS-OP CLUSTERS FOR EMPTY-HANDED UNITS ONLY. A carrying unit's step 1 is
                # restricted to delivery ops, so a mixed trip would fight that; it keeps the
                # existing path untouched.
                if state.unit_inv(i):
                    continue
                pos_i = tuple(state.positions[i])
                v = tasks_mod.route(state, pos_i, all_tasks, pr_v)
                if v is None or not v.tasks:
                    continue
                # THE AMORTISED COST APPLIES TO EVERY UNIT WITH A VISIT, reserved or not:
                # reserving the first stop guarantees the trip, but the corrected cost is what
                # lets a clustered task WIN ON MERIT inside `_pick` for the units that fall
                # through. Setting it only on reservation meant `_pick` never saw it and walking
                # did not move (measured 60.8 % vs the baseline's 60.1 %).
                visit_turns[i] = tasks_mod.visit_turns_map(v)
                if tasks_mod.reserve_ok(state, pos_i, v, all_tasks):
                    visit_first[i] = v.tasks[0]
        except Exception:                                 # noqa: BLE001
            visit_first, visit_turns = {}, {}

    preop = {}
    if params.SAME_TILE_FIRST:
        # A local job must NOT pre-empt a tile that is about to die -- but only for the
        # unit that would actually rescue it. Blocking EVERY unit whenever any critical
        # job exists made the guard inert (any pending critical is common on a big farm):
        # it removed the whole chaining gain (-$10,075 vs CHAIN, p=0.92 vs baseline).
        # Narrow form: the K nearest units to each pending critical job are "rescuers" and
        # may not take a non-critical job underfoot; everyone else keeps chaining.
        # Measured: docs/v0/step1-*.txt.
        rescuers = set()
        if params.SAME_TILE_PROTECT_CRITICAL:
            for j in jobs:
                if not j.critical or j.tile is None:
                    continue
                near = sorted(
                    range(n),
                    key=lambda i: routing.manhattan(state.positions[i], j.tile),
                )[:max(0, params.CRITICAL_RESCUE_K)]
                rescuers.update(near)
        for i in range(n):
            pos = state.positions[i]
            inv = state.unit_inv(i)
            best, best_key = None, None
            for jidx, j in enumerate(jobs):
                if assigned[jidx] or j.tile != pos:
                    continue
                if not _eligible(inv, j, state.day):
                    continue
                # An animal tile offers FEED/CARE/COLLECT on the SAME tile, so the trip is
                # only worth making if the unit clears the stack. This exemption lets those
                # three ops chain regardless of the generic threshold and of the rescuer
                # hold-back; crop-tile busywork keeps the gate that stops it starving a
                # dying tile. See params.SAME_TILE_ANIMAL_CHAIN.
                chain = (params.at("SAME_TILE_ANIMAL_CHAIN", state.day)
                         and j.op in _ANIMAL_VISIT_OPS)
                # THE CROP COMPANION. `P_FERTILIZE` is 54, under the 70 floor, so a unit
                # that just watered a tile leaves without fertilizing it. MEASURED
                # (`stack_trace`/`hop_regret`, d6-17): FERTILIZE chained 3.1 % vs Boey's
                # 93.3 % at 3.00 vs 0.02 moves/op, and `WATER -> FERTILIZE` is the top split
                # pair. See params.SAME_TILE_CROP_CHAIN.
                if params.at("SAME_TILE_CROP_CHAIN", state.day) and j.op in _CROP_VISIT_OPS:
                    chain = True
                # COMPLETE_TILE: finish whatever the tile still offers, except busywork.
                complete = (params.at("COMPLETE_TILE", state.day)
                            and j.op not in _BUSYWORK_OPS)
                if (not chain and not complete
                        and j.priority < params.at("SAME_TILE_MIN_PRIORITY", state.day)
                        and not j.critical):
                    continue      # not worth chaining; leave it to the global assignment
                if i in rescuers and not j.critical and not chain:
                    continue      # this unit is the nearest to a tile about to die
                keys = (-j.priority,)
                if best_key is None or keys < best_key:
                    best_key, best = keys, (jidx, j)
            if (best is not None
                    and params.at("SAME_TILE_CRITICAL_BREAK", state.day)
                    and not best[1].critical):
                cand = _pick(jobs, assigned, pos, inv, only_delivery=False,
                             prefer=pref[i], claimed=claimed, owner=occupied,
                             me=i, day=state.day)
                if cand is not None and cand[1].critical and cand[1].tile != pos:
                    best = None
            if best is not None and params.at("SAME_TILE_COMPARE", state.day):
                # SAME_TILE_COMPARE -- the reservation must WIN the comparison, not veto it.
                # See params.SAME_TILE_COMPARE: the pre-pass scores ON-TILE jobs only, so a
                # unit standing on an animal tile chained FEED(100)/CARE(70) while a
                # survival WATER(90) two tiles away was never considered.
                cand = _pick(jobs, assigned, pos, inv, only_delivery=False,
                             prefer=pref[i], claimed=claimed, owner=occupied,
                             me=i, day=state.day)
                if cand is not None and cand[1].tile != pos:
                    best = None
            if best is None and i in visit_first:
                # THE VISIT RESERVATION. `preop` already bypasses the band and `claimed`, and
                # runs before the greedy loop, so it is where a trip belongs -- and because it
                # only fires when nothing was underfoot, the kernel still gets first refusal.
                t0 = visit_first[i]
                preop[i] = Job(job_mod.P_PLANT, t0.tile, t0.op, t0.item, None, t0.critical)
            if best is not None:
                jidx, j = best
                assigned[jidx] = True
                preop[i] = j

    def _has_local(i):
        pos = state.positions[i]
        inv = state.unit_inv(i)
        for j in jobs:
            if j.tile == pos and _eligible(inv, j, day):
                return True
        return False

    order = list(range(n))
    if params.SAME_TILE_ORDER:
        # local-first: a unit standing on work chooses before a distant unit can claim it
        order.sort(key=lambda i: (0 if _has_local(i) else 1, i))
    # exact per-turn assignment: cheapest (unit, job) edge first, globally.
    #
    # A unit already holding a same-tile job in `preop` is EXCLUDED from the matching.
    # It used to be included, so it could win an edge, mark the job assigned, and then be
    # overridden by the `preop` branch a few lines below -- burning that job for the turn
    # and leaving the unit it would have served idle. That is the whole reason the earlier
    # `EXACT_ASSIGN=1` screen read "CARE 70 -> 8": the chaining jobs were being consumed by
    # units that never took them.
    exact = {}
    if params.EXACT_ASSIGN:
        edges = []
        for i in range(n):
            if i in preop:
                continue
            pos, inv = state.positions[i], state.unit_inv(i)
            deliv = bool(inv) and _carrying_deliverable(inv)
            for jidx, j in enumerate(jobs):
                if assigned[jidx] or j.tile is None:
                    continue
                if deliv and j.op not in _DELIVER_OPS:
                    continue
                if not _eligible(inv, j, state.day):
                    continue
                d = routing.manhattan(pos, j.tile)
                dcost = 0.0 if j.critical else params.at("MOVE_WEIGHT", state.day) * min(d, params.at("DIST_CAP", state.day))
                pen = 0.0
                if (use_slices and pref[i] is not None and j.op in _FIELD_OPS
                        and j.tile not in pref[i]):
                    pen = params.at("SLICE_PENALTY", state.day)
                edges.append(((dcost - j.priority + pen, d, -j.priority), i, jidx))
        edges.sort()
        used_u, used_j = set(), set()
        for _key, i, jidx in edges:
            if i in used_u or jidx in used_j:
                continue
            used_u.add(i)
            used_j.add(jidx)
            exact[i] = (jidx, jobs[jidx])

    occupied = {}
    for i in range(n):
        occupied.setdefault(tuple(state.positions[i]), i)

    # FLOOD ROUTING: one Dijkstra per unit per turn gives the true shortest path to every
    # tile. Cheap on a 10x10 board, and it removes the greedy step's detours/oscillation.
    floods = None
    if params.at("FLOOD_ROUTING", state.day):
        floods = [routing.flood(tuple(state.positions[i]), cost) for i in range(n)]

    # VISIT PLANNER: enumerate every scenario with a DEADLINE (src/tasks.py) and route each
    # unit over a cluster of them, so 2-3 adjacent ops cost 3 turns instead of 1 + 3 walks.
    # MEASURED: 60 % of our unit-turns are walking against the reference's 41 %, and with only
    # 2.8 % idle the job race can only reshuffle the remaining ~37 %. This decides the TRIP.
    # HORIZON: moves left before the day ends. See params.HORIZON_FILTER.
    hzn = max(0, 24 - state.hour) if params.at("HORIZON_FILTER", state.day) else None
    # WASTE GATE: drop every job the engine would silently ignore, counting the reason.
    # Measured defect this closes: `idle_share_pct` 2.7 while `plants_died` 53 and
    # `feed_surplus` -313 -- the crew was not idle, it was emitting actions with no effect.
    waste_fail = {}
    if params.at("WASTE_GATE", state.day):
        from . import waste as waste_mod
        waste_fail = collections.Counter()
        before = len(jobs)
        jobs = waste_mod.filter_jobs(state, jobs, fail=waste_fail)
        if params.SHOW_WASTE and before:
            print(waste_mod.budget_report(waste_fail, before, "   waste: "))

    # ALLOCATION ACTUATOR: hands per op class, from the graph pressures x unmet need.
    quota, taken = None, None
    if params.at("ALLOC_ACTUATOR", state.day):
        from . import plan as plan_mod
        quota = plan_mod.allocation(state, jobs, n)
        taken = collections.Counter()

    # VALUE_KERNEL: price every job in dollars once, then rank by dollars per unit-turn.
    vals, floor = None, 0.0
    if params.at("VALUE_KERNEL", state.day):
        from . import crew
        pr = crew.prices(state)
        herd_daily, at_risk = crew.herd_value_and_risk(state)
        steer_mul = crew.steer(state) if params.at("BENCH_STEER", state.day) else None
        vals = [crew.job_value(state, j, pr, herd_daily, at_risk, steer_mul) for j in jobs]
        pos_vals = [v for v, j in zip(vals, jobs) if v > 0 and j.tile is not None]
        best = max(pos_vals) if pos_vals else 0.0
        floor = float(params.at("VALUE_FLOOR_FRAC", state.day) or 0.0) * best

    for i in order:
        pos = state.positions[i]
        inv = state.unit_inv(i)
        op = None
        if i in preop:
            # must come FIRST: the pre-pass already chose this unit's job, and `exact`
            # must not have given it a different one (see the guard above).
            ops.append(_move_or_act(state, pos, preop[i], cost,
                                    first=floods[i][2] if floods else None))
            continue
        if i in exact:
            # THE EXACT ASSIGNMENT MUST BE TERMINAL. It used to fall through into the
            # `if inv:` / `else:` blocks below, which call `_pick` again -- and `_pick`
            # cannot see the jobs the matching already consumed, so it re-decided the turn
            # from a half-emptied job list. That is why `EXACT_ASSIGN=1` measured as a
            # catastrophe (idle 16.7 %, animals 16 -> 3): the global matching was computed,
            # billed for, and then thrown away. See params.EXACT_ASSIGN.
            jidx, j = exact[i]
            assigned[jidx] = True
            while len(ops) <= i:
                ops.append(None)
            ops[i] = _move_or_act(state, pos, j, cost,
                                  first=floods[i][2] if floods else None)
            continue
        def _take(best, _bunit=(i,)):
            jidx, j, d = best
            assigned[jidx] = True
            if taken is not None:
                taken[j.op] += 1
            if d > 0:
                claimed.add(j.tile)
            return _move_or_act(state, pos, j, cost,
                                first=floods[_bunit[0]][2] if floods else None)

        if inv:
            # 1. deliver a deliverable (feed/place/fertilize) if carrying one.
            if _carrying_deliverable(inv):
                best = _pick(jobs, assigned, pos, inv, only_delivery=True,
                             prefer=(pref[i] if params.at("CARRY_BAND_LOCAL", state.day)
                                     else None),
                             claimed=claimed, owner=occupied, me=i, day=state.day,
                             deliver_margin=params.at("CARRY_DELIVERY_MARGIN", state.day),
                             horizon=hzn, vals=vals, floor=floor, quota=quota, taken=taken, vmap=visit_turns.get(i))
                if best is not None:
                    op = _take(best)
            # 2. deposit when shed-adjacent (free), or during the endgame so
            #    carried produce reaches the shed and is liquidated before the bell.
            #    DSM DROPs ~2/day (the engine auto-drops at day-end anyway), so
            #    walking back after every harvest is wasted movement.
            if op is None and (pos in params.SHED_ACCESS_SET
                               or state.day >= params.LIQUIDATE_DAY):
                op = _deposit_op(state, pos, cost,
                                 first=floods[i][2] if floods else None)
            # 3. otherwise keep working while carrying.
            if op is None:
                best = _pick(jobs, assigned, pos, inv, only_delivery=False,
                             prefer=pref[i], claimed=claimed, owner=occupied, me=i,
                             day=state.day, horizon=hzn, vals=vals, floor=floor, quota=quota, taken=taken, vmap=visit_turns.get(i))
                if best is not None:
                    op = _take(best)
            # 4. nothing to do -> HOLD POSITION, not a shed trip.
            #
            # MEASURED (d6-17 per game, ours vs Boey's 60 replays): DROP 99 vs 32, MOVE
            # 1,839 vs 1,319, PASS 86 vs 152. Idle turns are IDENTICAL (185 vs 184) -- the
            # whole difference is that Boey's idle unit STANDS STILL and ours walks to the
            # shed. A unit that walks in has to walk back out when work appears, so the
            # trip is paid twice, and `_drop_inventories_to_shed` clears every unit for
            # free at `_end_of_day` anyway. Depositing mid-day only buys a same-day sale.
            if op is None:
                if (_hold and state.hour < params.at("DROP_HOUR", state.day)):
                    op = ["PASS"]
                else:
                    op = _deposit_op(state, pos, cost,
                                     first=floods[i][2] if floods else None)
        else:
            best = _pick(jobs, assigned, pos, inv, only_delivery=False,
                         prefer=pref[i], claimed=claimed, owner=occupied, me=i,
                         day=state.day, horizon=hzn, vals=vals, floor=floor, quota=quota, taken=taken, vmap=visit_turns.get(i))
            if best is not None:
                op = _take(best)
            else:
                op = ["PASS"]

        while len(ops) <= i:
            ops.append(None)
        ops[i] = op

    # Market order = funding priority. The engine resolves the list position by
    # position and settles HIRE/BUY_LAND atomically, so an earlier entry is paid for
    # before a later one is even considered, and the whole list is capped at
    # MAX_ORDERS=10 (tail entries are DROPPED, silently).
    #
    #   1. sells      -- the only cash inflow
    #   2. land/hires -- structural, cheap, and labour is what makes the rest work.
    #                    Measured: with the herd's feed buy ahead of hires the crew
    #                    fell to ZERO and the farm stalled, because feed drained the
    #                    turn's cash before the first HIRE was reached.
    #   3. herd       -- animals, then the feed top-up
    #   4. seeds      -- buffered, so the least urgent
    # DAY-GATED, like the jobs branch above. This branch used to be `if OPENING_TAPE:`
    # with no day test, so from d6 to the bell the market list was the TAPE's -- which
    # meant `sell_policy` ran only through the tape's internal call and
    # `herd_plan.market_intents` (herd expansion) and `crop_plan.market_intents` (the
    # seed buffer) NEVER RAN AT ALL. Measured cost of that mis-wiring: the midgame had
    # no seed rebuy and no herd buying, which is why the full-season idle sat at ~25 %.
    # Turning the tape's own sell block into the single owner exposed it as a $0 finish
    # with a full shed (discarded 140 units, shed pressure 17 days).
    # HIRE-FIRST. The crew is wiped nightly (`_end_of_day` clears `hands` and `hires_today`),
    # so the first turns of every day are a rebuild, and `MAX_ORDERS=10` truncates the tail.
    # MEASURED (mean units by hour, d6-29, 16 games): Boey 1.0/8.7/11.2/11.5..., us
    # 1.0/4.3/7.0/7.8 -- a complete crew at hour 2 against hour 12, ~40 unit-turns lost every
    # day. We are not cash-short ($18.5k idle at hour 0), the hires are simply behind sells
    # and land in the list. `budget.market_intents` refuses a hand it cannot afford, so
    # front-running it cannot overspend. See params.MARKET_HIRE_FIRST_HOURS.
    _hire_first = state.hour < int(params.at("MARKET_HIRE_FIRST_HOURS", state.day))
    if params.OPENING_TAPE and state.day <= params.OPENING_HERD_UNTIL_DAY:
        # The tape owns the opening market list (sells + full seed basket in one ordered
        # block); the per-turn layers do not also jostle for the 10 slots.
        market = list(opening.market_intents(state))
        market += budget.market_intents(state)
    elif _hire_first:
        market = list(budget.market_intents(state))
        market += list(sell_policy.market_intents(state))
        market += trade.sell_intents(state) if params.TRADE_MIDGAME else []
        if params.HERD_ENABLED:
            market += herd_plan.market_intents(state)
        market += crop_plan.market_intents(state)
    else:
        market = list(sell_policy.market_intents(state))
        # SEED BEFORE DISCRETIONARY BUYS. `empty` deficient -> the op class is BUY_SEED, and the
        # ask is `empty_tiles x the recipe crop's seed`. Slotted immediately after the SELLS (the
        # only inflow) and AHEAD of hires/animals/feed, because an empty owned tile is a rent --
        # it spawns weeds, lengthens every trip and earns nothing. Emitted last, it was the first
        # thing dropped by the MAX_ORDERS=10 cap, which is why we bought quadrants and never
        # sowed them.
        if params.at("SEED_FROM_EMPTY", state.day):
            try:
                from . import plan as plan_mod
                for crop_s, qty_s in plan_mod.seed_need(state):
                    market.append(["BUY_SEED", crop_s, qty_s])
            except Exception:                             # noqa: BLE001
                pass
        # THE CARRY RUNS ALL SEASON, not just the opening. It was wired only into the
        # tape (d0-d5), so 24 of 30 days had no market engine: `sell_policy` sold WHEAT
        # at TRICKLE and nothing ever bought it back. Boey's 6,786 wheat sales a season
        # are the same carry, run continuously. Its sell half sits with the other
        # inflows; its buy half is emitted last, with the herd's feed reserved.
        market += trade.sell_intents(state) if params.TRADE_MIDGAME else []
        if params.WINDOW_SEED_FIRST:
            market += _urgent_window_seeds(state)
        market += budget.market_intents(state)
        if params.HERD_ENABLED:
            market += herd_plan.market_intents(state)
        market += crop_plan.market_intents(state)
    market += crop_plan.fertilizer_buy_intent(state)
    market += endgame.market_intents(state)
    if params.TRADE_MIDGAME and not (params.OPENING_TAPE and state.day <= params.OPENING_HERD_UNTIL_DAY):
        feed_cash = params.FEED_PRICE_GUESS * max(0, state.herd_count()) * params.TRADE_MIDGAME_FEED_DAYS
        market += trade.buy_intents(state, reserve=feed_cash)
    ops = [o if o is not None else ['PASS'] for o in ops]
    return emit.assemble(state, ops, market)
