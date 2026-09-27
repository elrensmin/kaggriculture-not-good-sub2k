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
               routing, sell_policy)
from . import params
from .job import Job, P_PLANT

_DELIVER_OPS = ("FEED", "PLACE", "FERTILIZE")


def _move_or_act(state, pos, job, cost):
    if pos == job.tile:
        op = [job.op]
        if job.item is not None:
            op.append(job.item)
        if job.qty is not None:
            op.append(job.qty)
        return op
    op = routing.step_toward(pos, job.tile, cost)
    return [op] if op else ["PASS"]


def _deposit_op(state, pos, cost):
    """Route a carrying unit toward the shed; drop once adjacent."""
    if pos in params.SHED_ACCESS_SET:
        return ["DROP"]
    target = routing.nearest_shed_access(pos, cost)
    if target is None:
        return ["PASS"]
    op = routing.step_toward(pos, target, cost)
    return [op] if op else ["DROP"]


def _eligible(inv, job):
    """Whether a worker carrying `inv` can perform `job`."""
    if job.op == "FEED":
        return inv.get("WHEAT", 0) > 0
    if job.op == "PLACE" and job.item in ANIMALS:
        return inv.get(job.item, 0) > 0
    if job.op == "FERTILIZE":
        return inv.get("FERTILIZER", 0) > 0
    if job.op == "PICKUP":
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


def _plant_jobs(state, used, slices, n, limit=None):
    """One PLANT job per worker, on its OWN band (aligned: crops live where the
    worker works), kept monocropped per `_band_crop` so water windows cluster."""
    crops = crop_plan.plant_queue(state)
    if not crops:
        return []
    jobs = []
    all_band = [p for s in slices for p in s]
    for i in range(n if limit is None else min(n, limit)):
        crop = (_band_crop(state, slices[i], crops, i) if params.BAND_MONOCROP
                else crops[i % len(crops)])
        if crop is None:
            continue
        # WORK MUST NOT BE BOUND TO A BAND THAT DOES NOT CONTAIN IT. With ~13 opening
        # crop tiles and 6 bands some workers have no empty tile in their slice and
        # plant nothing while the script has a deficit. PLANT_GLOBAL lets any worker
        # take the nearest empty on the farm.
        band = all_band if params.PLANT_GLOBAL else slices[i]
        tile = _nearest_empty_in_slice(state, used, band)
        if tile is None:
            continue
        used.add(tile)
        jobs.append(Job(P_PLANT, tile, "PLANT", crop))
    return jobs


_FIELD_OPS = ("PLANT", "WATER", "HARVEST", "DIG", "FERTILIZE")


