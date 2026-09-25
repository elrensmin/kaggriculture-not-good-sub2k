#!/usr/bin/env python
"""dsm_profile — full behavioural map of the top player (DSM) vs us, for cloning.

Covers the modalities that matter, from the DSM replays + day CSVs:
  * herd        COW/SHEEP/GOOSE per day (endgame + curve)
  * structures  COOP/PASTURE counts per day, coop build days, land buys
  * shed        max/end shed pressure per day + end-of-day COMPOSITION
  * lifecycle   weeds, plants_fertilized, plants_watered, animals_fed/cared, discs
  * selling     per product: units, price-at-sell, share at the $1 floor, below base
  * labour      unit-op mix (WATER/HARVEST/FEED/CARE/FERTILIZE/...), idle share
  * crops       crop tiles per day + max single-crop share (rotation, not stacking)
  * curve       market inventory at the moment of every SELL, bucketed around I0
  * land        the day each quadrant was unlocked
  * discards    units discarded per product (flat vs concentrated)
  * mix         share of revenue per product (no line above 22%)
  * wheat       bought vs fed (a market-making wash shows up as buy >> fed)
  * yarn        herd and sales split by YARN_STORE presence (the demand response)

Committed quantities are used when the replay carries a market audit (our own
runs); leaderboard replays have none and fall back to the action's REQUESTED
quantities, which for our tape are `SELL <item> 1000` sentinels and must not be
read as volume. The `src=` tag on each selling row says which was used.

Usage:
  PYTHONPATH=src:. python -m tools.report.dsm_profile --compare --run-dir=diag-replays/run-1
  PYTHONPATH=src:. python -m tools.report.dsm_profile --profile dsm
"""
from __future__ import annotations

import argparse
import csv
import glob as globmod
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import diagnose

SELL_PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
STRUCT = ("max_shed_total", "end_shed_total", "weeds_max", "plants_fertilized",
          "plants_watered", "animals_fed", "animals_cared", "discarded_units",
          "hires", "idle_share_pct")
# Columns read from games.csv (per game, not per day). Absent for LB replay dirs.
GAMES_COLS = ("idle_units_ready_total", "locked_steps", "idle_share_pct",
              "discarded_units_total", "shed_overflow_days", "stranded_at_bell",
              "floor_sales", "animal_escapes", "feed_surplus")
I0 = 10000


def _seat_dsm(rep):
    names = (rep.get("info") or {}).get("TeamNames") or ["", ""]
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i
    steps = rep["steps"]
    for i in range(len(steps) - 1, -1, -1):
        si = steps[i]
        if len(si) > 1:
            try:
                return 0 if si[0]["observation"]["farms"][0]["money"] > si[1]["observation"]["farms"][1]["money"] else 1
            except (KeyError, TypeError):
                pass
    return 1


def _bucket(inv):
    if inv < I0:
        return "<I0"
    if inv < I0 + 50:
        return "I0..+50"
    if inv <= I0 + 100:
        return "+50..+100"
    return ">I0+100"


