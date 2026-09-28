#!/usr/bin/env python
"""boey_model — induce a midgame knowledge graph from an arm's replays.

Why this exists
---------------
`dag.py` is the structure WE believe; `divergence` says when each node crosses. Neither
reads the reference's own decision policy out of his games. This does: it parses his replays
into (context -> action) records, induces the thresholds and targets he actually runs, and
emits a knowledge graph with support and confidence on every edge. Run it with `--seat 1`
over our own arm and the two graphs diff into the clone worklist (W3).

What it emits
-------------
  * per-day state (medians): land, herd by species, crops, ops
  * timing: the day each quadrant is bought, the herd ramp, first-yield events
  * induced rules: for each decision, a threshold scan over the state variable that the
    GAME says gates it, with precision/recall and the support behind it. The herd gate is
    the important one -- it tests our assumed `WHEAT_TILES_PER_ANIMAL` against his play.
  * `docs/boey_kg.json` (machine-readable) and `docs/boey_kg.md` (readable)

It is descriptive: it reports what he does, with the support, and never asserts a cause the
data does not carry. Edges are tagged `engine` (a rule true by construction, shared with
`propagation_rules.py`) or `learned` (induced here).

Usage
-----
  PYTHONPATH=. python -m tools.phases.boey_model --ref-from replays/Boey/v1 --ref-max 120
  PYTHONPATH=. python -m tools.phases.boey_model --dir /tmp/w1-base --seat 1 --label ours
"""
from __future__ import annotations

import argparse
import collections
import glob as globmod
import json
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from kaggle_environments.envs.kaggriculture.kaggriculture import ANIMALS   # noqa: E402

from tools import team as team_mod                                          # noqa: E402
from tools.diagnose.window import in_window, parse_days                     # noqa: E402

DAY = 24


def _animal_counts(obs, seat):
    c = collections.Counter({"COW": 0, "SHEEP": 0, "GOOSE": 0})
    for row in obs["farms"][seat]["tiles"]:
        for t in row:
            if isinstance(t, dict) and "animal" in t:
                c[t["animal"]] += 1
    priv = obs.get("private") or {}
    for a, n in (priv.get("shed") or {}).items():
        if a in ANIMALS:
            c[a] += int(n)
    for inv in (priv.get("inventories") or []):
        for a, n in (inv or {}).items():
            if a in ANIMALS:
                c[a] += int(n)
    return c


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
    shops = [str(s) for s in ((obs.get("town") or {}).get("unlocked_shops") or [])]
    return {
        "money": float(farm.get("money") or 0.0),
        "animals": _animal_counts(obs, seat),
        "wheat_tiles": crops.get("WHEAT", 0),
        "straw_tiles": crops.get("STRAWBERRY", 0),
        "planted": planted,
        "empty": empty,
        "structs": structs,
        "quadrants": len(farm.get("unlocked_quadrants") or []),
        "yarn": int(any("YARN" in s for s in shops)),
        "shops": shops,
        "shed_wheat": int((priv.get("shed") or {}).get("WHEAT", 0)),
    }


