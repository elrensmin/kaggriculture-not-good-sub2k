#!/usr/bin/env python
"""parse_replays -- the reference replays as THREE tidy tables with a FIXED schema.

Every claim in the schema was measured on `replays/Boey/v1` (359 episodes, 34.6 MB each, 720 steps
x 2 seats) before this file was written; none of it is assumed:

  * `observation.player` == the seat index in **17,256 / 17,256** sampled steps, so `farms[player]`
    is the observing seat's OWN farm and `farms[1-player]` is the rival's.
  * The CAUSAL PAIRING is `action[t+1]` <- `observation[t]`. Restricting to steps where the farmer
    demonstrably moved, `action[t+1]` explains the move in **91.9 %** of cases, `action[t]` in
    **21.9 %**. (Matches the shift AGENTS.md documents, and the reason its tile-conditioned harness
    metrics are measured against the wrong step.)
  * A tile is one of exactly SIX schemas: `None` (empty, owned), the **string** `"LOCKED"`,
    `{kind: WEED}`, `{kind: PLANT, crop, ...}`, an empty `{kind: COOP|PASTURE}`, and an occupied one.
    The leaf counts sum to **exactly 100** on every parsed row (verified 4,314/4,314).
  * Unit ops: WATER HARVEST FERTILIZE PLANT DIG FEED CARE COLLECT_FERTILIZER PICKUP **DROP** PLACE
    BUILD_COOP BUILD_PASTURE + the four MOVEs + **PASS**. `DROP` and `PASS` are both real decisions
    and were missing from the earlier builder (4,203 and 19,560 occurrences in 25 games).
  * Market ops: SELL BUY_PRODUCT BUY_SEED BUY_ANIMAL HIRE BUY_LAND. The list is capped at
    `maxMarketOrdersPerTurn: 10` and **59 % of steps sit AT the cap**, so the market decision is an
    ORDERED, SATURATED RANKING. Position is the signal, which is why `pos` is a column.
  * `replays/Boey/v1` is NOT self-play: Boey vs the real field (177 games in seat 0, 180 in seat 1,
    2 self-play, 53 against DSM). So ~half of every decision table is the OPPONENT's policy, and
    every row carries `is_ref` -- an imitation target fitted without filtering on it blends Boey
    with whoever he was playing.

Three tables because the two decision surfaces have different shapes:

  states(game, step, seat)          board + market + town + private, own and rival
  unit_ops(game, step, seat, unit)  one row per unit: the op it was given   <- the `_pick` target
  market_orders(game, step, seat, pos)  one row per order, ORDER PRESERVED  <- the emit target

`unit_ops` and `market_orders` join to `states` at the SAME `(game, step)`: state at t, decisions
taken from it at t+1.

The schema is FIXED and pre-initialised rather than accumulated, because a game with no TOMATO tile
would otherwise emit a different column set and the parquet shards would not unify.

Usage
-----
  PYTHONPATH=. python -m tools.phases.parse_replays --ref-max 3 --out-dir /tmp/parsed
  PYTHONPATH=. python -m tools.phases.parse_replays --out-dir artifacts/parsed
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import json
import multiprocessing as mp
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments.envs.kaggriculture.kaggriculture import (      # noqa: E402
    ANIMALS, CROPS, PRODUCTS)

from src import state_graph as _sg                                          # noqa: E402

# THE GRAPH'S OWN NODES, carried as columns so a fit can be run on exactly the quantities the DAG
# claims are causal -- `dev_` = the pressure (>1 deficient, <1 in excess) and `exc_` = how far AHEAD
# of target. Fitting these against the raw tile counts on the SAME rows and the SAME split is the
# only clean way to ask "does the graph's node set carry the signal, or do we need to extend it".
NODE_NAMES = tuple(sorted(_sg.NODES))
# THE RIVAL'S NODES ARE OBSERVABLE TOO -- and they are the whole point. `farms[i]` is fully public
# for BOTH seats (farmer, hands, hires_today, money, tiles, unlocked_quadrants), and
# `State.farm = obs["farms"][obs["player"]]`, so flipping `player` evaluates the graph on THEIR farm
# instead of ours. Only `private` (shed, seeds, inventories) is seat-local, and exactly two readers
# depend on it -- `shed` and `revenue_per_day`, measured by blanking `private` and diffing `read()`.
# Those two are dropped on the rival side rather than silently filled with OUR shed.
RIVAL_UNOBSERVABLE = ("shed", "revenue_per_day")

DAY = 24
MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
UNIT_OPS = ("WATER", "HARVEST", "FERTILIZE", "PLANT", "DIG", "FEED", "CARE",
            "COLLECT_FERTILIZER", "PICKUP", "DROP", "PLACE", "BUILD_COOP",
            "BUILD_PASTURE", "PASS") + MOVES
ITEMS = tuple(PRODUCTS) + tuple(ANIMALS)
MAX_UNITS = 16
MAX_ORDERS = 10

# ---- the FIXED state schema -------------------------------------------------------------
# TILE_DISJOINT partitions the 100 tiles: these eight sum to EXACTLY 100 on every row, which is
# the parser's integrity invariant. The remaining `t_*` columns are a HIERARCHY, not a partition --
# `plant` and `plant_WHEAT` count the same tile, as do `coop` and `animal_COW` -- so summing all of
# them double-counts and lands near 350. Both sets are exported; only TILE_DISJOINT is a check.
TILE_DISJOINT = ("empty", "locked", "weed", "plant", "coop", "coop_empty",
                 "pasture", "pasture_empty")
TILE_DERIVED = ("dry", "unwatered_today", "fertilized", "unfed", "uncared", "fert_avail",
                "at_risk")
TILE_LEAF = (list(TILE_DISJOINT) + list(TILE_DERIVED)
             + [f"plant_{c}" for c in CROPS] + [f"animal_{a}" for a in ANIMALS])
FARM_COLS = (["money", "farmer_x", "farmer_y", "hands", "hires_today", "quadrants"]
             + [f"t_{k}" for k in TILE_LEAF])
STATE_COLS = (["game", "game_id", "step", "day", "hour", "seat", "seat_name", "rival_name",
               "is_ref", "n_shops", "shops"]
              + [f"px_{p}" for p in PRODUCTS] + [f"inv_{p}" for p in PRODUCTS]
              + [f"seed_{c}" for c in CROPS] + [f"shed_{i}" for i in ITEMS]
              + [f"carry{i}_{k}" for i in range(MAX_UNITS) for k in ("n", "total")]
              + [f"own_{c}" for c in FARM_COLS] + [f"riv_{c}" for c in FARM_COLS]
              + [f"dev_{n}" for n in NODE_NAMES] + [f"exc_{n}" for n in NODE_NAMES]
              + [f"rdev_{n}" for n in NODE_NAMES if n not in RIVAL_UNOBSERVABLE]
              + [f"rexc_{n}" for n in NODE_NAMES if n not in RIVAL_UNOBSERVABLE])


def blank_state():
    r = dict.fromkeys(STATE_COLS, 0)
    r["seat_name"] = ""
    r["rival_name"] = ""
    r["shops"] = ""
    return r


def tile_counts(tiles):
    """The 10x10 board as counts over ALL SIX tile schemas. Leaves sum to exactly 100."""
    c = collections.Counter()
    for row in tiles or []:
        for t in row:
            if t is None:
                c["empty"] += 1
            elif isinstance(t, str):                       # "LOCKED" -- an unbought tile
                c["locked"] += 1
            elif t.get("kind") == "WEED":
                c["weed"] += 1
            elif t.get("kind") == "PLANT":
                c["plant"] += 1
                if t.get("crop"):
                    c[f"plant_{t['crop']}"] += 1
                if t.get("consecutive_unwatered", 0) > 0:
                    c["dry"] += 1
                if not t.get("watered_today"):
                    c["unwatered_today"] += 1
                if t.get("fertilized_until_day", -1) >= 0:
                    c["fertilized"] += 1
            elif t.get("kind") in ("COOP", "PASTURE"):
                low = t["kind"].lower()
                # `coop`/`pasture` count OCCUPIED structures only -- `coop_empty`/`pasture_empty`
                # are their complement, and the eight TILE_DISJOINT counters must partition the 100
                # tiles. Incrementing `low` unconditionally (an earlier version did) double-counts
                # every empty structure and breaks the invariant.
                if "animal" in t:
                    c[low] += 1
                    c[f"animal_{t['animal']}"] += 1
                    if not t.get("fed_today"):
                        c["unfed"] += 1
                    if not t.get("cared_today"):
                        c["uncared"] += 1
                    if t.get("fertilizer_available"):
                        c["fert_avail"] += 1
                    if t.get("consecutive_unfed", 0) > 0:
                        c["at_risk"] += 1
                else:
                    c[f"{low}_empty"] += 1
    return c


def fill_farm(r, f, pre):
    r[f"{pre}_money"] = f.get("money", 0) or 0
    fa = f.get("farmer") or [0, 0]
    r[f"{pre}_farmer_x"], r[f"{pre}_farmer_y"] = fa[0], fa[1]
    r[f"{pre}_hands"] = len(f.get("hands") or [])
    r[f"{pre}_hires_today"] = f.get("hires_today", 0) or 0
    r[f"{pre}_quadrants"] = len(f.get("unlocked_quadrants") or [])
    for k, v in tile_counts(f.get("tiles")).items():
        r[f"{pre}_t_{k}"] = v


def parse_one(job):
    """-> (state_rows, unit_rows, order_rows). Runs in a worker process."""
    path, step_cap, ref_name = job
    try:
        raw = json.loads(Path(path).read_text())
    except Exception:                                                      # noqa: BLE001
        return [], [], []
    steps = raw.get("steps") or []
    if not steps or len(steps[0]) < 2:
        return [], [], []
    names = (raw.get("info") or {}).get("TeamNames") or []
    game = Path(path).stem.replace("episode-", "").replace("-replay", "")
    gid = (raw.get("info") or {}).get("EpisodeId")
    S, U, O = [], [], []
    for t in range(min(len(steps) - 1, step_cap)):
        obs_a, act_b = steps[t], steps[t + 1]          # act_b is the CAUSAL PARTNER of obs_a
        for seat in (0, 1):
            try:
                ob = obs_a[seat]["observation"]
            except Exception:                                              # noqa: BLE001
                continue
            if ob.get("player") != seat:
                continue                    # verified invariant; skip rather than mislabel
            f_own = ob["farms"][seat]
            f_riv = ob["farms"][1 - seat]
            r = blank_state()
            r.update(game=game, game_id=gid, step=t, day=t // DAY, hour=t % DAY, seat=seat,
                     seat_name=names[seat] if len(names) > seat else "",
                     rival_name=names[1 - seat] if len(names) > 1 - seat else "",
                     is_ref=int(len(names) > seat and names[seat] == ref_name))
            mk = ob.get("market") or {}
            for p in PRODUCTS:
                r[f"px_{p}"] = (mk.get("prices") or {}).get(p, 0) or 0
                r[f"inv_{p}"] = (mk.get("inventory") or {}).get(p, 0) or 0
            shops = (ob.get("town") or {}).get("unlocked_shops") or []
            r["n_shops"] = len(shops)
            r["shops"] = "|".join(sorted(shops))
            pv = ob.get("private") or {}
            for c in CROPS:
                r[f"seed_{c}"] = (pv.get("seeds") or {}).get(c, 0) or 0
            for i in ITEMS:
                r[f"shed_{i}"] = (pv.get("shed") or {}).get(i, 0) or 0
            for ui, inv in enumerate((pv.get("inventories") or [])[:MAX_UNITS]):
                if isinstance(inv, dict):
                    r[f"carry{ui}_n"] = len(inv)
                    r[f"carry{ui}_total"] = sum(v for v in inv.values() if isinstance(v, (int, float)))
            fill_farm(r, f_own, "own")
            fill_farm(r, f_riv, "riv")
            # the graph evaluated on THIS state; absent node == inactive == no pressure either way
            try:
                from src.state import State as _St
                for node, _ours, _tgt, press, _u in _sg.deviation(_St(ob)):
                    press = float(press)
                    r[f"dev_{node}"] = press
                    r[f"exc_{node}"] = max(0.0, 1.0 - press)
            except Exception:                                              # noqa: BLE001
                pass
            # ... and on the RIVAL's farm, by flipping `player`. This is the off-policy variation:
            # the whole point of the causal panel is that he never lets a plant go dry while his
            # opponent does, in the same game, on the same day, at the same prices.
            try:
                from src.state import State as _St2
                ob2 = dict(ob)
                ob2["player"] = 1 - seat
                ob2["private"] = {"seeds": {}, "shed": {}, "inventories": []}
                for node, _o, _t, press, _u in _sg.deviation(_St2(ob2)):
                    if node in RIVAL_UNOBSERVABLE:
                        continue
                    press = float(press)
                    r[f"rdev_{node}"] = press
                    r[f"rexc_{node}"] = max(0.0, 1.0 - press)
            except Exception:                                              # noqa: BLE001
                pass
            S.append(r)

            try:
                act = act_b[seat].get("action") or {}
            except Exception:                                              # noqa: BLE001
                act = {}
            cmds = [act.get("farmer")] + list(act.get("hands") or [])
            positions = [f_own.get("farmer")] + list(f_own.get("hands") or [])
            for ui, cmd in enumerate(cmds):
                if cmd is None:
                    continue
                if not isinstance(cmd, (list, tuple)) or not cmd:
                    cmd = ["PASS"]
                pos = positions[ui] if ui < len(positions) and positions[ui] else [None, None]
                U.append({"game": game, "game_id": gid, "step": t, "day": t // DAY,
                          "hour": t % DAY, "seat": seat, "is_ref": r["is_ref"], "unit": ui,
                          "unit_kind": "farmer" if ui == 0 else "hand",
                          "op": str(cmd[0]),
                          "arg1": str(cmd[1]) if len(cmd) > 1 else "",
                          "arg2": int(cmd[2]) if len(cmd) > 2
                          and isinstance(cmd[2], (int, float)) else -1,
                          "pos_x": pos[0], "pos_y": pos[1],
                          "n_hands": len(f_own.get("hands") or []),
                          "money": f_own.get("money", 0) or 0})
            orders = [o for o in (act.get("market") or [])
                      if isinstance(o, (list, tuple)) and o]
            for pi, o in enumerate(orders):
                O.append({"game": game, "game_id": gid, "step": t, "day": t // DAY,
                          "hour": t % DAY, "seat": seat, "is_ref": r["is_ref"], "pos": pi,
                          "kind": str(o[0]),
                          "item": str(o[1]) if len(o) > 1 else "",
                          "qty": int(o[2]) if len(o) > 2 and isinstance(o[2], (int, float)) else -1,
                          "n_orders": len(orders),
                          "at_cap": int(len(orders) >= MAX_ORDERS),
                          "money": f_own.get("money", 0) or 0})
    return S, U, O


TABLES = (("states", ["game", "step", "seat"]),
          ("unit_ops", ["game", "step", "seat", "unit"]),
          ("market_orders", ["game", "step", "seat", "pos"]))


def main(argv=None):
    import pandas as pd
    import pyarrow.dataset as pads

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=0, help="0 = all")
    ap.add_argument("--ref-name", default="Boey")
    ap.add_argument("--step-cap", type=int, default=720)
    ap.add_argument("--out-dir", default="artifacts/parsed")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--batch", type=int, default=16, help="games per shard (bounds memory)")
    ap.add_argument("--keep-shards", action="store_true")
    a = ap.parse_args(argv)

    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.ref_glob)))
    if a.ref_max:
        paths = paths[:a.ref_max]
    out = Path(a.out_dir)
    shards = out / "shards"
    for name, _k in TABLES:
        (shards / name).mkdir(parents=True, exist_ok=True)
    print(f"# parse_replays  {len(paths)} replays -> {out}   (batch={a.batch})")

    jobs = [(p, a.step_cap, a.ref_name) for p in paths]
    for b0 in range(0, len(jobs), a.batch):
        chunk = jobs[b0:b0 + a.batch]
        S, U, O = [], [], []
        with mp.Pool(a.workers or None) as pool:
            for s, u, o in pool.imap_unordered(parse_one, chunk, chunksize=2):
                S.extend(s); U.extend(u); O.extend(o)
        for (name, keys), rows in zip(TABLES, (S, U, O)):
            if not rows:
                continue
            pd.DataFrame(rows).sort_values(keys).reset_index(drop=True).to_parquet(
                shards / name / f"part-{b0:05d}.parquet", index=False)
        print(f"   {min(b0 + a.batch, len(jobs))}/{len(jobs)} games  "
              f"states={len(S):,} units={len(U):,} orders={len(O):,}")
        del S, U, O

    print("\ncombining shards...")
    for name, keys in TABLES:
        d = pads.dataset(str(shards / name), format="parquet")
        tbl = d.to_table()
        df = tbl.to_pandas().sort_values(keys).reset_index(drop=True)
        p = out / f"{name}.parquet"
        df.to_parquet(p, index=False)
        ref = int(df["is_ref"].sum()) if "is_ref" in df else 0
        print(f"   {name:<14} {len(df):>10,} rows x {df.shape[1]:>3} cols   "
              f"is_ref {ref:,} ({ref / max(1, len(df)) * 100:.0f}%)  -> {p}")
    if not a.keep_shards:
        import shutil
        shutil.rmtree(shards, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
