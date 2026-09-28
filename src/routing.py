"""Routing toolkit: Manhattan, Dijkstra, A*, nearest-tile, one-step moves.

The board is 10x10 = 100 cells, so flood fills are cheap and are preferred for
"nearest of a class"; A* is for a goal-directed route to one far tile under a
non-uniform cost. Callers pass a `cost(pos) -> float` model, never a bespoke path.
"""
from __future__ import annotations

import heapq

from . import params

N = params.BOARD
_ADJ = ((1, 0), (-1, 0), (0, 1), (0, -1))
_MOVE = {(1, 0): "EAST", (-1, 0): "WEST", (0, 1): "SOUTH", (0, -1): "NORTH"}


def in_bounds(p, n=N):
    return 0 <= p[0] < n and 0 <= p[1] < n


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def neighbors(p, n=N):
    for d in _ADJ:
        q = (p[0] + d[0], p[1] + d[1])
        if in_bounds(q, n):
            yield q, d


def dijkstra(origin, cost, n=N):
    """Full weighted flood: returns (dist: {pos: float}, prev: {pos: pos})."""
    dist = {origin: 0.0}
    prev = {}
    pq = [(0.0, origin)]
    while pq:
        d, p = heapq.heappop(pq)
        if d > dist.get(p, float("inf")):
            continue
        for q, _ in neighbors(p, n):
            nd = d + cost(q)
            if nd < dist.get(q, float("inf")):
                dist[q] = nd
                prev[q] = p
                heapq.heappush(pq, (nd, q))
    return dist, prev


def nearest(origin, match, cost, n=N):
    """Nearest cell satisfying match(pos) in cost order; returns (pos, dist)."""
    dist = {origin: 0.0}
    pq = [(0.0, origin)]
    while pq:
        d, p = heapq.heappop(pq)
        if d > dist.get(p, float("inf")):
            continue
        if match(p):
            return p, d
        for q, _ in neighbors(p, n):
            nd = d + cost(q)
            if nd < dist.get(q, float("inf")):
                dist[q] = nd
                heapq.heappush(pq, (nd, q))
    return None, float("inf")


def astar(start, goal, cost, n=N):
    """A* path from start to goal; returns list of positions [start .. goal] or None."""
    open_ = [(manhattan(start, goal), 0.0, start)]
    g = {start: 0.0}
    came = {}
    closed = set()
    while open_:
        _, gc, cur = heapq.heappop(open_)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        if cur in closed:
            continue
        closed.add(cur)
        for q, _ in neighbors(cur, n):
            ng = gc + cost(q)
            if ng < g.get(q, float("inf")):
                g[q] = ng
                came[q] = cur
                heapq.heappush(open_, (ng + manhattan(q, goal), ng, q))
    return None


def step_toward(pos, target, cost, n=N):
    """The one N/S/E/W op that moves `pos` toward `target` under the cost model.

    Returns the move string, or None when already standing on the target."""
    if pos == target:
        return None
    best = None
    best_key = None
    for q, d in neighbors(pos, n):
        key = (cost(q) + manhattan(q, target), manhattan(q, target))
        if best_key is None or key < best_key:
            best_key = key
            best = _MOVE[d]
    return best


def flood(origin, cost, n=N):
    """One Dijkstra from `origin`: exact path cost to EVERY tile, plus the back-pointers.

    The scheduler used to route with `step_toward`, a GREEDY one-step rule: it re-decides
    the direction every turn from the current cell, so a single blocked or LOCKED cell can
    make a unit oscillate (A->B->A) or detour, and the cost it optimised was not the cost
    of the path it would actually walk. A flood fill costs one Dijkstra per unit per turn
    on a 10x10 board and gives the true distance to every job AND the first step of the
    true shortest path -- so a hand walks the path a planner would have chosen.

    Returns (dist, prev, first) where `first[p]` is the first move FROM `origin` toward p.
    """
    dist, prev = dijkstra(origin, cost, n)
    first = {}
    for p in dist:
        cur = p
        while cur in prev and prev[cur] != origin:
            cur = prev[cur]
        if cur != origin:
            first[p] = cur
    return dist, prev, first


def step_of(origin, nxt):
    """The move op from `origin` to the adjacent cell `nxt`."""
    if nxt is None:
        return None
    return _MOVE.get((nxt[0] - origin[0], nxt[1] - origin[1]))


def default_cost(state):
    """Standard cost model: distance, penalising locked (unowned) tiles."""
    def cost(pos):
        if state.at(pos) == "LOCKED":
            return 1.0 + params.LOCKED_PENALTY
        return 1.0
    return cost


def nearest_shed_access(pos, cost, n=N):
    """Nearest shed-adjacent tile to `pos` (for deposit/pickup routing)."""
    return nearest(pos, lambda p: p in params.SHED_ACCESS_SET, cost, n)[0] \
        or min(params.SHED_ACCESS, key=lambda s: manhattan(pos, s))
