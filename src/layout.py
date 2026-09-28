"""Structural board plan + per-worker slice partition.

Workers spend ~66% of turns walking when they chase the nearest job across the
whole board. ``slice_partition`` assigns each worker a contiguous quadrant region
(round-robined among the workers sharing that quadrant), so a worker's jobs stay
within ~25 tiles instead of 100 — actions are the scarce resource, not tiles.
"""
from __future__ import annotations

from . import params


def _quadrant(x: int, y: int) -> str:
    return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def slice_partition(state, n_units: int):
    """Per-worker slices: contiguous blocks of the shed-outward tile order.

    Each worker owns one contiguous shed-outward band (~8 tiles), so its jobs stay
    clustered near the shed and it stops chasing work across the whole 100-tile
    board. This is the layout-aligned version (shed rings, not quadrants).
    """
    def shed_dist(p):
        return min(abs(p[0] - s[0]) + abs(p[1] - s[1]) for s in params.SHED_ACCESS)

    owned = [
        (x, y)
        for y in range(params.BOARD)
        for x in range(params.BOARD)
        if state.owned((x, y))
    ]
    # NOTE (DSM layout, measured): DSM puts animals in the inner ring (mean
    # shed-distance 1.78) and crops on the boundary (4.50), because animals need
    # ~3 visits/day. We reserve the STRUCTURE_HOLDBACK nearest-to-shed owned tiles
    # so herd_plan has somewhere to build -- it builds shed-outward, so it claims
    # exactly these. A count, not a radius: the geometric ANIMAL_ZONE reserved 40
    # of 100 tiles and left almost nothing for crops in a 25-tile opening quadrant.
    holdback = int(params.at("STRUCTURE_HOLDBACK", state.day))
    held = []
    if holdback > 0:
        held = sorted(owned, key=shed_dist)[:holdback]
        set_held = set(held)
        owned = [p for p in owned if p not in set_held]
    # snake (boustrophedon) order: contiguous chunks are compact horizontal strips,
    # so walking inside a worker's band is short and the crops stay grouped.
    # `LAYOUT_RADIAL` orders the same contiguous chunks by SHED DISTANCE instead of by row,
    # so a band is a piece of one ring around the shed and every worker's ground is at a
    # comparable distance from the shed it must visit for wheat/fertilizer/drops.
    # LAYOUT_BY_CROP_AGE -- order the per-worker bands so a band's crops share a water
    # calendar. MEASURED (d6-17, 8 games): a band of 5.13 tiles carries **2-3 distinct crop
    # ages** and only **2.35 tiles need water on a given day**, which is why consecutive
    # waters are 1.67 tiles apart against Boey's 1.07 and WATER is 47.9 % of all our moves.
    # `PLANT_BLOCK` cannot fix it: the midgame farm is already saturated, so a band can only
    # be re-shaped one freed tile at a time. This re-shapes the BANDS instead, grouping by
    # (crop, planted_day) so the day's thirsty tiles share an owner.
    if params.at("LAYOUT_BY_CROP_AGE", state.day):
        def _key(p):
            t = state.plant_at(p)
            if not t:
                return (1, "", 0, p[1], p[0])
            return (0, t.get("crop", ""), t.get("planted_day", 0), p[1], p[0])
        owned.sort(key=_key)
    elif params.at("LAYOUT_RADIAL", state.day):
        import math as _math
        def _angle(p):
            return _math.atan2(p[1] - 4.5, p[0] - 4.5)
        owned.sort(key=lambda p: (shed_dist(p), _angle(p)))
    else:
        owned.sort(key=lambda p: (p[1], p[0] if p[1] % 2 == 0 else -p[0]))
    if not owned:
        return [[] for _ in range(n_units)]

    # `LAYOUT_EVEN_BANDS` -- the `ceil(len/n)` chunking leaves the LAST workers with an empty
    # band whenever the tile count is not a multiple of the crew (63 tiles, 12 hands -> ten
    # bands of 6, one of 3, one of 0), so that worker has no local work on any turn and is a
    # pure rover. Fixing it is the obvious thing and it is MEASURED WORSE: d6-17,
    # plants died 10.0 -> 17.5, trade net 35,684 -> 34,434 at 16.5 animals. An empty band is
    # apparently how the farm keeps two units available as a farm-wide reserve. OFF.
    slices = [[] for _ in range(n_units)]
    if params.at("LAYOUT_EVEN_BANDS", state.day):
        base, extra = divmod(len(owned), n_units)
        idx = 0
        for i in range(n_units):
            k = base + (1 if i < extra else 0)
            slices[i] = owned[idx:idx + k]
            idx += k
    else:
        chunk = max(1, (len(owned) + n_units - 1) // n_units)
        for i in range(n_units):
            slices[i] = owned[i * chunk:(i + 1) * chunk]
    if params.at("BAND_ANIMALS", state.day) and held:
        # BAND THE ANIMAL RING TOO. `_pick`'s band preference only covers `_FIELD_OPS`
        # (PLANT/WATER/HARVEST/DIG/FERTILIZE), because the animal tiles sit in the
        # holdback ring and in no crop band -- so FEED/CARE/COLLECT are ALWAYS resolved by
        # the global pass and a unit will cross the farm for them. MEASURED
        # (tools/labour/walk_runs.py, d6-17, 4 games): FEED 241 + CARE 241 + COLLECT 424
        # = 906 of 3,073 walks start at an animal op, and our mean walk is 2.39 tiles
        # against Boey's 1.95. Give each worker the holdback tiles nearest its own band and
        # the animal visit becomes local work like any other.
        for p in sorted(held, key=lambda q: (q[1], q[0])):
            best, bd = 0, None
            for i, band in enumerate(slices):
                if not band:
                    continue
                d = min(abs(p[0] - t[0]) + abs(p[1] - t[1]) for t in band)
                if bd is None or d < bd:
                    bd, best = d, i
            slices[best].append(p)
    return slices
