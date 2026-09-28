#!/usr/bin/env python
"""boey_priors — the reference's own policy, extracted as a prior table.

Why this exists
---------------
`boey_model.py` induces a knowledge graph, but only over d6-d17 and only for the herd gate,
the land days and the yarn split. A money-first planner needs the WHOLE decision surface as
a starting policy: how much cash he holds, when he buys which land, what herd he runs
conditioned on the shops that have actually unlocked, how much stock he keeps in the shed,
and when he starts fertilising.

Every row here is a measured prior with support, not a guess, and it is the DEFAULT the
planner starts from -- `src/priors.py` loads the emitted JSON and the money model may only
leave it inside a tolerance band with a priced NPV.

What it measures
----------------
  cash_hold   money at end of day: p10 / median / p90            (how much to hold)
  land        day each BUY_LAND fires, and the quadrant order    (timing; the order is
                                                                  engine-fixed)
  herd        animals by species, per day, and CONDITIONED on the shop set unlocked by
              then (YARN -> sheep, PIZZA/ICE_CREAM/SMOOTHIE -> cow, BAKERY/BRUNCH -> goose)
  crops       wheat / strawberry / planted / empty per day
  hires       HIRE orders per day
  fert        FERTILIZE ops per day, and the animal count on days with and without
  shed        shed units per item per day                        (the hold levels)
  shops       first day each shop is seen, and its frequency

Usage
-----
  PYTHONPATH=. python -m tools.phases.boey_priors --ref-max 60          # quick
  PYTHONPATH=. python -m tools.phases.boey_priors --all --workers 8     # the full 359
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import json
import multiprocessing as mp
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS    # noqa: E402
from tools import team as team_mod                                          # noqa: E402
from tools.diagnose.window import in_window, parse_days                     # noqa: E402
from tools.phases.boey_model import _animal_counts                          # noqa: E402

DAY = 24
SPECIES = ("COW", "SHEEP", "GOOSE")
# The shop -> species coupling the planner needs, taken from the engine's SHOPS table.
SHOP_SPECIES = {
    "YARN_STORE": "SHEEP", "PIZZA_SHOP": "COW", "ICE_CREAM_SHOP": "COW",
    "SMOOTHIE_SHOP": "COW", "BAKERY": "GOOSE", "BRUNCH_SPOT": "GOOSE",
}


def _context(obs, seat):
    farm = obs["farms"][seat]
    unlocked = set(farm.get("unlocked_quadrants") or [])
    crops = collections.Counter()
    planted = empty = structs = 0
    for y, row in enumerate(farm["tiles"]):
        for x, t in enumerate(row):
            owned = (("N" if y < 5 else "S") + ("W" if x < 5 else "E")) in unlocked
            if isinstance(t, dict):
                if t.get("kind") == "PLANT":
                    planted += 1
                    crops[t["crop"]] += 1
                elif t.get("kind") in ("COOP", "PASTURE"):
                    structs += 1
            elif t is None and owned:
                empty += 1
    priv = obs.get("private") or {}
    shops = sorted({str(s) for s in ((obs.get("town") or {}).get("unlocked_shops") or [])})
    animals = _animal_counts(obs, seat)
    return {
        "money": float(farm.get("money") or 0.0),
        "animals": {a: int(animals.get(a, 0)) for a in SPECIES},
        "total_animals": int(sum(animals.get(a, 0) for a in SPECIES)),
        "wheat_tiles": crops.get("WHEAT", 0),
        "straw_tiles": crops.get("STRAWBERRY", 0),
        "planted": planted, "empty": empty, "structs": structs,
        "quadrants": tuple(farm.get("unlocked_quadrants") or []),
        "n_quadrants": len(farm.get("unlocked_quadrants") or []),
        "shops": shops,
        "shed": {k: int(v) for k, v in (priv.get("shed") or {}).items() if v > 0},
    }


def scan_one(path, seat_mode, win):
    try:
        rep = json.load(open(path))
    except Exception:                                  # noqa: BLE001
        return None
    steps = rep["steps"] if isinstance(rep, dict) else rep.steps
    if not steps or len(steps[0]) < 2:
        return None
    names = (rep.get("info") or {}).get("TeamNames") or []
    seat = team_mod.seat_of_names(names, fallback=0) if seat_mode == "auto" else int(seat_mode)
    ctx, acts = {}, collections.defaultdict(collections.Counter)
    for t in range(len(steps) - 1):
        obs = steps[t][seat].get("observation")
        if not obs:
            continue
        d = t // DAY
        if not in_window(d, win):
            continue
        if d not in ctx:
            ctx[d] = _context(obs, seat)
        act = steps[t + 1][seat].get("action") or {}
        rec = acts[d]
        for o in (act.get("market") or []):
            if not o:
                continue
            if o[0] == "BUY_LAND":
                rec["buy_land"] += 1
            elif o[0] == "HIRE":
                rec["hire"] += 1
            elif o[0] == "BUY_ANIMAL" and len(o) >= 3:
                rec["buy_" + str(o[1])] += int(o[2])
            elif o[0] == "SELL" and len(o) >= 3:
                rec["sell_" + str(o[1])] += int(o[2])
        for c in ([act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])):
            if c and c[0] == "FERTILIZE":
                rec["fert"] += 1
    if not ctx:
        return None
    return {"file": Path(path).name, "ctx": ctx, "acts": acts}


def _worker(task):
    path, seat_mode, win = task
    return scan_one(path, seat_mode, win)


def _pct(vals, q):
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * (len(v) - 1)))]


def _dist(rows, key):
    """{day: {'p10':..,'median':..,'p90':..,'n':..}} for ctx[key]."""
    per = collections.defaultdict(list)
    for r in rows:
        for d, c in r["ctx"].items():
            v = c.get(key)
            if isinstance(v, (dict, tuple, list)):
                continue
            per[d].append(v)
    return {str(d): {"p10": round(_pct(v, .1), 1), "median": round(st.median(v), 1),
                     "p90": round(_pct(v, .9), 1), "n": len(v)}
            for d, v in sorted(per.items())}


def _dist_species(rows, species, cond_fn=None):
    per = collections.defaultdict(list)
    for r in rows:
        for d, c in r["ctx"].items():
            if cond_fn is not None and not cond_fn(c):
                continue
            per[d].append(c["animals"].get(species, 0))
    if not per:
        return {}
    return {str(d): round(st.median(v), 1) for d, v in sorted(per.items())}


def build(rows, win):
    days = sorted({d for r in rows for d in r["ctx"]})
    out = {"games": len(rows), "days": [min(days), max(days)] if days else [0, 0]}
    out["cash_hold"] = _dist(rows, "money")
    out["total_animals"] = _dist(rows, "total_animals")
    out["crops"] = {k: _dist(rows, k) for k in
                    ("wheat_tiles", "straw_tiles", "planted", "empty", "structs",
                     "n_quadrants")}
    # herd, split by whether YARN has unlocked BY THAT DAY
    out["herd_yarn"] = {s: _dist_species(rows, s, lambda c: "YARN_STORE" in c["shops"])
                        for s in SPECIES}
    out["herd_noyarn"] = {s: _dist_species(rows, s, lambda c: "YARN_STORE" not in c["shops"])
                          for s in SPECIES}
    out["herd_all"] = {s: _dist_species(rows, s) for s in SPECIES}
    # per shop: median species on days the shop IS unlocked vs is NOT
    by_shop = {}
    for shop, sp in SHOP_SPECIES.items():
        yes = [c["animals"].get(sp, 0) for r in rows for c in r["ctx"].values()
               if shop in c["shops"]]
        no = [c["animals"].get(sp, 0) for r in rows for c in r["ctx"].values()
              if shop not in c["shops"]]
        if yes:
            by_shop[shop] = {"species": sp, "median_with": round(st.median(yes), 1),
                             "median_without": round(st.median(no), 1) if no else None,
                             "support": len(yes)}
    out["herd_by_shop"] = by_shop
    # land timing + quadrant order
    land_days = collections.Counter()
    cum = collections.defaultdict(list)
    for r in rows:
        tot = 0
        for d in sorted(r["acts"]):
            n = r["acts"][d].get("buy_land", 0)
            if n:
                land_days[d] += n
            tot += n
            cum[d].append(tot)
    out["land"] = {
        "buy_day_counts": {str(d): land_days[d] for d in sorted(land_days)},
        "cum_buys_by_day": {str(d): round(st.median(v), 1) for d, v in sorted(cum.items())},
        "final_quadrant_order": _top(
            collections.Counter(str(r["ctx"][max(r["ctx"])]["quadrants"]) for r in rows)),
    }
    out["hires"] = {str(d): round(st.median(v), 1)
                    for d, v in _per_day_action(rows, "hire").items()}
    out["fert"] = {str(d): round(st.median(v), 1)
                   for d, v in _per_day_action(rows, "fert").items()}
    # fertilise vs animal count: does he fertilise once the herd is big?
    with_fert = [c["total_animals"] for r in rows for d, c in r["ctx"].items()
                 if r["acts"].get(d, {}).get("fert", 0) > 0]
    no_fert = [c["total_animals"] for r in rows for d, c in r["ctx"].items()
               if r["acts"].get(d, {}).get("fert", 0) == 0]
    out["fert_gate"] = {"animals_median_when_fert": round(st.median(with_fert), 1)
                        if with_fert else None,
                        "animals_median_when_no_fert": round(st.median(no_fert), 1)
                        if no_fert else None,
                        "n_fert_days": len(with_fert)}
    # shed hold levels per item per day
    shed = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        for d, c in r["ctx"].items():
            for item, n in c["shed"].items():
                shed[item][d].append(n)
    out["shed_hold"] = {item: {str(d): round(st.median(v), 1) for d, v in sorted(dd.items())}
                        for item, dd in sorted(shed.items())}
    # shops: first day seen + frequency
    first, freq = {}, collections.Counter()
    for r in rows:
        seen = set()
        for d, c in r["ctx"].items():
            for s in c["shops"]:
                freq[s] += 1
                if s not in seen:
                    seen.add(s)
                    first.setdefault(s, []).append(d)
    out["shops"] = {"first_day_median": {s: round(st.median(v), 1) for s, v in first.items()},
                    "day_frequency": dict(freq)}
    out["window"] = str(win)
    return out


def _per_day_action(rows, key):
    per = collections.defaultdict(list)
    for r in rows:
        for d in r["ctx"]:
            per[d].append(r["acts"].get(d, {}).get(key, 0))
    return {d: v for d, v in sorted(per.items())}


def _top(counter, n=3):
    return [{"value": k, "n": v} for k, v in counter.most_common(n)]


def emit_md(model, out_path):
    L = [f"# Boey priors (auto) — {model['games']} games, d{model['days'][0]}-d{model['days'][1]}",
         ""]
    L.append("## Cash hold (money at end of day)")
    L.append("| day | p10 | median | p90 |")
    L.append("|---|---|---|---|")
    for d, v in model["cash_hold"].items():
        L.append(f"| d{d} | {v['p10']:,.0f} | {v['median']:,.0f} | {v['p90']:,.0f} |")
    L += ["", "## Herd by species, conditioned on YARN unlocked by that day"]
    L.append("| day | " + " | ".join(f"{s} yarn" for s in SPECIES)
             + " | " + " | ".join(f"{s} no-yarn" for s in SPECIES) + " |")
    L.append("|" + "---|" * (2 * len(SPECIES) + 1))
    days = sorted({int(d) for s in SPECIES for d in model["herd_yarn"].get(s, {})})
    for d in days:
        row = [f"d{d}"]
        for s in SPECIES:
            row.append(str(model["herd_yarn"].get(s, {}).get(str(d), "-")))
        for s in SPECIES:
            row.append(str(model["herd_noyarn"].get(s, {}).get(str(d), "-")))
        L.append("| " + " | ".join(row) + " |")
    L += ["", "## Herd response per shop (median species count)"]
    L.append("| shop | species | with shop | without | support |")
    L.append("|---|---|---|---|---|")
    for shop, v in model["herd_by_shop"].items():
        L.append(f"| {shop} | {v['species']} | {v['median_with']} | "
                 f"{v['median_without']} | {v['support']} |")
    L += ["", "## Land", f"final quadrant order: `{model['land']['final_quadrant_order']}`", "",
          "| day | buys | cumulative |", "|---|---|---|"]
    for d in sorted(set(model["land"]["buy_day_counts"]) | set(model["land"]["cum_buys_by_day"]),
                    key=int):
        L.append(f"| d{d} | {model['land']['buy_day_counts'].get(d, 0)} | "
                 f"{model['land']['cum_buys_by_day'].get(d, 0)} |")
    L += ["", "## Fertilise gate",
          f"- median animals on days WITH fertilize ops: "
          f"**{model['fert_gate']['animals_median_when_fert']}**",
          f"- median animals on days with NONE: "
          f"**{model['fert_gate']['animals_median_when_no_fert']}**",
          f"- fert days sampled: {model['fert_gate']['n_fert_days']}"]
    L += ["", "## Shed hold levels (median units, mid-game)", "",
          "| item | " + " | ".join(f"d{d}" for d in range(6, 20, 2)) + " |",
          "|" + "---|" * 8]
    for item, dd in model["shed_hold"].items():
        row = [item]
        for d in range(6, 20, 2):
            row.append(str(dd.get(str(d), 0)))
        L.append("| " + " | ".join(row) + " |")
    Path(out_path).write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--ref-max", type=int, default=60)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seat", default="auto")
    ap.add_argument("--days", default="0-29")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out-json", default="docs/boey_priors.json")
    ap.add_argument("--out-md", default="docs/boey_priors.md")
    ap.add_argument("--team", default=None)
    a = ap.parse_args(argv)
    team_mod.set_team(a.team or "Boey")
    win = parse_days(a.days)
    paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))
    if not a.all:
        paths = paths[:a.ref_max]
    print(f"# boey_priors  {len(paths)} episodes  d{a.days}")
    tasks = [(p, a.seat, win) for p in paths]
    w = int(a.workers or 0)
    if w <= 1 or len(tasks) <= 1:
        rows = [_worker(t) for t in tasks]
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=min(w, len(tasks))) as pool:
            rows = list(pool.imap_unordered(_worker, tasks))
    rows = [r for r in rows if r]
    if not rows:
        print("no data")
        return 1
    model = build(rows, win)
    Path(a.out_json).write_text(json.dumps(model, indent=1, default=str))
    emit_md(model, a.out_md)
    print(f"   games {model['games']}  days {model['days']}")
    ch = model["cash_hold"]
    print("   cash hold:", {d: ch[d]["median"] for d in ("0", "5", "10", "15", "20", "25", "29")
                            if d in ch})
    print("   land buys/day:", model["land"]["buy_day_counts"])
    print("   final quadrant order:", model["land"]["final_quadrant_order"])
    print("   fert gate:", model["fert_gate"])
    print(f"wrote {a.out_json} and {a.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
