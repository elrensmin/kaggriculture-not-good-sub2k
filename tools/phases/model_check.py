#!/usr/bin/env python
"""model_check — M0 gate: does the money model actually explain the reference's games?

`src/demand.py` and `src/value.py` claim to describe the economy as closed forms. If they
are wrong, every downstream decision is guesswork, so this runs them against real replays
and reports exact agreement rates. Run it before trusting anything.

Three checks, in order of how much they are worth:

  1. PRICE      `prices[item] == market.price(item, inventory[item])` at every observed
                step. Validates the curve AND the refresh timing. Expect 100 %; anything
                less means the re-export or the timing assumption is wrong.

  2. UNLOCK     Predict the day's shop from the engine's own draw, given the empty-tile count
                on both farms at hour 23:
                    rng = Random((seed*1_000_003) ^ day); one draw per empty tile of farm 0
                    then farm 1; the shop is the next rng.choice(sorted(SHOPS)).
                Compare with what the replay shows. This is the check that decides whether
                the shop schedule is a steerable planning input or noise.

  3. DRAIN      `inventory[t+1] - inventory[t] == -town_drain` on steps where NEITHER
                player traded that item, with the drain from `SHOPS` and the town centre at
                step index `t`. MEASURED: **100.00 %** (43,115/43,115) once the action list
                is read from `steps[t+1]` (the verified pairing) rather than `steps[t]`
                (94.98 %), and the drain step is `t` (68.86 % for `t+1`).

Usage
-----
  PYTHONPATH=. python -m tools.phases.model_check --max-games 20
  PYTHONPATH=. python -m tools.phases.model_check --max-games 60 --workers 6
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

from kaggle_environments.envs.kaggriculture.kaggriculture import (        # noqa: E402
    PRODUCTS, SHOPS,
)
from tools import team as team_mod                                        # noqa: E402
from src import demand, market, value                                     # noqa: E402

DAY = 24


def _orders(step_actions):
    """(sells, buys) counters per item from every player's market list this step."""
    sells, buys = collections.Counter(), collections.Counter()
    for act in step_actions:
        if not isinstance(act, dict):
            continue
        for o in (act.get("market") or []):
            if not o or len(o) < 3:
                continue
            try:
                q = int(o[2])
            except (TypeError, ValueError):
                continue
            if o[0] == "SELL":
                sells[o[1]] += q
            elif o[0] == "BUY_PRODUCT":
                buys[o[1]] += q
    return sells, buys


