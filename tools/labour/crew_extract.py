#!/usr/bin/env python
"""crew_extract — cache the per-unit-turn *work stream* of any agent's replays.

Why this exists
---------------
Every op in Kaggriculture is performed on the tile the unit **stands on**: the
engine action is ``["WATER"]`` / ``["HARVEST"]`` with no coordinates (the target
comes from the policy's own Job, which the replay does not record). So the only
honest, replay-visible measure of "did the crew allocate well?" is the
**transition between consecutive work tiles of the same unit**:

    for unit u with work tiles  p0, p1, p2, ...   (in turn order)
        chain_dist[k] = manhattan(p_k, p_{k+1})
        walk_turns[k] = turn_{k+1} - turn_k - 1      (turns spent moving)

A scheduler that picks the nearest eligible job produces ``chain_dist`` ~1; one
that lets priority override distance produces 2-3. This is exactly what
``scheduler._pick`` is supposed to optimise, and it is *format independent* — it
needs no target coordinate, no market audit, and it works identically on the #1's
leaderboard replays and on our own runs, so the two are directly comparable.

The cache also records what was on the tile when the op fired (crop / animal,
age, whether it had already been watered, standing yield), which is where the
*plant management* half of the pattern breakdown comes from.

Usage
-----
  # the #1's 123 leaderboard episodes -> one compact JSON per game
  PYTHONPATH=. python -m tools.labour.crew_extract --dir replays/DSM/v1 \
      --out diag-replays/crew-dsm

  # our own runs (any --pa/--batch/--seed the harness takes)
  PYTHONPATH=. python -m tools.labour.crew_extract --agent --pa 1-12 --batch 4 \
      --out diag-replays/crew-us

Then read them with ``tools/report/crew_patterns.py``.
"""
from __future__ import annotations

try:
    from tools import team as team_mod
except ImportError:  # bare-script execution: add the repo root to sys.path
    import pathlib as _pl
    import sys as _sys
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))
    from tools import team as team_mod

import argparse
import glob
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

TURNS_PER_DAY = 24

# op tokens the unit can perform on its own tile
TILE_OPS = (
    "PLANT", "WATER", "HARVEST", "DIG", "FERTILIZE", "FEED", "CARE",
    "COLLECT_FERTILIZER", "PLACE", "BUILD_COOP", "BUILD_PASTURE",
)
MOVE_OPS = ("NORTH", "SOUTH", "EAST", "WEST")
SHED_OPS = ("DROP", "PICKUP")

# compact integer codes so the cache stays small
OPC = {op: i for i, op in enumerate(
    TILE_OPS + MOVE_OPS + SHED_OPS + ("PASS",))}
OPN = {v: k for k, v in OPC.items()}


def _dsm_seats(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    return team_mod.seats_of_names(names) or [0]


# The shed is NOT a board tile — it is the fixed central 2x2 access set. Verified
# empirically: 100% of DROP/PICKUP ops in the #1's replays happen on exactly these
# four tiles. NOTE the #1 builds PASTURES *on* them and still drops there, so the
# herd literally occupies the shed ring; a "distance from shed" metric must use
# the min over the access set, not a single centre cell.
SHED_ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))


def shed_dist(x, y):
    return min(abs(x - sx) + abs(y - sy) for sx, sy in SHED_ACCESS)


def _shed_pos(tiles):
    return [4, 4]


def unit_records(steps, seat):
    """Extract the per-unit-turn work stream.

    Returns (records, turns). ``records`` is a list of
    ``[turn, unit, opcode, x, y, crop_id, age, watered, yield, kind_id]`` and
    ``turns`` is ``{turn: [money, n_hands, shed_total]}``.

    Pairing: the action at ``steps[t+1]`` was decided from ``steps[t]``'s
    observation (kaggle_environments records the action that *produced* a frame),
    so the unit positions are read from frame ``t`` and the ops from ``t+1``.
    """
    records = []
    turns = {}
    n = len(steps)
    for t in range(n - 1):
        if len(steps[t]) <= seat or len(steps[t + 1]) <= seat:
            continue
        o = steps[t][seat].get("observation")
        a = steps[t + 1][seat].get("action")
        if not o or not a:
            continue
        farm = o["farms"][seat]
        tiles = farm["tiles"]
        priv = o.get("private") or {}
        shed = priv.get("shed") or {}
        turns[t] = [farm.get("money", 0), len(farm.get("hands") or []),
                    sum(v for v in shed.values() if v > 0)]
        pos = [tuple(farm.get("farmer") or (0, 0))]
        pos += [tuple(p) for p in (farm.get("hands") or [])]
        cmds = [a.get("farmer")] + list(a.get("hands") or [])
        for u, c in enumerate(cmds):
            if not c or u >= len(pos):
                continue
            op = c[0]
            code = OPC.get(op)
            if code is None:
                continue
            x, y = pos[u]
            crop, age, wat, yld, kind = "", -1, -1, -1, ""
            if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
                cell = tiles[y][x]
                if isinstance(cell, dict):
                    kind = str(cell.get("kind") or "")
                    crop = str(cell.get("crop") or cell.get("animal") or "")
                    wy = cell.get("watered_today")
                    wat = -1 if wy is None else int(bool(wy))
                    yv = cell.get("yield_units")
                    yld = -1 if yv is None else int(yv)
                    pd = cell.get("planted_day")
                    if pd is not None:
                        age = t // TURNS_PER_DAY - int(pd)
                    else:
                        av = cell.get("age")
                        age = -1 if av is None else int(av)
            records.append([t, u, code, x, y, crop, age, wat, yld, kind])
    return records, turns


