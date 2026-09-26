#!/usr/bin/env python
"""sell_price — per-game, per-product price-at-sell for BOTH seats (no averaging).

Purpose: see what WE sell each product for vs what the OPPONENT sells it for, so
we can spot where we are being undercut (or where we are handing them a premium).

For each game it prints, per product, side by side:
    units sold | qty-weighted average price | units at the $1 floor | below-base units
plus a `gap` (ours - theirs) and an UNDER flag when the opponent clears a
materially better price than us.

Data source: the replay's market audit (`_diagnose_meta.audit`) for our own runs,
which records *executed* units and prices for BOTH seats. Leaderboard replays
carry no audit, so it falls back to each seat's SELL orders x the step price.

Usage:
  PYTHONPATH=. python -m tools.market.sell_price --dir diag-replays/consol-new2
  PYTHONPATH=. python -m tools.market.sell_price --dir diag-replays/consol-new2 --game 543252345
  PYTHONPATH=. python -m tools.market.sell_price --dir diag-replays/consol-new2 --product WOOL
  PYTHONPATH=. python -m tools.market.sell_price --path some_replay.json --seat 1
"""
from __future__ import annotations

import argparse
import glob as globmod
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tools import diagnose
from tools.diagnose.window import parse_days, in_window, describe
from kaggle_environments.envs.kaggriculture.kaggriculture import MARKET_PARAMS, PRICE_FLOOR

_WINDOW = None


def _in(day):
    return in_window(day, _WINDOW)


PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
            "EGG", "MILK", "WOOL", "FERTILIZER")
BASE = {p: MARKET_PARAMS[p]["base"] for p in MARKET_PARAMS}


def _seat_zero(rep):
    """Our seat: 1 on harness runs. On LB replays fall back to the non-DSM seat."""
    names = (rep.get("info") or {}).get("TeamNames") or []
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return 1 - i if len(names) > 1 else 1
    return 1


def _sell_from_audit(rep, seat):
    out = defaultdict(lambda: [0, 0.0, 0, 0])
    audit = (rep.get("_diagnose_meta") or {}).get("audit") or {}
    if not audit:
        return None
    for bucket in audit.values():
        s = bucket.get(str(seat)) or bucket.get(seat) or {}
        for item, rec in (s.get("sells") or {}).items():
            c = out[item]
            c[0] += rec.get("qty", 0)
            c[1] += rec.get("revenue", 0.0)
            c[2] += rec.get("floor", 0)
            c[3] += rec.get("below", 0)
    return {k: tuple(v) for k, v in out.items()} if out else {}


