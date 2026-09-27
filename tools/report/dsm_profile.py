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

Comparability contract (read before quoting a number)
----------------------------------------------------
Every arm prints five things the old report could not:

  * a POOL header -- replay JSONs, games.csv rows, EPISODES, opponents, the
    W/L/T episode tally and the YARN_STORE mix. An arm measured against ONE
    opponent has between-seed variance only and cannot be compared with an arm
    that spans 61 opponents; the header says which one you are looking at.
  * the five-number ladder `p10 p25 p50 p75 p90` on every per-game metric. p10
    is the number that decides "losses < $4k": a healthy median can still hide a
    deep loss tail. Per-day tables keep `median [p10-p90]` so rows stay legible.
  * a MARGIN block in the target's own terms (max loss, share losing >$4k,
    median win, share of wins >$30k).
  * a PER-OPPONENT table plus the MEDIAN-OF-PER-OPPONENT-MEDIANS. Aggregate per
    opponent, THEN average -- a pooled median folds between-opponent spread into
    the same number you are trying to read.
  * a games.csv filter by `agent`. A leaderboard games.csv holds BOTH seats of
    every episode (replays/DSM/v1/games.csv is 246 rows = 123 episodes x 2), so
    pooling every row would fold the opponent's bank and defects into ours.

Episodes, not rows, are the unit of a win tally: a pool run reuses the same
seed list for every opponent, so `(opponent, seed)` is the episode key.

Usage:
  PYTHONPATH=. python -m tools.report.dsm_profile --compare --run-dir=diag-replays/run-1
  PYTHONPATH=. python -m tools.report.dsm_profile --profile dsm
  # a 13-opponent pool arm (what a structural claim needs):
  PYTHONPATH=. python -m tools.report.dsm_profile --compare --run-dir=diag-replays/sweep_old_s4362837462_b15
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
import csv
import glob as globmod
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tools import diagnose

SELL_PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
STRUCT = ("max_shed_total", "end_shed_total", "weeds_max", "plants_fertilized",
          "plants_watered", "animals_fed", "animals_cared", "discarded_units",
          "hires", "idle_share_pct")
# Columns read from games.csv (per game, not per day). Absent for LB replay dirs.
# Split into two ladders so a defect cannot hide behind a cost:
#   GUARDS  -- physical defects (what went wrong)
#   LEDGER  -- the investment side (what we spent). Comparing spend is how you
#              see under-investment: DSM spends 40% more on seed and 29% more on
#              animals than we do, which is *why* its revenue is 30% higher.
GAMES_COLS = ("idle_units_ready_total", "locked_steps", "idle_share_pct",
              "discarded_units_total", "shed_overflow_days", "stranded_at_bell",
              "floor_sales", "animal_escapes", "at_risk_of_escape", "feed_surplus",
              "harvests", "missed_harvest_eod", "plants_died", "unwatered_eod",
              "unfed_signals", "weeds_peak",
              "sell_revenue_total")
LEDGER_COLS = ("seed_cost_total", "animal_cost_total", "product_cost_total",
               "hire_cost_total", "land_cost_total")
# land_cost_total is modelled for LB replays and reports up to 88,000 against a
# real 7,000 ceiling -- it is printed for our arm only.
I0 = 10000


def _seat_dsm(rep):
    names = (rep.get("info") or {}).get("TeamNames") or ["", ""]
    hits = team_mod.seats_of_names(names)
    if hits:
        return hits[0]
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
    # Opponent identity, so a games.csv written before the `opponent_idx` column
    # existed can still be grouped per opponent. LB replays carry no meta seed.
    meta = rep.get("_diagnose_meta") or {}
    names = (rep.get("info") or {}).get("TeamNames") or ["", ""]
    opp = meta.get("opponent")
    if opp is None:
        other = 1 - seat
        opp = names[other] if len(names) > other else ""
    idx = meta.get("opponent_idx")
    out["opp_idx"] = {(opp, str(meta.get("seed"))): idx} if idx not in (None, "") else {}
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