def _one(arg):
    path, which = arg
    try:
        rep = diagnose.load_replay(Path(path))
    except Exception:  # noqa: BLE001
        return None
    seat = _seat_dsm(rep) if which == "dsm" else 1
    steps = rep["steps"]
    audit = (rep.get("_diagnose_meta") or {}).get("audit") or {}
    out = {"days": {}, "ops": Counter(), "sell": {},
           "coop_day": Counter(), "land_day": Counter(), "pasture_end": 0, "coop_end": 0,
           "crop_day": {}, "shed_day": {}, "shed_comp": {},
           "inv_hist": defaultdict(Counter), "inv_hist_end": defaultdict(Counter),
           "quad_day": {}, "disc": Counter(),
           "wheat": [0, 0, 0], "yarn_day": None, "src": "audit" if audit else "action"}
    seen = set()
    seen_q = set()
    for i in range(len(steps)):
        si = steps[i]
        if len(si) <= seat:
            continue
        obs = si[seat].get("observation")
        act = si[seat].get("action")
        if not obs:
            continue
        d = i // 24
        farm = obs["farms"][seat]
        priv = obs.get("private") or {}
        inv = (obs.get("market") or {}).get("inventory") or {}
        prices = (obs.get("market") or {}).get("prices") or {}

        # ---- land: the day each quadrant first appears
        for q in (farm.get("unlocked_quadrants") or []):
            if q not in seen_q:
                seen_q.add(q)
                out["quad_day"][q] = d

        # ---- YARN response signal
        shops = (obs.get("town") or {}).get("unlocked_shops") or []
        if out["yarn_day"] is None and any("YARN" in str(s) for s in shops):
            out["yarn_day"] = d

        # ---- crops + shed, once per day
        if d not in seen:
            seen.add(d)
            c = s = g = pa = co = 0
            cr = Counter()
            for row in farm["tiles"]:
                for t in row:
                    if isinstance(t, dict):
                        a = t.get("animal")
                        if a == "COW": c += 1
                        elif a == "SHEEP": s += 1
                        elif a == "GOOSE": g += 1
                        if t.get("kind") == "PASTURE": pa += 1
                        elif t.get("kind") == "COOP": co += 1
                        if t.get("kind") == "PLANT" and t.get("crop"):
                            cr[t["crop"]] += 1
            out["days"][d] = (c, s, g, pa, co)
            out["pasture_end"] = pa
            out["coop_end"] = co
            out["crop_day"][d] = dict(cr)

        # ---- shed: peak within the day, and the composition at the day end
        shed = priv.get("shed") or {}
        tot = sum(v for v in shed.values() if v > 0)
        carried = sum(max(0, int(v)) for inv in (priv.get("inventories") or [])
                      for v in (inv or {}).values())
        # [shed@end, shed_peak, carried@end, carried_peak, system_peak]
        rec = out["shed_day"].setdefault(d, [0, 0, 0, 0, 0])
        while len(rec) < 5:
            rec.append(0)
        rec[1] = max(rec[1], tot)
        rec[3] = max(rec[3], carried)
        rec[4] = max(rec[4], tot + carried)
        if i % 24 == 23:
            rec[0] = tot
            rec[2] = carried
            out["shed_comp"][d] = {k: v for k, v in shed.items() if v > 0}

        # ---- committed selling when the audit exists
        step_audit = audit.get(i) or audit.get(str(i)) or {}
        rec_seat = step_audit.get(seat) or step_audit.get(str(seat)) or {}
        if rec_seat.get("sells"):
            for item, rec in rec_seat["sells"].items():
                cell = out["sell"].setdefault(item, [0, 0.0, 0])
                cell[0] += rec.get("qty", 0)
                cell[1] += rec.get("revenue", 0.0)
                cell[2] += rec.get("floor", 0)
        for it, n in (rec_seat.get("discard_items") or {}).items():
            out["disc"][it] += n

        if not act:
            continue
        cmds = [act.get("farmer") or []] + list(act.get("hands") or [])
        for cmd in cmds:
            if cmd:
                out["ops"][cmd[0]] += 1
                if cmd[0] == "BUILD_COOP":
                    out["coop_day"][d] += 1
                elif cmd[0] == "FEED":
                    out["wheat"][1] += 1
        for o in (act.get("market") or []):
            if not o:
                continue
            if o[0] == "BUY_LAND":
                out["land_day"][d] += 1
            elif o[0] == "BUY_PRODUCT" and len(o) >= 3 and o[1] == "WHEAT":
                out["wheat"][0] += max(0, int(o[2]))
        # Curve table fallback (no audit): distribute the requested volume across
        # this step's orders. Our tape sends `SELL <item> 1000` sentinels, so this
        # is only trustworthy for replays without an audit; the audit pass below
        # supersedes it.
        if not audit:
            for o in (act.get("market") or []):
                if not (o and o[0] == "SELL" and len(o) >= 3 and o[1] in SELL_PRODUCTS):
                    continue
                item = o[1]
                q = max(0, int(o[2]))
                p = float(prices.get(item, 0) or 0)
                out["inv_hist"][item][_bucket(int(inv.get(item, 0)))] += q
                cell = out["sell"].setdefault(item, [0, 0.0, 0])
                cell[0] += q; cell[1] += q * p
                if p <= 1:
                    cell[2] += q
                if item == "WHEAT":
                    out["wheat"][2] += q

    # Curve table from the AUDIT, keyed on the audit's own step. The replay does
    # not record an action for every step (measured: 127 of 208 sell steps carry
    # one), so walking actions drops ~80% of the volume.
    if audit:
        for k, bucket in audit.items():
            try:
                si = int(k)
            except (TypeError, ValueError):
                continue
            if si < 0 or si >= len(steps) or len(steps[si]) <= seat:
                continue
            obs = steps[si][seat].get("observation")
            if not obs:
                continue
            inv = (obs.get("market") or {}).get("inventory") or {}
            rs = bucket.get(seat) or bucket.get(str(seat)) or {}
            for item, rec in (rs.get("sells") or {}).items():
                q = rec.get("qty", 0)
                start = int(inv.get(item, 0))
                out["inv_hist"][item][_bucket(start)] += q
                # Where the order ENDS. The engine quotes per unit, so a large
                # order walks the curve: a start at I0+20 can end at $1. DSM's
                # orders are small and never cross; ours are sentinel-sized.
                out["inv_hist_end"][item][_bucket(start + q)] += q
    # ---- per-game scalars for the robust distributions
    ends = [v[0] for v in out["shed_day"].values()]
    peaks = [v[1] for v in out["shed_day"].values()]
    out["sell_g"] = {k: list(v) for k, v in out["sell"].items()}
    carried_end = [v[2] for v in out["shed_day"].values() if len(v) > 2]
    syspeak = [v[4] for v in out["shed_day"].values() if len(v) > 4]
    out["shed_g"] = [_mean(ends), max(peaks) if peaks else 0,
                     _mean(carried_end), max(syspeak) if syspeak else 0]
    out["wheat_g"] = out["wheat"][0] / max(1, out["wheat"][1])
    out["yarn_sheep_g"] = (max((v[1] for v in out["days"].values()), default=0)
                           if out["yarn_day"] is not None else None)
    out["quad_g"] = int("SE" in out["quad_day"])
    return out