def scan(paths, seat_mode, win):
    """One pass per replay -> per-day records + per-day action counts."""
    ctx_days = []          # list of dicts: per-game {day: context}
    acts_days = []         # list of dicts: per-game {day: Counter}
    meta = []
    for p in paths:
        try:
            rep = json.load(open(p))
        except Exception:
            continue
        steps = rep["steps"] if isinstance(rep, dict) else rep.steps
        if not steps or len(steps[0]) < 2:
            continue
        names = (rep.get("info") or {}).get("TeamNames") or []
        seat = team_mod.seat_of_names(names, fallback=0) if seat_mode == "auto" else int(seat_mode)
        ctx, acts = {}, collections.defaultdict(collections.Counter)
        first_yield = {}
        for t in range(len(steps) - 1):
            obs = steps[t][seat].get("observation")
            act = steps[t + 1][seat].get("action") or {}
            if not obs:
                continue
            d = t // DAY
            if not in_window(d, win):
                continue
            if d not in ctx:
                ctx[d] = _context(obs, seat)
            rec = acts[d]
            for o in (act.get("market") or []):
                if not o:
                    continue
                if o[0] == "BUY_ANIMAL" and len(o) >= 3:
                    rec["buy_" + str(o[1])] += int(o[2])
                elif o[0] == "BUY_LAND":
                    rec["buy_land"] += 1
                elif o[0] == "HIRE":
                    rec["hire"] += 1
                elif o[0] == "BUY_PRODUCT" and len(o) >= 3 and o[1] == "WHEAT":
                    rec["buy_wheat"] += int(o[2])
            cmds = [act.get("farmer") or ["PASS"]] + list(act.get("hands") or [])
            for c in cmds:
                if not c:
                    continue
                if c[0] == "PLANT" and len(c) > 1:
                    rec["plant_" + str(c[1])] += 1
                elif c[0] == "FERTILIZE":
                    rec["fert"] += 1
                elif c[0] == "BUILD_COOP":
                    rec["build_coop"] += 1
                elif c[0] == "BUILD_PASTURE":
                    rec["build_pasture"] += 1
            # first crop-yield day per species (first production event seen)
            for a in ("COW", "SHEEP", "GOOSE"):
                if a not in first_yield and ctx[d]["animals"][a] > 0:
                    first_yield[a] = d
        if ctx:
            ctx_days.append(ctx)
            acts_days.append(acts)
            meta.append({"file": Path(p).name, "days": sorted(ctx), "first_yield": first_yield,
                         "yarn": max((c["yarn"] for c in ctx.values()), default=0)})
    return ctx_days, acts_days, meta


def _med(vals):
    return st.median(vals) if vals else 0.0


def _series(ctx_days, key_fn):
    per = collections.defaultdict(list)
    for ctx in ctx_days:
        for d, c in ctx.items():
            per[d].append(key_fn(c))
    return {d: _med(v) for d, v in sorted(per.items())}


def _herd_threshold(ctx_days, acts_days, kmin=0.8, kmax=3.0, step=0.05):
    """Scan `wheat_tiles >= k * (animals+1)` as a predictor of an animal buy that day.

    This tests OUR assumed gate (`WHEAT_TILES_PER_ANIMAL = 1.7`) against what he runs.
    Precision/recall are per game-day; a rule that fires on almost every day has high
    recall and low precision and is not a gate.
    """
    obs_rows = []
    for ctx, acts in zip(ctx_days, acts_days):
        for d, c in ctx.items():
            bought = sum(v for k, v in acts.get(d, {}).items() if k.startswith("buy_"))
            herd = sum(c["animals"].values())
            obs_rows.append((c["wheat_tiles"], herd, bought > 0, d, c["money"]))
    pos = [r for r in obs_rows if r[2]]
    if not pos:
        return None, {"buy_days": 0, "days": len(obs_rows)}
    best = None
    k = kmin
    while k <= kmax + 1e-9:
        tp = fp = fn = tn = 0
        for (w, herd, bought, _d, _m) in obs_rows:
            pred = w >= k * (herd + 1)
            if pred and bought:
                tp += 1
            elif pred and not bought:
                fp += 1
            elif not pred and bought:
                fn += 1
            else:
                tn += 1
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if best is None or f1 > best[0]:
            best = (f1, round(k, 2), prec, rec, tp, fp, fn, tn)
        k += step
    # how does the buy RATE depend on the ratio? A gate shows a step; no gate shows a flat
    # rate. This is the read that says whether the constraint is real.
    buckets = [(0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 99.0)]
    rate = {}
    for lo, hi in buckets:
        rows = [r for r in obs_rows if lo <= r[0] / (r[1] + 1) < hi]
        if rows:
            rate[f"{lo}-{hi}"] = [len(rows), sum(1 for r in rows if r[2]),
                                  round(sum(1 for r in rows if r[2]) / len(rows), 2)]
    # what ratio does he actually hold on the days he buys, and overall?
    ratios = [w / (herd + 1) for (w, herd, _b, _d, _m) in obs_rows]
    pos_ratios = [w / (herd + 1) for (w, herd, b, _d, _m) in obs_rows if b]
    return {
        "best_f1": round(best[0], 3), "k": best[1], "precision": round(best[2], 3),
        "recall": round(best[3], 3), "tp": best[4], "fp": best[5], "fn": best[6],
        "tn": best[7],
        "buy_days": len(pos), "days": len(obs_rows),
        "ratio_median_all": round(_med(ratios), 2),
        "ratio_median_buy_days": round(_med(pos_ratios), 2),
        "buy_rate_by_ratio_bucket": rate,
    }, None