def analyse_replay(path, seat=None):
    rep = json.load(open(path))
    steps = rep["steps"]
    if seat is None:
        seat = _dsm_seats(rep)[0]
    info = rep.get("info") or {}
    names = info.get("TeamNames") or ["?", "?"]
    recs, turns = unit_records(steps, seat)
    tiles = steps[0][seat]["observation"]["farms"][seat]["tiles"] if steps else []
    return {
        "episode": info.get("EpisodeId") or os.path.basename(path),
        "file": os.path.basename(path),
        "seat": seat,
        "team": names[seat] if seat < len(names) else "?",
        "opp": names[1 - seat] if 1 - seat < len(names) else "?",
        "shed": list(_shed_pos(tiles) or (0, 0)),
        "records": recs,
        "turns": {str(k): v for k, v in turns.items()},
    }


def _work(path, seat):
    try:
        return analyse_replay(path, seat)
    except Exception as e:                                  # pragma: no cover
        return {"file": os.path.basename(path), "error": repr(e), "records": [],
                "turns": {}}


def _run_agent_games(out, pa, batch, seed, workers, max_games):
    """Run our own agent and dump the same cache shape."""
    import sys
    sys.path.insert(0, ".")
    from tools.diagnose.agents import load_public_agent
    from tools.diagnose.games import run_game
    from tools.labour.crew_extract import unit_records

    def fresh():
        for m in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
            del sys.modules[m]
        import src
        return src.agent

    os.makedirs(out, exist_ok=True)
    n = 0
    for opp in pa:
        for b in range(batch):
            if max_games and n >= max_games:
                return n
            s = (seed + b * 7919) if seed is not None else None
            env = run_game(fresh(), load_public_agent(opp), seed=s, seat=1,
                           audit=False)
            steps = env.steps if hasattr(env, "steps") else env["steps"]
            recs, turns = unit_records(steps, 1)
            name = f"us_vs{opp}_s{s}.json"
            json.dump({"episode": name, "file": name, "seat": 1, "team": "US",
                       "opp": f"pa{opp}", "shed": [0, 0],
                       "records": recs,
                       "turns": {str(k): v for k, v in turns.items()}},
                      open(os.path.join(out, name), "w"))
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="replays/DSM/v1")
    ap.add_argument("--out", default="diag-replays/crew-dsm")
    ap.add_argument("--seat", type=int, default=None)
    ap.add_argument("--max", type=int, default=0, help="cap games (0 = all)")
    ap.add_argument("--workers", type=int, default=0, help="0 = all cores")
    ap.add_argument("--agent", action="store_true",
                    help="run OUR agent instead of reading replays")
    ap.add_argument("--pa", default="1-12")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=4362837462)
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    a = ap.parse_args()
    team_mod.set_team(a.team)

    if a.agent:
        from tools.diagnose.window import parse_days  # noqa: F401  (import check)
        pa = []
        for part in str(a.pa).split(","):
            if "-" in part:
                lo, hi = part.split("-")
                pa += list(range(int(lo), int(hi) + 1))
            else:
                pa.append(int(part))
        n = _run_agent_games(a.out, pa, a.batch, a.seed, a.workers, a.max)
        print(f"wrote {n} games -> {a.out}")
        return

    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))
    if a.max:
        files = files[:a.max]
    os.makedirs(a.out, exist_ok=True)
    print(f"{len(files)} replays -> {a.out}")
    w = a.workers or None
    done = 0
    with ProcessPoolExecutor(max_workers=w) as ex:
        for res, path in zip(ex.map(_work, files, [a.seat] * len(files)), files):
            base = os.path.splitext(os.path.basename(path))[0]
            json.dump(res, open(os.path.join(a.out, base + ".json"), "w"))
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{len(files)}")
    print(f"done: {done}")


if __name__ == "__main__":
    main()
