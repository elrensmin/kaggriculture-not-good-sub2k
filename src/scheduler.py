"""Job generation, greedy assignment, routing. The execution layer.

Each turn: gather field jobs (harvest/water/plant/dig/feed/care/collect/place/...)
from the policy layers, greedily assign each worker the nearest eligible job, route
it one cell, and compile the market orders. Eligibility depends on what a worker is
carrying (FEED needs WHEAT, PLACE needs an animal, FERTILIZE needs FERTILIZER), so
a carrying worker prefers its delivery job and otherwise deposits at the shed.
``action(t) = f(state(t))`` only — no cross-turn positional memory.
"""
from __future__ import annotations

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS

from . import budget, crop_plan, emit, endgame, herd_plan, layout, routing, sell_policy
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


def _plant_jobs(state, used, slices, n):
    """One PLANT job per worker, on its OWN band (aligned: crops live where the
    worker works). Worker i plants crop ``plant_queue[i % len]`` so the mix is
    balanced across workers."""
    crops = crop_plan.plant_queue(state)
    if not crops:
        return []
    jobs = []
    for i in range(n):
        crop = crops[i % len(crops)]
        tile = _nearest_empty_in_slice(state, used, slices[i])
        if tile is None:
            continue
        used.add(tile)
        jobs.append(Job(P_PLANT, tile, "PLANT", crop))
    return jobs


_FIELD_OPS = ("PLANT", "WATER", "HARVEST", "DIG", "FERTILIZE")


def _pick(jobs, assigned, pos, inv, only_delivery, prefer=None, claimed=None):
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
            # Distance prices the tile cluster but is capped so local busywork can
            # never starve a far high-value job; a job that stops an irreversible
            # loss (tonight's weed/escape) pays no walk cost at all.
            if j.critical:
                dcost = 0.0
            else:
                dcost = params.MOVE_WEIGHT * min(d, params.DIST_CAP)
            key = (dcost - j.priority, d, -j.priority)
            if best_key is None or key < best_key:
                best_key, best = key, (jidx, j, d)
        if best is not None:
            return best
    return None


def plan(state):
    cost = routing.default_cost(state)
    n = state.unit_count()
    used = set()
    slices = layout.slice_partition(state, n)
    slice_sets = [set(s) for s in slices]

    jobs = crop_plan.jobs(state) + _plant_jobs(state, used, slices, n)
    if params.HERD_ENABLED:
        jobs += herd_plan.jobs(state)
    jobs += endgame.jobs(state)
    jobs.sort(key=lambda j: -j.priority)
    assigned = [False] * len(jobs)
    claimed = set()  # tiles another unit is already walking to this turn
    ops = []

    for i in range(n):
        pos = state.positions[i]
        inv = state.unit_inv(i)
        op = None

        def _take(best):
            jidx, j, d = best
            assigned[jidx] = True
            if d > 0:
                claimed.add(j.tile)
            return _move_or_act(state, pos, j, cost)

        if inv:
            # 1. deliver a deliverable (feed/place/fertilize) if carrying one.
            if _carrying_deliverable(inv):
                best = _pick(jobs, assigned, pos, inv, only_delivery=True, claimed=claimed)
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
                             prefer=slice_sets[i], claimed=claimed)
                if best is not None:
                    op = _take(best)
            # 4. nothing to do -> deposit.
            if op is None:
                op = _deposit_op(state, pos, cost)
        else:
            best = _pick(jobs, assigned, pos, inv, only_delivery=False,
                         prefer=slice_sets[i], claimed=claimed)
            if best is not None:
                op = _take(best)
            else:
                op = ["PASS"]

        ops.append(op)

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
    market = list(sell_policy.market_intents(state))
    market += budget.market_intents(state)
    if params.HERD_ENABLED:
        market += herd_plan.market_intents(state)
    market += crop_plan.market_intents(state)
    market += endgame.market_intents(state)
    return emit.assemble(state, ops, market)