def _days_csv(days_glob, agent):
    acc = defaultdict(lambda: defaultdict(list))
    mix = defaultdict(lambda: defaultdict(float))
    for f in sorted(globmod.glob(days_glob)):
        for r in csv.DictReader(open(f)):
            if agent and r.get("agent") != agent:
                continue
            try:
                d = int(r["day"])
            except (KeyError, ValueError):
                continue
            for col in STRUCT:
                try:
                    acc[d][col].append(float(r.get(col) or 0))
                except ValueError:
                    pass
            key = (f, r.get("seed"))
            for prod in SELL_PRODUCTS:
                try:
                    mix[key][prod] += float(r.get(f"revenue_{prod}") or 0)
                except ValueError:
                    pass
    out = {d: {c: list(v) for c, v in cols.items()} for d, cols in acc.items()}
    return out, _mix(mix)


def _mix(mix):
    """Median per-game share of revenue per product (each game's own split)."""
    shares = defaultdict(list)
    for _k, byp in mix.items():
        tot = sum(byp.values())
        if tot <= 0:
            continue
        for prod, v in byp.items():
            shares[prod].append(100.0 * v / tot)
    out = {}
    for prod, v in shares.items():
        v = sorted(v)
        out[prod] = v[len(v) // 2] if v else 0.0
    return out


def _games_csv(run_dir):
    path = os.path.join(run_dir, "games.csv")
    if not os.path.isfile(path):
        return None
    acc = defaultdict(list)
    for r in csv.DictReader(open(path)):
        for col in GAMES_COLS:
            try:
                acc[col].append(float(r.get(col) or 0))
            except ValueError:
                pass
    out = {}
    for col, v in acc.items():
        v = sorted(v)
        if not v:
            continue
        q = lambda f: v[min(len(v) - 1, int(f * len(v)))]
        out[col] = {"median": q(.5), "p25": q(.25), "p75": q(.75), "p90": q(.90),
                    "mean": sum(v) / len(v), "min": v[0], "max": v[-1]}
    return out or None


def profile(name, replay_glob, days_glob, agent, workers=0, run_dir=None):
    paths = sorted(globmod.glob(replay_glob))
    agg = {"days": defaultdict(list), "ops": Counter(), "sell": {},
           "coop_day": Counter(), "land_day": Counter(), "games": 0,
           "crop_day": defaultdict(lambda: defaultdict(list)),
           "shed_day": defaultdict(list), "shed_comp": defaultdict(lambda: defaultdict(float)),
           "inv_hist": defaultdict(Counter), "inv_hist_end": defaultdict(Counter),
           "quad_day": defaultdict(list),
           "disc": Counter(), "wheat": [0, 0, 0], "yarn": 0, "src": "action",
           "sell_g": [], "shed_g": [], "wheat_g": [], "yarn_sheep_g": [], "quad_g": []}
    tasks = [(p, name) for p in paths]
    if workers == 0:
        workers = os.cpu_count() or 1
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_one, tasks):
            if not r:
                continue
            agg["games"] += 1
            agg["src"] = r["src"]
            for d, rec in r["days"].items():
                agg["days"][d].append(rec)
            for d, rec in r["crop_day"].items():
                agg["crop_day"][d]["_games"].append(1)
                for cr, n in rec.items():
                    agg["crop_day"][d][cr].append(n)
            for d, rec in r["shed_day"].items():
                while len(rec) < 5:
                    rec.append(0)
                agg["shed_day"][d].append(rec)
            for d, rec in r["shed_comp"].items():
                for k, v in rec.items():
                    agg["shed_comp"][d][k] += v
            for q, d in r["quad_day"].items():
                agg["quad_day"][q].append(d)
            for item, cnt in r["inv_hist"].items():
                agg["inv_hist"][item] += cnt
            for item, cnt in r["inv_hist_end"].items():
                agg["inv_hist_end"][item] += cnt
            agg["sell_g"].append(r["sell_g"])
            agg["shed_g"].append(r["shed_g"])
            agg["wheat_g"].append(r["wheat_g"])
            if r["yarn_sheep_g"] is not None:
                agg["yarn_sheep_g"].append(r["yarn_sheep_g"])
            agg["quad_g"].append(r["quad_g"])
            agg["disc"] += r["disc"]
            agg["wheat"] = [a + b for a, b in zip(agg["wheat"], r["wheat"])]
            if r["yarn_day"] is not None:
                agg["yarn"] += 1
            agg["ops"] += r["ops"]
            for k, v in r["sell"].items():
                cell = agg["sell"].setdefault(k, [0, 0.0, 0])
                cell[0] += v[0]; cell[1] += v[1]; cell[2] += v[2]
            agg["coop_day"] += r["coop_day"]; agg["land_day"] += r["land_day"]
    dc, mix = _days_csv(days_glob, agent)
    return {"name": name, "agg": agg, "days_csv": dc, "mix": mix,
            "games_csv": _games_csv(run_dir) if run_dir else None}


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def _q(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(f * len(xs)))] if xs else 0.0


