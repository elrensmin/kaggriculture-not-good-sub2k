"""tools/discards.py — W5 trace: WHAT gets thrown away at the day-end drop, DSM vs ours.

The engine force-drops every worker inventory into the shed at hour 23 and
DESTROYS whatever no longer fits. `discarded_units_total` measures how much; this
tool measures *what*, because the composition is the defect:

  * our discards are WHEAT + STRAWBERRY + CARROT -- the feed reserve and the top
    revenue line
  * DSM's are spread thinly over all nine products and dominated by EGG, a good
    with a gentle log curve that can be sold almost without limit

For OUR runs the market audit records the exact per-item discards. LB replays
(DSM) have no audit, so the day-end drop is MODELLED: room = cap - shed, and the
inventories are dropped in turn; anything past the room is a discard. The model is
labelled in the output so an estimate is never read as a measurement.

It also prints, at each drop, the shed composition and the market price of each
item -- i.e. what we threw away versus what we chose to keep.

Usage:
  PYTHONPATH=. python -m tools.market.discards --dir diag-replays/w3a-a \
      --dsm-max 30 --out docs/w5/discards.txt
"""
from __future__ import annotations

import argparse
from tools.diagnose.window import parse_days, in_window, describe
import glob
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

_WINDOW = None


def _in(day):
    return in_window(day, _WINDOW)


PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK",
            "WOOL", "FERTILIZER")


def _seat(rep, which):
    names = (rep.get("info") or {}).get("TeamNames") or []
    for i, nm in enumerate(names):
        if nm and "DSM" in str(nm).upper():
            return i if which == "dsm" else 1 - i
    return 1


def _one(arg):
    path, which, cap = arg
    try:
        rep = json.load(open(path))
    except Exception:  # noqa: BLE001
        return None
    seat = _seat(rep, which)
    audit = (rep.get("_diagnose_meta") or {}).get("audit") or {}
    out = {"disc": Counter(), "by_day": defaultdict(Counter), "shed_at_drop": Counter(),
           "kept_at_drop": Counter(), "price_at_drop": Counter(), "events": 0,
           "games": 1, "src": "model", "audit": Counter()}
    steps = rep["steps"]
    for t, frame in enumerate(steps):
        # exact audit cross-check, all steps (the audit wraps both the mid-turn
        # DROP overflow and the day-end force-drop)
        _sa = audit.get(t) or audit.get(str(t)) or {}
        _rec = _sa.get(seat) or _sa.get(str(seat)) or {}
        for _it, _n in (_rec.get("discard_items") or {}).items():
            out["audit"][_it] += _n
        if t % 24 != 23 or len(frame) <= seat:
            continue
        obs = frame[seat].get("observation")
        if not obs:
            continue
        private = obs.get("private") or {}
        shed = {k: int(v) for k, v in (private.get("shed") or {}).items() if v > 0}
        invs = private.get("inventories") or []
        prices = (obs.get("market") or {}).get("prices") or {}
        total = sum(shed.values())
        out["shed_at_drop"]["total"] += total
        for k, v in shed.items():
            out["shed_at_drop"][k] += v
            out["price_at_drop"][k] += float(prices.get(k, 0) or 0)
        out["events"] += 1
        day = t // 24
        if not _in(day):  # window-guard
            continue
        # ONE estimator for both arms so they are comparable: model the hour-23
        # force-drop (room = cap - shed, inventories dropped in order).
        disc = {}
        room = max(0, cap - total)
        for inv in invs:
            for item, n in (inv or {}).items():
                n = int(n)
                if n <= 0:
                    continue
                take = min(n, room)
                room -= take
                if n - take > 0:
                    disc[item] = disc.get(item, 0) + (n - take)
        for item, n in disc.items():
            out["disc"][item] += n
            out["by_day"][day][item] += n
    return out


def _run(paths, which, cap, workers):
    tasks = [(p, which, cap) for p in paths]
    workers = workers or min(len(tasks), os.cpu_count() or 4)
    agg = {"disc": Counter(), "by_day": defaultdict(Counter), "shed_at_drop": Counter(),
           "kept_at_drop": Counter(), "price_at_drop": Counter(), "events": 0,
           "games": 0, "src": "-", "audit": Counter()}
    if not tasks:
        return agg
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        for r in ex.map(_one, tasks):
            if not r:
                continue
            agg["games"] += 1
            agg["src"] = r["src"]
            agg["disc"] += r["disc"]
            agg["audit"] += r["audit"]
            agg["events"] += r["events"]
            agg["shed_at_drop"] += r["shed_at_drop"]
            agg["price_at_drop"] += r["price_at_drop"]
            for d, c in r["by_day"].items():
                agg["by_day"][d] += c
    return agg