def _sell_from_action(rep, seat):
    out = defaultdict(lambda: [0, 0.0, 0, 0])
    steps = rep["steps"]
    for t in range(len(steps)):
        si = steps[t]
        if len(si) <= seat:
            continue
        obs = si[seat].get("observation")
        act = si[seat].get("action") or {}
        if not _in(t // 24):  # window-guard
            continue
        if not obs:
            continue
        px = (obs.get("market") or {}).get("prices") or {}
        for o in (act.get("market") or []):
            if o and o[0] == "SELL" and len(o) >= 3 and o[1] in PRODUCTS:
                q = max(0, int(o[2]))
                pr = float(px.get(o[1], 0) or 0)
                c = out[o[1]]
                c[0] += q
                c[1] += q * pr
                if pr <= PRICE_FLOOR:
                    c[2] += q
                if pr < BASE.get(o[1], 0):
                    c[3] += q
    return {k: tuple(v) for k, v in out.items()}


def analyse(path, our_seat=None, opp_seat=None):
    try:
        rep = diagnose.load_replay(Path(path))
    except Exception:  # noqa: BLE001
        return None
    ours = our_seat if our_seat is not None else _seat_zero(rep)
    opp = opp_seat if opp_seat is not None else (1 - ours)
    a = _sell_from_audit(rep, ours)
    if a is None:
        a = _sell_from_action(rep, ours)
    b = _sell_from_audit(rep, opp)
    if b is None:
        b = _sell_from_action(rep, opp)
    return {"file": os.path.basename(path), "seed": (rep.get("info") or {}).get("seed"),
            "names": (rep.get("info") or {}).get("TeamNames") or [],
            "seat": ours, "opp_seat": opp, "ours": a, "opp": b}


def _price(cell):
    return (cell[1] / cell[0]) if cell and cell[0] else 0.0


def print_game(g, only=None):
    seed = g["seed"] or g["file"]
    names = g["names"]
    ourname = names[g["seat"]] if len(names) > g["seat"] else f"seat{g['seat']}"
    oppname = names[g["opp_seat"]] if len(names) > g["opp_seat"] else f"seat{g['opp_seat']}"
    print(f"--- {seed}  us={ourname or g['seat']} vs opp={oppname or g['opp_seat']} ---")
    print(f"    {'product':<12}{'ours u':>8}{'ours $':>8}{'fl':>5} | {'opp u':>7}{'opp $':>8}{'fl':>5} | {'gap$':>7}  flag")
    rows = []
    for p in PRODUCTS:
        a = g["ours"].get(p); b = g["opp"].get(p)
        if not (a or b):
            continue
        if only and p != only:
            continue
        pa, pb = _price(a), _price(b)
        gap = pa - pb
        flag = ""
        if b and a and pb > pa * 1.05:
            flag = "UNDER"
        elif a and b and pa > pb * 1.05:
            flag = "ahead"
        rows.append((p, a, b, pa, pb, gap, flag))
    rows.sort(key=lambda r: (r[6] != "UNDER", r[0]))
    for p, a, b, pa, pb, gap, flag in rows:
        au, af = (a[0], a[2]) if a else (0, 0)
        bu, bf = (b[0], b[2]) if b else (0, 0)
        print(f"    {p:<12}{au:>8}{pa:>8.1f}{af:>5} | {bu:>7}{pb:>8.1f}{bf:>5} | {gap:>+7.1f}  {flag}")
    print()


def summarise(games, only=None):
    agg = defaultdict(lambda: {"ou": 0, "orv": 0.0, "of": 0, "bu": 0, "brv": 0.0, "bf": 0,
                               "undercut": 0, "ahead": 0, "both": 0})
    for g in games:
        for p in PRODUCTS:
            if only and p != only:
                continue
            a = g["ours"].get(p); b = g["opp"].get(p)
            if not (a and b and a[0] and b[0]):
                continue
            c = agg[p]
            c["ou"] += a[0]; c["orv"] += a[1]; c["of"] += a[2]
            c["bu"] += b[0]; c["brv"] += b[1]; c["bf"] += b[2]
            c["both"] += 1
            if _price(b) > _price(a) * 1.05:
                c["undercut"] += 1
            elif _price(a) > _price(b) * 1.05:
                c["ahead"] += 1
    print(f"\n== summary over {len(games)} games (totals + per-game counts; no averaging) ==")
    print(f"   {'product':<12}{'our units':>10}{'our avg$':>9}{'our floor%':>11} | "
          f"{'opp units':>10}{'opp avg$':>9}{'opp floor%':>11} | under/ahead")
    for p in PRODUCTS:
        c = agg.get(p)
        if not c or not c["both"]:
            continue
        oa = c["orv"] / c["ou"] if c["ou"] else 0
        ba = c["brv"] / c["bu"] if c["bu"] else 0
        ofp = 100 * c["of"] / c["ou"] if c["ou"] else 0
        bfp = 100 * c["bf"] / c["bu"] if c["bu"] else 0
        print(f"   {p:<12}{c['ou']:>10}{oa:>9.1f}{ofp:>10.0f}% | "
              f"{c['bu']:>10}{ba:>9.1f}{bfp:>10.0f}% | {c['undercut']:>5}/{c['ahead']:<5}")


def _one(arg):
    return analyse(*arg)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--days", default=None, help="restrict analysis to day window, e.g. 0-5 or 0-5,12-17")
    ap.add_argument("--path", default=None)
    ap.add_argument("--glob", default=None)
    ap.add_argument("--seat", type=int, default=None, help="our seat (default 1, or non-DSM on LB)")
    ap.add_argument("--product", default=None, help="only this product")
    ap.add_argument("--game", default=None, help="only games whose file/seed contains this")
    ap.add_argument("--summary", action="store_true", help="print only the cross-game summary")
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()
    global _WINDOW
    _WINDOW = parse_days(args.days)
    if _WINDOW:
        print("window:", describe(_WINDOW))

    only = args.product.upper() if args.product else None

    if args.path:
        paths = [args.path]
    else:
        d = args.dir or "."
        pat = args.glob or ("*_vs_*.json" if globmod.glob(os.path.join(d, "*_vs_*.json")) else "*.json")
        paths = sorted(globmod.glob(os.path.join(d, pat)))
    if args.game:
        paths = [p for p in paths if args.game in os.path.basename(p)]
    if not paths:
        print("no replays found")
        return
    workers = args.workers or (os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        games = [g for g in ex.map(_one, [(p, args.seat, None) for p in paths]) if g]
    print(f"\n===== sell_price: {args.path or args.dir} ({len(games)} games, both seats) =====")
    if not args.summary:
        for g in games:
            print_game(g, only)
    summarise(games, only)


if __name__ == "__main__":
    main()