def build(ctx_days, acts_days, meta):
    model = {"games": len(ctx_days), "edges": [], "series": {}, "rules": {}}
    ser = model["series"]
    for name, fn in (
        ("animals", lambda c: sum(c["animals"].values())),
        ("cow", lambda c: c["animals"]["COW"]), ("sheep", lambda c: c["animals"]["SHEEP"]),
        ("goose", lambda c: c["animals"]["GOOSE"]),
        ("wheat_tiles", lambda c: c["wheat_tiles"]),
        ("straw_tiles", lambda c: c["straw_tiles"]),
        ("planted", lambda c: c["planted"]), ("empty", lambda c: c["empty"]),
        ("structs", lambda c: c["structs"]), ("quadrants", lambda c: c["quadrants"]),
        ("money", lambda c: c["money"]), ("yarn", lambda c: c["yarn"]),
    ):
        ser[name] = {int(d): round(v, 1) for d, v in _series(ctx_days, fn).items()}
    for op in ("plant_WHEAT", "plant_STRAWBERRY", "plant_TOMATO", "plant_CARROT",
               "plant_MELON", "buy_COW", "buy_SHEEP", "buy_GOOSE", "buy_land", "hire",
               "fert", "build_coop", "build_pasture", "buy_wheat"):
        per = collections.defaultdict(list)
        for acts in acts_days:
            for d, a in acts.items():
                per[d].append(a.get(op, 0))
        ser["op_" + op] = {int(d): round(_med(v), 1) for d, v in sorted(per.items())}

    # ---- induced rules ----
    thr, _ = _herd_threshold(ctx_days, acts_days)
    model["rules"]["herd_gate"] = thr
    if thr:
        model["edges"].append(dict(
            cause="wheat_tiles / (animals+1)", effect="BUY_ANIMAL", kind="learned",
            condition=f">= {thr['k']}", support=thr["tp"] + thr["fn"],
            confidence=thr["precision"], lag=0,
            note=f"F1 {thr['best_f1']}, recall {thr['recall']}; median ratio on buy days "
                 f"{thr['ratio_median_buy_days']}, overall {thr['ratio_median_all']}"))

    land_days = collections.defaultdict(list)
    for acts in acts_days:
        for d, a in acts.items():
            if a.get("buy_land"):
                land_days[d].append(a["buy_land"])
    model["rules"]["land_buy_days"] = {int(d): round(_med(v), 1) for d, v in sorted(land_days.items())}

    yarn_games = [i for i, m in enumerate(meta) if m["yarn"]]
    noyarn = [i for i, m in enumerate(meta) if not m["yarn"]]
    last = max((max(c) for c in ctx_days if c), default=0)

    def _end_species(idx):
        out = {}
        for a in ("COW", "SHEEP", "GOOSE"):
            vals = [ctx_days[i].get(last, {}).get("animals", {}).get(a, 0) for i in idx]
            out[a] = round(_med(vals), 1)
        return out
    model["rules"]["herd_target_by_yarn"] = {
        "yarn_games": len(yarn_games), "no_yarn_games": len(noyarn),
        "yarn": _end_species(yarn_games) if yarn_games else {},
        "no_yarn": _end_species(noyarn) if noyarn else {},
    }
    model["edges"].append(dict(
        cause="YARN_STORE unlocked", effect="SHEEP/GOOSE target", kind="learned",
        condition="YARN present -> more SHEEP", support=len(yarn_games),
        confidence=None, lag=0,
        note=str(model["rules"]["herd_target_by_yarn"])))

    first = collections.defaultdict(list)
    for m in meta:
        for a, d in (m.get("first_yield") or {}).items():
            first[a].append(d)
    model["rules"]["first_day_with_species"] = {a: round(_med(v), 1) for a, v in first.items()}
    return model