def _games_rows(run_dir, agent):
    """games.csv rows for ONE arm only.

    A leaderboard games.csv carries BOTH seats of every episode (the DSM dir's is
    246 rows = 123 episodes x 2 seats, with `agent` naming the row's OWN team),
    so pooling every row folds the opponent's bank and defect counts into our
    distribution. Keep only rows whose `agent` is this arm's agent -- and if that
    finds nothing, say so loudly instead of silently pooling.
    """
    if not run_dir:
        return []
    path = os.path.join(run_dir, "games.csv")
    if not os.path.isfile(path):
        return []
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    keep = [r for r in rows if (r.get("agent") or "") == agent]
    if keep:
        return keep
    labels = sorted({(r.get("agent") or "") for r in rows})
    alt = [a for a in labels if a and a != agent]
    if len(alt) == 1:
        keep = [r for r in rows if (r.get("agent") or "") == alt[0]]
        if keep:
            print(f"   ! games.csv has no agent={agent!r}; using agent={alt[0]!r} "
                  f"({len(keep)}/{len(rows)} rows) -- pass --agent to pin it")
            return keep
    if rows:
        print(f"   ! games.csv agents={labels} do not include {agent!r}; pooling all "
              f"{len(rows)} rows UNFILTERED -- the seat/opponent mix is not controlled")
    return rows


def _episode_key(r):
    """One key per episode. A pool run reuses the same seed list for every
    opponent, so `seed` alone is NOT unique -- (opponent, seed) is."""
    opp = (r.get("opponent") or "").strip()
    seed = (r.get("seed") or "").strip()
    return (opp, seed) if opp else (seed,)


def _margin(r):
    try:
        return float(r.get("final_money") or 0) - float(r.get("opponent_final") or 0)
    except (TypeError, ValueError):
        return None


def _rows_ladder(rows, cols):
    """{column: [values]} for the columns this games.csv actually carries."""
    header = set(rows[0].keys()) if rows else set()
    out = {}
    for col in cols:
        if col not in header:
            continue
        v = []
        for r in rows:
            try:
                v.append(float(r.get(col) or 0))
            except (TypeError, ValueError):
                pass
        if v:
            out[col] = v
    return out


def _normed(by_opp, agent, col):
    """median-of-per-opponent-medians for one column: each OPPONENT counts once.

    The frame is unbalanced by construction and they are not the same shape: our
    arm is 13 public agents x 15 seeds (balanced), DSM's is 67 ladder teams with
    1-14 games each. A pooled median over DSM's 124 rows is partly a description
    of the *matchmaking pool* -- 14 games against Majkel1337 outvote 1 game
    against Ebi. Taking each opponent's own median first removes that, so the
    two arms can be read side by side.
    """
    meds = []
    for opp, rs in by_opp.items():
        if opp == agent:
            continue
        v = []
        for r in rs:
            try:
                v.append(float(r.get(col) or 0))
            except (TypeError, ValueError):
                pass
        if v:
            meds.append(_q(v, .5))
    return _q(meds, .5) if meds else None


def _pool(rows, agent, games, yarn, yarngames):
    """What this arm is a sample OF -- the comparability check."""
    eps = {}
    for r in rows:
        eps.setdefault(_episode_key(r), r)
    by_opp = defaultdict(list)
    eps_by_opp = defaultdict(list)
    for r in rows:
        by_opp[r.get("opponent") or "unknown"].append(r)
    wins = losses = ties = 0
    eps_rows = []
    for r in eps.values():
        if (r.get("opponent") or "") == agent:
            continue  # self-play mirror: one guaranteed W and one guaranteed L
        eps_rows.append(r)
        eps_by_opp[r.get("opponent") or "unknown"].append(r)
        res = (r.get("result") or "").upper()
        wins += res == "WIN"
        losses += res == "LOSS"
        ties += res == "TIE"
    sizes = sorted((len(v) for v in eps_by_opp.values()), reverse=True)
    return {"rows": len(rows), "episodes": len(eps), "by_opp": by_opp,
            "eps_by_opp": eps_by_opp, "opp_sizes": sizes,
            "wins": wins, "losses": losses, "ties": ties,
            "mirrors": len(rows) - len(eps), "games": games,
            "yarn": yarn, "yarn_games": yarngames, "eps_rows": eps_rows}


