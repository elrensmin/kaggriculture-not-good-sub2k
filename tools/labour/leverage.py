#!/usr/bin/env python
"""leverage — decide whether an idle hand can be safely re-routed.

While `tools/missed_work.py` enumerates undone work, this answers the counter-
question: for every step where a hand PASSes (idle), what is that hand ABOUT to do
next, and how much money is that work worth? We look ahead W steps for the SAME
hand index, walking its position, and value each upcoming action at CURRENT market
prices.

Provenance of the look-ahead: this used to read the production agent's route tape
(`main._IMPL.chassis.routes`), which does not exist for the from-scratch arm. It now
reads the **committed trajectory recorded in the replay itself**
(`steps[s][seat]["action"]`), which is strictly better for this purpose: it is what
the agent actually did, for every arm (old / new / scratch / DSM), and it needs no
chassis. The only thing it loses is the pre-commit *intent*; the only staleness is
the tile forecast, which still reads the current board.

This produces the decision: if the hand's near-term plan is HIGH-leverage (it's
about to harvest/collect/sell something worth a lot), rerouting it to water is
DESTRUCTIVE (you forfeit the high-margin sale). If its near-term plan is LOW-
leverage or another idle (nothing worth doing), rerouting to cover pending work is
FREE. We group idle-hand events by forfeit value so you can see which bucket is
large enough to matter.

Usage:
  PYTHONPATH=. python -m tools.labour.leverage --dir diag-replays/v0-us \
      --glob 'scratch_vs_*.json' [--horizon 8] [--seat 1]
"""
from __future__ import annotations

import argparse
import glob as globmod
from collections import Counter
from pathlib import Path

from tools import diagnose
from tools.diagnose.window import parse_days, in_window, describe

_WINDOW = None


def _in(day):
    return in_window(day, _WINDOW)


TEST_SEAT = 1
MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}
WATER_OP = "WATER"
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
# value of a WATER turn (keeps a crop alive; the sale comes later, discounted).
WATER_VALUE = 0.0


def _replay_route(steps, seat):
    """The seat's committed per-step action list, used as the look-ahead track.

    Shape matches the old tape: a list of action dicts indexed by step, each with
    ``farmer`` / ``hands`` keys.
    """
    return [st[seat].get("action") or {} if len(st) > seat else {} for st in steps]



def _action_value(op, tile, prices):
    """Leverage value of a hand action at this turn, at current market prices."""
    if not op:
        return 0.0
    if op in ("HARVEST", "COLLECT_FERTILIZER", "FEED", "CARE"):
        if not isinstance(tile, dict):
            return 1.0  # unknown; tiny floor so it's not zero.
        if "animal" in tile:
            prod = ANIMAL_PRODUCT.get(tile.get("animal"))
            if prod:
                return max(0.0, float(prices.get(prod, 0) or 0))
        if tile.get("kind") == "PLANT":
            return max(0.0, float(prices.get(tile.get("crop"), 0) or 0))
        return 1.0
    if op == WATER_OP:
        return WATER_VALUE
    # PASS / moves / build / plant / drop / pickup / place: setup or neutral.
    return 0.0


def _lookahead(route, routes, step, hi, px, py, obs, horizon, seat=TEST_SEAT):
    """Walk hand-index hi along the recorded track for `horizon` steps from (px,py).

    Returns list of (rel_step, op, value) for that hand, and the max value (forfeit).
    """
    out = []
    pos = [px, py]
    prices = (obs.get("market") or {}).get("prices") or {}
    farm = obs["farms"][seat]
    tiles = farm["tiles"]
    maxv = 0.0
    for k in range(1, horizon + 1):
        s = step + k
        if s >= len(routes[route]):
            break
        a = routes[route][s]
        cmds = [a.get("farmer") or ["PASS"]] + [c for c in a.get("hands") or []]
        if hi >= len(cmds):
            break
        c = cmds[hi]
        op = c[0] if c and isinstance(c, list) else "PASS"
        # forecast tile (current board, may be stale but fine for a leverage estimate)
        x, y = pos
        tile = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]) else None
        if op in MOVES:
            dx, dy = MOVES[op]
            pos = [max(0, min(9, x + dx)), max(0, min(9, y + dy))]
            out.append((k, op, 0.0))
        else:
            v = _action_value(op, tile, prices)
            if v > 0:
                # value is realized at the tile where it lands; use forecast tile.
                v = _action_value(op, tile, prices)
            maxv = max(maxv, v)
            out.append((k, op, v))
    return out, maxv