def emit_md(model, label, out):
    L = [f"# Knowledge graph — {label}", ""]
    L.append(f"games: **{model['games']}**")
    L.append("")
    s = model["series"]
    L.append("## Per-day state (medians)")
    L.append("")
    keys = [k for k in s if not k.startswith("op_")]
    days = sorted({int(d) for k in keys for d in s[k]})
    days = [d for d in days if d <= 30]
    hdr_days = [6, 8, 10, 12, 14, 16, 17, 20, 24, 29]
    L.append("| | " + " | ".join(f"d{d}" for d in hdr_days) + " |")
    L.append("|---|" + "---|" * len(hdr_days))
    for k in keys:
        row = " | ".join(str(s[k].get(d, "")) for d in hdr_days)
        L.append(f"| {k} | {row} |")
    L.append("")
    L.append("## Actions per day (medians)")
    L.append("")
    L.append("| | " + " | ".join(f"d{d}" for d in hdr_days) + " |")
    L.append("|---|" + "---|" * len(hdr_days))
    for k in sorted(s):
        if not k.startswith("op_"):
            continue
        row = " | ".join(str(s[k].get(d, "")) for d in hdr_days)
        L.append(f"| {k[3:]} | {row} |")
    L.append("")
    L.append("## Induced rules")
    L.append("")
    for e in model["edges"]:
        L.append(f"- **{e['cause']} → {e['effect']}** ({e['kind']}) — {e.get('condition')}  ")
        L.append(f"  support {e.get('support')}, confidence {e.get('confidence')}, lag {e.get('lag')}  ")
        L.append(f"  {e.get('note','')}")
    L.append("")
    hg = model["rules"].get("herd_gate")
    if hg:
        L.append("## Herd gate, induced")
        L.append("")
        L.append(f"- best separation: `wheat_tiles >= {hg['k']} * (animals+1)` "
                 f"(F1 {hg['best_f1']}, precision {hg['precision']}, recall {hg['recall']})")
        L.append(f"- buy-day support {hg['buy_days']}/{hg['days']} game-days")
        L.append(f"- median ratio (wheat/(animals+1)): **{hg['ratio_median_all']}** overall, "
                 f"{hg['ratio_median_buy_days']} on buy days")
    L.append("")
    L.append(f"## Land buy days (medians)")
    L.append("")
    L.append(f"`{model['rules'].get('land_buy_days')}`")
    L.append("")
    Path(out).write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--seat", default="1")
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--max-games", type=int, default=120)
    ap.add_argument("--ref-from", default="replays/Boey/v1")
    ap.add_argument("--ref-max", type=int, default=120)
    ap.add_argument("--ref-seat", default="auto")
    ap.add_argument("--team", default=None)
    ap.add_argument("--days", default="6-17")
    ap.add_argument("--label", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    a = ap.parse_args(argv)
    team_mod.set_team(a.team)
    win = parse_days(a.days)
    if a.dir:
        paths = sorted(globmod.glob(str(Path(a.dir) / a.glob)))[: a.max_games]
        label = a.label or Path(a.dir).name
        mode = a.seat
    else:
        paths = sorted(globmod.glob(str(Path(a.ref_from) / a.glob)))[: a.ref_max]
        label = a.label or f"{Path(a.ref_from).name} ({a.ref_seat})"
        mode = a.ref_seat
    ctx_days, acts_days, meta = scan(paths, mode, win)
    model = build(ctx_days, acts_days, meta)
    model["label"] = label
    model["days"] = list(win) if win else "all"
    print(json.dumps({k: model[k] for k in ("label", "games", "rules")}, indent=2, default=str))
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(model, indent=1, default=str))
        print(f"wrote {a.out_json}")
    if a.out_md:
        emit_md(model, label, a.out_md)
        print(f"wrote {a.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
