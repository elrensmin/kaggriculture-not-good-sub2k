"""Diagnose our REAL leaderboard (lb) games for system-level inefficiencies.

``fetch_lb_tapes.py`` downloads episodes our submitted agent actually played in
the wild against real opponents and caches each FULL replay under
``replays/lb/``. This script reads those cached replays and reuses the exact
analysis machinery from ``diagnose.py`` (``replay_to_summary`` ->
``build_frames`` / ``build_days`` / ``summarize``) to compute inefficiency
statistics for **our** seat AND the **opponent's** seat, side by side.

Because every signal is per-game and per-side, this matches the AGENTS.md rule:
never average across games — the report lets you point at a concrete defect in a
specific game (idle steps, shed overflow, floor sales, plants died, missed
harvests, unfed/unwatered animals, escapes) regardless of seed or opponent.

Usage:
    python diagnose_lb.py                 # all cached replays, compact table
    python diagnose_lb.py --dir replays/lb
    python diagnose_lb.py --detail        # full per-game side-by-side table
    python diagnose_lb.py --csv path.csv  # write one row per game (both seats)

The output CSV has one row per game; every inefficiency metric appears twice,
suffixed ``_us`` and ``_them`` (the opponent seat), so you can diff directly.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import diagnose

ROOT = Path(__file__).resolve().parent
LB_DIR = ROOT / "replays" / "lb"

# Every signal that diagnose.summarize() computes for ONE seat.  (label, key).
METRICS = [
    ("final_money", "final_money"),
    ("idle_steps", "idle_steps"),
    ("idle_units_ready", "idle_units_ready_total"),
    ("shed_pressure_days", "shed_pressure_days"),
    ("shed_overflow_days", "shed_overflow_days"),
    ("discarded_units", "discarded_units_total"),
    ("max_shed", "max_shed_total"),
    ("floor_sales", "floor_sales"),
    ("below_base_sales", "below_base_sales"),
    ("animal_escapes", "animal_escapes"),
    ("unfed_signals", "unfed_animal_signals"),
    ("plants_died", "plants_died_to_weeds"),
    ("unwatered_eod", "unwatered_crop_eod"),
    ("missed_harvest_eod", "missed_harvest_eod"),
    ("harvests_total", "harvests_total"),
    ("weeds_peak", "weeds_peak"),
    ("hires_total", "hires_total"),
    ("land_unlocks", "land_unlocks_total"),
    ("revenue_total", "revenue_total"),
    ("expenses_total", "expenses_total"),
]

# For floor_sales / below_base_sales these are dicts keyed by item; total them.
_DICT_SUMS = {"floor_sales", "below_base_sales"}


def _metric_value(s, key):
    v = s.get(key, 0) if s else 0
    if key in _DICT_SUMS and isinstance(v, dict):
        return sum(v.values())
    if isinstance(v, (int, float)):
        return v
    return 0


def analyze_seat(record, seat):
    """Return the summarize() OrderedDict for one seat of one cached replay."""
    replay = record.get("replay")
    if not replay:
        return None
    return diagnose.replay_to_summary(replay, seat)[2]


def load_lb_records(lb_dir: Path):
    files = sorted(lb_dir.glob("episode-*.json"))
    records = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIP bad record {f.name}: {exc}", file=sys.stderr)
            continue
        if not d.get("replay"):
            print(f"  SKIP {f.name}: no full replay cached (re-fetch with fetch_lb_tapes.py)",
                  file=sys.stderr)
            continue
        records.append((f, d))
    return records


def game_row(meta, our_summary, them_summary):
    row = {
        "episode_id": meta.get("episode_id", ""),
        "seed": meta.get("seed", ""),
        "opponent": meta.get("opponent_name", "unknown"),
    }
    our_s = our_summary or {}
    them_s = them_summary or {}
    our_final = _metric_value(our_s, "final_money")
    them_final = _metric_value(them_s, "final_money")
    row["our_final"] = our_final
    row["them_final"] = them_final
    row["result"] = ("WIN" if our_final > them_final
                     else "LOSS" if our_final < them_final else "TIE")
    for label, key in METRICS:
        row[f"{label}_us"] = _metric_value(our_s, key)
        row[f"{label}_them"] = _metric_value(them_s, key)
    return row


def print_compact(rows):
    if not rows:
        return
    cols = ["episode_id", "seed", "opponent", "result", "our_final", "them_final",
            "idle_steps_us", "shed_overflow_days_us", "floor_sales_us",
            "plants_died_us", "missed_harvest_eod_us", "discarded_units_us",
            "animal_escapes_us", "unfed_signals_us", "unwatered_eod_us"]
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  ".join(c.rjust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).rjust(widths[c]) for c in cols))


def print_detail(records, rows):
    for (f, meta), row in zip(records, rows):
        print(f"\n=== {f.name}  seed={row['seed']}  vs {row['opponent']}  -> {row['result']}"
              f"  us ${row['our_final']:,.0f}  them ${row['them_final']:,.0f}")
        label_headers = [label for label, _ in METRICS]
        w = max(len(h) for h in label_headers) + 1
        print((" " * w) + "OUR".rjust(12) + "THEM".rjust(12))
        for (label, key) in METRICS:
            print(label.ljust(w) + f"{row[f'{label}_us']:.0f}".rjust(12)
                  + f"{row[f'{label}_them']:.0f}".rjust(12))


def write_csv(rows, path: Path):
    if not rows:
        print("no rows to write", file=sys.stderr)
        return
    cols = list(rows[0].keys())
    with open(path, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in rows:
            wr.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=None, help="cached-lb dir (default replays/lb)")
    ap.add_argument("--compact", action="store_true",
                    help="print the compact table (default when --detail is off)")
    ap.add_argument("--detail", action="store_true",
                    help="print a full per-game side-by-side table")
    ap.add_argument("--csv", default=None, help="also write one row per game to this CSV")
    args = ap.parse_args()

    lb_dir = Path(args.dir) if args.dir else LB_DIR
    records = load_lb_records(lb_dir)
    print(f"{len(records)} cached lb replays in {lb_dir}\n")

    rows = []
    for f, meta in records:
        our_summary = analyze_seat(meta, meta.get("our_seat", 0))
        them_summary = analyze_seat(meta, meta.get("opponent_seat", 1 - meta.get("our_seat", 0)))
        rows.append(game_row(meta, our_summary, them_summary))

    print_compact(rows)
    if args.detail:
        print_detail(records, rows)
    if args.csv:
        write_csv(rows, Path(args.csv))
        print(f"\nwrote {Path(args.csv)} ({len(rows)} rows, both seats, per game)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