def analyze_game(path, horizon=8, seat=TEST_SEAT):
    rep = diagnose.load_replay(Path(path))
    steps = rep["steps"]
    route, routes = 0, [_replay_route(steps, seat)]
    events = []
    # PAIRING: steps[t]["action"] is the action that PRODUCED steps[t]["observation"],
    # so the action taken FROM steps[t]'s observation is at t+1 (verified: 97.1 % of
    # moves satisfy pos[t+1] == pos[t] + action[t+1], vs 53.3 % same-index).
    for i in range(max(0, len(steps) - 1)):
        if not _in(i // 24):  # window-guard
            continue
        si = steps[i]
        if len(si) <= seat or len(steps[i + 1]) <= seat:
            continue
        obs = si[seat].get("observation")
        act = steps[i + 1][seat].get("action")
        if not obs or not act:
            continue
        farm = obs["farms"][seat]
        positions = [tuple(farm["farmer"])] + [tuple(p) for p in farm["hands"]]
        units = [list(act.get("farmer") or ["PASS"])] + [list(c) for c in act.get("hands") or []]
        for hi, u in enumerate(units):
            if hi == 0 or hi >= len(positions):
                continue
            op = u[0] if u else "PASS"
            if op != "PASS":
                continue
            px, py = positions[hi]
            forecast, forfeit = _lookahead(route, routes, i, hi, px, py, obs, horizon, seat)
            events.append({
                "step": i, "day": i // 24, "hand": hi, "pos": (px, py),
                "forfeit": forfeit, "forecast": [o for (_, o, _) in forecast],
            })
    # bucket by forfeit (value of the highest-margin action the hand is about to do)
    buckets = {"HIGH_LEVERAGE(>=50)": 0, "MID(15-49)": 0, "LOW(<15)": 0}
    for e in events:
        f = e["forfeit"]
        if f >= 50:
            buckets["HIGH_LEVERAGE(>=50)"] += 1
        elif f >= 15:
            buckets["MID(15-49)"] += 1
        else:
            buckets["LOW(<15)"] += 1
    return {"path": str(path), "events": len(events), "buckets": buckets,
            "forfeit_hist": Counter(round(e["forfeit"]) for e in events),
            "events_sample": events[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--days", default=None, help="restrict analysis to day window, e.g. 0-5 or 0-5,12-17")
    ap.add_argument("--glob", default="*_vs_*.json")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--top-idle", type=int, default=15,
                    help="print this many highest-forfeit idle events as examples")
    ap.add_argument("--seat", type=int, default=TEST_SEAT,
                    help="seat of the agent under test (default 1, our arm)")
    args = ap.parse_args()
    global _WINDOW
    _WINDOW = parse_days(args.days)
    if _WINDOW:
        print("window:", describe(_WINDOW))

    paths = sorted(globmod.glob(str(Path(args.dir) / args.glob)))
    agg_buckets = Counter(); agg_events = 0; agg_forfeit = Counter()
    for p in paths:
        try:
            r = analyze_game(p, args.horizon, args.seat)
        except Exception as e:  # noqa: BLE001
            print("ERR", Path(p).name, e)
            continue
        agg_events += r["events"]
        agg_buckets.update(r["buckets"])
        agg_forfeit.update(r["forfeit_hist"])
        print(f"{Path(p).name}: idle-hand events={r['events']}  {dict(r['buckets'])}")
        # show a few highest-forfeit idle hands (the ones you'd NOT reroute)
        sample = sorted(r["events_sample"], key=lambda e: -e["forfeit"])[:2]
        for e in sample:
            print(f"    e.g. hand{e['hand']} day{e['day']} step{e['step']} @{e['pos']} "
                  f"forfeit={e['forfeit']:.0f} next={e['forecast'][:6]}")
    print(f"\n=== AGGREGATE over {len(paths)} games, horizon={args.horizon} ===")
    print(f"  idle-hand events total: {agg_events}")
    print(f"  buckets: {dict(agg_buckets)}")
    if agg_events:
        hi = agg_buckets["HIGH_LEVERAGE(>=50)"]
        share = 100 * hi / agg_events
        print(f"  -> {share:.0f}% of idle hands are about to do HIGH-leverage work "
              f"(rerouting them is destructive); {100-share:.0f}% are LOW/MID "
              f"(potentially free to reroute).")


if __name__ == "__main__":
    main()