def _pick(jobs, assigned, pos, inv, only_delivery, prefer=None, claimed=None,
          owner=None, me=None):
    """Choose the best job for a unit: minimise ``walk_cost - priority``.

    Distance is priced (``MOVE_WEIGHT`` per tile) rather than used as a tie-break,
    so a unit finishes the ops on its own tile/neighbour before crossing the farm
    (DSM's ~0.76 moves/act). ``claimed`` stops two units walking to the same tile
    for two different ops, which would burn one of the two turns.
    """
    # two passes: band-local field work first (adjacent tasks, DSM-like), then a
    # global fallback so a worker never idles while cross-band work exists.
    for restrict in (True, False):
        best, best_key = None, None
        for jidx, j in enumerate(jobs):
            if assigned[jidx] or j.tile is None:
                continue
            if only_delivery and j.op not in _DELIVER_OPS:
                continue
            if not _eligible(inv, j):
                continue
            if restrict and prefer is not None and j.op in _FIELD_OPS and j.tile not in prefer:
                continue
            d = routing.manhattan(pos, j.tile)
            if claimed is not None and d > 0 and j.tile in claimed:
                continue
            if (params.OWNER_FIRST and owner is not None and d > 0
                    and owner.get(j.tile) not in (None, me)):
                continue      # the unit standing there gets first refusal
            # Distance prices the tile cluster but is capped so local busywork can
            # never starve a far high-value job; a job that stops an irreversible
            # loss (tonight's weed/escape) pays no walk cost at all.
            dcost = params.MOVE_WEIGHT * min(d, params.DIST_CAP)
            if j.critical:
                dcost *= params.CRITICAL_FREE_WALK_FRAC
            # Finishing the visit: a job on the tile the unit already occupies costs no
            # movement, so it is strictly better than walking away and returning -- yet on
            # the score below it still loses to any distant job more than MOVE_WEIGHT*DIST_CAP
            # priority points higher (a distant PICKUP_WHEAT 101 beats the CARE 70 underfoot).
            # See params.ON_TILE_BONUS for the measured visit trace. 0 = off.
            on_tile = params.ON_TILE_BONUS if d == 0 else 0
            key = (dcost - j.priority - on_tile, d, -j.priority)
            if best_key is None or key < best_key:
                best_key, best = key, (jidx, j, d)
        if best is not None:
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
    pref = slice_sets if params.USE_SLICES else [None] * n

    field_jobs = crop_plan.jobs(state)
    plant_limit = n
    if params.PLANT_WATER_CAP_DIVISOR:
        # don't create new tiles while the survival backlog is already too big to serve
        n_surv = sum(1 for j in field_jobs if j.op == "WATER" and j.critical)
        plant_limit = max(0, n - n_surv // params.PLANT_WATER_CAP_DIVISOR)
    if params.OPENING_TAPE and state.day <= params.OPENING_HERD_UNTIL_DAY:
        # `opening.jobs` owns the tape's job list: field work + named-tile plant jobs +
        # herd + endgame, with the herd's daily loop re-prioritised. It was DEAD CODE
        # until now -- the scheduler rebuilt the same list without the herd bonus, so
        # BUILD/PICKUP/PLACE (60/60/95) lost the race to PLANT/WATER (85/90) and only
        # 1 of the 5 d0 animals got placed, against Boey's 5.
        jobs = opening.jobs(state)
    else:
        jobs = field_jobs + _plant_jobs(state, used, slices, n, limit=plant_limit)
        if params.HERD_ENABLED:
            jobs += herd_plan.jobs(state)
        jobs += endgame.jobs(state)
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
                if not _eligible(inv, j):
                    continue
                if j.priority < params.SAME_TILE_MIN_PRIORITY and not j.critical:
                    continue      # not worth chaining; leave it to the global assignment
                if i in rescuers and not j.critical:
                    continue      # this unit is the nearest to a tile about to die
                keys = (-j.priority,)
                if best_key is None or keys < best_key:
                    best_key, best = keys, (jidx, j)
            if best is not None:
                jidx, j = best
                assigned[jidx] = True
                preop[i] = j

    def _has_local(i):
        pos = state.positions[i]
        inv = state.unit_inv(i)
        for j in jobs:
            if j.tile == pos and _eligible(inv, j):
                return True
        return False

    order = list(range(n))
    if params.SAME_TILE_ORDER:
        # local-first: a unit standing on work chooses before a distant unit can claim it
        order.sort(key=lambda i: (0 if _has_local(i) else 1, i))
    # exact per-turn assignment: cheapest (unit, job) edge first, globally
    exact = {}
    if params.EXACT_ASSIGN:
        edges = []
        for i in range(n):
            pos, inv = state.positions[i], state.unit_inv(i)
            deliv = bool(inv) and _carrying_deliverable(inv)
            for jidx, j in enumerate(jobs):
                if j.tile is None:
                    continue
                if deliv and j.op not in _DELIVER_OPS:
                    continue
                if not _eligible(inv, j):
                    continue
                d = routing.manhattan(pos, j.tile)
                dcost = 0.0 if j.critical else params.MOVE_WEIGHT * min(d, params.DIST_CAP)
                pen = 0.0
                if (params.USE_SLICES and pref[i] is not None and j.op in _FIELD_OPS
                        and j.tile not in pref[i]):
                    pen = params.SLICE_PENALTY
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

    for i in order:
        pos = state.positions[i]
        inv = state.unit_inv(i)
        op = None
        if i in exact:
            jidx, j = exact[i]
            assigned[jidx] = True
            op = _move_or_act(state, pos, j, cost)
        if params.EXACT_ASSIGN and op is None:
            # not assigned a job this turn: use the same fallbacks as before
            if inv and (pos in params.SHED_ACCESS_SET
                        or state.day >= params.LIQUIDATE_DAY):
                op = _deposit_op(state, pos, cost)
            elif inv:
                op = _deposit_op(state, pos, cost)
            else:
                op = ["PASS"]
        if i in preop:
            ops.append(_move_or_act(state, pos, preop[i], cost))
            continue

        def _take(best):
            jidx, j, d = best
            assigned[jidx] = True
            if d > 0:
                claimed.add(j.tile)
            return _move_or_act(state, pos, j, cost)

        if inv:
            # 1. deliver a deliverable (feed/place/fertilize) if carrying one.
            if _carrying_deliverable(inv):
                best = _pick(jobs, assigned, pos, inv, only_delivery=True,
                             claimed=claimed, owner=occupied, me=i)
                if best is not None:
                    op = _take(best)
            # 2. deposit when shed-adjacent (free), or during the endgame so
            #    carried produce reaches the shed and is liquidated before the bell.
            #    DSM DROPs ~2/day (the engine auto-drops at day-end anyway), so
            #    walking back after every harvest is wasted movement.
            if op is None and (pos in params.SHED_ACCESS_SET
                               or state.day >= params.LIQUIDATE_DAY):
                op = _deposit_op(state, pos, cost)
            # 3. otherwise keep working while carrying.
            if op is None:
                best = _pick(jobs, assigned, pos, inv, only_delivery=False,
                             prefer=pref[i], claimed=claimed, owner=occupied, me=i)
                if best is not None:
                    op = _take(best)
            # 4. nothing to do -> deposit.
            if op is None:
                op = _deposit_op(state, pos, cost)
        else:
            best = _pick(jobs, assigned, pos, inv, only_delivery=False,
                         prefer=pref[i], claimed=claimed, owner=occupied, me=i)
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
    if params.OPENING_TAPE:
        # The tape owns the opening market list (sells + full seed basket in one ordered
        # block); the per-turn layers do not also jostle for the 10 slots.
        market = list(opening.market_intents(state))
        market += budget.market_intents(state)
    else:
        market = list(sell_policy.market_intents(state))
        if params.WINDOW_SEED_FIRST:
            market += _urgent_window_seeds(state)
        market += budget.market_intents(state)
        if params.HERD_ENABLED:
            market += herd_plan.market_intents(state)
        market += crop_plan.market_intents(state)
    market += crop_plan.fertilizer_buy_intent(state)
    market += endgame.market_intents(state)
    ops = [o if o is not None else ['PASS'] for o in ops]
    return emit.assemble(state, ops, market)
