#!/usr/bin/env python
"""idle_pool — classify every idle turn by how it could be recovered.

For every work-unit PASS turn, decide whether it is recoverable WITHOUT moving
(an act is legal right where the hand stands) vs needs movement vs is genuinely
not-recoverable. This sizes the pool you can soak up with idle hands at (near)
zero revenue risk, which is the lever for idle_share_pct.

Per-tile legal acts (no movement):
  WATER   - plant crop in-window and not yet watered today: any hand can do it.
  CARE    - animal not cared today: any hand can do it (no resource needed).
  HARVEST - plant ready/mature, or animal with yield>0: needs shed room.
  FEED    - animal unfed today: needs the hand to be carrying wheat (conditional).

Everything else is either movement-needed (pending work at another tile — the
revenue-negative path) or truly idle (no pending work anywhere it can help).

Usage:
  PYTHONPATH=src:. python -m tools.labour.idle_pool --dir diag-replays/run-5 --glob 'old_vs_*.json'
"""
from __future__ import annotations

import argparse
import glob as globmod
from collections import Counter
from pathlib import Path

import diagnose

TEST_SEAT = 1
CROP_MAXDAY = {"WHEAT": 4, "CARROT": 3, "TOMATO": 99, "STRAWBERRY": 99, "MELON": 12}
SHED_CAP = 100


def _per_tile_act(t, day, shed_room, has_wheat):
    """Return ('KIND', reason) if a no-move act is legal on this tile, else None."""
    if not isinstance(t, dict):
        return None
    k = t.get("kind")
    if k == "PLANT":
        crop = t.get("crop")
        age = day - int(t.get("planted_day", 0))
        if crop not in CROP_MAXDAY:
            return None
        if not t.get("watered_today") and 0 <= age < CROP_MAXDAY[crop]:
            return ("WATER", "unwatered in-window crop")
        yld = int(t.get("yield_units", 0))
        if yld > 0 and (crop in ("TOMATO", "STRAWBERRY") or age >= CROP_MAXDAY[crop]):
            return ("HARVEST", "ready plant produce")
        return None
    if "animal" in t:
        if not t.get("fed_today"):
            if has_wheat:
                return ("FEED", "animal needs feed, hand has wheat")
            return ("FEED_COND", "animal needs feed, hand wheat unknown/absent")
        if not t.get("cared_today"):
            return ("CARE", "animal needs care")
        if int(t.get("yield_units", 0)) > 0 and shed_room > 0:
            return ("HARVEST", "animal ready produce, shed room")
        return None
    return None


def _has_any_pending(farm, day, shed_room):
    """Whether ANY pending work exists on the board (for movement-needed test)."""
    for y in range(len(farm["tiles"])):
        for x in range(len(farm["tiles"][y])):
            if _per_tile_act(farm["tiles"][y][x], day, shed_room, True):
                return True
    return False


def analyze_game(path):
    rep = diagnose.load_replay(Path(path))
    steps = rep["steps"]
    cls = Counter()
    for i in range(len(steps)):
        si = steps[i]
        if len(si) <= TEST_SEAT:
            continue
        obs = si[TEST_SEAT].get("observation")
        act = si[TEST_SEAT].get("action")
        if not obs or not act:
            continue
        day = i // 24
        farm = obs["farms"][TEST_SEAT]
        priv = obs.get("private") or {}
        shed_room = SHED_CAP - sum(int(v) for v in (priv.get("shed") or {}).values())
        positions = [tuple(farm["farmer"])] + [tuple(p) for p in farm["hands"]]
        units = [list(act.get("farmer") or ["PASS"])] + [list(c) for c in act.get("hands") or []]
        tiles = farm["tiles"]
        for hi, u in enumerate(units):
            if u and u[0] != "PASS":
                continue
            if hi >= len(positions):
                continue
            px, py = positions[hi]
            if not (0 <= py < len(tiles) and 0 <= px < len(tiles[0])):
                cls["out_of_board_idle"] += 1
                continue
            t = tiles[py][px]
            r = _per_tile_act(t, day, shed_room, has_wheat=(hi == 0))  # farmer carries wheat; hands unknown
            if r:
                cls["per_tile_" + r[0]] += 1
            elif _has_any_pending(farm, day, shed_room):
                cls["movement_needed"] += 1
            else:
                cls["truly_idle_no_work"] += 1
    return {"path": str(path), "cls": cls, "idle_total": sum(cls.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--glob", default="old_vs_*.json")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    paths = sorted(globmod.glob(str(Path(args.dir) / args.glob)))
    agg = Counter()
    n = 0
    for p in paths:
        try:
            r = analyze_game(p)
        except Exception as e:  # noqa: BLE001
            print("ERR", Path(p).name, e)
            continue
        n += 1
        agg.update(r["cls"])
        if not args.summary_only:
            per = r["cls"]
            print(f"{Path(p).name}: idle={r['idle_total']}  per-tile WATER={per['per_tile_WATER']} "
                  f"CARE={per['per_tile_CARE']} FEED={per['per_tile_FEED']} "
                  f"HARVEST={per['per_tile_HARVEST']}  move-needed={per['movement_needed']}")
    print(f"\n=== AGGREGATE over {n} games ===")
    for k, v in agg.most_common():
        print(f"  {k}: {v}  ({v/n:.0f}/game)")


if __name__ == "__main__":
    main()