def _band(xs, nd=1):
    """median [p25-p75] -- the robust replacement for mean. These metrics are
    bounded, discrete and often multi-modal (locked_steps: 37/78 games at exactly
    197), so mean+/-sd spans gaps where no game sits."""
    if not xs:
        return "-"
    return f"{_q(xs,.5):.{nd}f} [{_q(xs,.25):.{nd}f}-{_q(xs,.75):.{nd}f}]"


def _tail(xs, nd=0):
    """p90, for the tail that the median deliberately hides."""
    return f"{_q(xs,.90):.{nd}f}" if xs else "-"


def show(p):
    a = p["agg"]; g = max(1, a["games"])
    print(f"\n############ {p['name']}  (replay games={a['games']}) ############")
    print("-- structures per game (endgame mean) --")
    ndays = max(1, sum(len(v) for v in a["days"].values()))
    ce = sum(r[4] for v in a["days"].values() for r in v) / ndays
    pe = sum(r[3] for v in a["days"].values() for r in v) / ndays
    print(f"   COOP~{ce:.1f}  PASTURE~{pe:.1f}")
    print("-- herd per game (day10 / day16 / day29, median [p25-p75]) --")
    for d in (10, 16, 29):
        v = a["days"].get(d, [])
        if v:
            print(f"   d{d}: COW {_band([r[0] for r in v])}  "
                  f"SHEEP {_band([r[1] for r in v])}  GOOSE {_band([r[2] for r in v])}")
    print("-- coop builds / land buys by day --")
    print("   coop:", dict(sorted(a["coop_day"].items())))
    print("   land:", dict(sorted(a["land_day"].items())))
    print("-- quadrant unlock day (median, games with it / total) --")
    print("   " + "  ".join(f"{q}={_med(v):.0f} ({len(v)}/{a['games']})"
                            for q, v in sorted(a["quad_day"].items())))
    print("-- unit op mix (share) --")
    tot = sum(a["ops"].values()) or 1
    print("   " + "  ".join(f"{k}={100*v/tot:.0f}%" for k, v in a["ops"].most_common(12)))
    print(f"-- selling per game (src={a['src']}): units / px@sell / %at$1 floor, median [p25-p75] --")
    print("   product            units                  px@sell              floor%          floor%p90")
    for prod in SELL_PRODUCTS:
        G = [sg.get(prod, [0, 0.0, 0]) for sg in a["sell_g"]]
        units = [v[0] for v in G]
        px = [v[1] / v[0] for v in G if v[0]]
        fl = [100.0 * v[2] / v[0] for v in G if v[0]]
        if sum(units) <= 0:
            continue
        print(f"   {prod:11s} {_band(units):>22s} {_band(px):>22s} {_band(fl):>18s} {_tail(fl):>10s}")
    print("-- CROPS per game (mean tiles by day) + max single-crop share --")
    print("   day | " + "".join(f"{c[:6]:>8s}" for c in CROPS) + "   maxshare")
    for d in range(6, 30, 3):
        rec = a["crop_day"].get(d)
        if not rec:
            continue
        tots = {c: _mean(rec.get(c, [0])) for c in CROPS}
        s = sum(tots.values())
        share = (max(tots.values()) / s) if s else 0.0
        print(f"   {d:3d} | " + "".join(f"{tots[c]:8.1f}" for c in CROPS) + f"   {100*share:5.1f}%")
    print("-- SHED + CARRIED by day (mean shed end / shed peak / carried end / system peak) --")
    print("   day |   end  peak | carry |  SYSTEM | top items at day end")
    for d in range(6, 30, 3):
        v = a["shed_day"].get(d)
        if not v:
            continue
        comp = a["shed_comp"].get(d) or {}
        ct = sum(comp.values()) or 1
        top = "  ".join(f"{k}={100*x/ct:.0f}%" for k, x in
                        sorted(comp.items(), key=lambda kv: -kv[1])[:3])
        print(f"   {d:3d} | {_mean([r[0] for r in v]):5.1f} {_mean([r[1] for r in v]):5.1f} |"
              f" {_mean([r[2] for r in v]):5.1f} | {_mean([r[4] for r in v]):7.1f} | {top}")
    if a["shed_g"]:
        print(f"   end-of-day SHED    (per-game mean): {_band([r[0] for r in a['shed_g']])}  p90 {_tail([r[0] for r in a['shed_g']])}")
        print(f"   end-of-day CARRIED (per-game mean): {_band([r[2] for r in a['shed_g']])}  p90 {_tail([r[2] for r in a['shed_g']])}")
        print(f"   peak SHED          (per-game max) : {_band([r[1] for r in a['shed_g']])}  p90 {_tail([r[1] for r in a['shed_g']])}")
        print(f"   peak SYSTEM        (per-game max) : {_band([r[3] for r in a['shed_g']])}  p90 {_tail([r[3] for r in a['shed_g']])}")
        print("   NOTE: shed alone understates stock -- the market can only SELL from the")
        print("   shed, so units carried in hands are unsellable until dropped.")
    print("-- MARKET INVENTORY AT SELL (units by START bucket; END=-of-order >I0+100) --")
    print("   product      <I0   I0..+50  +50..+100   >I0+100 |  END>+100")
    for prod in SELL_PRODUCTS:
        h = a["inv_hist"].get(prod)
        if not h:
            continue
        row = [h.get(k, 0) / g for k in ("<I0", "I0..+50", "+50..+100", ">I0+100")]
        end = (a["inv_hist_end"].get(prod, {}) or {}).get(">I0+100", 0) / g
        print(f"   {prod:11s}" + "".join(f"{x:10.1f}" for x in row) + f" | {end:9.1f}")
    if a["disc"]:
        dt = sum(a["disc"].values())
        print("-- DISCARDS per game (units, and share of total) --")
        print("   " + "  ".join(f"{k}={v/g:.1f} ({100*v/dt:.0f}%)" for k, v in a["disc"].most_common()))
    if p["mix"]:
        print("-- REVENUE MIX (median per-game share) --")
        print("   " + "  ".join(f"{k}={p['mix'][k]:.1f}%" for k in
                               sorted(p["mix"], key=lambda k: -p["mix"][k])))
    b, f_, _s = a["wheat"]
    wsell = a["sell"].get("WHEAT", (0, 0, 0))[0] / g
    print(f"-- WHEAT per game: bought {b/g:.0f}  fed {f_/g:.0f}  sold {wsell:.0f}"
          f"   buy/feed={b/max(1,f_):.2f}")
    print(f"-- YARN_STORE present in {a['yarn']}/{a['games']} games")
    if p["games_csv"]:
        print("-- GUARDS from games.csv (median / mean / min / max) --")
        for k, v in p["games_csv"].items():
            print(f"   {k:24s} {v['median']:9.1f} {v['mean']:9.1f} {v['min']:9.1f} {v['max']:9.1f}")
    print("-- DISTRIBUTIONS across games (median [p25-p75], p90) --")
    if a["quad_g"]:
        print(f"   4 quadrants (% of games)            {100.0*_mean(a['quad_g']):.1f}%")
    if a["wheat_g"]:
        print(f"   wheat bought / fed                 {_band(a['wheat_g'],2)}   p90 {_tail(a['wheat_g'],2)}")
    if a["yarn_sheep_g"]:
        print(f"   SHEEP max, YARN worlds             {_band(a['yarn_sheep_g'])}   p90 {_tail(a['yarn_sheep_g'])}")
    if p["games_csv"]:
        for k, v in p["games_csv"].items():
            print(f"   {k:34s} {v['median']:8.1f} [{v['p25']:.1f}-{v['p75']:.1f}]   p90 {v['p90']:.1f}")
    print("-- structural per day (day CSV MEDIANS [p25-p75]) --")
    dc = p["days_csv"]
    print("   day | shed_max(p50[p25-p75])  shed_end  weeds   fert   watered  idle%")
    for d in range(6, 30, 3):
        c = dc.get(d)
        if not c:
            continue
        def b(col, nd=1):
            v = c.get(col) or []
            return _band(v, nd) if v else "-"
        print(f"   {d:3d} | {b('max_shed_total'):>21s}  {b('end_shed_total'):>13s}  "
              f"{b('weeds_max',2):>12s}  {b('plants_fertilized'):>12s}  "
              f"{b('plants_watered'):>13s}  {b('idle_share_pct',2)}")


def _dsm_dir():
    """DSM replays may live directly in replays/DSM or in a versioned subdir."""
    for cand in ("replays/DSM/v1", "replays/DSM"):
        if globmod.glob(f"{cand}/*.json"):
            return cand
    return "replays/DSM"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=("ours", "dsm"), default="dsm")
    ap.add_argument("--run-dir", default="diag-replays/run-5")
    ap.add_argument("--dsm-dir", default=None, help="DSM replay dir (default: replays/DSM/v1 if present)")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    want = ("ours", "dsm") if args.compare else (args.profile,)
    profs = []
    if "ours" in want:
        profs.append(profile("ours", f"{args.run_dir}/*_vs_*.json", f"{args.run_dir}/days_seed*.csv",
                             "old", args.workers, run_dir=args.run_dir))
    if "dsm" in want:
        d = args.dsm_dir or _dsm_dir()
        profs.append(profile("dsm", f"{d}/*.json", f"{d}/days_seed*.csv", "DSM", args.workers))
    for p in profs:
        show(p)


if __name__ == "__main__":
    main()
