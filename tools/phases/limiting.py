#!/usr/bin/env python
"""limiting — which factor is actually holding the farm back: CASH, LAND, LABOUR, ACTION?

Why this exists
---------------
A farm is a resource-conversion chain and it can only be short of four things:

  CASH    money to buy seeds / animals / feed / land / hands
  LAND    owned, EMPTY tiles -- ground you have paid for and are not using
  LABOUR  unit-turns (hired hands x 24)
  ACTION  whether the labour is spent on productive ops or on walking

Every "why are we behind" argument reduces to which of the four is binding on that day,
and the four need completely different fixes. Aggregates cannot tell them apart: a farm
with 19 empty tiles and $10 in the bank is CASH-bound; one with 0 empty tiles and $900 in
the bank is LABOUR-bound; one with 19 empty tiles and $900 in the bank is failing to buy
things it can afford.

This runs the SAME episodes twice in lockstep -- `HIS` (the reference's recorded actions)
and `OURS` (our agent in his seat from d0) -- and prints, per day:

  CASH    end money, that day's realised net, and WHAT THE ORDERS ASKED FOR
          (sell / seed / animal / feed / land / hire), priced off the observation's own
          price table, so the flow is attributable even without the market audit
  LAND    owned / empty-owned / planted / structs, and the empty share
  LABOUR  hands, unit-turns, hire orders
  ACTION  acts, moves, PASS and the move share

plus a one-line verdict per day naming the binding factor.

Usage
-----
  PYTHONPATH=. python -m tools.phases.limiting --n 16 --cut-day 10 --workers 4
  PYTHONPATH=. python -m tools.phases.limiting --n 16 --days 5-10 --metric cash
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import multiprocessing as mp
import random
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments import make                                   # noqa: E402
from tools import team as team_mod                                     # noqa: E402
from tools.phases.transplant import (DAY, STEPS, _agent, _recorded,     # noqa: E402
                                     _selfplay)

MOVES = ("NORTH", "SOUTH", "EAST", "WEST")
# Order token -> which cash bucket it belongs to.
_BUCKET = {"SELL": "sell", "BUY_SEED": "seed", "BUY_ANIMAL": "animal",
           "BUY_PRODUCT": "feed", "BUY_LAND": "land", "HIRE": "hire"}


def _price(obs, item):
    """Current market price for `item`, or the base from params as a fallback."""
    try:
        return float(obs["market"]["prices"][item])
    except Exception:                          # noqa: BLE001
        try:
            from src import params
            return float(params.MARKET_PARAMS[item]["base"])
        except Exception:                      # noqa: BLE001
            return 0.0


def _animal_price(animal):
    from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS
    return float(ANIMALS[animal]["cost"])


def _land_price(quadrants):
    from src import params
    return float(getattr(params, "LAND_PRICE", 1000))


def _hire_price(hires_today):
    """Fibonacci hire cost, as the engine charges it."""
    a, b = 1, 1
    for _ in range(max(0, hires_today)):
        a, b = b, a + b
    return float(a)


def _parse_orders(orders, obs_before, hires_so_far):
    """Cash asked for by one turn's market list, priced off the observation's own table."""
    buckets = Counter()
    for order in orders or []:
        if not order:
            continue
        tok = str(order[0])
        b = _BUCKET.get(tok)
        if b is None:
            continue
        qty = float(order[2]) if len(order) > 2 else 1.0
        if tok == "SELL":
            buckets["sell"] += qty * _price(obs_before, order[1])
            buckets["sell_" + str(order[1])] += qty * _price(obs_before, order[1])
        elif tok == "BUY_SEED":
            buckets["seed"] += qty * _price(obs_before, order[1])
        elif tok == "BUY_ANIMAL":
            buckets["animal"] += qty * _animal_price(order[1])
        elif tok == "BUY_PRODUCT":
            buckets["feed"] += qty * _price(obs_before, order[1])
        elif tok == "BUY_LAND":
            buckets["land"] += _land_price(0)
        elif tok == "HIRE":
            buckets["hire"] += _hire_price(hires_so_far)
            hires_so_far += 1
        buckets["n_" + b] += 1
    return buckets, hires_so_far


def _counts(act):
    ops = [list((act or {}).get("farmer") or ["PASS"])]
    ops += [list(c or ["PASS"]) for c in ((act or {}).get("hands") or [])]
    n_act = n_move = n_pass = 0
    for op in ops:
        nm = str(op[0]) if op else "PASS"
        if nm in MOVES:
            n_move += 1
        elif nm == "PASS":
            n_pass += 1
        else:
            n_act += 1
    return n_act, n_move, n_pass, len(ops)


def _land(obs, seat):
    farm = obs["farms"][seat]
    owned = empty = planted = structs = 0
    for row in farm["tiles"]:
        for t in row:
            if t == "LOCKED":
                continue
            owned += 1
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                planted += 1
            elif isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE"):
                structs += 1
            elif t is None:
                empty += 1
    return owned, empty, planted, structs


def _series(path, prefix):
    from tools.diagnose.games import load_replay
    rep = load_replay(Path(path))
    seat = team_mod.seat_of_names((rep.get("info") or {}).get("TeamNames") or [], fallback=0)
    seed = (rep.get("info") or {}).get("seed")
    env = make("kaggriculture", configuration={"episodeSteps": STEPS, "seed": seed})
    env.reset()
    agent = _agent()
    acc = {}
    for t in range(STEPS):
        obs = [env.state[i]["observation"] for i in range(2)]
        acts = [None, None]
        acts[1 - seat] = _recorded(rep, t, 1 - seat)
        acts[seat] = (_recorded(rep, t, seat) if prefix == "recorded" else agent(obs[seat]))
        if acts[seat] is None or acts[1 - seat] is None:
            break
        d = t // DAY
        a = acc.setdefault(d, {"hired": 0, "acts": 0, "moves": 0, "pass": 0, "ut": 0,
                               "hands_max": 1, "sell": 0.0, "seed": 0.0, "animal": 0.0,
                               "feed": 0.0, "land": 0.0, "hire": 0.0})
        if "money0" not in a:
            a["money0"] = float(obs[seat]["farms"][seat].get("money") or 0.0)
        buckets, a["hired"] = _parse_orders(acts[seat].get("market"), obs[seat], a["hired"])
        for k, v in buckets.items():
            a[k] = a.get(k, 0) + v
        na, nm, npp, nut = _counts(acts[seat])
        a["acts"] += na
        a["moves"] += nm
        a["pass"] += npp
        a["ut"] += nut
        a["hands_max"] = max(a["hands_max"], 1 + len(obs[seat]["farms"][seat].get("hands") or []))
        env.step(acts)
        if env.done:
            break
        if (t + 1) % DAY == 0:
            fin = env.state[seat]["observation"]
            owned, empty, planted, structs = _land(fin, seat)
            a.update({"money": float(fin["farms"][seat].get("money") or 0.0),
                      "owned": owned, "empty": empty, "planted": planted,
                      "structs": structs, "hands": 1 + len(fin["farms"][seat].get("hands") or [])})
            a["hands_peak"] = a["hands_max"]
            a["net"] = a["money"] - a["money0"]
    return {str(k): v for k, v in acc.items() if "money" in v}, seat


def _worker(task):
    path, prefix = task
    try:
        days, seat = _series(path, prefix)
        return {"file": Path(path).name, "prefix": prefix, "days": days}
    except Exception as exc:                     # noqa: BLE001
        return {"file": Path(path).name, "prefix": prefix, "error": repr(exc)}


def _med(rows, d, key, default=0.0):
    vals = [r["days"][str(d)][key] for r in rows
            if str(d) in r["days"] and key in r["days"][str(d)]]
    return st.median(vals) if vals else default


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--shuffle-seed", type=int, default=20260929)
    ap.add_argument("--days", default="0-10")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--metric", default="cash,land,labour,action")
    ap.add_argument("--out", default=None)
    ap.add_argument("--team", default=None)
    a = ap.parse_args(argv)
    team_mod.set_team(a.team or "Boey")
    lo, hi = (int(x) for x in a.days.split("-"))
    want = set(a.metric.split(","))

    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))
    if not a.all:
        rnd = random.Random(a.shuffle_seed)
        paths = rnd.sample(paths, min(a.n, len(paths)))
    keep = []
    for p in paths:
        try:
            if not _selfplay(json.load(open(p))):
                keep.append(p)
        except Exception:                        # noqa: BLE001
            pass
    paths = keep
    print(f"# limiting factors  ref={a.ref_from}  {len(paths)} episodes  d{lo}-d{hi}")
    tasks = [(p, pre) for pre in ("recorded", "ours") for p in paths]
    w = int(a.workers or 0)
    if w <= 1 or len(tasks) <= 1:
        rows = [_worker(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_worker, tasks))
    his = [r for r in rows if r.get("prefix") == "recorded" and "error" not in r]
    ours = [r for r in rows if r.get("prefix") == "ours" and "error" not in r]
    errs = [r for r in rows if "error" in r]
    if errs:
        print(f"   {len(errs)} errored, e.g. {errs[0]['error']}")
    if not his or not ours:
        print("no data")
        return 1
    print(f"   {len(his)} episodes per arm")

    def row(lbl, key, fmt="{:>9.1f}"):
        cells = []
        for d in range(lo, hi + 1):
            o, h = _med(ours, d, key), _med(his, d, key)
            cells.append(f"{fmt.format(o)}/{fmt.format(h)}")
        print(f"   {lbl:<22}" + "".join(f"{c:>19}" for c in cells))

    hdr = "   " + " " * 22 + "".join(f"{('d' + str(d)):>19}" for d in range(lo, hi + 1))
    print("\n   (ours/his on every column)\n" + hdr)
    if "cash" in want:
        print("   -- CASH --")
        row("money (end of day)", "money", "{:>9.0f}")
        row("net (realised)", "money", "{:>9.0f}")
        row("orders: SELL value", "sell", "{:>9.0f}")
        row("orders: seed spend", "seed", "{:>9.0f}")
        row("orders: animal spend", "animal", "{:>9.0f}")
        row("orders: feed spend", "feed", "{:>9.0f}")
        row("orders: hire orders", "n_hire", "{:>9.0f}")
    if "land" in want:
        print("   -- LAND --")
        row("owned tiles", "owned", "{:>9.0f}")
        row("EMPTY owned tiles", "empty", "{:>9.0f}")
        row("planted", "planted", "{:>9.0f}")
        row("structs", "structs", "{:>9.0f}")
    if "labour" in want:
        print("   -- LABOUR --")
        row("hands (end of day)", "hands", "{:>9.0f}")
        row("unit-turns", "ut", "{:>9.0f}")
    if "action" in want:
        print("   -- ACTION --")
        row("acts", "acts", "{:>9.0f}")
        row("moves", "moves", "{:>9.0f}")
        row("PASS", "pass", "{:>9.0f}")
        cells = []
        for d in range(lo, hi + 1):
            o = _med(ours, d, "moves") / max(1.0, _med(ours, d, "acts"))
            h = _med(his, d, "moves") / max(1.0, _med(his, d, "acts"))
            cells.append(f"{o:.2f}/{h:.2f}")
        print(f"   {'moves per act':<22}" + "".join(f"{c:>19}" for c in cells))

    print("\n   -- REVENUE BY PRODUCT (order value we ASKED to sell) --")
    items = ["MILK", "WOOL", "EGG", "WHEAT", "FERTILIZER", "STRAWBERRY", "MELON",
             "CARROT", "TOMATO"]
    for it in items:
        cells = []
        for d in range(lo, hi + 1):
            o, h = _med(ours, d, "sell_" + it), _med(his, d, "sell_" + it)
            cells.append(f"{o:.0f}/{h:.0f}")
        if any(c != "0/0" for c in cells):
            print(f"   {'sell ' + it:<22}" + "".join(f"{c:>19}" for c in cells))
    print("\n   -- VERDICT (binding factor per day) --")
    for d in range(lo, hi + 1):
        verdicts = []
        for lbl, rows_ in (("ours", ours), ("his", his)):
            cash = _med(rows_, d, "money")
            empty = _med(rows_, d, "empty")
            mv = _med(rows_, d, "moves")
            ac = _med(rows_, d, "acts")
            if empty > 3 and cash < 60:
                v = "CASH (empty land, no money)"
            elif empty > 3 and cash >= 60:
                v = "CAN'T-BUY (affordable but unused)"
            elif ac <= 0:
                v = "LABOUR (no acts)"
            elif mv / max(1.0, ac) > 1.4:
                v = "ACTION (walking)"
            else:
                v = "land-full, working"
            verdicts.append(f"{lbl}={v}")
        print(f"   d{d:<3}" + "   ".join(verdicts))
    if a.out:
        Path(a.out).write_text(json.dumps({"his": his, "ours": ours}, default=str))
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
