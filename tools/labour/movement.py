#!/usr/bin/env python
"""movement — the movement modality, ours vs DSM.

The single largest labour cost is movement (DSM 42% of unit-turns, ours ~61%).
`ready_idle`/`idle_pool`/`missed_work` cover idle; this covers *walking*. It prints:

  * movement / productive / PASS share per arm;
  * moves-per-act (how far a unit walks between two acts);
  * movement by hour-of-day (the daily spawn->work walk shows as the early spike);
  * empty-handed vs carrying moves (carrying moves are deposit/delivery trips).

Usage:
  PYTHONPATH=. python -m tools.labour.movement --dir diag-replays/scratch-t1 \
      --glob 'scratch_vs_*.json' --dsm-max 8
"""
from __future__ import annotations

import argparse
import glob as globmod
from collections import Counter
from pathlib import Path

from tools import diagnose
from tools.diagnose.window import parse_days, in_window, describe

_WINDOW = None


def _in(day):
    return in_window(day, _WINDOW)


MOVE = {"NORTH", "SOUTH", "EAST", "WEST"}
PASS = {"PASS"}


def _scan(paths, seat_fn):
    ops = Counter()
    by_hour = Counter()
    mv_hour = Counter()
    mv_empty = mv_carry = 0
    for p in paths:
        try:
            rep = diagnose.load_replay(Path(p))
        except Exception:  # noqa: BLE001
            continue
        seat = seat_fn(rep)
        for si, frame in enumerate(rep["steps"]):
            if not _in(si // 24):  # window-guard
                continue
            if len(frame) <= seat:
                continue
            st = frame[seat]
            a = st.get("action") or {}
            obs = st.get("observation")
            if not obs:
                continue
            invs = (obs.get("private") or {}).get("inventories") or []
            h = si % 24
            for ui, u in enumerate([a.get("farmer") or ["PASS"]] + list(a.get("hands") or [])):
                if not u:
                    continue
                ops[u[0]] += 1
                by_hour[h] += 1
                if u[0] in MOVE:
                    mv_hour[h] += 1
                    inv = invs[ui] if ui < len(invs) else {}
                    if any(v > 0 for v in inv.values()):
                        mv_carry += 1
                    else:
                        mv_empty += 1
    return ops, by_hour, mv_hour, mv_empty, mv_carry


def _report(label, ops, by_hour, mv_hour, mv_empty, mv_carry):
    tot = sum(ops.values()) or 1
    mov = sum(v for k, v in ops.items() if k in MOVE)
    pas = ops.get("PASS", 0)
    prod = tot - mov - pas
    print(f"\n===== {label}  (unit-turns {tot:,}) =====")
    print(f"  movement={100*mov/tot:5.1f}%  PASS={100*pas/tot:5.1f}%  productive={100*prod/tot:5.1f}%")
    print(f"  moves-per-act={mov/max(1,prod):.2f}  (DSM ~0.77)   "
          f"empty-handed={100*mv_empty/max(1,mov):.0f}% of moves")
    print("  movement by hour-of-day (early spike = the daily spawn->work walk):")
    row = "   "
    for h in range(24):
        if by_hour[h]:
            row += f" h{h}:{100*mv_hour[h]/by_hour[h]:.0f}%"
    print(row)


def _ours_seat(rep):
    return 1


def _dsm_seat(rep):
    names = (rep.get("info") or {}).get("TeamNames") or []
    for i, n in enumerate(names):
        if n and "DSM" in str(n).upper():
            return i
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="harness run dir (ours; seat 1)")
    ap.add_argument("--days", default=None, help="restrict analysis to day window, e.g. 0-5 or 0-5,12-17")
    ap.add_argument("--glob", default="*_vs_*.json")
    ap.add_argument("--dsm-dir", default="replays/DSM/v1")
    ap.add_argument("--dsm-max", type=int, default=8)
    args = ap.parse_args()

    global _WINDOW
    _WINDOW = parse_days(args.days)
    if _WINDOW:
        print("window:", describe(_WINDOW))

    ours = sorted(globmod.glob(str(Path(args.dir) / args.glob)))
    _report(f"ours [{args.dir}]", *_scan(ours, _ours_seat))
    dsm = sorted(globmod.glob(str(Path(args.dsm_dir) / "*.json")))[:args.dsm_max]
    _report("dsm", *_scan(dsm, _dsm_seat))


if __name__ == "__main__":
    main()