def _dump(name, a, out, baseline=None):
    g = max(1, a["games"])
    tot = sum(a["disc"].values())
    out.append(f"\n############ {name}  (games={a['games']}, source={a['src']}) ############")
    out.append(f"  discards {tot:,}u over {a['games']} games = {tot/g:.2f}/game "
               f"({a['events']/g:.1f} drop-days/game)")
    au = sum(a["audit"].values())
    if au:
        out.append(f"  calibration: the exact market audit reports {au/g:.2f}/game on "
                   f"this arm, vs {tot/g:.2f} modelled -- the model's bias is "
                   f"{100*(tot-au)/max(1,au):+.0f}%.")
    out.append("  Discards are MODELLED for both arms from the hour-23 force-drop so "
               "they are comparable; treat as +-10%.")
    out.append("  -- by item (units/game, share) --")
    base = baseline["disc"] if baseline else {}
    for item, n in a["disc"].most_common():
        bg = (base.get(item, 0) / max(1, baseline["games"])) if baseline else 0
        out.append(f"     {item:<11}{n/g:>7.2f}  {100*n/max(1,tot):>5.1f}%"
                   + (f"   DSM {bg:>6.2f}" if baseline else ""))
    out.append("  -- by day --")
    days = sorted(a["by_day"])
    if days:
        out.append("     day:  " + "".join(f"{d:>5}" for d in days))
        out.append("     all:  " + "".join(f"{sum(a['by_day'][d].values()):>5}" for d in days))
        for item in a["disc"]:
            if a["disc"][item] / max(1, tot) < 0.05:
                continue
            out.append(f"     {item[:5]:<5}:" + "".join(f"{a['by_day'][d].get(item,0):>5}" for d in days))
    # what we kept while throwing the rest away
    ev = max(1, a["events"])
    out.append("  -- at the drop: mean shed total, and mean units held per item --")
    out.append(f"     shed total {a['shed_at_drop']['total']/ev:.1f} / 100")
    for item in PRODUCTS:
        held = a["shed_at_drop"].get(item, 0) / ev
        if held > 0.05:
            px = a["price_at_drop"].get(item, 0) / ev
            out.append(f"     held {item:<11}{held:>6.2f}u @ ${px:>7.1f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--days", default=None, help="restrict analysis to day window, e.g. 0-5 or 0-5,12-17")
    ap.add_argument("--dsm-dir", default=None)
    ap.add_argument("--dsm-max", type=int, default=30)
    ap.add_argument("--cap", type=int, default=100)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    global _WINDOW
    _WINDOW = parse_days(args.days)
    if _WINDOW:
        print("window:", describe(_WINDOW))

    ours = sorted(glob.glob(os.path.join(args.dir, "*_vs_*.json")))
    a = _run(ours, "ours", args.cap, args.workers)
    dsm_dir = args.dsm_dir
    if dsm_dir is None:
        for cand in ("replays/DSM/v1", "replays/DSM"):
            if glob.glob(f"{cand}/*.json"):
                dsm_dir = cand
                break
    dsm = sorted(glob.glob(os.path.join(dsm_dir or "replays/DSM", "*.json")))[:args.dsm_max]
    b = _run(dsm, "dsm", args.cap, args.workers)

    out = ["discards — W5 trace: composition of the hour-23 force-drop",
           f"ours: {args.dir} ({a['games']} games, {a['src']})",
           f"dsm : {dsm_dir} ({b['games']} games, {b['src']})"]
    _dump("ours", a, out, baseline=b)
    _dump("dsm", b, out)
    go, gd = max(1, a["games"]), max(1, b["games"])
    out.append("\n############ SIDE BY SIDE (per game) ############")
    ta, tb = sum(a["disc"].values()) / go, sum(b["disc"].values()) / gd
    out.append(f"   {'metric':<26}{'ours':>10}{'dsm':>10}")
    out.append(f"   {'discards/game':<26}{ta:>10.2f}{tb:>10.2f}")
    out.append(f"   {'drop-days/game':<26}{a['events']/go:>10.2f}{b['events']/gd:>10.2f}")
    out.append(f"   {'shed total at drop':<26}{a['shed_at_drop']['total']/max(1,a['events']):>10.1f}"
               f"{b['shed_at_drop']['total']/max(1,b['events']):>10.1f}")
    out.append(f"   {'largest item share':<26}"
               f"{100*max(a['disc'].values() or [0])/max(1,sum(a['disc'].values())):>9.1f}%"
               f"{100*max(b['disc'].values() or [0])/max(1,sum(b['disc'].values())):>9.1f}%")
    text = "\n".join(out)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        open(args.out, "w").write(text + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
