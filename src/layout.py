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
    if params.STRUCTURE_HOLDBACK > 0:
        held = set(sorted(owned, key=shed_dist)[:params.STRUCTURE_HOLDBACK])
        owned = [p for p in owned if p not in held]
    # snake (boustrophedon) order: contiguous chunks are compact horizontal strips,
    # so walking inside a worker's band is short and the crops stay grouped.
    owned.sort(key=lambda p: (p[1], p[0] if p[1] % 2 == 0 else -p[0]))
    if not owned:
        return [[] for _ in range(n_units)]

    slices = [[] for _ in range(n_units)]
    chunk = max(1, (len(owned) + n_units - 1) // n_units)
    for i in range(n_units):
        slices[i] = owned[i * chunk:(i + 1) * chunk]
    return slices