def check_one(path, seat_mode):
    try:
        rep = json.load(open(path))
    except Exception:                                     # noqa: BLE001
        return None
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    if not steps or len(steps[0]) < 2:
        return None
    names = (rep.get("info") or {}).get("TeamNames") or []
    if len(names) >= 2 and names[0] == names[1]:
        return None
    seed = (rep.get("info") or {}).get("seed")
    if seed is None:
        return None
    seat = team_mod.seat_of_names(names, fallback=0) if seat_mode == "auto" else int(seat_mode)
    res = collections.Counter()
    unlock_pairs = []
    for t in range(len(steps) - 1):
        obsp = steps[t][0].get("observation")
        if not obsp:
            continue
        day = t // DAY
        for pl in range(len(steps[t])):
            o, n = steps[t][pl].get("observation"), steps[t + 1][pl].get("observation")
            if not o or not n:
                continue
            farm = o["farms"][pl]
            pos = [tuple(farm["farmer"])] + [tuple(q) for q in (farm.get("hands") or [])]
            cmds = [steps[t + 1][pl].get("action", {}).get("farmer") or ["PASS"]]
            cmds += list(steps[t + 1][pl].get("action", {}).get("hands") or [])
            # Scope: ONE-SHOT crops only (an ongoing crop's `yield_units` is credited at
            # day end by a different rule, modelled in `value.ongoing_yield`), and only
            # when no other unit acts on the same tile this turn (the first unit's effect
            # is what the engine applies; a second is a no-op). Under that scope the rule
            # is exact: 19,659/19,659 mid-day and 856/856 at the day boundary.
            touch = collections.Counter()
            for ui2, c2 in enumerate(cmds):
                if ui2 < len(pos) and c2 and c2[0] != "PASS":
                    touch[pos[ui2]] += 1
            for ui, cmd in enumerate(cmds):
                if ui >= len(pos) or not cmd or cmd[0] != "WATER":
                    continue
                x, y = pos[ui]
                _tb0 = farm["tiles"][y][x]
                from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
                if not (isinstance(_tb0, dict) and _tb0.get("kind") == "PLANT"
                        and not CROPS[_tb0["crop"]]["ongoing"] and touch[(x, y)] == 1):
                    continue
                tb = farm["tiles"][y][x]
                ta = n["farms"][pl]["tiles"][y][x]
                if not (isinstance(tb, dict) and tb.get("kind") == "PLANT"
                        and isinstance(ta, dict) and ta.get("kind") == "PLANT"):
                    continue
                crop = tb["crop"]
                cd = market.CROPS[crop] if hasattr(market, "CROPS") else None
                from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
                cd = CROPS[crop]
                age = day - tb["planted_day"]
                w = value.water_window(crop)
                gain = 0
                # `WATER` returns immediately when the tile is already watered today.
                if (not tb.get("watered_today")) and w and w[0] <= age <= w[1]:
                    gain = 2 if tb.get("fertilized_until_day", -1) >= day else 1
                want = min(cd["max_yield"], tb.get("yield_units", 0) + gain)
                res["yield_n"] += 1
                if ta.get("yield_units", 0) == want:
                    res["yield_ok"] += 1
    for t in range(len(steps) - 1):
        obs = steps[t][0].get("observation")
        nobs = steps[t + 1][0].get("observation")
        if not obs or not nobs:
            continue
        # ---- 1. PRICE ----
        inv, prices = obs["market"]["inventory"], obs["market"]["prices"]
        for item in PRODUCTS:
            res["price_n"] += 1
            if int(prices.get(item, -1)) == int(market.price(item, inv.get(item, 0))):
                res["price_ok"] += 1
        # ---- 3. DRAIN ----
        # The action that CAUSES the t -> t+1 transition lives at index t+1 (the verified
        # pairing). Using index t scores 94.98 %; index t+1 scores **100.00 %**.
        acts = [steps[t + 1][i].get("action") for i in range(len(steps[t + 1]))]
        sells, buys = _orders(acts)
        shops = [str(s) for s in (obs.get("town") or {}).get("unlocked_shops") or []]
        for item in PRODUCTS:
            # Only untraded steps are checkable: a SELL/BUY order's FILL depends on the
            # shed and the cash, so a requested quantity is not a committed one.
            if sells.get(item, 0) or buys.get(item, 0):
                continue
            res["drain_n"] += 1
            drop = inv.get(item, 0) - nobs["market"]["inventory"].get(item, 0)
            if drop == demand.drain_at_step(t, item, shops):
                res["drain_ok"] += 1
        # ---- 2. UNLOCK ----
        if t % DAY == DAY - 1:
            day = t // DAY
            cur = list((obs.get("town") or {}).get("unlocked_shops") or [])
            nxt = list((nobs.get("town") or {}).get("unlocked_shops") or [])
            if nxt != cur:
                gained = nxt[len(cur):] if len(nxt) > len(cur) else []
                if gained:
                    # The draw count is the empty-tile count AFTER the hour-23 action and
                    # BEFORE weeds spawn. A replay only shows hour-23 (pre-action) and
                    # hour-0-next-day (post-weed), so the count is off by the hour-23
                    # action's tile effects. We therefore check the base count exactly and
                    # then whether SOME offset explains it -- at runtime we do know the
                    # action, so the count is available exactly.
                    e = (demand.counts_empty(obs["farms"][0]["tiles"])
                         + demand.counts_empty(obs["farms"][1]["tiles"]))
                    pred = demand.shop_unlock(seed, day, e, 0, cur)
                    explained = any(demand.shop_unlock(seed, day, e + off, 0, cur) == gained[0]
                                    for off in range(-6, 7) if e + off >= 0)
                    unlock_pairs.append((pred, gained[0], day, e, int(explained)))
    if not unlock_pairs and res["price_n"] == 0:
        return None
    res["unlock_n"] = len(unlock_pairs)
    res["unlock_ok"] = sum(1 for p, a, _d, _e, _x in unlock_pairs if p == a)
    res["unlock_explained"] = sum(1 for _p, _a, _d, _e, x in unlock_pairs if x)
    return {"file": Path(path).name, "res": dict(res),
            "unlock_misses": [(p, a, d, e, x) for p, a, d, e, x in unlock_pairs
                              if p != a and not x][:4]}


def _worker(task):
    path, seat_mode = task
    try:
        return check_one(path, seat_mode)
    except Exception as exc:                              # noqa: BLE001
        return {"file": Path(path).name, "error": repr(exc)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=20)
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--team", default=None)
    a = ap.parse_args(argv)
    team_mod.set_team(a.team or "Boey")
    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))[:a.max_games]
    print(f"# model_check  {len(paths)} episodes")
    tasks = [(p, a.seat) for p in paths]
    w = int(a.workers or 0)
    if w <= 1 or len(tasks) <= 1:
        rows = [_worker(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_worker, tasks))
    errs = [r for r in rows if r and "error" in r]
    rows = [r for r in rows if r and "res" in r]
    if errs:
        print(f"   {len(errs)} errored: {errs[0]['error']}")
    if not rows:
        print("no data")
        return 1
    tot = collections.Counter()
    for r in rows:
        for k, v in r["res"].items():
            tot[k] += v
    print(f"   games checked {len(rows)}")
    for name, ok, n in (("PRICE  prices==curve", "price_ok", "price_n"),
                        ("DRAIN  untraded step", "drain_ok", "drain_n"),
                        ("UNLOCK from empty count", "unlock_ok", "unlock_n"),
                        ("UNLOCK explained +-6", "unlock_explained", "unlock_n"),
                        ("YIELD  water gain", "yield_ok", "yield_n")):
        o, m = tot[ok], tot[n]
        print(f"   {name:<24}{o:>10}/{m:<10} = {100*o/max(1,m):>6.2f}%"
              f"{'   <-- GATE PASS' if o == m and m else ''}")
    misses = [(r["file"], x) for r in rows for x in r.get("unlock_misses", [])]
    if misses:
        print(f"   unlock misses ({len(misses)}):")
        for f, x in misses[:8]:
            print(f"      {f[:28]:<30} predicted {x[0]} got {x[1]}  d{x[2]} empties {x[3]}/{x[4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