def _opponent_table(rows, agent):
    """Per-opponent medians, then the median OF those -- never a pooled median."""
    by_opp = defaultdict(list)
    for r in rows:
        by_opp[r.get("opponent") or "unknown"].append(r)
    print(f"   {'opponent':32s} {'idx':>4s} {'n':>3s} {'W':>3s} {'L':>3s} {'T':>3s} "
          f"{'p10mgn':>9s} {'p50mgn':>9s} {'p90mgn':>9s} {'worst':>9s}")
    meds = []
    for opp, rs in sorted(by_opp.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if opp == agent:
            continue
        idx = next((r.get("opponent_idx") for r in rs if r.get("opponent_idx")), "")
        mgn = [m for m in (_margin(r) for r in rs) if m is not None]
        if not mgn:
            continue
        w = l = t = 0
        for r in rs:
            res = (r.get("result") or "").upper()
            w += res == "WIN"; l += res == "LOSS"; t += res == "TIE"
        meds.append(_q(mgn, .5))
        print(f"   {opp[:32]:32s} {str(idx):>4s} {len(rs):3d} {w:3d} {l:3d} {t:3d} "
              f"{_q(mgn,.10):9.0f} {_q(mgn,.5):9.0f} {_q(mgn,.90):9.0f} {min(mgn):9.0f}")
    if meds:
        print(f"   MEDIAN-OF-PER-OPPONENT-MEDIANS {_q(meds,.5):.0f}   "
              f"(best {max(meds):.0f} / worst {min(meds):.0f} over {len(meds)} opponents)")
        print("   (aggregate per opponent, THEN average -- a pooled median would fold")
        print("    between-opponent spread into the same number)")


def profile(name, replay_glob, days_glob, agent, workers=0, run_dir=None):
    paths = sorted(globmod.glob(replay_glob))
    agg = {"days": defaultdict(list), "ops": Counter(), "sell": {},
           "coop_day": Counter(), "land_day": Counter(), "games": 0,
           "crop_day": defaultdict(lambda: defaultdict(list)),
           "shed_day": defaultdict(list), "shed_comp": defaultdict(lambda: defaultdict(float)),
           "inv_hist": defaultdict(Counter), "inv_hist_end": defaultdict(Counter),
           "quad_day": defaultdict(list),
           "disc": Counter(), "wheat": [0, 0, 0], "yarn": 0, "src": "action",
           "sell_g": [], "shed_g": [], "wheat_g": [], "yarn_sheep_g": [], "quad_g": [],
           "opp_idx": {}}
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
            agg["opp_idx"].update(r.get("opp_idx") or {})
    dc, mix = _days_csv(days_glob, agent)
    rows = _games_rows(run_dir, agent)
    # Backfill opponent_idx for run dirs written before the column existed.
    for r in rows:
        if not r.get("opponent_idx"):
            key = (r.get("opponent") or "", str(r.get("seed")))
            if agg["opp_idx"].get(key) not in (None, ""):
                r["opponent_idx"] = agg["opp_idx"][key]
    return {"name": name, "agent": agent, "agg": agg, "days_csv": dc, "mix": mix,
            "games_rows": rows}


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


def _band1090(xs, nd=1):
    """median [p10-p90] -- the same shape, with the tail the median hides. Used
    for the per-day tables, where a full five-number ladder per cell would not
    fit on a line."""
    if not xs:
        return "-"
    return f"{_q(xs,.5):.{nd}f} [{_q(xs,.10):.{nd}f}-{_q(xs,.90):.{nd}f}]"


def _tail(xs, nd=0):
    """p90, for the tail that the median deliberately hides."""
    return f"{_q(xs,.90):.{nd}f}" if xs else "-"


# The five-number ladder. p10 is the number the old report could not show, and
# it is the one that decides "losses < $4k": a healthy median can still hide a
# tail deep enough to lose the match.
_PCTS = (.10, .25, .50, .75, .90)
LADDER_HDR = " ".join(f"{f'p{int(p*100)}':>9s}" for p in _PCTS)


def _ladder(xs, nd=1):
    """`p10 p25 p50 p75 p90`, fixed width so rows align under LADDER_HDR."""
    if not xs:
        return " " * len(LADDER_HDR)
    return " ".join(f"{_q(xs, p):>9.{nd}f}" for p in _PCTS)


def _row(label, xs, nd=1, width=26, hdr=False):
    """One labelled ladder row; `hdr=True` prints the column names instead."""
    return f"   {label:{width}s} {LADDER_HDR if hdr else _ladder(xs, nd)}"


def _srow(prod, lab, xs, nd=1, hdr=False):
    """Selling-table row: product, then the metric name within that product."""
    return f"   {prod:11s} {lab:8s} {LADDER_HDR if hdr else _ladder(xs, nd)}"


def show_pool(p, pool):
    """The comparability header -- print it BEFORE quoting any number."""
    print("-- POOL (what this arm is a sample OF) --")
    sizes = pool["opp_sizes"]
    n_opp = len([k for k in pool["by_opp"] if k != p["agent"]])
    self_play = len(pool["by_opp"]) - n_opp
    print(f"   replay JSONs {pool['games']}   games.csv rows {pool['rows']}   "
          f"episodes {pool['episodes']}   opponents {n_opp}"
          + (f"  (+{self_play} self-play)" if self_play else ""))
    if sizes:
        balanced = len(set(sizes)) == 1
        print(f"   frame: {len(sizes)} matchups, games each min {sizes[-1]} / max {sizes[0]}"
              f"  -> {'BALANCED' if balanced else 'UNBALANCED -- read the `norm` column'}")
    tally = pool["wins"] + pool["losses"] + pool["ties"]
    print(f"   episodes {pool['wins']}W {pool['losses']}L {pool['ties']}T   "
          f"win% {100.0*pool['wins']/max(1,tally):.1f}  (self-play excluded)")
    if pool["mirrors"]:
        print(f"   ! {pool['mirrors']} duplicate/self-play row(s) beyond the episode count"
              f" -- a mirror episode contributes a guaranteed W AND a guaranteed L")
    print(f"   shop mix: YARN_STORE present in {pool['yarn']}/{pool['yarn_games']} games")
    if len(pool["by_opp"]) <= 1:
        print("   ! SINGLE-OPPONENT ARM -- between-opponent variance is absent, so p10/p90")
        print("     below describe seed variance inside ONE matchup and are NOT comparable")
        print("     to a field sample. Structural claims need a multi-opponent run")
        print("     (e.g. ./scripts/sweep.sh old 4362837462 15)")


def show(p):
    a = p["agg"]; g = max(1, a["games"])
    rows = p.get("games_rows") or []
    pool = _pool(rows, p["agent"], a["games"], a["yarn"], a["games"])
    print(f"\n############ {p['name']}  (replay games={a['games']}) ############")
    show_pool(p, pool)

    print("-- structures per game (endgame mean) --")
    ndays = max(1, sum(len(v) for v in a["days"].values()))
    ce = sum(r[4] for v in a["days"].values() for r in v) / ndays
    pe = sum(r[3] for v in a["days"].values() for r in v) / ndays
    print(f"   COOP~{ce:.1f}  PASTURE~{pe:.1f}")
    print(f"-- herd per game (day10 / day16 / day29; ladder {LADDER_HDR.strip()}) --")
    for d in (10, 16, 29):
        v = a["days"].get(d, [])
        if not v:
            continue
        for i, sp in enumerate(("COW", "SHEEP", "GOOSE")):
            print(_row(f"d{d} {sp}", [r[i] for r in v], 1, 10))
    print("-- coop builds / land buys by day --")
    print("   coop:", dict(sorted(a["coop_day"].items())))
    print("   land:", dict(sorted(a["land_day"].items())))
    print("-- quadrant unlock day (median, games with it / total) --")
    print("   " + "  ".join(f"{q}={_med(v):.0f} ({len(v)}/{a['games']})"
                            for q, v in sorted(a["quad_day"].items())))
    print("-- unit op mix (share) --")
    tot = sum(a["ops"].values()) or 1
    print("   " + "  ".join(f"{k}={100*v/tot:.0f}%" for k, v in a["ops"].most_common(12)))
    print(f"-- selling per game (src={a['src']}): units / px@sell / %at$1 floor --")
    print(_srow("", "", None, hdr=True))
    for prod in SELL_PRODUCTS:
        G = [sg.get(prod, [0, 0.0, 0]) for sg in a["sell_g"]]
        units = [v[0] for v in G]
        px = [v[1] / v[0] for v in G if v[0]]
        fl = [100.0 * v[2] / v[0] for v in G if v[0]]
        if sum(units) <= 0:
            continue
        print(_srow(prod, "units", units))
        print(_srow("", "px@sell", px))
        print(_srow("", "floor%", fl))
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
        print(_row("", None, hdr=True, width=22))
        for lab, i in (("end-of-day SHED", 0), ("peak SHED", 1),
                       ("end-of-day CARRIED", 2), ("peak SYSTEM", 3)):
            print(_row(lab, [r[i] for r in a["shed_g"]], 1, 22))
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
    else:
        print("-- REVENUE MIX -- unavailable: leaderboard replays carry no market audit, so")
        print("   every per-day revenue_<product> column is 0. Use")
        print("   `python -m tools.report.dsm_flows --summary` for DSM's mix (modelled).")
    b, f_, _s = a["wheat"]
    wsell = a["sell"].get("WHEAT", (0, 0, 0))[0] / g
    print(f"-- WHEAT per game: bought {b/g:.0f}  fed {f_/g:.0f}  sold {wsell:.0f}"
          f"   buy/feed={b/max(1,f_):.2f}")

    if rows:
        # Episode-deduped, mirror-excluded: the same row set the POOL tally uses,
        # so the win% here cannot disagree with the win% up there.
        er = pool["eps_rows"]
        mgn = [m for m in (_margin(r) for r in er) if m is not None]
        print(f"-- GUARDS from games.csv (n={len(er)} episodes; ladder {LADDER_HDR.strip()}; "
              f"norm = per-opponent median) --")
        for k, v in _rows_ladder(er, GAMES_COLS).items():
            if k == "sell_revenue_total" and not any(v):
                print(_row(k, v, 1, 26) + "  | no market audit on these replays")
                continue
            nv = _normed(pool["eps_by_opp"], p["agent"], k)
            print(_row(k, v, 1, 26) + (f"  | {nv:9.1f}" if nv is not None else ""))
        led = _rows_ladder(er, LEDGER_COLS)
        if led:
            print(f"-- LEDGER (investment per game; ladder {LADDER_HDR.strip()}; "
                  f"norm = per-opponent median) --")
            for k, v in led.items():
                if k == "land_cost_total" and p["name"] == "dsm":
                    continue  # modelled for LB replays: up to 88,000 vs a 7,000 ceiling
                nv = _normed(pool["eps_by_opp"], p["agent"], k)
                print(_row(k, v, 0, 26) + (f"  | {nv:9.0f}" if nv is not None else ""))
            cols = [c for c in led if c != "land_cost_total"]
            if cols:
                tot = []
                for r in er:
                    s = 0.0
                    for c in cols:
                        try:
                            s += float(r.get(c) or 0)
                        except (TypeError, ValueError):
                            pass
                    tot.append(s)
                print(_row("input spend (excl. land)", tot, 0, 26))
        if mgn:
            wins = [m for m in mgn if m > 0]
            loss = [m for m in mgn if m < 0]
            print(f"-- MARGIN (final_money - opponent_final; n={len(mgn)}; ladder {LADDER_HDR.strip()}) --")
            print(_row("all games", mgn, 0, 26))
            if wins:
                print(_row("wins", wins, 0, 26))
            if loss:
                print(_row("losses", loss, 0, 26))
            print(f"   TARGET READ p10 {_q(mgn,.10):.0f}   max loss {min(mgn):.0f}   "
                  f"losing < -$4k: {100.0*sum(1 for m in mgn if m < -4000)/len(mgn):.1f}%")
            print(f"   TARGET READ median win {_med(wins):.0f}   wins > $30k: "
                  f"{100.0*sum(1 for m in wins if m > 30000)/max(1,len(wins)):.1f}%   "
                  f"win% {100.0*len(wins)/len(mgn):.1f}")
            nmeds = []
            for opp, rs in pool["eps_by_opp"].items():
                if opp == p["agent"]:
                    continue
                mm = [m for m in (_margin(r) for r in rs) if m is not None]
                if mm:
                    nmeds.append(_med(mm))
            if nmeds:
                print(f"   NORMALISED margin = median of the {len(nmeds)} per-opponent "
                      f"medians: {_med(nmeds):.0f}   (best {max(nmeds):.0f} / "
                      f"worst {min(nmeds):.0f})")
    else:
        print("-- GUARDS from games.csv -- none (no games.csv for this arm) --")
    print(f"-- DISTRIBUTIONS across games (ladder {LADDER_HDR.strip()}) --")
    if a["quad_g"]:
        print(f"   4 quadrants (% of games)             {100.0*_mean(a['quad_g']):.1f}%")
    if a["wheat_g"]:
        print(_row("wheat bought / fed", a["wheat_g"], 2, 32))
    if a["yarn_sheep_g"]:
        print(_row("SHEEP max, YARN worlds", a["yarn_sheep_g"], 1, 32))
    print("-- structural per day (day CSV MEDIAN [p10-p90]) --")
    dc = p["days_csv"]
    print("   day | shed_max(med[p10-p90])  shed_end  weeds   fert   watered  idle%")
    for d in range(6, 30, 3):
        c = dc.get(d)
        if not c:
            continue
        def b(col, nd=1):
            v = c.get(col) or []
            return _band1090(v, nd) if v else "-"
        print(f"   {d:3d} | {b('max_shed_total'):>25s}  {b('end_shed_total'):>17s}  "
              f"{b('weeds_max',2):>16s}  {b('plants_fertilized'):>16s}  "
              f"{b('plants_watered'):>17s}  {b('idle_share_pct',2)}")
    if rows:
        print(f"-- PER-OPPONENT ({len(pool['by_opp'])} opponents) --")
        _opponent_table(pool["eps_rows"], p["agent"])


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
    ap.add_argument("--agent", default="old",
                    help="games.csv `agent` label for the ours arm (old/new); the arm's "
                         "own rows are selected so the opponent's seat is never pooled in")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--team", default=None,
                    help="leaderboard team to analyse (default: DSM / $KAGG_OPPONENT)")
    args = ap.parse_args()
    team_mod.set_team(args.team)
    want = ("ours", "dsm") if args.compare else (args.profile,)
    profs = []
    if "ours" in want:
        profs.append(profile("ours", f"{args.run_dir}/*_vs_*.json", f"{args.run_dir}/days_seed*.csv",
                             args.agent, args.workers, run_dir=args.run_dir))
    if "dsm" in want:
        d = args.dsm_dir or _dsm_dir()
        # run_dir is passed for the DSM arm too: replays/DSM/v1/games.csv holds
        # both seats of every episode, and the `agent == "DSM"` filter in
        # _games_rows is what keeps it to DSM's own 124 rows / 123 episodes.
        profs.append(profile("dsm", f"{d}/*.json", f"{d}/days_seed*.csv", team_mod.get(),
                             args.workers, run_dir=d))
    for p in profs:
        show(p)


if __name__ == "__main__":
    main()
